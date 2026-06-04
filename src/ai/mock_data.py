"""
ai/mock_data.py
----------------
Akıllı Mock Veri Motoru — API key olmadan gerçekçi, şirkete özgü simülasyon.

Neden ayrı modül?
  → claude_client.py ve 03_outreach_writer.py ikisi de bu veriyi kullanır
  → Tek yerden güncellenebilir
  → Test/demo ortamında "hepsi aynı" sorununu çözer

Tasarım prensipleri:
  1. Şirket adına → doğru sektör (keyword-first, sonra fuzzy match)
  2. Her şirkete özgü pain point metni (template değil, dinamik string)
  3. Lead skoru = sektör ağırlığı × kıdem çarpanı × şirket büyüklüğü + jitter
  4. Outreach mesajı = şirket + sektör + kıdem birleşimi (her kombinasyon farklı)
"""

import random
import hashlib
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
#  ŞİRKET → SEKTÖR KNOWLEDGE BASE
#  (Türkiye'nin önde gelen şirketleri için elle etiketlenmiş)
# ─────────────────────────────────────────────────────────────────────────────

COMPANY_SECTOR_MAP: dict[str, str] = {
    # Fintech / Ödeme
    "papara":          "Fintech / Ödeme Sistemleri",
    "iyzico":          "Fintech / Ödeme Sistemleri",
    "param":           "Fintech / Ödeme Sistemleri",
    "figopara":        "Fintech / Kredi Teknolojisi",
    "craftgate":       "Fintech / Ödeme Altyapısı",
    "colendi":         "Fintech / Kredi Skorlama",
    # Hızlı Teslimat / Lojistik
    "getir":           "Hızlı Teslimat / Q-Commerce",
    "trendyol":        "E-ticaret / Marketplace",
    "hepsiburada":     "E-ticaret / Marketplace",
    "gittigidiyor":    "E-ticaret / Marketplace",
    "n11":             "E-ticaret / Marketplace",
    "marti":           "Mikromobilite / Paylaşımlı Ulaşım",
    "trink":           "Mikromobilite / Paylaşımlı Ulaşım",
    # Bankacılık
    "garanti bbva":    "Bankacılık / Özel Banka",
    "akbank":          "Bankacılık / Özel Banka",
    "yapı kredi":      "Bankacılık / Özel Banka",
    "iş bankası":      "Bankacılık / Kamu-Özel",
    "ziraat bankası":  "Bankacılık / Kamu Bankası",
    "halkbank":        "Bankacılık / Kamu Bankası",
    "vakıfbank":       "Bankacılık / Kamu Bankası",
    "qnb finansbank":  "Bankacılık / Yabancı Sermayeli",
    "denizbank":       "Bankacılık / Yabancı Sermayeli",
    "hsbc türkiye":    "Bankacılık / Yabancı Sermayeli",
    "ing türkiye":     "Bankacılık / Yabancı Sermayeli",
    "odeabank":        "Bankacılık / Özel Banka",
    "teb":             "Bankacılık / Özel Banka",
    "fibabanka":       "Bankacılık / Özel Banka",
    "albaraka türk":   "Bankacılık / Katılım Bankası",
    "kuveyt türk":     "Bankacılık / Katılım Bankası",
    # Telekomünikasyon
    "turkcell":        "Telekomünikasyon / Mobil Operatör",
    "vodafone türkiye":"Telekomünikasyon / Mobil Operatör",
    "türk telekom":    "Telekomünikasyon / Altyapı & Sabit Hat",
    "netgsm":          "Telekomünikasyon / MVNO",
    "superonline":     "Telekomünikasyon / İnternet Servisi",
    "millenicom":      "Telekomünikasyon / İnternet Servisi",
    "turkcell teknoloji": "Teknoloji / Telekomünikasyon BT",
    # Teknoloji / SaaS
    "insider":         "Teknoloji / Pazarlama Otomasyonu SaaS",
    "logo yazılım":    "Teknoloji / Kurumsal ERP SaaS",
    "netas":           "Teknoloji / Sistem Entegrasyonu",
    "etiya":           "Teknoloji / Telekomünikasyon Yazılımı",
    "forceget":        "Teknoloji / Tedarik Zinciri SaaS",
    "apsiyon":         "Teknoloji / Gayrimenkul Yönetim SaaS",
    "kariyer.net":     "İK Teknolojisi / İşe Alım Platformu",
    "armut":           "Teknoloji / Hizmet Marketplace",
    # Oyun
    "peak games":      "Oyun / Mobil Oyun Geliştirme",
    "dream games":     "Oyun / Mobil Oyun Geliştirme",
    # Perakende
    "bim":             "Perakende / Gıda Zinciri",
    "a101":            "Perakende / Gıda Zinciri",
    "şok":             "Perakende / Gıda Zinciri",
    "migros":          "Perakende / Süpermarket Zinciri",
    "carrefour sa":    "Perakende / Hipermarket Zinciri",
    "lc waikiki":      "Perakende / Moda & Hazır Giyim",
    "defacto":         "Perakende / Moda & Hazır Giyim",
    "mavi":            "Perakende / Moda & Hazır Giyim",
    "koton":           "Perakende / Moda & Hazır Giyim",
    "boyner":          "Perakende / Mağazacılık",
    "gratis":          "Perakende / Kozmetik & Kişisel Bakım",
    "watsons türkiye": "Perakende / Kozmetik & Eczane",
    "mediamarkt türkiye": "Perakende / Elektronik Mağazacılık",
    "teknosa":         "Perakende / Elektronik Mağazacılık",
    "vatan bilgisayar":"Perakende / Elektronik Mağazacılık",
    # Holdingler / Sanayi
    "koç holding":     "Holding / Çok Sektörlü Sanayi",
    "sabancı holding": "Holding / Çok Sektörlü Sanayi",
    "zorlu holding":   "Holding / Enerji & Tüketim",
    "alarko holding":  "Holding / İnşaat & Enerji",
    "limak holding":   "Holding / İnşaat & Altyapı",
    "rönesans holding":"Holding / İnşaat & Altyapı",
    "tekfen i̇nşaat":  "İnşaat / EPC Proje Yönetimi",
    "arçelik":         "Üretim / Beyaz Eşya & Tüketim Elektroniği",
    "vestel":          "Üretim / Tüketim Elektroniği",
    "ford otosan":     "Otomotiv / Araç Üretimi",
    "tofaş":           "Otomotiv / Araç Üretimi",
    "türk traktör":    "Otomotiv / Tarım Makineleri",
    "çimsa":           "Üretim / Çimento & İnşaat Malzemeleri",
    "oyak çimento":    "Üretim / Çimento & İnşaat Malzemeleri",
    "kordsa":          "Üretim / Teknik Tekstil & Kompozit",
    "petkim":          "Üretim / Petrokimya",
    "tüpraş":          "Üretim / Rafineri & Enerji",
    "enerjisa":        "Enerji / Elektrik Dağıtım & Perakende",
    "ülker bisküvi":   "FMCG / Gıda Üretimi",
    "anadolu efes":    "FMCG / İçecek Üretimi",
    # Danışmanlık / Big4
    "pwc türkiye":     "Danışmanlık / Denetim & Vergi (Big4)",
    "deloitte türkiye":"Danışmanlık / Denetim & Strateji (Big4)",
    "kpmg türkiye":    "Danışmanlık / Denetim & Danışmanlık (Big4)",
    "ey türkiye":      "Danışmanlık / Denetim & Danışmanlık (Big4)",
    "mckinsey türkiye":"Danışmanlık / Strateji (MBB)",
    "bcg türkiye":     "Danışmanlık / Strateji (MBB)",
    "accenture türkiye":"Danışmanlık / Teknoloji & Operasyon",
    # İK / İstihdam
    "manpower group türkiye": "İK Hizmetleri / Geçici İstihdam",
    "adecco türkiye":  "İK Hizmetleri / İşe Alım & Outsourcing",
    "randstad türkiye":"İK Hizmetleri / İşe Alım & Outsourcing",
    "michael page türkiye": "İK Hizmetleri / Yönetici Arama",
    "kelly services türkiye": "İK Hizmetleri / Geçici İstihdam",
    # Sağlık
    "acıbadem sağlık grubu": "Sağlık / Özel Hastane Grubu",
    "memorial hastaneler grubu": "Sağlık / Özel Hastane Grubu",
    "medicana":        "Sağlık / Özel Hastane Zinciri",
    "medical park":    "Sağlık / Özel Hastane Zinciri",
    "dünya göz":       "Sağlık / Göz Hastalıkları Kliniği",
    "doktor takvimi":  "Sağlık Teknolojisi / Randevu Platformu",
    # Eğitim
    "bahçeşehir üniversitesi": "Yükseköğretim / Vakıf Üniversitesi",
    "özyeğin üniversitesi":    "Yükseköğretim / Vakıf Üniversitesi",
    "mef üniversitesi":        "Yükseköğretim / Vakıf Üniversitesi",
    "sabancı üniversitesi":    "Yükseköğretim / Araştırma Üniversitesi",
    "bilgi üniversitesi":      "Yükseköğretim / Vakıf Üniversitesi",
    "udemy türkiye":   "Eğitim Teknolojisi / Online Öğrenme",
    "benim hocam":     "Eğitim Teknolojisi / Sınav Hazırlık",
    # Lojistik / Kargo
    "ups türkiye":     "Lojistik / Uluslararası Kargo",
    "dhl türkiye":     "Lojistik / Uluslararası Kargo",
    "yurtiçi kargo":   "Lojistik / Yurt İçi Kargo",
    "aras kargo":      "Lojistik / Yurt İçi Kargo",
    "mng kargo":       "Lojistik / Yurt İçi Kargo",
    "horoz lojistik":  "Lojistik / Depolama & Dağıtım",
    "netlog":          "Lojistik / Tedarik Zinciri",
    "ekol lojistik":   "Lojistik / Uluslararası Karayolu",
    # Gayrimenkul
    "emlak konut":     "Gayrimenkul / Kamu GYO",
    "torunlar gyo":    "Gayrimenkul / AVM & Konut GYO",
    "ağaoğlu":         "Gayrimenkul / Konut Geliştirme",
}

