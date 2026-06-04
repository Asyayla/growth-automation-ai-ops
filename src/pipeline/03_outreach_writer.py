"""
pipeline/03_outreach_writer.py
-------------------------------
AI Outreach Sistemi — enriched leadler için kişiselleştirilmiş mesajlar üretir.

Akış:
  1. SQLite 'enrichments' tablosunu leads ile JOIN'leyerek oku
  2. Her lead için sırayla LinkedIn DM + Cold Email üret (iki ayrı API çağrısı)
  3. SQLite 'messages' tablosuna kaydet
  4. leads.status → 'messaged' güncelle
  5. data/outreach/messages_ready.csv olarak export et

Standalone çalıştırma:
    PYTHONPATH=src python src/pipeline/03_outreach_writer.py
    PYTHONPATH=src python src/pipeline/03_outreach_writer.py --limit 5
    PYTHONPATH=src python src/pipeline/03_outreach_writer.py --type linkedin
    PYTHONPATH=src python src/pipeline/03_outreach_writer.py --all
"""

import sys
import time
import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.claude_client import ClaudeClient, ClaudeAPIError
from ai.prompts import (
    SYSTEM_OUTREACH_LINKEDIN,
    SYSTEM_OUTREACH_EMAIL,
    user_outreach,
)
from db.database import Database
from db.models import Message
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
#  MOCK MESAJ ÜRETECİ — API key olmadan gerçekçi örnek üretir
# ─────────────────────────────────────────────────────────────────────────────

def _mock_linkedin_dm(lead: dict) -> dict:
    """Akıllı mock LinkedIn DM — mock_data motoru üzerinden şirkete özgü üretim."""
    from ai.mock_data import build_linkedin_dm_mock
    return build_linkedin_dm_mock(lead)


def _mock_cold_email(lead: dict) -> dict:
    """Akıllı mock Cold Email — mock_data motoru üzerinden şirkete özgü üretim."""
    from ai.mock_data import build_cold_email_mock
    return build_cold_email_mock(lead)
def write_messages_for_lead(
    lead: dict,
    client: ClaudeClient,
    message_types: list[str],
) -> list[Message]:
    """
    Tek bir lead için istenen tiplerde mesaj üretir.

    Args:
        lead          : leads + enrichments JOIN'inden gelen dict
        client        : ClaudeClient instance
        message_types : ['linkedin_dm', 'cold_email'] veya sadece biri

    Returns:
        list[Message]: Üretilen mesaj nesneleri
    """
    messages: list[Message] = []
    lead_id   = lead["id"]
    full_name = lead.get("full_name") or f"{lead['first_name']} {lead['last_name']}"

    for msg_type in message_types:
        system_prompt = (
            SYSTEM_OUTREACH_LINKEDIN if msg_type == "linkedin_dm"
            else SYSTEM_OUTREACH_EMAIL
        )

        log.debug(f"  ✍️  [{msg_type}] yazılıyor → {full_name} @ {lead['company']}")

        if client.mock:
            # ── Mock mod: kişiye özgü Python-üretimi mesaj ──────────────────
            raw_data = (
                _mock_linkedin_dm(lead) if msg_type == "linkedin_dm"
                else _mock_cold_email(lead)
            )
        else:
            # ── Gerçek API çağrısı ────────────────────────────────────────────
            prompt = user_outreach(
                full_name           = full_name,
                first_name          = lead.get("first_name", ""),
                title               = lead.get("title", ""),
                seniority           = lead.get("seniority", "Mid"),
                company             = lead.get("company", ""),
                company_city        = lead.get("company_city", "İstanbul"),
                industry            = lead.get("industry", ""),
                company_size        = lead.get("company_size", ""),
                company_size_est    = lead.get("company_size_est") or 0,
                pain_point          = lead.get("pain_point", ""),
                english_need_reason = lead.get("english_need_reason", ""),
                outreach_angle      = lead.get("outreach_angle", ""),
                english_need_score  = lead.get("english_need_score") or 5,
                lead_score          = lead.get("lead_score") or 50,
                message_type        = msg_type,
            )

            try:
                raw_data = client.complete_json(
                    system_prompt = system_prompt,
                    user_prompt   = prompt,
                    max_tokens    = 700,
                )
            except ClaudeAPIError as e:
                log.error(f"    ❌ API hatası [{msg_type}] — {full_name}: {e}")
                continue

            if "error" in raw_data:
                log.warning(f"    ⚠️  JSON parse hatası [{msg_type}] — {full_name}")
                continue

        # ── Message nesnesini oluştur ─────────────────────────────────────────
        msg = Message(
            lead_id               = lead_id,
            message_type          = raw_data.get("message_type", msg_type),
            subject               = raw_data.get("subject"),
            body                  = raw_data.get("body", ""),
            cta                   = raw_data.get("cta"),
            personalization_notes = raw_data.get("personalization_notes"),
            status                = "draft",
            ai_model_used         = config.claude_model if not client.mock else "mock",
        )
        messages.append(msg)
        log.debug(f"    ✅ [{msg_type}] hazır")

    return messages


