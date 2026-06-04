"""
pipeline/01_data_generator.py
------------------------------
Türkiye'deki HR profesyoneli lead listesini üretir VEYA harici CSV'den okur.

Çalışma modu otomatik belirlenir — önce external CSV aranır:

  EXTERNAL MOD (öncelikli):
    Şu konumlardan biri varsa gerçek scraping verisi olarak işlenir:
      1. <proje_kökü>/leads_external.csv
      2. <proje_kökü>/data/leads_external.csv
    Desteklenen formatlar:
      - Apollo.io   CSV export (First Name, Last Name, Title, Company ...)
      - PhantomBuster LinkedIn export (fullName, firstName, companyName ...)
      - Kendi formatın (full_name / first_name + last_name kombinasyonu)

  MOCK MOD (fallback):
    External CSV bulunamazsa 100 kişilik gerçekçi mock veri üretilir.

Standalone çalıştırma:
    PYTHONPATH=src python src/pipeline/01_data_generator.py
    PYTHONPATH=src python src/pipeline/01_data_generator.py --mock   # Mock'u zorla
    PYTHONPATH=src python src/pipeline/01_data_generator.py --external path/to/file.csv
"""

import random
import sys
import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from db.database import Database
from db.models import Lead
from utils.config import config
from utils.logger import get_logger, log_pipeline_start, log_pipeline_end, log_progress

log = get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  EXTERNAL CSV ARAMA & DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# Pipeline'ın arayacağı yollar — öncelik sırasıyla
_EXTERNAL_CSV_CANDIDATES: list[Path] = [
    config.root_dir / "leads_external.csv",
    config.root_dir / "data" / "leads_external.csv",
    config.data_raw_dir / "leads_external.csv",
]

# Apollo.io sütun ismi → Lead field mapping
# (hem "First Name" hem "first_name" formatını destekle)
_APOLLO_COLUMN_MAP: dict[str, str] = {
    # Ad / Soyad
    "first name":       "first_name",
    "first_name":       "first_name",
    "last name":        "last_name",
    "last_name":        "last_name",
    # Tam ad (PhantomBuster tarzı)
    "full name":        "full_name",
    "fullname":         "full_name",
    "name":             "full_name",
    # Ünvan
    "title":            "title",
    "job title":        "title",
    "jobtitle":         "title",
    "position":         "title",
    # Şirket
    "company":          "company",
    "company name":     "company",
    "companyname":      "company",
    "organization":     "company",
    # Şehir
    "city":             "company_city",
    "company city":     "company_city",
    "location":         "company_city",
    # LinkedIn
    "linkedin url":     "linkedin_url",
    "linkedin_url":     "linkedin_url",
    "linkedinurl":      "linkedin_url",
    "profile url":      "linkedin_url",
    "profileurl":       "linkedin_url",
    # Email
    "email":            "email",
    "email address":    "email",
    "work email":       "email",
    # Çalışan sayısı (zenginleştirmede kullanılır)
    "# employees":      "company_size_raw",
    "employees":        "company_size_raw",
    "company size":     "company_size_raw",
    # Sektör (bonus — varsa alınır)
    "industry":         "industry_raw",
}

# Çalışan sayısı → company_size label
_EMPLOYEE_SIZE_MAP: list[tuple[int, str]] = [
    (10,   "1-10"),
    (50,   "11-50"),
    (200,  "51-200"),
    (500,  "201-500"),
    (9999, "500+"),
]


# ─────────────────────────────────────────────────────────────────────────────
#  EXTERNAL CSV LOADER
# ─────────────────────────────────────────────────────────────────────────────

