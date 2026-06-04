"""
db/models.py
------------
SQLite tablo şemaları ve CREATE TABLE ifadeleri.
Her tablo bir dataclass + SQL string çiftiyle tanımlanır.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
#  SQL CREATE Statements
# ─────────────────────────────────────────────────────────────────────────────

SQL_CREATE_LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Temel Kimlik Bilgileri
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    full_name       TEXT GENERATED ALWAYS AS (first_name || ' ' || last_name) STORED,
    title           TEXT,                   -- Ünvan (İnsan Kaynakları Müdürü vb.)
    seniority       TEXT,                   -- Junior | Mid | Senior | Director | C-Level

    -- Şirket Bilgileri
    company         TEXT NOT NULL,
    company_city    TEXT DEFAULT 'İstanbul',

    -- İletişim Bilgileri
    linkedin_url    TEXT,
    email           TEXT,

    -- Metadata
    source          TEXT DEFAULT 'mock_generator',   -- Verinin kaynağı
    status          TEXT DEFAULT 'new',              -- new | enriched | messaged | sent | replied
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    updated_at      TEXT DEFAULT (datetime('now','localtime'))
);
"""

SQL_CREATE_ENRICHMENTS = """
CREATE TABLE IF NOT EXISTS enrichments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id             INTEGER NOT NULL UNIQUE,

    -- Şirket Verileri
    industry            TEXT,           -- Teknoloji, Finans, Perakende...
    company_size        TEXT,           -- 1-10 | 11-50 | 51-200 | 201-500 | 500+
    company_size_est    INTEGER,        -- Tahmini çalışan sayısı

    -- AI Analizi
    pain_point          TEXT,           -- Kişinin/şirketin olası sorunu
    english_need_score  INTEGER,        -- 1-10 (10 = çok yüksek ihtiyaç)
    english_need_reason TEXT,           -- Sebebi
    outreach_angle      TEXT,           -- Mesaj için önerilen yaklaşım açısı
    lead_score          INTEGER,        -- 1-100 genel lead kalite skoru

    -- AI Meta
    ai_model_used       TEXT,
    enriched_at         TEXT DEFAULT (datetime('now','localtime')),

    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""

SQL_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER NOT NULL,

    -- Mesaj İçeriği
    message_type    TEXT NOT NULL,      -- linkedin_dm | cold_email
    subject         TEXT,               -- Email için konu satırı
    body            TEXT NOT NULL,      -- Mesaj gövdesi
    cta             TEXT,               -- Call-to-action ifadesi

    -- Kişiselleştirme Notları
    personalization_notes TEXT,         -- AI'ın neden bu açıyı seçtiğine dair not

    -- Durum
    status          TEXT DEFAULT 'draft',   -- draft | approved | sent | replied | bounced
    sent_at         TEXT,
    replied_at      TEXT,

    -- AI Meta
    ai_model_used   TEXT,
    generated_at    TEXT DEFAULT (datetime('now','localtime')),

    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""

SQL_CREATE_CRM_STATUS = """
CREATE TABLE IF NOT EXISTS crm_status (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id             INTEGER NOT NULL UNIQUE,

    -- Pipeline Konumu
    stage               TEXT DEFAULT 'new',
    -- Stages: new → enriched → message_ready → contacted → replied → qualified → closed

    -- Outreach Takibi
    contact_attempts    INTEGER DEFAULT 0,
    last_contact_at     TEXT,
    next_followup_at    TEXT,
    followup_count      INTEGER DEFAULT 0,

    -- Sonuç
    outcome             TEXT,       -- interested | not_interested | bounced | no_reply | meeting_set
    notes               TEXT,       -- Manuel notlar

    -- Skorlar
    lead_score          INTEGER DEFAULT 0,      -- 0-100
    priority            TEXT DEFAULT 'medium',  -- low | medium | high | urgent

    -- Timestamps
    created_at          TEXT DEFAULT (datetime('now','localtime')),
    updated_at          TEXT DEFAULT (datetime('now','localtime')),

    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""

# Güncelleme trigger'ı — updated_at otomatik güncellensin
SQL_TRIGGER_LEADS_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_leads_updated_at
    AFTER UPDATE ON leads
BEGIN
    UPDATE leads SET updated_at = datetime('now','localtime') WHERE id = NEW.id;
END;
"""

SQL_TRIGGER_CRM_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_crm_updated_at
    AFTER UPDATE ON crm_status
BEGIN
    UPDATE crm_status SET updated_at = datetime('now','localtime') WHERE id = NEW.id;
END;
"""

# Kolay erişim için hepsini bir listede tut
ALL_CREATE_STATEMENTS = [
    SQL_CREATE_LEADS,
    SQL_CREATE_ENRICHMENTS,
    SQL_CREATE_MESSAGES,
    SQL_CREATE_CRM_STATUS,
    SQL_TRIGGER_LEADS_UPDATE,
    SQL_TRIGGER_CRM_UPDATE,
]


# ─────────────────────────────────────────────────────────────────────────────
#  Python Dataclass Modeller (tip güvenliği + IDE autocomplete)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Lead:
    first_name:     str
    last_name:      str
    title:          str
    company:        str
    company_city:   str = "İstanbul"
    seniority:      str = "Mid"
    linkedin_url:   Optional[str] = None
    email:          Optional[str] = None
    source:         str = "mock_generator"
    status:         str = "new"
    id:             Optional[int] = None
    created_at:     str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def to_dict(self) -> dict:
        return {
            "first_name":   self.first_name,
            "last_name":    self.last_name,
            "full_name":    self.full_name,
            "title":        self.title,
            "seniority":    self.seniority,
            "company":      self.company,
            "company_city": self.company_city,
            "linkedin_url": self.linkedin_url,
            "email":        self.email,
            "source":       self.source,
            "status":       self.status,
        }


@dataclass
class Enrichment:
    lead_id:                int
    industry:               Optional[str] = None
    company_size:           Optional[str] = None
    company_size_est:       Optional[int] = None
    pain_point:             Optional[str] = None
    english_need_score:     Optional[int] = None
    english_need_reason:    Optional[str] = None
    outreach_angle:         Optional[str] = None
    lead_score:             Optional[int] = None
    ai_model_used:          str = "mock"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Message:
    lead_id:                int
    message_type:           str         # linkedin_dm | cold_email
    body:                   str
    subject:                Optional[str] = None
    cta:                    Optional[str] = None
    personalization_notes:  Optional[str] = None
    status:                 str = "draft"
    ai_model_used:          str = "mock"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class CRMStatus:
    lead_id:            int
    stage:              str = "new"
    lead_score:         int = 0
    priority:           str = "medium"
    contact_attempts:   int = 0
    outcome:            Optional[str] = None
    notes:              Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}