# ─────────────────────────────────────────────────────────────────────────────
#  CSV EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_messages_csv(db: Database, output_path: Path) -> int:
    """
    messages + leads JOIN'ini okunabilir CSV formatına yazar.
    Her satır: kişi bilgisi + mesaj içeriği yan yana.
    """
    all_msgs = db.get_all_messages()
    if not all_msgs:
        log.warning("Export için mesaj bulunamadı.")
        return 0

    rows = []
    for msg in all_msgs:
        lead = db.get_lead_by_id(msg["lead_id"]) or {}
        full_name = lead.get("full_name") or (
            f"{lead.get('first_name','')} {lead.get('last_name','')}".strip()
        )
        rows.append({
            "lead_id":               msg["lead_id"],
            "full_name":             full_name,
            "title":                 lead.get("title", ""),
            "company":               lead.get("company", ""),
            "linkedin_url":          lead.get("linkedin_url", ""),
            "email":                 lead.get("email", ""),
            "message_type":          msg["message_type"],
            "subject":               msg.get("subject", ""),
            "body":                  msg.get("body", ""),
            "cta":                   msg.get("cta", ""),
            "personalization_notes": msg.get("personalization_notes", ""),
            "status":                msg.get("status", "draft"),
            "generated_at":          msg.get("generated_at", ""),
        })

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    log.success(f"💾 Messages CSV kaydedildi → {output_path}  ({len(df)} satır)")
    return len(df)


# ─────────────────────────────────────────────────────────────────────────────
#  TERMINAL PREVIEW — mesajları güzel formatla yazdırır
# ─────────────────────────────────────────────────────────────────────────────

def print_message_preview(db: Database, messages: list[Message], max_show: int = 3) -> None:
    """Her lead için üretilen mesajları terminalde önizler."""
    if not messages:
        return

    shown_leads: set = set()
    shown_count = 0

    log.info(f"\n{'═' * 65}")
    log.info(f"  📨  ÜRETILEN MESAJ ÖNİZLEMESİ  (ilk {max_show} lead)")
    log.info(f"{'═' * 65}")

    for msg in messages:
        if shown_count >= max_show:
            break
        if msg.lead_id in shown_leads and msg.message_type != "cold_email":
            continue

        lead = db.get_lead_by_id(msg.lead_id) or {}
        full_name = lead.get("full_name") or (
            f"{lead.get('first_name','')} {lead.get('last_name','')}".strip()
        )

        if msg.lead_id not in shown_leads:
            log.info(f"\n  👤  {full_name} | {lead.get('title','')} @ {lead.get('company','')}")
            shown_leads.add(msg.lead_id)
            shown_count += 1

        type_label = "💼 LinkedIn DM" if msg.message_type == "linkedin_dm" else "📧 Cold Email"
        log.info(f"\n  {type_label}")

        if msg.subject:
            log.info(f"  Konu : {msg.subject}")

        # Body'yi satırlara bölerek girintili yazdır
        body_lines = (msg.body or "").split("\n")
        for line in body_lines:
            if line.strip():
                log.info(f"  │  {line}")

        log.info(f"  CTA  : {msg.cta}")
        log.info(f"  📌  {msg.personalization_notes}")
        log.info(f"  {'─' * 60}")


# ─────────────────────────────────────────────────────────────────────────────
#  ANA ÇALIŞTIRICI
# ─────────────────────────────────────────────────────────────────────────────