def find_external_csv() -> Optional[Path]:
    """
    Önceden tanımlı konumlarda leads_external.csv arar.

    Returns:
        Path: Bulunan dosya yolu, yoksa None
    """
    for candidate in _EXTERNAL_CSV_CANDIDATES:
        if candidate.exists() and candidate.stat().st_size > 0:
            log.info(f"📂 External CSV bulundu → {candidate}")
            return candidate
    return None


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Farklı tool export formatlarını (Apollo, PhantomBuster, custom)
    ortak bir şemaya indirger.

    Strateji:
      1. Sütun isimlerini küçük harfe çevir + strip
      2. Bilinen alias'ları canonical isimlere map et
      3. 'full_name' varsa first/last'a böl; yoksa birleştir
    """
    # Sütun isimlerini normalize et
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Alias → canonical rename
    rename_map = {}
    for col in df.columns:
        canonical = _APOLLO_COLUMN_MAP.get(col)
        if canonical and canonical not in rename_map.values():
            rename_map[col] = canonical

    df = df.rename(columns=rename_map)

    # full_name → first_name + last_name ayrıştır
    if "full_name" in df.columns and "first_name" not in df.columns:
        split = df["full_name"].fillna("").str.strip().str.split(r"\s+", n=1, expand=True)
        df["first_name"] = split[0].fillna("")
        df["last_name"]  = split[1].fillna("") if 1 in split.columns else ""

    # first_name + last_name → full_name oluştur (yoksa)
    if "first_name" in df.columns and "full_name" not in df.columns:
        df["full_name"] = (
            df["first_name"].fillna("").str.strip()
            + " "
            + df.get("last_name", pd.Series([""] * len(df))).fillna("").str.strip()
        ).str.strip()

    return df


def _parse_company_size(raw: str) -> str:
    """
    '5001-10000', '1001+', '500' gibi ham string'i
    standart company_size label'ına dönüştür.
    """
    if not raw or str(raw).strip() in ("", "nan"):
        return "51-200"   # bilinmiyorsa makul default

    raw = str(raw).replace(",", "").replace("+", "").strip()

    # Aralık formatı: "1001-5000" → üst değeri al
    if "-" in raw:
        parts = raw.split("-")
        try:
            num = int(parts[-1])
        except ValueError:
            return "51-200"
    else:
        try:
            num = int(raw)
        except ValueError:
            return "51-200"

    for threshold, label in _EMPLOYEE_SIZE_MAP:
        if num <= threshold:
            return label
    return "500+"


def _infer_seniority(title: str) -> str:
    """Ünvandan kıdem seviyesini tahmin et."""
    title_lower = (title or "").lower()
    if any(k in title_lower for k in ["chief", "vp ", "vice president", "cpo", "chro"]):
        return "C-Level"
    if any(k in title_lower for k in ["director", "direktör", "head of", "head,", "müdür"]):
        return "Director"
    if any(k in title_lower for k in ["senior", "kıdemli", "lead ", "principal", "manager", "yönetici"]):
        return "Senior"
    if any(k in title_lower for k in ["junior", "asistan", "assistant", "koordinatör", "coordinator"]):
        return "Junior"
    return "Mid"


def _clean_linkedin_url(raw: str) -> Optional[str]:
    """LinkedIn URL'ini normalize et — boşsa None döner."""
    if not raw or str(raw).strip() in ("", "nan", "N/A", "n/a"):
        return None
    url = str(raw).strip()
    # Kısa format varsa tam URL'e çevir
    if url.startswith("linkedin.com"):
        url = "https://www." + url
    elif url.startswith("www.linkedin.com"):
        url = "https://" + url
    return url


def _clean_email(raw: str) -> Optional[str]:
    """Email adresini temizle — geçersizse None döner."""
    if not raw or str(raw).strip() in ("", "nan", "N/A", "n/a"):
        return None
    email = str(raw).strip().lower()
    # Basit format kontrolü
    if "@" not in email or "." not in email.split("@")[-1]:
        return None
    return email


