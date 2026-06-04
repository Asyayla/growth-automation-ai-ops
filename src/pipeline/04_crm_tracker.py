"""
pipeline/04_crm_tracker.py
---------------------------
CRM Durum Takibi & Pipeline Analitik Aşaması.

Görevleri:
  1. Tüm mesajı hazır leadlerin crm_status'unu 'contacted' aşamasına taşı
  2. Enrichment verilerinden lead_score'ları crm_status'a senkronize et
  3. Lead öncelik (priority) etiketlerini skora göre ata
  4. Pipeline geneli özet istatistikleri hesapla ve döndür
  5. Sonraki follow-up tarihlerini otomatik ata (demo için)

Standalone:
    PYTHONPATH=src python src/pipeline/04_crm_tracker.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from db.database import Database
from db.models import CRMStatus
from utils.config import config
from utils.logger import (
    get_logger,
    log_pipeline_start,
    log_pipeline_end,
)

log = get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  ÖNCELİK ETİKETLEME
# ─────────────────────────────────────────────────────────────────────────────

def _score_to_priority(score: int) -> str:
    """Lead skorunu öncelik etiketine dönüştür."""
    if score >= 80:  return "urgent"
    if score >= 65:  return "high"
    if score >= 45:  return "medium"
    return "low"


def _next_followup_date(priority: str) -> str:
    """Önceliğe göre follow-up tarihi hesapla."""
    days_map = {"urgent": 1, "high": 2, "medium": 4, "low": 7}
    days = days_map.get(priority, 3)
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
#  SENKRONIZASYON
# ─────────────────────────────────────────────────────────────────────────────

def sync_scores_to_crm(db: Database) -> int:
    """
    Enrichment tablosundaki lead_score değerlerini
    crm_status tablosuna yansıt ve öncelikleri güncelle.

    Returns:
        int: Güncellenen kayıt sayısı
    """
    enriched = db.get_enriched_leads_full()
    updated  = 0

    for lead in enriched:
        lead_id = lead["id"]
        score   = lead.get("lead_score") or 0
        priority = _score_to_priority(score)
        followup = _next_followup_date(priority)

        with db.connection() as conn:
            conn.execute(
                """
                UPDATE crm_status
                SET
                    lead_score       = ?,
                    priority         = ?,
                    next_followup_at = ?,
                    updated_at       = datetime('now','localtime')
                WHERE lead_id = ?
                """,
                (score, priority, followup, lead_id),
            )
        updated += 1

    log.debug(f"  🔄  {updated} lead'in CRM skoru senkronize edildi")
    return updated


def advance_messaged_leads(db: Database) -> int:
    """
    Status'u 'messaged' olan leadleri CRM'de
    'message_ready' → 'contacted' aşamasına ilerlet.
    contact_attempts sayacını artır.

    Returns:
        int: İlerlenen lead sayısı
    """
    messaged_leads = db.get_all_leads(status="messaged")
    advanced = 0

    for lead in messaged_leads:
        lead_id = lead["id"]
        with db.connection() as conn:
            conn.execute(
                """
                UPDATE crm_status
                SET
                    stage            = 'contacted',
                    contact_attempts = contact_attempts + 1,
                    last_contact_at  = datetime('now','localtime'),
                    updated_at       = datetime('now','localtime')
                WHERE lead_id = ?
                """,
                (lead_id,),
            )
        advanced += 1

    log.debug(f"  📬  {advanced} lead 'contacted' aşamasına taşındı")
    return advanced


# ─────────────────────────────────────────────────────────────────────────────
#  İSTATİSTİK HESAPLAMA
# ─────────────────────────────────────────────────────────────────────────────

def compute_pipeline_stats(db: Database) -> dict:
    """
    Tüm pipeline boyunca toplanan özet istatistikleri hesapla.
    HTML rapor ve terminal özeti için kullanılır.

    Returns:
        dict: Kapsamlı pipeline istatistikleri
    """
    counts    = db.get_table_counts()
    crm_stages = db.get_pipeline_summary()
    enriched  = db.get_enriched_leads_full()
    all_msgs  = db.get_all_messages()
    all_leads = db.get_all_leads()

    # ── Temel sayılar ─────────────────────────────────────────────────────────
    total_leads      = counts["leads"]
    total_enriched   = counts["enrichments"]
    total_messages   = counts["messages"]
    linkedin_msgs    = sum(1 for m in all_msgs if m["message_type"] == "linkedin_dm")
    email_msgs       = sum(1 for m in all_msgs if m["message_type"] == "cold_email")
    leads_messaged   = len(set(m["lead_id"] for m in all_msgs))

    # ── Skor istatistikleri ────────────────────────────────────────────────────
    scores = [r["lead_score"] for r in enriched if r.get("lead_score")]
    eng_scores = [r["english_need_score"] for r in enriched if r.get("english_need_score")]

    avg_lead_score = round(sum(scores) / len(scores), 1) if scores else 0
    avg_eng_score  = round(sum(eng_scores) / len(eng_scores), 1) if eng_scores else 0
    max_score      = max(scores) if scores else 0
    min_score      = min(scores) if scores else 0

    # ── Öncelik dağılımı ──────────────────────────────────────────────────────
    priority_counts = {"urgent": 0, "high": 0, "medium": 0, "low": 0}
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT priority, COUNT(*) as cnt FROM crm_status GROUP BY priority"
        ).fetchall()
    for row in rows:
        p = row["priority"] or "medium"
        priority_counts[p] = row["cnt"]

    # ── Sektör dağılımı ───────────────────────────────────────────────────────
    sector_counts: dict[str, int] = {}
    for r in enriched:
        s = r.get("industry", "Diğer")
        sector_counts[s] = sector_counts.get(s, 0) + 1
    top_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)

    # ── Kıdem dağılımı ────────────────────────────────────────────────────────
    seniority_counts: dict[str, int] = {}
    for l in all_leads:
        s = l.get("seniority", "Mid")
        seniority_counts[s] = seniority_counts.get(s, 0) + 1

    # ── Şehir dağılımı ────────────────────────────────────────────────────────
    city_counts: dict[str, int] = {}
    for l in all_leads:
        c = l.get("company_city", "İstanbul")
        city_counts[c] = city_counts.get(c, 0) + 1
    top_cities = sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── Dönüşüm oranları ─────────────────────────────────────────────────────
    enrichment_rate = round((total_enriched / total_leads * 100), 1) if total_leads else 0
    outreach_rate   = round((leads_messaged / total_enriched * 100), 1) if total_enriched else 0

    # ── En iyi leadler ────────────────────────────────────────────────────────
    top_leads = sorted(enriched, key=lambda x: x.get("lead_score") or 0, reverse=True)[:5]

    # ── CRM aşama sayıları ────────────────────────────────────────────────────
    stage_map: dict[str, int] = {row["stage"]: row["count"] for row in crm_stages}

    return {
        # Temel
        "total_leads":       total_leads,
        "total_enriched":    total_enriched,
        "total_messages":    total_messages,
        "linkedin_msgs":     linkedin_msgs,
        "email_msgs":        email_msgs,
        "leads_messaged":    leads_messaged,
        # Skorlar
        "avg_lead_score":    avg_lead_score,
        "avg_eng_score":     avg_eng_score,
        "max_score":         max_score,
        "min_score":         min_score,
        # Oranlar
        "enrichment_rate":   enrichment_rate,
        "outreach_rate":     outreach_rate,
        # Dağılımlar
        "priority_counts":   priority_counts,
        "top_sectors":       top_sectors,
        "seniority_counts":  seniority_counts,
        "top_cities":        top_cities,
        "stage_map":         stage_map,
        # Top leadler
        "top_leads":         top_leads,
        # Meta
        "generated_at":      datetime.now().strftime("%d %B %Y, %H:%M"),
        "ai_model":          config.claude_model,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  TERMINAL ÖZET
# ─────────────────────────────────────────────────────────────────────────────

def print_crm_summary(stats: dict) -> None:
    log.info(f"\n{'═' * 60}")
    log.info(f"  🗂️   CRM & PİPELİNE DURUM RAPORU")
    log.info(f"{'═' * 60}")
    log.info(f"  TOPLANAN LEADLER    : {stats['total_leads']:>5}")
    log.info(f"  ZENGİNLEŞTİRİLEN    : {stats['total_enriched']:>5}  (%{stats['enrichment_rate']})")
    log.info(f"  MESAJ YAZILAN       : {stats['leads_messaged']:>5}  (%{stats['outreach_rate']})")
    log.info(f"  TOPLAM MESAJ        : {stats['total_messages']:>5}  (LinkedIn: {stats['linkedin_msgs']} | Email: {stats['email_msgs']})")
    log.info(f"{'─' * 60}")
    log.info(f"  Ort. Lead Skoru     : {stats['avg_lead_score']}/100")
    log.info(f"  Ort. İng. İhtiyacı  : {stats['avg_eng_score']}/10")
    log.info(f"{'─' * 60}")

    p = stats["priority_counts"]
    log.info(f"  ÖNCELİK DAĞILIMI:")
    log.info(f"    🔴 Urgent  : {p.get('urgent',0)}")
    log.info(f"    🟠 High    : {p.get('high',0)}")
    log.info(f"    🟡 Medium  : {p.get('medium',0)}")
    log.info(f"    🟢 Low     : {p.get('low',0)}")

    if stats["top_leads"]:
        log.info(f"{'─' * 60}")
        log.info(f"  ⭐ EN İYİ 5 LEAD (skora göre):")
        for lead in stats["top_leads"]:
            name = lead.get("full_name","")
            log.info(
                f"    {lead.get('lead_score',0):>3}/100  │  "
                f"{name:<25}  │  {lead.get('company',''):<20}  │  "
                f"{lead.get('industry','')}"
            )
    log.info(f"{'═' * 60}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  ANA ÇALIŞTIRICI
# ─────────────────────────────────────────────────────────────────────────────

def run() -> dict:
    """
    Pipeline orchestrator'dan veya standalone olarak çağrılır.

    Returns:
        dict: compute_pipeline_stats() çıktısı (HTML raporu için)
    """
    log_pipeline_start("04 — CRM Takip & Analitik")

    db = Database(config.db_path)

    synced   = sync_scores_to_crm(db)
    advanced = advance_messaged_leads(db)
    stats    = compute_pipeline_stats(db)

    print_crm_summary(stats)

    log.info(f"  CRM sync  : {synced} lead güncellendi")
    log.info(f"  Aşama     : {advanced} lead → 'contacted'")

    log_pipeline_end("04 — CRM Takip & Analitik")
    return stats


if __name__ == "__main__":
    run()
