"""
db/database.py
--------------
SQLite bağlantı yönetimi ve CRUD operasyonları.
Context manager pattern ile bağlantı güvenliği sağlanır.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator

from db.models import ALL_CREATE_STATEMENTS, Lead, Enrichment, Message, CRMStatus
from utils.logger import get_logger

log = get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  Bağlantı Yönetimi
# ─────────────────────────────────────────────────────────────────────────────

class Database:
    """
    SQLite veritabanı wrapper sınıfı.
    Kullanım:
        db = Database("pipeline.db")
        db.init()
        with db.connection() as conn:
            conn.execute(...)
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Thread-safe bağlantı context manager."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row          # dict-like erişim
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # Eşzamanlı okuma için
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error(f"DB transaction rollback: {e}")
            raise
        finally:
            conn.close()

    def init(self) -> None:
        """Tüm tabloları ve trigger'ları oluştur (idempotent)."""
        with self.connection() as conn:
            for statement in ALL_CREATE_STATEMENTS:
                conn.execute(statement)
        log.success(f"✅ Veritabanı hazır → {self.db_path}")

    def get_table_counts(self) -> dict:
        """Her tablodaki kayıt sayısını döner."""
        tables = ["leads", "enrichments", "messages", "crm_status"]
        counts = {}
        with self.connection() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                counts[table] = row["cnt"]
        return counts


# ─────────────────────────────────────────────────────────────────────────────
#  LEADS CRUD
# ─────────────────────────────────────────────────────────────────────────────

    def insert_lead(self, lead: Lead) -> int:
        """Tek lead ekler, oluşturulan ID'yi döner."""
        sql = """
            INSERT INTO leads
                (first_name, last_name, title, seniority, company, company_city,
                 linkedin_url, email, source, status)
            VALUES
                (:first_name, :last_name, :title, :seniority, :company, :company_city,
                 :linkedin_url, :email, :source, :status)
        """
        with self.connection() as conn:
            cursor = conn.execute(sql, lead.to_dict())
            lead_id = cursor.lastrowid

        # CRM kaydını otomatik oluştur
        self.upsert_crm_status(CRMStatus(lead_id=lead_id))
        return lead_id

    def insert_leads_bulk(self, leads: list[Lead]) -> int:
        """Toplu lead ekleme — tek transaction."""
        sql = """
            INSERT INTO leads
                (first_name, last_name, title, seniority, company, company_city,
                 linkedin_url, email, source, status)
            VALUES
                (:first_name, :last_name, :title, :seniority, :company, :company_city,
                 :linkedin_url, :email, :source, :status)
        """
        data = [lead.to_dict() for lead in leads]
        with self.connection() as conn:
            conn.executemany(sql, data)
            count = conn.execute("SELECT COUNT(*) as cnt FROM leads").fetchone()["cnt"]

        # Her lead için CRM kaydı oluştur
        with self.connection() as conn:
            rows = conn.execute("SELECT id FROM leads ORDER BY id DESC LIMIT ?",
                                (len(leads),)).fetchall()
        for row in rows:
            self.upsert_crm_status(CRMStatus(lead_id=row["id"]))

        log.info(f"📥 {len(leads)} lead eklendi. Toplam: {count}")
        return len(leads)

    def get_all_leads(self, status: Optional[str] = None) -> list[dict]:
        """Tüm leadleri (opsiyonel status filtresiyle) döner."""
        if status:
            sql = "SELECT * FROM leads WHERE status = ? ORDER BY id"
            params = (status,)
        else:
            sql = "SELECT * FROM leads ORDER BY id"
            params = ()
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_lead_by_id(self, lead_id: int) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None

    def update_lead_status(self, lead_id: int, status: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE leads SET status = ? WHERE id = ?",
                (status, lead_id)
            )