# Sektör → Şirket büyüklüğü profili
SECTOR_SIZE_PROFILE: dict[str, tuple[str, int, int]] = {
    # (label, min_est, max_est)
    "Fintech / Ödeme Sistemleri":         ("201-500",  200,  600),
    "Fintech / Kredi Teknolojisi":         ("51-200",    50,  250),
    "Fintech / Ödeme Altyapısı":           ("51-200",    80,  300),
    "Fintech / Kredi Skorlama":            ("51-200",    60,  200),
    "Hızlı Teslimat / Q-Commerce":         ("500+",    2000, 8000),
    "E-ticaret / Marketplace":             ("500+",    3000,15000),
    "Mikromobilite / Paylaşımlı Ulaşım":   ("51-200",   100,  400),
    "Bankacılık / Özel Banka":             ("500+",    5000,20000),
    "Bankacılık / Kamu Bankası":           ("500+",   15000,60000),
    "Bankacılık / Yabancı Sermayeli":      ("500+",    3000,10000),
    "Bankacılık / Katılım Bankası":        ("201-500", 1000, 4000),
    "Telekomünikasyon / Mobil Operatör":   ("500+",    5000,15000),
    "Telekomünikasyon / Altyapı & Sabit Hat":("500+",  8000,30000),
    "Telekomünikasyon / İnternet Servisi": ("51-200",    50,  300),
    "Telekomünikasyon / MVNO":             ("11-50",     20,   80),
    "Teknoloji / Pazarlama Otomasyonu SaaS":("201-500", 800, 2000),
    "Teknoloji / Kurumsal ERP SaaS":       ("500+",    1500, 4000),
    "Teknoloji / Sistem Entegrasyonu":     ("201-500",  500, 1500),
    "Teknoloji / Telekomünikasyon Yazılımı":("51-200",  100,  500),
    "Teknoloji / Tedarik Zinciri SaaS":    ("51-200",    80,  300),
    "Teknoloji / Gayrimenkul Yönetim SaaS":("51-200",   60,  250),
    "İK Teknolojisi / İşe Alım Platformu": ("51-200",   100,  400),
    "Teknoloji / Hizmet Marketplace":      ("51-200",    80,  350),
    "Oyun / Mobil Oyun Geliştirme":        ("201-500",  300,  800),
    "Perakende / Gıda Zinciri":            ("500+",   10000,60000),
    "Perakende / Süpermarket Zinciri":     ("500+",    5000,20000),
    "Perakende / Moda & Hazır Giyim":      ("500+",    3000,12000),
    "Perakende / Elektronik Mağazacılık":  ("500+",    1000, 5000),
    "Danışmanlık / Denetim & Vergi (Big4)":("500+",    1500, 4000),
    "Danışmanlık / Strateji (MBB)":        ("51-200",    50,  250),
    "Danışmanlık / Teknoloji & Operasyon": ("500+",    2000, 6000),
    "İK Hizmetleri / Geçici İstihdam":     ("201-500",  200,  800),
    "İK Hizmetleri / İşe Alım & Outsourcing":("201-500",150, 600),
    "İK Hizmetleri / Yönetici Arama":      ("51-200",   50,  200),
    "Sağlık / Özel Hastane Grubu":         ("500+",    5000,20000),
    "Sağlık / Özel Hastane Zinciri":       ("500+",    2000, 8000),
    "Sağlık / Göz Hastalıkları Kliniği":   ("201-500",  300,  900),
    "Sağlık Teknolojisi / Randevu Platformu":("51-200",  80,  300),
    "Yükseköğretim / Vakıf Üniversitesi":  ("201-500",  500, 2000),
    "Yükseköğretim / Araştırma Üniversitesi":("201-500",800, 3000),
    "Eğitim Teknolojisi / Online Öğrenme": ("51-200",    50,  300),
    "Lojistik / Uluslararası Kargo":       ("500+",    2000, 8000),
    "Lojistik / Yurt İçi Kargo":           ("500+",    3000,10000),
    "Lojistik / Tedarik Zinciri":          ("201-500",  300, 1000),
    "Lojistik / Uluslararası Karayolu":    ("500+",    1500, 5000),
    "Gayrimenkul / Kamu GYO":              ("201-500",  500, 2000),
    "Gayrimenkul / AVM & Konut GYO":       ("201-500",  300, 1200),
    "Gayrimenkul / Konut Geliştirme":      ("201-500",  400, 1500),
    "Holding / Çok Sektörlü Sanayi":       ("500+",   10000,80000),
    "Üretim / Beyaz Eşya & Tüketim Elektroniği":("500+",8000,25000),
    "Otomotiv / Araç Üretimi":             ("500+",    5000,20000),
    "Üretim / Çimento & İnşaat Malzemeleri":("500+",   2000, 8000),
    "Üretim / Teknik Tekstil & Kompozit":  ("500+",    1500, 5000),
    "Üretim / Petrokimya":                 ("500+",    2000, 6000),
    "Üretim / Rafineri & Enerji":          ("500+",    3000,10000),
    "Enerji / Elektrik Dağıtım & Perakende":("500+",   2000, 7000),
    "FMCG / Gıda Üretimi":                 ("500+",    5000,20000),
    "FMCG / İçecek Üretimi":               ("500+",    3000,12000),
    "İnşaat / EPC Proje Yönetimi":         ("500+",    2000, 8000),
    "Teknoloji / Telekomünikasyon BT":     ("500+",    1000, 4000),
}

