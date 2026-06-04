"""
utils/config.py
---------------
python-dotenv ile .env dosyasını okuyan merkezi konfigürasyon katmanı.
Tüm modüller sabit/ayar için buraya başvurur — asla hardcode etmez.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

from utils.logger import get_logger

log = get_logger()

# ── .env Yükle ────────────────────────────────────────────────────────────────
# Proje kök dizinindeki .env'i bul (src/ altından çalışırken de bulur)
_ROOT_DIR = Path(__file__).resolve().parents[2]   # konusurak-ogren-growth/
_ENV_PATH = _ROOT_DIR / ".env"

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
    log.debug(f".env yüklendi → {_ENV_PATH}")
else:
    log.warning(f".env bulunamadı → {_ENV_PATH}  (varsayılanlar kullanılacak)")


# ── Konfigürasyon Dataclass'ı ─────────────────────────────────────────────────

@dataclass
class AppConfig:
    """
    Uygulama genelinde tüm ayarlar tek yerden yönetilir.
    Yeni bir sabit eklemek = buraya bir field eklemek.
    """

    # Proje Dizinleri
    root_dir:           Path = field(default_factory=lambda: _ROOT_DIR)
    data_raw_dir:       Path = field(default_factory=lambda: _ROOT_DIR / "data" / "raw")
    data_enriched_dir:  Path = field(default_factory=lambda: _ROOT_DIR / "data" / "enriched")
    data_outreach_dir:  Path = field(default_factory=lambda: _ROOT_DIR / "data" / "outreach")
    output_dir:         Path = field(default_factory=lambda: _ROOT_DIR / "output")
    logs_dir:           Path = field(default_factory=lambda: _ROOT_DIR / "logs")

    # Dosya İsimleri
    leads_raw_csv:      str = "leads_raw.csv"
    leads_enriched_csv: str = "leads_enriched.csv"
    messages_csv:       str = "messages_ready.csv"
    db_filename:        str = "pipeline.db"

    # API Anahtarları (.env'den okunur)
    anthropic_api_key:  str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )

    # AI Model Ayarları
    claude_model:       str = field(
        default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    )
    ai_max_tokens:      int = field(
        default_factory=lambda: int(os.getenv("AI_MAX_TOKENS", "1000"))
    )
    ai_temperature:     float = field(
        default_factory=lambda: float(os.getenv("AI_TEMPERATURE", "0.7"))
    )

    # Pipeline Ayarları
    batch_size:         int = field(
        default_factory=lambda: int(os.getenv("BATCH_SIZE", "10"))
    )
    enrich_delay_sec:   float = field(
        default_factory=lambda: float(os.getenv("ENRICH_DELAY_SEC", "0.5"))
    )
    leads_target_count: int = field(
        default_factory=lambda: int(os.getenv("LEADS_TARGET_COUNT", "100"))
    )

    # Outreach Ayarları
    outreach_type:      str = field(
        default_factory=lambda: os.getenv("OUTREACH_TYPE", "both")  # linkedin | email | both
    )
    sender_name:        str = field(
        default_factory=lambda: os.getenv("SENDER_NAME", "Konuşarak Öğren Ekibi")
    )
    product_name:       str = "Konuşarak Öğren"
    product_url:        str = "konusarakogren.com"

    def __post_init__(self):
        """Dizinleri otomatik oluştur."""
        for dir_path in [
            self.data_raw_dir,
            self.data_enriched_dir,
            self.data_outreach_dir,
            self.output_dir,
            self.logs_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # API anahtarı kontrolü (uyarı ver, raise etme — generator mock çalışabilsin)
        if not self.anthropic_api_key:
            log.warning(
                "ANTHROPIC_API_KEY bulunamadı. "
                "AI zenginleştirme ve outreach adımları mock modda çalışacak."
            )

    @property
    def db_path(self) -> Path:
        return self.root_dir / self.db_filename

    @property
    def leads_raw_path(self) -> Path:
        return self.data_raw_dir / self.leads_raw_csv

    @property
    def leads_enriched_path(self) -> Path:
        return self.data_enriched_dir / self.leads_enriched_csv

    @property
    def messages_path(self) -> Path:
        return self.data_outreach_dir / self.messages_csv

    def summary(self) -> str:
        """Terminal'e konfigürasyon özetini yazdırır."""
        has_key = "✅ Mevcut" if self.anthropic_api_key else "❌ Eksik"
        return (
            f"\n{'═' * 50}\n"
            f"  🔧  KONFİGÜRASYON ÖZETİ\n"
            f"{'═' * 50}\n"
            f"  Model         : {self.claude_model}\n"
            f"  API Key       : {has_key}\n"
            f"  DB            : {self.db_path}\n"
            f"  Hedef Lead    : {self.leads_target_count}\n"
            f"  Outreach Tipi : {self.outreach_type}\n"
            f"  Batch Size    : {self.batch_size}\n"
            f"{'═' * 50}"
        )


# ── Singleton ─────────────────────────────────────────────────────────────────
# Tüm modüller `from utils.config import config` ile aynı nesneyi paylaşır.
config = AppConfig()
