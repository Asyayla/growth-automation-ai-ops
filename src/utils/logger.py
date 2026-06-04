"""
utils/logger.py
---------------
Loguru tabanlı renkli, pipeline-aware merkezi log yapısı.
Loguru yüklü değilse stdlib logging ile graceful fallback yapar.
"""

import sys
import os

# ── Loguru'yu dene, yoksa stdlib fallback ─────────────────────────────────────
try:
    from loguru import logger as _loguru_logger
    _HAS_LOGURU = True
except ImportError:
    _HAS_LOGURU = False

import logging as _stdlib_logging


def setup_logger(log_level: str = "DEBUG", log_file: str = "logs/pipeline.log") -> None:
    os.makedirs("logs", exist_ok=True)

    if _HAS_LOGURU:
        from loguru import logger as _lg
        _lg.remove()

        terminal_format = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
            "<level>{message}</level>"
        )
        _lg.add(sys.stdout, format=terminal_format, level=log_level,
                colorize=True, backtrace=True, diagnose=True)
        _lg.add(log_file, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
                level="DEBUG", rotation="10 MB", retention="7 days",
                compression="zip", encoding="utf-8")
    else:
        # Renkli stdlib fallback
        _fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        _date = "%H:%M:%S"
        _stdlib_logging.basicConfig(
            level=getattr(_stdlib_logging, log_level, _stdlib_logging.DEBUG),
            format=_fmt, datefmt=_date,
            handlers=[
                _stdlib_logging.StreamHandler(sys.stdout),
                _stdlib_logging.FileHandler(log_file, encoding="utf-8"),
            ]
        )


class _StdlibWrapper:
    """stdlib logger'ı loguru API'sine benzetir."""
    def __init__(self):
        self._log = _stdlib_logging.getLogger("pipeline")

    def debug(self, msg, *a, **kw):    self._log.debug(str(msg))
    def info(self, msg, *a, **kw):     self._log.info(str(msg))
    def warning(self, msg, *a, **kw):  self._log.warning(str(msg))
    def error(self, msg, *a, **kw):    self._log.error(str(msg))
    def success(self, msg, *a, **kw):  self._log.info(f"✅ {msg}")
    def exception(self, msg, *a, **kw): self._log.exception(str(msg))
    def bind(self, **kw):              return self
    def opt(self, **kw):               return self


# ── Pipeline yardımcıları ─────────────────────────────────────────────────────

def log_pipeline_start(stage_name: str) -> None:
    _logger = get_logger()
    _logger.info(f"{'─' * 55}")
    _logger.info(f"🚀  AŞAMA BAŞLADI  →  {stage_name.upper()}")
    _logger.info(f"{'─' * 55}")


def log_pipeline_end(stage_name: str, count: int = 0, unit: str = "kayıt") -> None:
    _logger = get_logger()
    _logger.success(f"AŞAMA TAMAMLANDI  →  {stage_name.upper()}")
    if count:
        _logger.success(f"    Toplam işlenen: {count} {unit}")
    _logger.info(f"{'─' * 55}")


def log_pipeline_error(stage_name: str, error: Exception) -> None:
    _logger = get_logger()
    _logger.error(f"❌  AŞAMA HATASI  →  {stage_name.upper()}")
    _logger.error(f"    Hata detayı: {error}")
    _logger.info(f"{'─' * 55}")


def log_progress(current: int, total: int, label: str = "") -> None:
    _logger = get_logger()
    pct = int((current / total) * 100) if total > 0 else 0
    bar_filled = int(pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    _logger.debug(f"[{bar}] {pct:>3}%  ({current}/{total})  {label}")


# ── Singleton ─────────────────────────────────────────────────────────────────
_logger_instance = None


def get_logger():
    global _logger_instance
    if _logger_instance is None:
        os.makedirs("logs", exist_ok=True)
        setup_logger()
        if _HAS_LOGURU:
            from loguru import logger as _lg
            _logger_instance = _lg
        else:
            _logger_instance = _StdlibWrapper()
    return _logger_instance