# ─────────────────────────────────────────────────────────────────────────────
#  ENRICHMENTS CRUD
# ─────────────────────────────────────────────────────────────────────────────

    def upsert_enrichment(self, enrichment: Enrichment) -> None:
        """Zenginleştirme verisini ekler veya günceller."""
        sql = """
            INSERT INTO enrichments
                (lead_id, industry, company_size, company_size_est,
                 pain_point, english_need_score, english_need_reason,
                 outreach_angle, lead_score, ai_model_used)
            VALUES
                (:lead_id, :industry, :company_size, :company_size_est,
                 :pain_point, :english_need_score, :english_need_reason,
                 :outreach_angle, :lead_score, :ai_model_used)
            ON CONFLICT(lead_id) DO UPDATE SET
                industry            = excluded.industry,
                company_size        = excluded.company_size,
                company_size_est    = excluded.company_size_est,
                pain_point          = excluded.pain_point,
                english_need_score  = excluded.english_need_score,
                english_need_reason = excluded.english_need_reason,
                outreach_angle      = excluded.outreach_angle,
                lead_score          = excluded.lead_score,
                ai_model_used       = excluded.ai_model_used,
                enriched_at         = datetime('now','localtime')
        """
        with self.connection() as conn:
            conn.execute(sql, enrichment.to_dict())
        self.update_lead_status(enrichment.lead_id, "enriched")

    def get_enrichment(self, lead_id: int) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM enrichments WHERE lead_id = ?", (lead_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_enriched_leads_full(self) -> list[dict]:
        """leads + enrichments JOIN — outreach adımı için kullanılır."""
        sql = """
            SELECT
                l.*,
                e.industry, e.company_size, e.company_size_est,
                e.pain_point, e.english_need_score, e.english_need_reason,
                e.outreach_angle, e.lead_score
            FROM leads l
            JOIN enrichments e ON l.id = e.lead_id
            ORDER BY e.lead_score DESC
        """
        with self.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  MESSAGES CRUD
# ─────────────────────────────────────────────────────────────────────────────

    def insert_message(self, message: Message) -> int:
        sql = """
            INSERT INTO messages
                (lead_id, message_type, subject, body, cta,
                 personalization_notes, status, ai_model_used)
            VALUES
                (:lead_id, :message_type, :subject, :body, :cta,
                 :personalization_notes, :status, :ai_model_used)
        """
        with self.connection() as conn:
            cursor = conn.execute(sql, message.to_dict())
            return cursor.lastrowid

    def get_messages_by_lead(self, lead_id: int) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE lead_id = ? ORDER BY generated_at",
                (lead_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_all_messages(self, status: Optional[str] = None) -> list[dict]:
        if status:
            sql = "SELECT * FROM messages WHERE status = ? ORDER BY generated_at"
            params = (status,)
        else:
            sql = "SELECT * FROM messages ORDER BY generated_at"
            params = ()
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  CRM STATUS CRUD
# ─────────────────────────────────────────────────────────────────────────────

    def upsert_crm_status(self, crm: CRMStatus) -> None:
        sql = """
            INSERT INTO crm_status
                (lead_id, stage, lead_score, priority, contact_attempts, outcome, notes)
            VALUES
                (:lead_id, :stage, :lead_score, :priority, :contact_attempts, :outcome, :notes)
            ON CONFLICT(lead_id) DO UPDATE SET
                stage            = excluded.stage,
                lead_score       = excluded.lead_score,
                priority         = excluded.priority,
                outcome          = excluded.outcome,
                notes            = excluded.notes
        """
        with self.connection() as conn:
            conn.execute(sql, crm.to_dict())

    def update_crm_stage(self, lead_id: int, stage: str, notes: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE crm_status
                   SET stage = ?, notes = ?, updated_at = datetime('now','localtime')
                   WHERE lead_id = ?""",
                (stage, notes, lead_id)
            )

    def get_pipeline_summary(self) -> list[dict]:
        """Her aşamada kaç lead var — dashboard için."""
        sql = """
            SELECT stage, COUNT(*) as count, AVG(lead_score) as avg_score
            FROM crm_status
            GROUP BY stage
            ORDER BY count DESC
        """
        with self.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