# Sektör → İngilizce ihtiyaç skoru (1-10) + gerekçe
SECTOR_ENGLISH_PROFILE: dict[str, tuple[int, int, str]] = {
    # (min_score, max_score, gerekçe_template)
    "Fintech / Ödeme Sistemleri":         (8, 10, "Uluslararası ödeme ağları (SWIFT, SEPA), Avrupa düzenleyici kurumlarıyla yazışmalar ve yabancı yatırımcı raporlamaları"),
    "Fintech / Kredi Teknolojisi":         (7,  9, "Global fintech ekosistemiyle entegrasyon, yabancı ortaklık görüşmeleri ve teknik dokümantasyon"),
    "Hızlı Teslimat / Q-Commerce":         (8, 10, "Çok ülkeli operasyon yönetimi, yabancı tedarikçi müzakereleri ve uluslararası yatırımcı ilişkileri"),
    "E-ticaret / Marketplace":             (8, 10, "Cross-border satıcı onboarding, global lojistik ortakları ve uluslararası genişleme operasyonları"),
    "Bankacılık / Özel Banka":             (8, 10, "Muhabir bankacılık, uluslararası kredi sendikasyonları, FATCA/CRS uyum yazışmaları"),
    "Bankacılık / Kamu Bankası":           (7,  9, "Uluslararası finansman anlaşmaları, AB fonları yazışmaları, yabancı muhabir banka ilişkileri"),
    "Bankacılık / Yabancı Sermayeli":      (9, 10, "Merkez şirketle (yabancı) sürekli İngilizce raporlama, global standart uyum ve audit süreçleri"),
    "Bankacılık / Katılım Bankası":        (7,  9, "İslami finans küresel standartları (AAOIFI), Körfez ülkeleri yatırımcı ilişkileri"),
    "Telekomünikasyon / Mobil Operatör":   (7,  9, "Roaming anlaşmaları, ekipman tedarikçi müzakereleri (Ericsson, Nokia vb.), GSMA standartları"),
    "Telekomünikasyon / Altyapı & Sabit Hat":(7,9, "Uluslararası transit bağlantı anlaşmaları, global fiber ortaklıklar"),
    "Teknoloji / Pazarlama Otomasyonu SaaS":(8,10, "Küresel müşteri portföyü, İngilizce ürün dokümantasyonu ve uluslararası satış döngüleri"),
    "Teknoloji / Kurumsal ERP SaaS":       (7,  9, "Uluslararası entegrasyon projeleri, yabancı holding müşterileri, teknik destek yazışmaları"),
    "Danışmanlık / Denetim & Vergi (Big4)":(9, 10, "Global metodoloji standartları, uluslararası proje ekipleri ve yabancı müşteri raporlamaları zorunlu İngilizce kullanımı gerektirir"),
    "Danışmanlık / Strateji (MBB)":        (9, 10, "Tüm proje deliverable'ları, yönetim sunumları ve global firma standartları İngilizce"),
    "Danışmanlık / Teknoloji & Operasyon": (8, 10, "Uluslararası proje metodolojileri, global müşteri teslimatlari ve offshore ekip koordinasyonu"),
    "İK Hizmetleri / Yönetici Arama":      (8, 10, "Uluslararası aday iletişimi, global yetkinlik değerlendirme araçları ve yabancı client raporları"),
    "Sağlık / Özel Hastane Grubu":         (7,  9, "Medikal turizm hasta iletişimi, JCI akreditasyon süreçleri, uluslararası sigorta şirketi yazışmaları"),
    "Oyun / Mobil Oyun Geliştirme":        (9, 10, "Tüm teknik ve yaratıcı süreçler İngilizce yürütülür; global yayıncı-platform (App Store, Google Play) ilişkileri"),
    "Yükseköğretim / Araştırma Üniversitesi":(8,10,"Uluslararası araştırma işbirlikleri, Erasmus+ koordinasyonu ve akademik yayınlar"),
    "Eğitim Teknolojisi / Online Öğrenme": (7,  9, "İçerik üretim süreçleri, global platform entegrasyonları ve uluslararası eğitmen iletişimi"),
    "Lojistik / Uluslararası Kargo":       (8, 10, "Gümrük dokümantasyonu, uluslararası taşıma hukuku yazışmaları ve yabancı hub koordinasyonu"),
    "Holding / Çok Sektörlü Sanayi":       (7,  9, "Çok uluslu iştiraki olan holdinglerde yönetim katmanında İngilizce raporlama ve yabancı ortak toplantıları"),
    "Üretim / Beyaz Eşya & Tüketim Elektroniği":(7,9,"Avrupa satış kanalları, Ar-Ge ortaklıkları ve tedarikçi müzakere süreçleri"),
    "Otomotiv / Araç Üretimi":             (8,  9, "OEM ortaklık görüşmeleri, Avrupa ihracat prosedürleri ve teknik standart yazışmaları"),
    "FMCG / Gıda Üretimi":                 (6,  8, "İhracat pazarlaması, uluslararası kalite sertifikasyonu (BRC, IFS) ve global distribütör yönetimi"),
    "Gayrimenkul / AVM & Konut GYO":       (6,  8, "Uluslararası kiracı (perakende zinciri) müzakereleri ve yabancı fon yatırımcı raporlaması"),
    "İnşaat / EPC Proje Yönetimi":         (8,  9, "Yurt dışı projeler, uluslararası konsorsiyum ortaklıkları ve FIDIC sözleşme yönetimi"),
    "Teknoloji / Telekomünikasyon BT":     (7,  9, "Uluslararası yazılım geliştirme ekipleri ve global müşteri entegrasyon projeleri"),
}

