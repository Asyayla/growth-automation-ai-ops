"""
pipeline/02_enricher.py
------------------------
Lead Zenginleştirme Aşaması — her lead için AI analizi çalıştırır.

Akış:
  1. data/raw/leads_raw.csv oku (veya SQLite leads tablosu)
  2. Her lead için Claude API'ye zenginleştirme isteği gönder
  3. JSON yanıtı parse edip Enrichment nesnesine dönüştür
  4. SQLite 'enrichments' tablosuna kaydet
  5. leads tablosundaki status'u 'enriched' yap
  6. data/enriched/leads_enriched.csv olarak export et

Standalone çalıştırma:
    PYTHONPATH=src python src/pipeline/02_enricher.py
    PYTHONPATH=src python src/pipeline/02_enricher.py --limit 5
    PYTHONPATH=src python src/pipeline/02_enricher.py --all
"""

import sys
import time
import argparse
import csv
from pathlib import Path
from typing import Optional

import pandas as pd

# Proje kök dizinini path'e ekle (standalone çalışma için)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.claude_client import ClaudeClient, ClaudeAPIError
from ai.prompts import SYSTEM_ENRICHMENT, user_enrichment
from db.database import Database
from db.models import Enrichment
from utils.config import config
from utils.logger import (
    get_logger,
    log_pipeline_start,
    log_pipeline_end,
    log_pipeline_error,
    log_progress,
)

log = get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  ZENGİNLEŞTİRME MANTIĞI
# ─────────────────────────────────────────────────────────────────────────────

def enrich_single_lead(
    lead: dict,
    client: ClaudeClient,
) -> Optional[Enrichment]:
    """
    Tek bir lead için Claude API'ye zenginleştirme isteği gönderir.

    Args:
        lead   : SQLite'tan gelen lead dict'i
        client : ClaudeClient instance

    Returns:
        Enrichment nesnesi veya hata durumunda None
    """
    lead_id   = lead["id"]
    full_name = lead.get("full_name") or f"{lead['first_name']} {lead['last_name']}"

    log.debug(f"  🔍 Zenginleştiriliyor: {full_name} @ {lead['company']}")

    # Kullanıcı prompt'unu oluştur
    prompt = user_enrichment(
        full_name    = full_name,
        title        = lead.get("title", ""),
        seniority    = lead.get("seniority", ""),
        company      = lead.get("company", ""),
        company_city = lead.get("company_city", "İstanbul"),
        linkedin_url = lead.get("linkedin_url"),
        email        = lead.get("email"),
    )

    try:
        raw_data = client.complete_json(
            system_prompt=SYSTEM_ENRICHMENT,
            user_prompt=prompt,
            max_tokens=600,
        )

        # API hata yanıtı döndüyse
        if "error" in raw_data:
            log.warning(f"    ⚠️  JSON parse hatası — lead_id={lead_id}: {raw_data['error']}")
            return _fallback_enrichment(lead_id, raw_data.get("raw", ""))

        # Enrichment nesnesini oluştur
        enrichment = Enrichment(
            lead_id             = lead_id,
            industry            = _safe_str(raw_data.get("industry")),
            company_size        = _safe_str(raw_data.get("company_size")),
            company_size_est    = _safe_int(raw_data.get("company_size_est")),
            pain_point          = _safe_str(raw_data.get("pain_point")),
            english_need_score  = _safe_int(raw_data.get("english_need_score"), clamp=(1, 10)),
            english_need_reason = _safe_str(raw_data.get("english_need_reason")),
            outreach_angle      = _safe_str(raw_data.get("outreach_angle")),
            lead_score          = _safe_int(raw_data.get("lead_score"), clamp=(1, 100)),
            ai_model_used       = config.claude_model if not client.mock else "mock",
        )

        log.debug(
            f"    ✅ {full_name} → "
            f"sektör: {enrichment.industry} | "
            f"İng skoru: {enrichment.english_need_score}/10 | "
            f"lead skoru: {enrichment.lead_score}/100"
        )
        return enrichment

    except ClaudeAPIError as e:
        log.error(f"    ❌ API hatası — {full_name}: {e}")
        return None
    except Exception as e:
        log.error(f"    ❌ Beklenmedik hata — {full_name}: {e}")
        return None