def run(
    limit: Optional[int] = 3,
    message_types: Optional[list[str]] = None,
    skip_existing: bool = True,
) -> int:
    """
    Pipeline orchestrator'dan veya standalone olarak çağrılır.

    Args:
        limit         : Kaç lead için mesaj üretilecek (None = hepsi)
        message_types : ['linkedin_dm', 'cold_email'] — None ise ikisi de
        skip_existing : Mesajı zaten olan leadları atla

    Returns:
        int: Toplam üretilen mesaj sayısı
    """
    log_pipeline_start("03 — AI Outreach Yazıcı")

    db     = Database(config.db_path)
    client = ClaudeClient()

    # Varsayılan: her iki kanal da üretilsin
    types = message_types or ["linkedin_dm", "cold_email"]

    # ── 1. Enriched leadleri çek ──────────────────────────────────────────────
    enriched_leads = db.get_enriched_leads_full()

    if not enriched_leads:
        log.error(
            "Zenginleştirilmiş lead bulunamadı. "
            "Önce 02_enricher.py çalıştır."
        )
        return 0

    # Zaten mesajı olanları atla (opsiyonel)
    if skip_existing:
        existing_msgs = db.get_all_messages()
        messaged_lead_ids = {m["lead_id"] for m in existing_msgs}
        enriched_leads = [l for l in enriched_leads if l["id"] not in messaged_lead_ids]

        if not enriched_leads:
            log.warning(
                "Tüm zenginleştirilmiş leadların mesajları zaten üretilmiş. "
                "--no-skip ile yeniden üretebilirsin."
            )
            return 0

    # Limit uygula
    target_leads = enriched_leads[:limit] if limit else enriched_leads
    total        = len(target_leads)
    total_msgs   = total * len(types)

    mode_tag = "MOCK" if client.mock else "CLAUDE API"
    log.info(f"📋 {total} lead × {len(types)} tip = {total_msgs} mesaj üretilecek | Mod: {mode_tag}")
    if limit and limit < len(enriched_leads):
        log.info(f"   (toplam {len(enriched_leads)} zenginleştirilmiş leadden ilk {limit} alındı)")

    # ── 2. Her lead için mesaj üret ───────────────────────────────────────────
    all_messages:   list[Message] = []
    failed_lead_ids: list[int]    = []

    for idx, lead in enumerate(target_leads, start=1):
        full_name = lead.get("full_name") or f"{lead['first_name']} {lead['last_name']}"
        log_progress(idx, total, f"{full_name} @ {lead['company']}")

        msgs = write_messages_for_lead(lead, client, types)

        if not msgs:
            failed_lead_ids.append(lead["id"])
            continue

        # DB'ye kaydet
        for msg in msgs:
            try:
                msg_id = db.insert_message(msg)
                msg.lead_id = lead["id"]  # referans için tut
                all_messages.append(msg)
            except Exception as e:
                log.error(f"DB yazma hatası — lead_id={lead['id']}: {e}")

        # Lead status güncelle
        db.update_lead_status(lead["id"], "messaged")
        db.update_crm_stage(lead["id"], "message_ready")

        # Rate limit koruması
        if not client.mock and idx < total:
            time.sleep(config.enrich_delay_sec)

    # ── 3. Önizleme ───────────────────────────────────────────────────────────
    print_message_preview(db, all_messages, max_show=3)

    # ── 4. Özet ──────────────────────────────────────────────────────────────
    if failed_lead_ids:
        log.warning(f"⚠️  {len(failed_lead_ids)} lead için mesaj üretilemedi: {failed_lead_ids}")

    # ── 5. CSV export ─────────────────────────────────────────────────────────
    export_messages_csv(db, config.messages_path)

    log_pipeline_end("03 — AI Outreach Yazıcı", len(all_messages), "mesaj")
    return len(all_messages)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="AI outreach mesaj üretici",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python 03_outreach_writer.py                    # İlk 3 lead, her iki kanal
  python 03_outreach_writer.py --limit 10         # İlk 10 lead
  python 03_outreach_writer.py --type linkedin    # Sadece LinkedIn DM
  python 03_outreach_writer.py --type email       # Sadece Cold Email
  python 03_outreach_writer.py --all              # Tüm zenginleştirilmiş leadler
  python 03_outreach_writer.py --no-skip          # Var olanları da yenile
        """
    )
    parser.add_argument("--limit",   type=int,  default=3,   help="Lead sayısı (varsayılan: 3)")
    parser.add_argument("--all",     action="store_true",    help="Tüm leadleri işle")
    parser.add_argument("--no-skip", action="store_true",    help="Mevcut mesajları yenile")
    parser.add_argument(
        "--type",
        choices=["linkedin", "email", "both"],
        default="both",
        help="Kanal seçimi (varsayılan: both)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    type_map = {
        "linkedin": ["linkedin_dm"],
        "email":    ["cold_email"],
        "both":     ["linkedin_dm", "cold_email"],
    }

    run(
        limit         = None if args.all else args.limit,
        message_types = type_map[args.type],
        skip_existing = not args.no_skip,
    )