# Sektör → İngilizce ihtiyaç ağırlığı (lead score hesabı için)
SECTOR_ENGLISH_WEIGHT: dict[str, float] = {
    "Fintech":      1.10,
    "Bankacılık":   1.05,
    "Danışmanlık":  1.10,
    "Teknoloji":    1.08,
    "Lojistik":     1.05,
    "Sağlık":       0.95,
    "Perakende":    0.90,
    "Üretim":       0.88,
    "Holding":      0.92,
    "Eğitim":       0.85,
    "Gayrimenkul":  0.80,
    "İK":           0.95,
    "Oyun":         1.12,
    "Hızlı":        1.08,
    "E-ticaret":    1.05,
    "Telekomünikasyon": 0.98,
    "FMCG":         0.85,
    "Otomotiv":     0.90,
    "Enerji":       0.85,
}

# Kıdem çarpanı (lead score için)
SENIORITY_MULTIPLIER: dict[str, float] = {
    "C-Level":  1.20,
    "Director": 1.10,
    "Senior":   1.00,
    "Mid":      0.88,
    "Junior":   0.72,
}

# Sektöre özgü pain point şablonları
# {company} ve {seniority_context} placeholder'ları dinamik doldurulur
SECTOR_PAIN_POINTS: dict[str, list[str]] = {
    "Fintech": [
        "{company}'ın hızlı büyüme sürecinde yeni işe alınan ekip üyelerinin uluslararası ödeme standartları (SWIFT, SEPA, PSD2) terminolojisine hâkim olmadan yabancı banka ve regülatörlerle yazışma yapması kritik hataları beraberinde getiriyor.",
        "{company} bünyesinde Avrupa pazarına açılım sürecinde ürün ve teknik ekiplerin İngilizce toplantı, demo ve investor deck hazırlama konusundaki güven eksikliği ilerleyişi yavaşlatıyor.",
        "Uluslararası yatırımcı görüşmelerinde ve due diligence süreçlerinde {company} ekibinin İngilizce sözlü iletişim yetkinliğindeki boşluk, güven ve profesyonellik algısını olumsuz etkiliyor.",
    ],
    "Bankacılık": [
        "{company}'da muhabir bankacılık ve uluslararası sendikasyon kredisi süreçlerinde çalışan ekiplerin SWIFT mesajlaşma standartları ve İngilizce kredi dokümantasyonunu hatasız yönetmesi giderek daha kritik hale geliyor.",
        "Denetim ve uyum süreçlerinde (FATCA, CRS, Basel III) {company} çalışanlarının yabancı denetçiler ve muhabir bankalarla İngilizce yazışma kapasitesi yetersiz kaldığında ciddi operasyonel riskler doğuyor.",
        "{company}'ın yabancı sermayeli yapısı gereği merkez şirketle tüm raporlama süreçleri İngilizce yürütülüyor; yönetim kademesinden uyum ve risk ekiplerine kadar geniş bir İngilizce yetkinlik ihtiyacı var.",
    ],
    "Danışmanlık": [
        "{company}'da uluslararası proje ekiplerinde görev alan danışmanların küresel metodoloji dokümanlarını, vaka çalışmalarını ve müşteri sunumlarını akıcı İngilizce ile üretememesi kariyer ilerleyişini ve proje kalitesini doğrudan etkiliyor.",
        "{company} bünyesindeki yeni danışmanlar global firmadan gelen İngilizce proje brief'leri, deliverable template'leri ve müşteri yazışmalarını hızlı şekilde özümsemekte zorlanıyor.",
        "Yabancı müşteri toplantılarında ve global pitch süreçlerinde {company} danışmanlarının İngilizce gerçek zamanlı iletişim güveni, kazanma oranını doğrudan belirliyor.",
    ],
    "Teknoloji": [
        "{company}'ın global büyüme sürecinde ürün, pazarlama ve satış ekiplerinin İngilizce demo, onboarding materyali ve müşteri yazışmaları üretmedeki yetersizliği yeni pazarlara açılım hızını frenliyor.",
        "Teknik ekiplerin uluslararası konferanslarda sunum yapması, açık kaynak topluluklarına katkı sağlaması ve yabancı müşteriyle teknik görüşme yürütmesi için {company}'da sistematik bir İngilizce gelişim programına ihtiyaç var.",
        "{company}'da çalışanların İngilizce kaynaklara (teknik dokümantasyon, API referans, partner portalları) doğrudan erişim kapasitesi, ürün geliştirme döngüsünü ve öğrenme hızını belirliyor.",
    ],
    "Lojistik": [
        "{company}'ın uluslararası kargo ve gümrük süreçlerinde çalışan ekipler İngilizce teslim belgeleri, B/L, AWB gibi kritik dokümantasyonu hata yapmadan işlemek zorunda — bu yetkinlik eksikliği ciddi gecikme ve ceza risklerine yol açıyor.",
        "Yabancı havayolu, deniz taşımacılığı ve gümrük acenteleriyle {company} operasyon ekibinin günlük yazışmaları İngilizce yürütülüyor; gerçek zamanlı konuşma güveni olmadan iletişim kopuklukları kaçınılmaz oluyor.",
    ],
    "Sağlık": [
        "{company}'da medikal turizm süreçlerinde hasta ilişkileri ve uluslararası koordinasyon ekibinin İngilizce sözlü iletişim yetkinliği, hasta memnuniyetini ve referans gelirini doğrudan etkiliyor.",
        "JCI akreditasyon görüşmeleri, uluslararası tıp kongreleri ve yabancı sigorta şirketi yazışmalarında {company} klinik ve idari ekiplerinin İngilizce üretkenliği kurumsal imajı belirliyor.",
    ],
    "Oyun": [
        "{company} oyun stüdyosunda tüm teknik dokümantasyon, global yayıncı iletişimi (App Store, Google Play) ve uluslararası iş görüşmeleri İngilizce yürütülüyor; yeni işe alınan yeteneklerin bu ekosisteme hızla adapte olması kritik.",
        "Küresel oyun topluluklarında varlık göstermek, yabancı yatırımcı pitch'leri hazırlamak ve e-spor etkinliklerinde temsil için {company}'da İngilizce iletişim yetkinliği rekabet avantajının ayrılmaz bir parçası.",
    ],
    "Perakende": [
        "{company}'ın global marka tedarikçileri ve uluslararası franchise ortaklarıyla müzakere süreçlerinde İngilizce yazışma ve toplantı yetkinliği, ticari koşulları doğrudan etkiliyor.",
        "E-ticaret büyümesiyle birlikte {company}'ın cross-border satış ekipleri ve uluslararası alıcı/satıcı ilişki yönetiminde İngilizce iletişim kapasitesi operasyonel bir zorunluluk haline geliyor.",
    ],
    "Üretim": [
        "{company}'ın Avrupa ihracat kanallarındaki alıcılarla teknik yazışmalar, kalite sertifikasyonu süreçleri ve OEM görüşmelerinde mühendislik ve satış ekiplerinin İngilizce yetkinliği ihracat gelirine dönüşüyor.",
        "Global tedarik zinciri yönetiminde {company}'ın satın alma ve lojistik ekiplerinin yabancı tedarikçilerle İngilizce müzakere ve yazışma kapasitesi, maliyet ve temin süresini etkiliyor.",
    ],
    "default": [
        "{company}'ın büyüme sürecinde uluslararası paydaşlarla iletişim kurulmasını gerektiren projelerde ekiplerin İngilizce iletişim güveninin yetersizliği, fırsatların değerlendirilmesini zorlaştırıyor.",
        "{company}'da çalışanların İngilizce konuşma pratiğine sistematik erişimi olmadığından, yabancı müşteri/ortak toplantılarına hazırlık ciddi ölçüde zaman alıyor.",
    ],
}