def load_external_csv(csv_path: Path) -> list[Lead]:
    """
    Apollo.io / PhantomBuster / custom CSV dosyasını okuyup
    Lead nesneleri listesine dönüştürür.

    Robust davranış:
      - Eksik zorunlu sütunlar → uyarı + atla
      - Eksik opsiyonel alanlar → None / default
      - Encoding otomatik tespit (utf-8 → utf-8-sig → latin-1 fallback)
      - Duplicate (isim + şirket) satırlar otomatik filtrelenir

    Args:
        csv_path: Okunacak CSV dosyasının Path'i

    Returns:
        list[Lead]: Dönüştürülmüş lead nesneleri

    Raises:
        ValueError: Zorunlu sütun (first_name veya full_name, company) yoksa
    """
    log.info(f"📥 External CSV okunuyor → {csv_path}")

    # ── Encoding-safe okuma ──────────────────────────────────────────────────
    df: Optional[pd.DataFrame] = None
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1254"):
        try:
            df = pd.read_csv(csv_path, encoding=enc, dtype=str)
            log.debug(f"  Encoding: {enc} | {len(df)} satır | {len(df.columns)} sütun")
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    if df is None or df.empty:
        raise ValueError(f"CSV okunamadı veya boş: {csv_path}")

    # ── Sütun normalize ───────────────────────────────────────────────────────
    df = _normalize_columns(df)

    # ── Zorunlu alan kontrolü ─────────────────────────────────────────────────
    has_name    = "first_name" in df.columns or "full_name" in df.columns
    has_company = "company" in df.columns

    if not has_name:
        raise ValueError(
            f"CSV'de isim sütunu bulunamadı. "
            f"Beklenen: 'First Name', 'first_name', 'fullName', 'name' ...\n"
            f"Mevcut sütunlar: {list(df.columns)}"
        )
    if not has_company:
        raise ValueError(
            f"CSV'de şirket sütunu bulunamadı. "
            f"Beklenen: 'Company', 'company', 'companyName' ...\n"
            f"Mevcut sütunlar: {list(df.columns)}"
        )

    # ── Lead dönüşümü ─────────────────────────────────────────────────────────
    leads:   list[Lead] = []
    skipped: int        = 0
    seen:    set[str]   = set()

    for idx, row in df.iterrows():
        first   = str(row.get("first_name", "")).strip()
        last    = str(row.get("last_name",  "")).strip()
        company = str(row.get("company",    "")).strip()
        title   = str(row.get("title",      "")).strip()

        # Zorunlu alanlar boşsa atla
        if not first and not str(row.get("full_name", "")).strip():
            skipped += 1
            continue
        if not company or company == "nan":
            skipped += 1
            continue

        # full_name'den first/last türet (PhantomBuster tarzı)
        if not first:
            full = str(row.get("full_name", "")).strip()
            parts = full.split(" ", 1)
            first = parts[0]
            last  = parts[1] if len(parts) > 1 else ""

        # Duplicate kontrolü
        key = f"{first.lower()}_{last.lower()}_{company.lower()}"
        if key in seen:
            skipped += 1
            continue
        seen.add(key)

        # Şehir — "Istanbul, Turkey" → "İstanbul" normalize
        raw_city = str(row.get("company_city", "İstanbul")).strip()
        city = _normalize_city(raw_city)

        # company_size
        size_label = _parse_company_size(str(row.get("company_size_raw", "")))

        # Ünvandan kıdem çıkar
        seniority = _infer_seniority(title or "")

        lead = Lead(
            first_name   = first,
            last_name    = last,
            title        = title or "HR Professional",
            seniority    = seniority,
            company      = company,
            company_city = city,
            linkedin_url = _clean_linkedin_url(str(row.get("linkedin_url", ""))),
            email        = _clean_email(str(row.get("email", ""))),
            source       = f"external:{csv_path.name}",
            status       = "new",
        )
        leads.append(lead)

    log.info(f"  ✅ {len(leads)} lead dönüştürüldü")
    if skipped:
        log.warning(f"  ⚠️  {skipped} satır atlandı (eksik zorunlu alan veya duplicate)")

    return leads


