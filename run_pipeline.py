#!/usr/bin/env python3
"""
run_pipeline.py
----------------
Ana orkestratör — tek komutla tüm pipeline'ı uçtan uca çalıştırır.

Kullanım:
    python run_pipeline.py               # Tüm aşamalar, varsayılan limit=3
    python run_pipeline.py --limit 10    # Her AI aşamasında max 10 lead
    python run_pipeline.py --all         # Limitsiz (tüm leadler)
    python run_pipeline.py --stage 2     # Sadece 2. aşamadan başla
    python run_pipeline.py --fresh       # DB + CSV sıfırla, baştan başla
    python run_pipeline.py --report-only # Sadece HTML raporu yenile
"""

import sys
import os
import time
import argparse
import importlib.util
from pathlib import Path
from datetime import datetime

# ── Path ─────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR  = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

os.makedirs("logs", exist_ok=True)

from utils.logger import get_logger, setup_logger
from utils.config import config

setup_logger(log_level="INFO", log_file="logs/pipeline.log")
log = get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  DYNAMIC MODULE LOADER — 01_ prefix'li dosyaları güvenle yükler
# ─────────────────────────────────────────────────────────────────────────────

def load_stage(filename: str) -> object:
    """src/pipeline/<filename>.py dosyasını dinamik olarak yükler ve döner."""
    path = SRC_DIR / "pipeline" / filename
    if not path.exists():
        raise FileNotFoundError(f"Aşama dosyası bulunamadı: {path}")
    spec   = importlib.util.spec_from_file_location(filename.replace(".py",""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE RESULT
# ─────────────────────────────────────────────────────────────────────────────

class StageResult:
    def __init__(self, stage: int, name: str):
        self.stage    = stage
        self.name     = name
        self.success  = False
        self.count    = 0
        self.duration = 0.0
        self.error    = None

    def __str__(self):
        icon  = "✅" if self.success else "❌"
        dur   = f"{self.duration:.1f}s"
        count = f"({self.count} kayıt)" if self.count else "       "
        err   = f" — Hata: {self.error}" if self.error else ""
        return f"  {icon}  Aşama {self.stage} · {self.name:<28} {count}  {dur}{err}"


def run_stage(num: int, name: str, fn, *args, **kwargs) -> StageResult:
    r = StageResult(num, name)
    t0 = time.time()
    try:
        out = fn(*args, **kwargs)
        r.success = True
        r.count   = out if isinstance(out, int) else 0
    except Exception as e:
        import traceback
        r.error = str(e)
        log.error(f"Aşama {num} hatası: {e}")
        log.error(traceback.format_exc())
    finally:
        r.duration = time.time() - t0
    return r


# ─────────────────────────────────────────────────────────────────────────────
#  BANNER & ÖZET
# ─────────────────────────────────────────────────────────────────────────────

def print_banner(limit: int | None, _mode: str = "") -> None:
    log.info("")
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║   🚀  KONUŞARAK ÖĞREN — GROWTH PIPELINE                ║")
    log.info("║      Growth Automation & AI Ops Intern Challenge        ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    log.info(f"  Tarih  : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    log.info(f"  Model  : {config.claude_model}")
    log.info(f"  Mod    : {'🤖 Gerçek API' if config.anthropic_api_key else '🔧 Mock'}")
    log.info(f"  Limit  : {limit if limit else 'Tüm leadler'}")
    log.info("")


def print_summary(results: list[StageResult], total_time: float) -> None:
    log.info("")
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║                  📋  PIPELINE ÖZET                     ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    for r in results:
        log.info(str(r))
    sep = "─" * 58
    log.info(f"  {sep}")
    ok = sum(1 for r in results if r.success)
    log.info(f"  Sonuç : {ok}/{len(results)} aşama başarılı  |  Toplam süre: {total_time:.1f}s")
    rpt = config.output_dir / "pipeline_report.html"
    if rpt.exists():
        log.info(f"  Rapor : {rpt}")
    log.info("")


# ─────────────────────────────────────────────────────────────────────────────
#  FRESH START
# ─────────────────────────────────────────────────────────────────────────────

def fresh_start() -> None:
    for p in [config.db_path, config.leads_raw_path,
              config.leads_enriched_path, config.messages_path]:
        if p.exists():
            p.unlink()
            log.info(f"🗑️   Silindi: {p.name}")
    log.info("🔄  Temiz başlangıç hazır\n")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args    = _parse_args()
    results = []
    t0      = time.time()
    limit   = None if args.all else args.limit

    print_banner(limit)

    if args.fresh:
        fresh_start()

    # ── Report-only kısa devre ────────────────────────────────────────────────
    if args.report_only:
        crm = load_stage("04_crm_tracker.py")
        rpt = load_stage("report_generator.py")
        from db.database import Database
        stats = crm.compute_pipeline_stats(Database(config.db_path))
        rpt.generate_report(stats)
        return

    start = args.stage

    # ── AŞAMA 1 ───────────────────────────────────────────────────────────────
    if start <= 1:
        log.info("━━━━━━━  AŞAMA 1 / 4 — Veri Üretimi  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        gen = load_stage("01_data_generator.py")
        r = run_stage(1, "Veri Üretimi", gen.run,
                      target_count=limit or config.leads_target_count)
        results.append(r)
        if not r.success:
            log.error("Aşama 1 başarısız — pipeline durduruluyor.")
            print_summary(results, time.time() - t0)
            sys.exit(1)

    # ── AŞAMA 2 ───────────────────────────────────────────────────────────────
    if start <= 2:
        log.info("━━━━━━━  AŞAMA 2 / 4 — Lead Zenginleştirme  ━━━━━━━━━━━━━━━━━━━━━━━━")
        enr = load_stage("02_enricher.py")
        r = run_stage(2, "Lead Zenginleştirme", enr.run,
                      limit=limit, skip_existing=True)
        results.append(r)

    # ── AŞAMA 3 ───────────────────────────────────────────────────────────────
    if start <= 3:
        log.info("━━━━━━━  AŞAMA 3 / 4 — Outreach Yazıcı  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        out = load_stage("03_outreach_writer.py")
        r = run_stage(3, "Outreach Yazıcı", out.run,
                      limit=limit, skip_existing=True)
        results.append(r)

    # ── AŞAMA 4 + RAPOR ───────────────────────────────────────────────────────
    if start <= 4:
        log.info("━━━━━━━  AŞAMA 4 / 4 — CRM Takip & Rapor  ━━━━━━━━━━━━━━━━━━━━━━━━━")
        crm = load_stage("04_crm_tracker.py")
        r4  = run_stage(4, "CRM Takip", crm.run)
        results.append(r4)

        # HTML Rapor
        rpt = load_stage("report_generator.py")
        from db.database import Database

        def _make_report():
            stats = crm.compute_pipeline_stats(Database(config.db_path))
            rpt.generate_report(stats)
            return 1

        r5 = run_stage(5, "HTML Rapor", _make_report)
        results.append(r5)

    print_summary(results, time.time() - t0)
    sys.exit(0 if all(r.success for r in results) else 1)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Konuşarak Öğren — Growth Pipeline Orkestratörü",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python run_pipeline.py                  # Varsayılan (limit=3, aşama 1-4)
  python run_pipeline.py --limit 10       # 10 lead ile test
  python run_pipeline.py --all            # 100 lead, tüm aşamalar
  python run_pipeline.py --stage 2        # 2. aşamadan devam
  python run_pipeline.py --fresh --all    # Temiz slate, 100 lead
  python run_pipeline.py --report-only    # Sadece HTML raporu yenile
        """
    )
    p.add_argument("--limit",       type=int, default=3,
                   help="AI aşamaları için lead limiti (varsayılan: 3)")
    p.add_argument("--all",         action="store_true",
                   help="Tüm leadleri işle")
    p.add_argument("--stage",       type=int, default=1, choices=[1,2,3,4],
                   help="Başlangıç aşaması (varsayılan: 1)")
    p.add_argument("--fresh",       action="store_true",
                   help="DB ve CSV'leri sıfırla")
    p.add_argument("--report-only", action="store_true",
                   help="Sadece HTML raporu yenile")
    return p.parse_args()


if __name__ == "__main__":
    main()