# Sektöre göre outreach açısı şablonları
SECTOR_OUTREACH_ANGLES: dict[str, list[str]] = {
    "Fintech": [
        "Avrupa genişleme hedefleri veya yatırımcı pitch süreçleri üzerinden konuş — İngilizce yetkinliği bu aşamada somut ROI'a dönüşüyor.",
        "Uluslararası ödeme standartları (PSD2, SEPA) uyum süreçlerinde İngilizce konuşma pratiğinin operasyonel riski nasıl azalttığını somutlaştır.",
    ],
    "Bankacılık": [
        "Muhabir bankacılık veya yabancı sermaye iletişim süreçlerini referans ver — bunlar İngilizce ihtiyacının en somut kanıtı.",
        "Denetim süreçlerinde (FATCA, CRS) İngilizce belgelerle çalışmanın günlük iş yükü oluşturduğunu kabul et, çözümü ROI üzerinden sun.",
    ],
    "Danışmanlık": [
        "Global metodoloji akreditasyonu veya yabancı müşteri kazanımı odağında yaklaş — bunlar danışmanlık firmalarının en değer verdiği İngilizce kullanım alanları.",
        "Yeni konsültanların onboarding sürecini hızlandırmak için İngilizce yetkinliği bir verimlilik yatırımı olarak konumlandır.",
    ],
    "Teknoloji": [
        "Ürünü uluslararası pazara sunarken veya yabancı teknik ortaklarla çalışırken İngilizce konuşma güveninin hız ve kaliteye katkısını öne çıkar.",
        "Şirketin GitHub, Stack Overflow veya uluslararası konferanslardaki görünürlüğüne değin — teknik topluluklarda İngilizce varlık rekabet avantajı.",
    ],
    "Sağlık": [
        "Medikal turizm büyümesi ve JCI akreditasyon süreçleri çerçevesinde İngilizce iletişim yetkinliğini ROI'ye bağla.",
        "Uluslararası hasta memnuniyeti ve referans geliri üzerinden somut bir değer önerisi kur.",
    ],
    "Lojistik": [
        "Uluslararası kargo operasyonlarında dokümantasyon hataları ve gecikme maliyetleri üzerinden konuş — İngilizce yetkinlik direkt operasyonel tasarrufa dönüşüyor.",
        "Yabancı lojistik ortakları ve gümrük süreçlerindeki günlük İngilizce kullanımı somut bir problem olarak çerçevele.",
    ],
    "default": [
        "Çalışan gelişim bütçesinin İngilizce eğitimine ayrılan kısmının ölçülebilir iş çıktısına nasıl dönüştüğünü ROI diliyle anlat.",
        "Şirketin uluslararası büyüme hedeflerini referans vererek İngilizce yetkinliğini stratejik bir HR yatırımı olarak konumlandır.",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
#  YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────────────────────────────────────

def _company_key(company: str) -> str:
    """Şirket adını lookup için normalize eder."""
    return company.lower().strip()


def get_sector(company: str) -> str:
    """
    Şirket adından sektör belirler.
    1. Tam eşleşme (COMPANY_SECTOR_MAP)
    2. Keyword eşleşmesi
    3. Default fallback
    """
    key = _company_key(company)

    # 1. Tam eşleşme
    if key in COMPANY_SECTOR_MAP:
        return COMPANY_SECTOR_MAP[key]

    # 2. Kısmi eşleşme (şirket adı birden fazla kelimeden oluşabilir)
    for known_company, sector in COMPANY_SECTOR_MAP.items():
        if known_company in key or key in known_company:
            return sector

    # 3. Keyword fallback
    keyword_map = {
        "bank": "Bankacılık / Özel Banka",
        "finans": "Bankacılık / Özel Banka",
        "sigorta": "Sigorta / Finansal Hizmetler",
        "yatırım": "Finans / Yatırım",
        "kargo": "Lojistik / Yurt İçi Kargo",
        "lojistik": "Lojistik / Tedarik Zinciri",
        "nakliyat": "Lojistik / Uluslararası Taşımacılık",
        "hastane": "Sağlık / Özel Hastane Grubu",
        "klinik": "Sağlık / Klinik Hizmetler",
        "sağlık": "Sağlık / Sağlık Hizmetleri",
        "üniversite": "Yükseköğretim / Vakıf Üniversitesi",
        "okul": "Eğitim / K-12",
        "eğitim": "Eğitim Teknolojisi / Online Öğrenme",
        "yazılım": "Teknoloji / Kurumsal Yazılım",
        "teknoloji": "Teknoloji / BT Hizmetleri",
        "bilişim": "Teknoloji / BT Hizmetleri",
        "market": "Perakende / Süpermarket Zinciri",
        "mağaza": "Perakende / Mağazacılık",
        "holding": "Holding / Çok Sektörlü Sanayi",
        "grup": "Holding / Çok Sektörlü Sanayi",
        "inşaat": "İnşaat / EPC Proje Yönetimi",
        "yapı": "İnşaat / Konut Geliştirme",
        "enerji": "Enerji / Elektrik Dağıtım & Perakende",
        "petrol": "Enerji / Petrol & Gaz",
        "tekstil": "Üretim / Tekstil",
        "gıda": "FMCG / Gıda Üretimi",
        "ilaç": "Sağlık / İlaç & Biyoteknoloji",
        "danışmanlık": "Danışmanlık / Yönetim Danışmanlığı",
        "medya": "Medya / Dijital Medya",
        "reklam": "Pazarlama / Dijital Reklam",
    }
    for kw, sector in keyword_map.items():
        if kw in key:
            return sector

    return "Teknoloji / BT Hizmetleri"  # bilinmeyen şirketler için makul default


def _get_sector_family(sector: str) -> str:
    """'Fintech / Ödeme Sistemleri' → 'Fintech' ana ailesi."""
    return sector.split("/")[0].strip()


def get_size_profile(sector: str) -> tuple[str, int]:
    """Sektörden şirket büyüklük label'ı ve tahmini çalışan sayısı döner."""
    profile = SECTOR_SIZE_PROFILE.get(sector)
    if profile:
        label, min_e, max_e = profile
        est = random.randint(min_e, max_e)
        return label, est
    return "201-500", random.randint(200, 600)


def get_english_profile(sector: str, company: str, seed: int) -> tuple[int, str]:
    """
    Sektörden İngilizce ihtiyaç skoru (1-10) ve gerekçe döner.
    seed: aynı şirket için tutarlı sonuç.
    """
    family = _get_sector_family(sector)
    profile = SECTOR_ENGLISH_PROFILE.get(sector) or SECTOR_ENGLISH_PROFILE.get(
        next((k for k in SECTOR_ENGLISH_PROFILE if k.startswith(family)), ""), None
    )
    if profile:
        min_s, max_s, reason_template = profile
    else:
        min_s, max_s = 5, 8
        reason_template = f"{sector} sektöründe uluslararası iş ilişkileri ve yabancı ortaklıklar"

    # Seed ile tutarlı ama farklı skor
    rng = random.Random(seed)
    score = rng.randint(min_s, max_s)
    reason = reason_template  # şirket adı zaten dışarıdan ekleniyor
    return score, reason


def get_pain_point(sector: str, company: str, seed: int) -> str:
    """Sektöre özgü, şirket adını içeren pain point metni seçer."""
    family = _get_sector_family(sector)
    candidates = SECTOR_PAIN_POINTS.get(family) or SECTOR_PAIN_POINTS["default"]
    rng = random.Random(seed + 1)
    template = rng.choice(candidates)
    return template.format(company=company, seniority_context="")


def get_outreach_angle(sector: str, seed: int) -> str:
    """Sektöre özgü outreach açısı seçer."""
    family = _get_sector_family(sector)
    candidates = SECTOR_OUTREACH_ANGLES.get(family) or SECTOR_OUTREACH_ANGLES["default"]
    rng = random.Random(seed + 2)
    return rng.choice(candidates)


def compute_lead_score(
    sector:    str,
    seniority: str,
    company:   str,
    english_score: int,
    seed:      int,
) -> int:
    """
    Çok faktörlü lead skoru hesapla (65-95 aralığı).

    Faktörler:
      - Sektör ağırlığı (fintech/danışmanlık yüksek, gayrimenkul düşük)
      - Kıdem çarpanı  (C-Level / Director daha değerli)
      - İngilizce ihtiyacı (yüksek ihtiyaç = yüksek skor)
      - Şirkete özgü jitter (gerçekçilik için ±5)
    """
    family  = _get_sector_family(sector)
    eng_w   = next((v for k, v in SECTOR_ENGLISH_WEIGHT.items() if k in family), 1.0)
    sen_mul = SENIORITY_MULTIPLIER.get(seniority, 1.0)

    # Baz skor: İngilizce ihtiyaç skoru ×10 normalleştirilmiş
    base = (english_score / 10) * 80

    # Faktör uygulamaları
    score = base * eng_w * sen_mul

    # Jitter: aynı şirket için tutarlı ama unique
    rng   = random.Random(seed + 3)
    jitter = rng.uniform(-4, 6)
    score += jitter

    # [65, 95] aralığına sıkıştır
    return max(65, min(95, round(score)))


def _seed_for(company: str, name: str) -> int:
    """Şirket + isim için deterministik seed üret."""
    raw = f"{company.lower()}::{name.lower()}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


# ─────────────────────────────────────────────────────────────────────────────
#  ANA PUBLIC API — claude_client ve 03_outreach_writer bu fonksiyonları çağırır
# ─────────────────────────────────────────────────────────────────────────────

def build_enrichment_mock(
    company:   str,
    full_name: str,
    title:     str,
    seniority: str,
) -> dict:
    """
    Şirket ve kişi bilgisinden eksiksiz enrichment JSON'u üretir.
    claude_client._mock_response()'ın yerini alır.

    Returns:
        dict: Enrichment şemasıyla tam uyumlu veri
    """
    seed     = _seed_for(company, full_name)
    sector   = get_sector(company)
    size_label, size_est = get_size_profile(sector)
    eng_score, eng_reason = get_english_profile(sector, company, seed)
    pain_point  = get_pain_point(sector, company, seed)
    outreach_angle = get_outreach_angle(sector, seed)
    lead_score  = compute_lead_score(sector, seniority, company, eng_score, seed)

    return {
        "industry":            sector,
        "company_size":        size_label,
        "company_size_est":    size_est,
        "pain_point":          pain_point,
        "english_need_score":  eng_score,
        "english_need_reason": f"{company} özelinde: {eng_reason}.",
        "outreach_angle":      outreach_angle,
        "lead_score":          lead_score,
    }


def build_linkedin_dm_mock(lead: dict) -> dict:
    """
    Şirket + sektör + kıdem'e göre farklılaştırılmış LinkedIn DM üretir.
    03_outreach_writer._mock_linkedin_dm()'ın yerini alır.
    """
    first    = lead.get("first_name", "Merhaba")
    company  = lead.get("company", "şirketiniz")
    title    = lead.get("title", "")
    industry = lead.get("industry") or get_sector(company)
    seed     = _seed_for(company, first)
    family   = _get_sector_family(industry)

    # Sektöre özgü açılış gözlemi
    sector_hooks = {
        "Fintech":         f"{company}'ın uluslararası ödeme ağı genişlemesini ve Avrupa pazarı hamlelerini takip ediyorum",
        "Bankacılık":      f"{company}'ın muhabir bankacılık ağını ve uluslararası kredi operasyonlarını yakından izliyorum",
        "Danışmanlık":     f"{company}'ın global proje portföyünü ve yeni pazar kazanımlarını takip ediyorum",
        "Teknoloji":       f"{company}'ın ürün büyümesini ve uluslararası genişleme stratejisini izliyorum",
        "Hızlı":           f"{company}'ın çok ülkeli operasyon altyapısını ve büyüme temposunu takip ediyorum",
        "E-ticaret":       f"{company}'ın cross-border marketplace büyümesini ve satıcı ekosistemini izliyorum",
        "Lojistik":        f"{company}'ın uluslararası kargo ve gümrük operasyonlarını yakından takip ediyorum",
        "Sağlık":          f"{company}'ın medikal turizm büyümesini ve uluslararası hasta portföyünü izliyorum",
        "Oyun":            f"{company}'ın global oyun yayıncısı ortaklıklarını ve store performansını takip ediyorum",
        "Telekomünikasyon": f"{company}'ın altyapı yatırımlarını ve kurumsal müşteri portföyünü izliyorum",
        "Perakende":       f"{company}'ın global tedarik ağını ve uluslararası marka büyümesini takip ediyorum",
        "Üretim":          f"{company}'ın Avrupa ihracat stratejisini ve OEM ortaklıklarını izliyorum",
        "Holding":         f"{company}'ın uluslararası iştiraki büyümesini ve çok bölgeli operasyonlarını takip ediyorum",
    }
    hook = sector_hooks.get(family, f"{company}'ın büyüme hikayesini ve uluslararası adımlarını takip ediyorum")

    # Kıdem bazlı soru & ton
    is_decision_maker = any(
        kw in title.lower()
        for kw in ["direktör", "müdür", "director", "vp", "chief", "cpo", "chro", "head"]
    )

    rng = random.Random(seed + 10)
    if is_decision_maker:
        pain_questions = [
            f"Bu büyüme temposunda ekibinizin İngilizce iletişim yetkinliği yabancı paydaşlarla görüşmelerde ne kadar kritik bir rol oynuyor?",
            f"Uluslararası süreçlerde çalışanların İngilizce konuşma güveni HR gündeminde ne kadar yer tutuyor?",
            f"Bu süreçte ekibinizin İngilizce müzakere ve yazışma kapasitesi operasyonel bir darboğaz oluyor mu?",
        ]
        ctas = [
            "Bu konuda 15 dakikalık stratejik bir fikir alışverişi yapabilir miyiz?",
            "Benzer şirketlerden referans vaka çalışmalarını 15 dakikada paylaşabilir miyim?",
            "Kısa bir görüşmede nasıl çözdüklerini aktarabilir miyim?",
        ]
    else:
        pain_questions = [
            f"{industry.split('/')[0].strip()} sektöründeki HR profesyonellerinden duyduğumuz en büyük zorluk: uluslararası süreçlerde çalışanların İngilizce konuşma pratiği — {company}'da da benzer bir tablo var mı?",
            f"Ekip içi gelişim programlarında İngilizce konuşma pratiği {company}'da ne kadar yer buluyor?",
            f"İK tarafında çalışan gelişimini planlarken İngilizce yetkinliği öncelikli gündem maddelerinizden biri mi?",
        ]
        ctas = [
            "Nasıl çözdüklerini anlatan hızlı bir demo ayarlayabilir miyiz?",
            "10 dakikalık bir görüşmede somut örnekleri paylaşabilir miyim?",
            "Benzer şirketlerdeki uygulamayı kısaca aktarabilir miyim?",
        ]

    body = (
        f"Merhaba {first}, {hook}. "
        f"{rng.choice(pain_questions)} "
        f"Konuşarak Öğren olarak {industry.split('/')[0].strip()} sektöründen "
        f"referans vakalarımızla AI destekli kurumsal İngilizce pratiği sunuyoruz."
    )

    return {
        "message_type": "linkedin_dm",
        "subject":      None,
        "body":         body,
        "cta":          rng.choice(ctas),
        "personalization_notes": (
            f"Şirket referansı ({company}), "
            f"sektöre özgü bağlam ({industry}), "
            f"kıdem bazlı ton ({title})"
        ),
    }


def build_cold_email_mock(lead: dict) -> dict:
    """
    Şirket + sektör + kıdem'e göre farklılaştırılmış Cold Email üretir.
    03_outreach_writer._mock_cold_email()'ın yerini alır.
    """
    first    = lead.get("first_name", "")
    company  = lead.get("company", "şirketiniz")
    title    = lead.get("title", "")
    industry = lead.get("industry") or get_sector(company)
    city     = lead.get("company_city", "")
    seed     = _seed_for(company, first)
    family   = _get_sector_family(industry)
    rng      = random.Random(seed + 20)

    # Sektöre özgü konu satırları
    subject_templates = {
        "Fintech":     [
            f"{company} ekibinin Avrupa müzakere pratiği",
            f"{company} — yatırımcı pitch İngilizcesi için bir fikir",
            f"{company} büyüme ekibine soru",
        ],
        "Bankacılık":  [
            f"{company} çalışanlarının muhabir banka İngilizcesi",
            f"{company} — uluslararası süreçlerde İngilizce yetkinlik",
            f"{company} ekibi için İngilizce pratik önerisi",
        ],
        "Danışmanlık": [
            f"{company} danışmanlarının global proje İngilizcesi",
            f"{company} — yeni konsültanların İngilizce onboarding'i",
            f"{company} yabancı müşteri pitch'i için bir fikir",
        ],
        "Teknoloji":   [
            f"{company}'ın global ekibi nasıl İngilizce pratik ediyor?",
            f"{company} — ürün demolarında İngilizce güveni",
            f"{company} teknik ekibi için İngilizce pratik fikri",
        ],
        "Sağlık":      [
            f"{company} medikal turizm ekibine soru",
            f"{company} — uluslararası hasta iletişiminde İngilizce",
            f"{company} için İngilizce pratik önerisi",
        ],
        "Lojistik":    [
            f"{company} operasyon ekibine İngilizce pratik sorusu",
            f"{company} — gümrük yazışmalarında İngilizce yetkinlik",
            f"{company} uluslararası ekibine bir öneri",
        ],
        "default":     [
            f"{company} ekibi için İngilizce pratik fikri",
            f"{company} çalışan gelişimine dair bir soru",
            f"{company} bünyesinde İngilizce yetkinlik — bir gözlem",
        ],
    }
    subjects = subject_templates.get(family, subject_templates["default"])
    subject  = rng.choice(subjects)

    # P1: Araştırma yapmış izlenimi veren açılış
    p1_templates = {
        "Fintech":     f"{company}'ın uluslararası büyüme hızını ve Avrupa pazarına açılım adımlarını takip ediyorum; bu ölçekte büyüyen fintech ekiplerinde İngilizce iletişim kapasitesi çok hızlı kritik bir darboğaza dönüşüyor.",
        "Bankacılık":  f"{company}'ın muhabir bankacılık ve uluslararası kredi operasyonlarını izliyorum; bu süreçlerin yönetimi İngilizce yazışma yetkinliğini her seviyede zorunlu kılıyor.",
        "Danışmanlık": f"{company}'ın global proje portföyünü ve yeni pazar kazanımlarını takip ediyorum; bu ölçekte büyüyen danışmanlık firmalarında İngilizce proje yürütme kapasitesi doğrudan gelir yaratıyor.",
        "Teknoloji":   f"{company}'ın ürün büyümesini ve uluslararası müşteri tabanını izliyorum; global satış ve teknik süreçlerde İngilizce iletişim hızı ile kalitesi büyümeyi doğrudan etkiliyor.",
        "Sağlık":      f"{company}'ın medikal turizm büyümesini ve uluslararası hasta portföyünü takip ediyorum; bu alanda İngilizce iletişim yetkinliği hasta memnuniyetini ve referans gelirini doğrudan belirliyor.",
        "Lojistik":    f"{company}'ın uluslararası kargo operasyonlarını ve gümrük süreçlerini takip ediyorum; bu alanda İngilizce dokümantasyon hatalarının operasyonel maliyeti çok yüksek olabiliyor.",
        "Oyun":        f"{company}'ın küresel yayıncı ortaklıklarını ve App Store performansını izliyorum; global oyun pazarında İngilizce iletişim yetkinliği her fonksiyonda rekabet avantajı.",
        "default":     f"{company}'ın büyüme hikayesini ve uluslararası adımlarını takip ediyorum; bu ölçekte büyüyen şirketlerde ekiplerin İngilizce iletişim kapasitesi hızla kritik bir meseleye dönüşüyor.",
    }
    p1 = p1_templates.get(family, p1_templates["default"])

    # P2: Sektörel pain point + veri
    pain = lead.get("pain_point") or get_pain_point(industry, company, seed)
    # Pain'den ilk cümleyi al
    p2_base  = pain.split(".")[0] + "."
    stat_map = {
        "Fintech":     "%72'si",
        "Bankacılık":  "%65'i",
        "Danışmanlık": "%78'i",
        "Teknoloji":   "%68'i",
        "Sağlık":      "%61'i",
        "Lojistik":    "%64'ü",
        "default":     "%68'i",
    }
    stat = stat_map.get(family, "%68'i")
    p2 = (
        f"{p2_base} "
        f"{industry.split('/')[0].strip()} sektöründe yaptığımız araştırmaya göre "
        f"çalışanların {stat} İngilizce konuşma pratiğini en öncelikli gelişim alanı olarak görüyor."
    )

    # P3: CTA
    is_dm = any(kw in title.lower() for kw in ["direktör", "müdür", "director", "vp", "chief"])
    if is_dm:
        p3 = "Konuşarak Öğren olarak bu boşluğu AI konuşma pratiği + canlı ders hibrid modeliyle kapatıyoruz; 15 dakikalık bir görüşmede somut vaka çalışmalarını paylaşabilir miyim?"
    else:
        p3 = "Konuşarak Öğren olarak bu boşluğu AI konuşma pratiği + canlı ders hibrid modeliyle kapatıyoruz; 10 dakika konuşabilir miyiz?"

    imza = "Konuşarak Öğren Ekibi\nkonusarakogren.com"
    body = f"{p1}\n\n{p2}\n\n{p3}\n\n{imza}"

    return {
        "message_type": "cold_email",
        "subject":       subject,
        "body":          body,
        "cta":           p3.split(";")[-1].strip() if ";" in p3 else p3,
        "personalization_notes": (
            f"Sektöre özgü konu satırı ({family}), "
            f"şirket büyüme gözlemi ({company}), "
            f"ünvan bazlı CTA tonu ({title})"
        ),
    }