def _normalize_city(raw: str) -> str:
    """
    'Istanbul, Turkey', 'istanbul', 'İSTANBUL' → 'İstanbul' gibi
    yaygın şehir varyantlarını normalize et.
    """
    if not raw or raw.strip() in ("", "nan"):
        return "İstanbul"

    # Virgül sonrasını at: "Istanbul, Turkey" → "Istanbul"
    city = raw.split(",")[0].strip()

    # Bilinen ASCII → Türkçe mapping
    city_map = {
        "istanbul":  "İstanbul",
        "ankara":    "Ankara",
        "izmir":     "İzmir",
        "bursa":     "Bursa",
        "antalya":   "Antalya",
        "adana":     "Adana",
        "kocaeli":   "Kocaeli",
        "gaziantep": "Gaziantep",
        "konya":     "Konya",
        "mersin":    "Mersin",
    }
    normalized = city_map.get(city.lower())
    return normalized if normalized else city.title()


def print_external_summary(leads: list[Lead], csv_path: Path) -> None:
    """External CSV yüklemesinin kısa özetini terminale yazar."""
    sources = set(l.source for l in leads)
    cities  = {}
    for l in leads:
        cities[l.company_city] = cities.get(l.company_city, 0) + 1
    top_cities = sorted(cities.items(), key=lambda x: x[1], reverse=True)[:3]

    log.info(f"\n{'─' * 65}")
    log.info(f"  📂  EXTERNAL CSV YÜKLEMESİ ÖZETİ")
    log.info(f"{'─' * 65}")
    log.info(f"  Kaynak dosya    : {csv_path.name}")
    log.info(f"  Yüklenen lead   : {len(leads)}")
    log.info(f"  Email coverage  : {sum(1 for l in leads if l.email)}/{len(leads)}")
    log.info(f"  LinkedIn cov.   : {sum(1 for l in leads if l.linkedin_url)}/{len(leads)}")
    log.info(f"  Başlıca şehirler: {', '.join(f'{c}({n})' for c, n in top_cities)}")
    log.info(f"{'─' * 65}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  MOCK VERİ ÜRETECİ (mevcut kod — değişmedi)
# ─────────────────────────────────────────────────────────────────────────────

FIRST_NAMES = [
    "Ayşe", "Fatma", "Zeynep", "Elif", "Merve", "Selin", "Büşra", "Esra",
    "Tuğba", "Derya", "Özge", "Pınar", "Gizem", "Cansu", "Beyza", "Neslihan",
    "Hülya", "Sibel", "Özlem", "Arzu", "Yasemin", "Melis", "Ebru", "Serap",
    "Mehmet", "Mustafa", "Ahmet", "Ali", "Hüseyin", "İbrahim", "Hasan", "Emre",
    "Burak", "Serkan", "Murat", "Onur", "Kemal", "Oğuz", "Tolga", "Berk",
    "Cem", "Eren", "Alper", "Uğur", "Kaan", "Selçuk", "Furkan", "Ozan",
    "Tarık", "Yasin", "Berkay", "Deniz", "Ömer", "Barış", "Caner", "Taner",
]

LAST_NAMES = [
    "Yılmaz", "Kaya", "Demir", "Çelik", "Şahin", "Doğan", "Kılıç", "Arslan",
    "Taş", "Aydın", "Özdemir", "Aksoy", "Kaplan", "Bulut", "Güneş", "Yıldız",
    "Erdoğan", "Çetin", "Koç", "Kurt", "Aktaş", "Erdem", "Bozkurt", "Güler",
    "Polat", "Çakır", "Öztürk", "Albayrak", "Güzel", "Karaca", "Korkmaz",
    "Tekin", "Ünal", "Avcı", "Bayram", "Boz", "Duman", "Eker", "Gündüz",
    "Işık", "Karakoç", "Mutlu", "Nalbant", "Özcan", "Sönmez", "Türk", "Uysal",
    "Vardar", "Yalçın", "Zorlu", "Acun", "Başaran", "Ceylan", "Dinçer",
]

HR_TITLES = {
    "C-Level": [
        "Chief People Officer", "Chief Human Resources Officer",
        "VP of Human Resources", "VP of People & Culture",
        "İnsan Kaynakları Direktörü",
    ],
    "Director": [
        "HR Director", "İnsan Kaynakları Müdürü", "People & Culture Manager",
        "Talent Acquisition Director", "Learning & Development Director",
        "İK Müdürü", "Organizasyonel Gelişim Müdürü",
    ],
    "Senior": [
        "Senior HR Business Partner", "Senior Talent Acquisition Specialist",
        "Senior İK Uzmanı", "HR Business Partner",
        "Kıdemli İnsan Kaynakları Uzmanı", "Learning & Development Manager",
        "Compensation & Benefits Manager", "İşe Alım Müdürü",
        "People Operations Manager",
    ],
    "Mid": [
        "HR Specialist", "Talent Acquisition Specialist",
        "İnsan Kaynakları Uzmanı", "İşe Alım Uzmanı", "HR Generalist",
        "Recruiter", "Eğitim ve Gelişim Uzmanı", "İK Generalist",
        "People Operations Specialist", "HRBP", "Organizasyonel Gelişim Uzmanı",
    ],
    "Junior": [
        "HR Assistant", "Recruitment Coordinator",
        "İnsan Kaynakları Asistanı", "İK Koordinatörü",
        "HR Coordinator", "Talent Acquisition Coordinator",
    ],
}

COMPANIES = {
    "Teknoloji / SaaS": [
        "Getir", "Trendyol", "Hepsiburada", "Peak Games", "Dream Games",
        "Insider", "Armut", "GittiGidiyor", "Modanisa", "N11",
        "Marti", "Trink", "Logo Yazılım", "Netas", "Turkcell Teknoloji",
        "Etiya", "Forceget", "Craftgate", "Iyzico", "Papara",
        "Param", "Figopara", "Colendi", "Apsiyon", "Kariyer.net",
    ],
    "Finans / Bankacılık": [
        "Garanti BBVA", "İş Bankası", "Yapı Kredi", "Akbank", "Ziraat Bankası",
        "QNB Finansbank", "Denizbank", "HSBC Türkiye", "ING Türkiye",
        "Odeabank", "TEB", "Vakıfbank", "Halkbank", "Fibabanka",
        "Albaraka Türk", "Kuveyt Türk",
    ],
    "Perakende / E-ticaret": [
        "BİM", "A101", "ŞOK", "Migros", "Carrefour SA",
        "LC Waikiki", "DeFacto", "Mavi", "Koton", "Boyner",
        "Gratis", "Watsons Türkiye", "Mediamarkt Türkiye", "Teknosa",
    ],
    "Telekomünikasyon": [
        "Turkcell", "Vodafone Türkiye", "Türk Telekom", "Netgsm",
        "Superonline", "Millenicom",
    ],
    "Üretim / Sanayi": [
        "Koç Holding", "Sabancı Holding", "Arçelik", "Vestel",
        "Ford Otosan", "Tofaş", "Türk Traktör", "Çimsa", "Oyak Çimento",
        "Kordsa", "Petkim", "Tüpraş", "Enerjisa", "Zorlu Holding",
        "Ülker Bisküvi", "Anadolu Efes",
    ],
    "Danışmanlık / Hizmet": [
        "PwC Türkiye", "Deloitte Türkiye", "KPMG Türkiye", "EY Türkiye",
        "McKinsey Türkiye", "BCG Türkiye", "Accenture Türkiye",
        "Manpower Group Türkiye", "Adecco Türkiye", "Randstad Türkiye",
    ],
    "Sağlık": [
        "Acıbadem Sağlık Grubu", "Memorial Hastaneler Grubu",
        "Medicana", "Medical Park", "Dünya Göz", "Doktor Takvimi",
    ],
    "Eğitim": [
        "Bahçeşehir Üniversitesi", "Özyeğin Üniversitesi",
        "Sabancı Üniversitesi", "Bilgi Üniversitesi", "Udemy Türkiye",
    ],
    "Lojistik / Ulaşım": [
        "UPS Türkiye", "DHL Türkiye", "Yurtiçi Kargo", "Aras Kargo",
        "MNG Kargo", "Horoz Lojistik", "Netlog", "Ekol Lojistik",
    ],
    "Gayrimenkul / İnşaat": [
        "Emlak Konut", "Torunlar GYO", "Ağaoğlu",
        "Tekfen İnşaat", "Limak Holding", "Rönesans Holding",
    ],
}

CITIES = [
    "İstanbul", "İstanbul", "İstanbul", "İstanbul", "İstanbul",
    "Ankara", "Ankara", "İzmir",
    "Bursa", "Antalya", "Kocaeli", "Adana", "Gaziantep",
]


def _slugify(text: str) -> str:
    replacements = {
        "ş": "s", "ğ": "g", "ı": "i", "ö": "o", "ü": "u", "ç": "c",
        "Ş": "s", "Ğ": "g", "İ": "i", "Ö": "o", "Ü": "u", "Ç": "c",
        " ": "", "-": "", ".": "", ",": "", "(": "", ")": "",
    }
    result = text.lower()
    for k, v in replacements.items():
        result = result.replace(k, v)
    return result[:20]


def _generate_email(first: str, last: str, company: str) -> Optional[str]:
    if random.random() > 0.75:
        return None
    slug   = _slugify(company)
    domain = random.choice(["{s}.com", "{s}.com.tr", "{s}.net"]).format(s=slug)
    fc, lc = _slugify(first), _slugify(last)
    return random.choice([
        f"{fc}.{lc}@{domain}", f"{fc[0]}{lc}@{domain}",
        f"{fc}@{domain}",      f"{fc}.{lc[0]}@{domain}",
    ])


def _generate_linkedin_url(first: str, last: str) -> Optional[str]:
    if random.random() > 0.80:
        return None
    fc, lc = _slugify(first), _slugify(last)
    suffix = random.choice(["", f"-{random.randint(10,99)}", "-tr"])
    return f"https://www.linkedin.com/in/{fc}-{lc}{suffix}"


def _pick_seniority_weighted() -> tuple[str, str]:
    level = random.choices(
        ["Junior", "Mid", "Senior", "Director", "C-Level"],
        weights=[15, 40, 30, 12, 3], k=1
    )[0]
    return level, random.choice(HR_TITLES[level])


def generate_leads(count: int = 100) -> list[Lead]:
    """Gerçekçi mock HR lead listesi üret."""
    leads: list[Lead] = []
    seen:  set[str]   = set()

    all_companies = [
        (co, sec) for sec, cos in COMPANIES.items() for co in cos
    ]

    log.info(f"🎲 {count} adet gerçekçi HR lead üretiliyor...")

    attempts, max_attempts = 0, count * 5
    while len(leads) < count and attempts < max_attempts:
        attempts += 1
        first    = random.choice(FIRST_NAMES)
        last     = random.choice(LAST_NAMES)
        city     = random.choice(CITIES)
        seniority, title = _pick_seniority_weighted()
        company, _sector = random.choice(all_companies)

        key = f"{first}_{last}_{company}"
        if key in seen:
            continue
        seen.add(key)

        leads.append(Lead(
            first_name   = first,
            last_name    = last,
            title        = title,
            seniority    = seniority,
            company      = company,
            company_city = city,
            linkedin_url = _generate_linkedin_url(first, last),
            email        = _generate_email(first, last, company),
            source       = "mock_generator",
            status       = "new",
        ))

        if len(leads) % 20 == 0:
            log_progress(len(leads), count, "lead üretildi")

    log.success(f"✅ {len(leads)} lead üretildi ({attempts} deneme)")
    return leads


# ─────────────────────────────────────────────────────────────────────────────
#  ORTAK YARDIMCILAR
# ─────────────────────────────────────────────────────────────────────────────

def save_to_csv(leads: list[Lead], path: Path) -> None:
    """Lead listesini CSV olarak kaydet."""
    df   = pd.DataFrame([l.to_dict() for l in leads])
    cols = [
        "full_name", "first_name", "last_name", "title", "seniority",
        "company", "company_city", "linkedin_url", "email", "source", "status",
    ]
    df = df[[c for c in cols if c in df.columns]]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.success(f"💾 CSV kaydedildi → {path}  ({len(df)} satır)")


def print_sample(leads: list[Lead], n: int = 5) -> None:
    log.info(f"\n{'─' * 70}")
    log.info(f"  📋  ÖRNEK {n} LEAD")
    log.info(f"{'─' * 70}")
    for lead in leads[:n]:
        log.info(
            f"  👤  {lead.full_name:<25} | "
            f"{lead.title:<35} | "
            f"{lead.company:<25} | "
            f"{lead.company_city}"
        )
    log.info(f"{'─' * 70}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  ANA ÇALIŞTIRICI
# ─────────────────────────────────────────────────────────────────────────────

def run(
    target_count: int = None,
    force_mock: bool  = False,
    external_path: Optional[Path] = None,
) -> int:
    """
    Pipeline orchestrator'dan veya standalone olarak çağrılır.

    Öncelik sırası:
      1. external_path parametresi verilmişse → o dosyayı yükle
      2. leads_external.csv otomatik bulunursa  → onu yükle
      3. force_mock=True veya hiçbiri yoksa     → mock üret

    Returns:
        int: Veritabanına eklenen lead sayısı
    """
    log_pipeline_start("01 — Veri Üretimi")

    # ── Mod kararı ─────────────────────────────────────────────────────────
    csv_path: Optional[Path] = None

    if not force_mock:
        csv_path = external_path or find_external_csv()

    if csv_path:
        # ── EXTERNAL MOD ───────────────────────────────────────────────────
        log.info("🌐 MOD: External CSV (Apollo / PhantomBuster / custom)")
        try:
            leads = load_external_csv(csv_path)
            print_external_summary(leads, csv_path)
        except (ValueError, Exception) as e:
            log.error(f"External CSV yüklenemedi: {e}")
            log.warning("⚠️  Mock moda geçiliyor...")
            leads    = generate_leads(target_count or config.leads_target_count)
            csv_path = None   # mock kaynağını işaretle
    else:
        # ── MOCK MOD ───────────────────────────────────────────────────────
        log.info("🎲 MOD: Mock veri üretimi (leads_external.csv bulunamadı)")
        leads = generate_leads(target_count or config.leads_target_count)

    if not leads:
        log.error("Hiç lead üretilemedi / yüklenemedi.")
        return 0

    print_sample(leads, n=5)

    # ── DB + CSV kayıt ─────────────────────────────────────────────────────
    db = Database(config.db_path)
    db.init()
    inserted = db.insert_leads_bulk(leads)
    save_to_csv(leads, config.leads_raw_path)

    log.info(f"📊 DB Durum: {db.get_table_counts()}")
    log_pipeline_end("01 — Veri Üretimi", inserted, "lead")
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lead veri üreticisi / external CSV yükleyici",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python 01_data_generator.py                         # Otomatik mod
  python 01_data_generator.py --mock                  # Mock'u zorla
  python 01_data_generator.py --external apollo.csv   # Belirli dosya
  python 01_data_generator.py --validate apollo.csv   # Sadece doğrula, yükleme
        """
    )
    p.add_argument("--mock",     action="store_true",
                   help="External CSV varsa bile mock üret")
    p.add_argument("--external", type=str, default=None, metavar="CSV_PATH",
                   help="Yüklenecek external CSV dosyası")
    p.add_argument("--validate", type=str, default=None, metavar="CSV_PATH",
                   help="CSV'yi yüklemeden doğrula ve önizle (dry-run)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # ── Validate (dry-run) modu ───────────────────────────────────────────
    if args.validate:
        path = Path(args.validate)
        log.info(f"🔍 DRY-RUN: {path}")
        try:
            leads = load_external_csv(path)
            print_external_summary(leads, path)
            print_sample(leads, n=10)
            log.success(f"✅ Doğrulama başarılı — {len(leads)} lead yüklenebilir")
        except Exception as e:
            log.error(f"❌ Doğrulama başarısız: {e}")
        sys.exit(0)

    run(
        force_mock    = args.mock,
        external_path = Path(args.external) if args.external else None,
    )