def _fallback_enrichment(lead_id: int, raw_text: str = "") -> Enrichment:
    """API yanıtı parse edilemediğinde minimal fallback döner."""
    return Enrichment(
        lead_id             = lead_id,
        industry            = "Bilinmiyor",
        company_size        = "51-200",
        company_size_est    = 100,
        pain_point          = "Analiz yapılamadı — manuel inceleme gerekli.",
        english_need_score  = 5,
        english_need_reason = "Otomatik analiz başarısız.",
        outreach_angle      = "Genel kurumsal İngilizce ihtiyacı açısından yaklaş.",
        lead_score          = 40,
        ai_model_used       = "fallback",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  TİP GÜVENLİK YARDIMCILARI
# ─────────────────────────────────────────────────────────────────────────────

def _safe_str(val, default: str = "") -> str:
    if val is None:
        return default
    return str(val).strip()[:500]          # 500 karakter sınırı


def _safe_int(
    val,
    default: int = 0,
    clamp: Optional[tuple] = None,
) -> int:
    try:
        result = int(float(str(val)))
        if clamp:
            result = max(clamp[0], min(clamp[1], result))
        return result
    except (ValueError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
#  CSV EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_enriched_csv(db: Database, output_path: Path) -> int:
    """
    leads + enrichments JOIN sonucunu CSV'ye yazar.

    Returns:
        int: Yazılan satır sayısı
    """
    rows = db.get_enriched_leads_full()
    if not rows:
        log.warning("Export için zenginleştirilmiş lead bulunamadı.")
        return 0

    df = pd.DataFrame(rows)

    # Sütun sırası — okunabilirlik için
    priority_cols = [
        "id", "full_name", "title", "seniority", "company", "company_city",
        "industry", "company_size", "company_size_est",
        "english_need_score", "lead_score",
        "pain_point", "english_need_reason", "outreach_angle",
        "linkedin_url", "email", "status",
    ]
    existing_cols  = [c for c in priority_cols if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + remaining_cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    log.success(f"💾 Enriched CSV kaydedildi → {output_path}  ({len(df)} satır)")
    return len(df)


# ─────────────────────────────────────────────────────────────────────────────
#  ÖZET RAPOR (terminal)
# ─────────────────────────────────────────────────────────────────────────────

def print_enrichment_summary(db: Database, enriched: list[Enrichment]) -> None:
    """İşlem sonrası terminale özet istatistik yazdırır."""
    if not enriched:
        return

    scores  = [e.lead_score for e in enriched if e.lead_score]
    eng_scr = [e.english_need_score for e in enriched if e.english_need_score]
    sectors = [e.industry for e in enriched if e.industry and e.industry != "Bilinmiyor"]

    avg_lead = sum(scores) / len(scores) if scores else 0
    avg_eng  = sum(eng_scr) / len(eng_scr) if eng_scr else 0

    # Sektör dağılımı
    sector_counts: dict = {}
    for s in sectors:
        sector_counts[s] = sector_counts.get(s, 0) + 1
    top_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    log.info(f"\n{'═' * 55}")
    log.info(f"  📊  ZENGİNLEŞTİRME ÖZET RAPORU")
    log.info(f"{'═' * 55}")
    log.info(f"  İşlenen lead      : {len(enriched)}")
    log.info(f"  Ort. lead skoru   : {avg_lead:.1f}/100")
    log.info(f"  Ort. İng. ihtiyacı: {avg_eng:.1f}/10")
    log.info(f"  En yüksek skor    : {max(scores) if scores else 0}/100")
    if top_sectors:
        log.info(f"  Başlıca sektörler : {', '.join(f'{s}({c})' for s, c in top_sectors)}")
    log.info(f"{'═' * 55}\n")

    # Yüksek öncelikli leadleri vurgula
    high_priority = [e for e in enriched if (e.lead_score or 0) >= 70]
    if high_priority:
        log.info(f"  🎯  YÜKSEK ÖNCELİKLİ LEADLER (skor ≥ 70):")
        for e in sorted(high_priority, key=lambda x: x.lead_score or 0, reverse=True):
            lead = db.get_lead_by_id(e.lead_id)
            if lead:
                name = lead.get("full_name") or f"{lead['first_name']} {lead['last_name']}"
                log.info(
                    f"    ⭐  {name:<25} | "
                    f"{lead.get('company',''):<20} | "
                    f"Skor: {e.lead_score}/100"
                )


# ─────────────────────────────────────────────────────────────────────────────
#  ANA ÇALIŞTIRICI
# ─────────────────────────────────────────────────────────────────────────────

def run(limit: Optional[int] = 3, skip_existing: bool = True) -> int:
    """
    Pipeline orchestrator'dan veya standalone olarak çağrılır.

    Args:
        limit         : Kaç lead zenginleştirilecek (None = hepsi)
        skip_existing : Zaten zenginleştirilmiş leadları atla (varsayılan: True)

    Returns:
        int: Başarıyla zenginleştirilen lead sayısı
    """
    log_pipeline_start("02 — Lead Zenginleştirme")

    db     = Database(config.db_path)
    client = ClaudeClient()   # API key yoksa otomatik mock moda geçer

    # ── 1. Zenginleştirilecek leadleri belirle ────────────────────────────────
    all_leads = db.get_all_leads(status="new") if skip_existing else db.get_all_leads()

    if not all_leads:
        # 'new' status yoksa tüm leadlere bak
        all_leads = db.get_all_leads()
        if not all_leads:
            log.error("Veritabanında hiç lead bulunamadı. Önce 01_data_generator çalıştır.")
            return 0

    # Limit uygula
    target_leads = all_leads[:limit] if limit else all_leads
    total        = len(target_leads)

    mode_tag = f"MOCK" if client.mock else "CLAUDE API"
    log.info(f"📋 {total} lead zenginleştirilecek | Mod: {mode_tag}")
    if limit and limit < len(all_leads):
        log.info(f"   (toplam {len(all_leads)} leadden ilk {limit} alındı — test modu)")

    # ── 2. Her lead için AI çağrısı ───────────────────────────────────────────
    enriched_list: list[Enrichment] = []
    failed_ids:    list[int]        = []

    for idx, lead in enumerate(target_leads, start=1):
        log_progress(idx, total, f"{lead.get('full_name', lead['first_name'])} @ {lead['company']}")

        enrichment = enrich_single_lead(lead, client)

        if enrichment:
            try:
                db.upsert_enrichment(enrichment)          # DB'ye yaz
                enriched_list.append(enrichment)
            except Exception as e:
                log.error(f"DB yazma hatası — lead_id={enrichment.lead_id}: {e}")
                failed_ids.append(lead["id"])
        else:
            failed_ids.append(lead["id"])

        # Rate limit koruması: gerçek API kullanıyorsa bekle
        if not client.mock and idx < total:
            time.sleep(config.enrich_delay_sec)

    # ── 3. Sonuçları raporla ──────────────────────────────────────────────────
    if failed_ids:
        log.warning(f"⚠️  {len(failed_ids)} lead zenginleştirilemedi: {failed_ids}")

    print_enrichment_summary(db, enriched_list)

    # ── 4. CSV export ─────────────────────────────────────────────────────────
    exported = export_enriched_csv(db, config.leads_enriched_path)

    log_pipeline_end("02 — Lead Zenginleştirme", len(enriched_list), "lead")
    return len(enriched_list)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI ARGÜMANLAR (standalone kullanım için)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Lead zenginleştirme pipeline aşaması",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python 02_enricher.py                  # İlk 3 lead (varsayılan)
  python 02_enricher.py --limit 10       # İlk 10 lead
  python 02_enricher.py --all            # Tüm leadler
  python 02_enricher.py --no-skip        # Zenginleştirilmişleri de yenile
        """
    )
    parser.add_argument(
        "--limit", type=int, default=3,
        help="Zenginleştirilecek lead sayısı (varsayılan: 3)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Tüm leadleri zenginleştir (--limit'i geçersiz kılar)"
    )
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Daha önce zenginleştirilmiş leadları da yeniden işle"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args        = _parse_args()
    limit_val   = None if args.all else args.limit
    skip_val    = not args.no_skip
    run(limit=limit_val, skip_existing=skip_val)
