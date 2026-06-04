# 🎯 Konuşarak Öğren — Growth Automation & AI Ops Pipeline

> **End-to-end AI-driven outbound growth system** for reaching HR professionals across Turkey.
> Built as a 48-hour technical challenge for the *Growth Automation & AI Ops Intern* position.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Claude API](https://img.shields.io/badge/Claude-Sonnet_4-D97706?style=flat-square&logo=anthropic&logoColor=white)](https://anthropic.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-10B981?style=flat-square)](LICENSE)

---

## 📌 Project Overview & Value Proposition

Konuşarak Öğren is Turkey's leading AI-powered corporate English training platform. To scale its outbound B2B growth, this pipeline automates the entire lead-to-message workflow — from data generation to personalized outreach — without manual intervention.

**What this system does, end-to-end:**

1. Generates a realistic database of **100 Turkish HR professionals** across sectors (fintech, banking, retail, SaaS, healthcare, logistics, and more)
2. Enriches each lead using **Claude AI** — inferring company sector, size, pain points, and English training needs
3. Writes **hyper-personalized outreach messages** (LinkedIn DM + cold email) per lead, calibrated to their seniority, company, and industry context
4. Tracks every lead through a **CRM pipeline** (new → enriched → messaged → contacted) and generates a polished HTML analytics dashboard

**Why it matters for growth teams:**
- Replaces hours of manual research and copy-paste outreach with a single `python run_pipeline.py`
- Every message references the lead's actual company, sector, and pain point — zero generic templates
- Dual-write architecture (SQLite + CSV) means the data is instantly queryable *and* shareable in Excel
- Modular design: swap any stage, add new data sources, or plug in a real sending layer with minimal code changes

---

## 🏗️ Architecture & Data Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    run_pipeline.py  (Orchestrator)                  │
│          Single entry point — runs all stages sequentially          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │        STAGE 01 — Data Generation        │
          │  01_data_generator.py                    │
          │                                          │
          │  • 100 realistic HR leads                │
          │  • Names, titles, companies, cities      │
          │  • LinkedIn URLs + corporate emails      │
          │                                          │
          │  OUT: leads table  ·  leads_raw.csv      │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │       STAGE 02 — Lead Enrichment         │
          │  02_enricher.py  +  claude_client.py     │
          │                                          │
          │  Claude API call per lead →              │
          │  • Company sector & size estimate        │
          │  • English training pain point           │
          │  • English need score  (1–10)            │
          │  • Outreach angle suggestion             │
          │  • Lead quality score  (1–100)           │
          │                                          │
          │  OUT: enrichments table · leads_enriched.csv │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │      STAGE 03 — AI Outreach Writer       │
          │  03_outreach_writer.py  +  prompts.py    │
          │                                          │
          │  Two Claude API calls per lead →         │
          │  • LinkedIn DM  (≤4 sentences, no emoji) │
          │  • Cold Email   (3-para structure + sig) │
          │                                          │
          │  Seniority-aware tone (C-Level = ROI     │
          │  language; Mid = practical/field tone)   │
          │                                          │
          │  OUT: messages table · messages_ready.csv│
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │       STAGE 04 — CRM Tracker             │
          │  04_crm_tracker.py                       │
          │                                          │
          │  • Syncs lead scores → crm_status table  │
          │  • Priority tagging: urgent/high/med/low │
          │  • Auto follow-up date assignment        │
          │  • Advances pipeline stages              │
          │  • Computes full analytics stats         │
          │                                          │
          │  OUT: crm_status table                   │
          └────────────────────┬────────────────────┘
                               │
          ┌────────────────────▼────────────────────┐
          │       HTML Dashboard Report              │
          │  report_generator.py                     │
          │                                          │
          │  • KPI cards, bar charts, donut legend   │
          │  • Top leads table with priority badges  │
          │  • Channel split, city & sector maps     │
          │  • Zero JS dependencies — pure HTML/CSS  │
          │                                          │
          │  OUT: output/pipeline_report.html        │
          └─────────────────────────────────────────┘
```

### Data Storage — SQLite + CSV Hybrid

| Layer | Purpose | Location |
|---|---|---|
| `pipeline.db` | Source of truth — all relational queries | project root |
| `leads_raw.csv` | Sharable raw lead list | `data/raw/` |
| `leads_enriched.csv` | Enriched leads with AI scores | `data/enriched/` |
| `messages_ready.csv` | Final outreach messages | `data/outreach/` |
| `pipeline_report.html` | Analytics dashboard | `output/` |

**Four SQLite tables:**

```sql
leads        → identity, contact, status, seniority
enrichments  → sector, size, pain point, English score, lead score
messages     → type, subject, body, CTA, personalization notes
crm_status   → pipeline stage, priority, follow-up dates, outcomes
```

### Project Structure

```
konusurak-ogren-growth/
│
├── run_pipeline.py              ← Single entry point
├── .env                         ← API keys (not committed)
├── requirements.txt
│
├── src/
│   ├── pipeline/
│   │   ├── 01_data_generator.py
│   │   ├── 02_enricher.py
│   │   ├── 03_outreach_writer.py
│   │   ├── 04_crm_tracker.py
│   │   └── report_generator.py
│   │
│   ├── ai/
│   │   ├── claude_client.py     ← Anthropic API wrapper (retry + mock)
│   │   └── prompts.py           ← All system + user prompts
│   │
│   ├── db/
│   │   ├── database.py          ← SQLite CRUD + context manager
│   │   └── models.py            ← Dataclasses + CREATE TABLE statements
│   │
│   └── utils/
│       ├── config.py            ← Singleton config from .env
│       └── logger.py            ← Loguru setup + pipeline helpers
│
├── data/
│   ├── raw/leads_raw.csv
│   ├── enriched/leads_enriched.csv
│   └── outreach/messages_ready.csv
│
├── output/
│   └── pipeline_report.html
│
└── logs/
    └── pipeline.log
```

---

## 🛠️ Tech Stack

| Category | Tool | Why |
|---|---|---|
| **Language** | Python 3.11+ | Rapid prototyping, rich ecosystem |
| **AI Engine** | Anthropic Claude (Sonnet 4) | Best-in-class Turkish reasoning, structured JSON output |
| **Database** | SQLite 3 | Zero-setup, relational, version-controllable |
| **Data Layer** | Pandas | CSV I/O, DataFrame transforms |
| **HTTP / API** | `anthropic` SDK | Native retry, streaming, type safety |
| **Logging** | Loguru (+ stdlib fallback) | One-line setup, color, rotation, file sink |
| **Config** | python-dotenv | Secure key management, 12-factor compliant |
| **Report** | Pure HTML/CSS | Zero frontend dependencies, opens in any browser |
| **Architecture** | Modular pipeline | Each stage independently testable and runnable |

---

## ⚡ Installation & Quick Start

### 1. Clone & install

```bash
git clone https://github.com/your-username/konusurak-ogren-growth.git
cd konusurak-ogren-growth

pip install -r requirements.txt
```

**`requirements.txt`**
```
anthropic>=0.25.0
pandas>=2.0.0
python-dotenv>=1.0.0
loguru>=0.7.0
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required for real AI enrichment and outreach generation
ANTHROPIC_API_KEY=sk-ant-...

# Optional — override defaults
CLAUDE_MODEL=claude-sonnet-4-20250514
LEADS_TARGET_COUNT=100
BATCH_SIZE=10
ENRICH_DELAY_SEC=0.5        # Rate limit buffer between API calls
OUTREACH_TYPE=both           # linkedin | email | both
```

> **No API key?** The pipeline runs in **mock mode** automatically — every stage executes with deterministic synthetic outputs. All CSV and DB outputs are still generated. This is useful for testing the full architecture without incurring API costs.

### 3. Run the pipeline

```bash
# Quick test — 3 leads through all 4 stages (default)
python run_pipeline.py

# Full run — all 100 leads
python run_pipeline.py --all

# Controlled test — 10 leads
python run_pipeline.py --limit 10

# Resume from a specific stage (leads already generated)
python run_pipeline.py --stage 2 --all

# Clean slate — wipe DB and CSVs, start fresh
python run_pipeline.py --fresh --all

# Regenerate HTML report without re-running the pipeline
python run_pipeline.py --report-only
```

**Expected terminal output:**
```
╔══════════════════════════════════════════════════════════╗
║   🚀  KONUŞARAK ÖĞREN — GROWTH PIPELINE                ║
║      Growth Automation & AI Ops Intern Challenge        ║
╚══════════════════════════════════════════════════════════╝
  Tarih  : 04.06.2026 13:23:42
  Model  : claude-sonnet-4-20250514
  Mod    : 🤖 Gerçek API
  Limit  : 10

━━━━━━━  AŞAMA 1 / 4 — Veri Üretimi  ━━━━━━━━━━━━━━━━━━━━━
  🎲 100 lead üretiliyor...
  ✅ 100 lead üretildi | CSV → data/raw/leads_raw.csv

━━━━━━━  AŞAMA 2 / 4 — Lead Zenginleştirme  ━━━━━━━━━━━━━━
  📋 10 lead zenginleştirilecek | Mod: CLAUDE API
  [████████████████████] 100%  (10/10)
  ⭐ Yüksek öncelikli leadler (skor ≥ 70): 4

━━━━━━━  AŞAMA 3 / 4 — Outreach Yazıcı  ━━━━━━━━━━━━━━━━━━
  📋 10 lead × 2 tip = 20 mesaj üretilecek
  [████████████████████] 100%  (10/10)

━━━━━━━  AŞAMA 4 / 4 — CRM Takip & Rapor  ━━━━━━━━━━━━━━━━
  ✅ HTML Rapor → output/pipeline_report.html

╔══════════════════════════════════════════════════════════╗
║                  📋  PIPELINE ÖZET                     ║
╚══════════════════════════════════════════════════════════╝
  ✅  Aşama 1 · Veri Üretimi          (100 kayıt)   0.1s
  ✅  Aşama 2 · Lead Zenginleştirme    (10 kayıt)   12.4s
  ✅  Aşama 3 · Outreach Yazıcı        (20 kayıt)   18.7s
  ✅  Aşama 4 · CRM Takip                           0.1s
  ✅  Aşama 5 · HTML Rapor              (1 kayıt)    0.1s
  ──────────────────────────────────────────────────────
  Sonuç : 5/5 aşama başarılı  |  Toplam süre: 31.4s
```

### 4. Run individual stages

Each stage is independently executable — useful for iteration and debugging:

```bash
# Stage 1 only
PYTHONPATH=src python src/pipeline/01_data_generator.py

# Stage 2 — enrich first 5 leads
PYTHONPATH=src python src/pipeline/02_enricher.py --limit 5

# Stage 3 — LinkedIn DM only
PYTHONPATH=src python src/pipeline/03_outreach_writer.py --type linkedin --limit 5

# Stage 4 — CRM sync
PYTHONPATH=src python src/pipeline/04_crm_tracker.py
```

---

## 📨 Sample AI Outputs & Analytics Dashboard

### Lead Enrichment Output

For a lead like **Serap Sönmez** (İK Generalist, Memorial Hastaneler Grubu), the AI enrichment produces:

```json
{
  "industry": "Sağlık",
  "company_size": "201-500",
  "company_size_est": 350,
  "pain_point": "Uluslararası hasta ilişkileri ve medikal turizm operasyonlarında
                 İngilizce iletişim boşluğu; yabancı ortaklarla yapılan klinik
                 protokol görüşmelerinde çalışanların konuşma güveni eksikliği.",
  "english_need_score": 8,
  "english_need_reason": "Sağlık sektöründe uluslararası akreditasyon süreçleri
                          ve medikal turizm büyümesi, ekiplerin İngilizce sözlü
                          iletişim kapasitesini kritik hale getiriyor.",
  "outreach_angle": "Medikal turizm büyümesi ve JCI akreditasyon süreçleri
                     çerçevesinde İngilizce iletişim yetkinliğini ROI'ye bağla.",
  "lead_score": 83
}
```

### Personalized LinkedIn DM

> *Tailored for a Mid-level HR profile — practical tone, curiosity-first, no hard sell:*

```
Merhaba Serap, Memorial Hastaneler Grubu'ın büyüme hikayesini takip
ediyorum. İK profesyonelleriyle konuştuğumda Sağlık sektöründe
çalışanların İngilizce konuşma pratiği en çok zorlandıkları nokta
oluyor — Memorial'da da benzer bir durum var mı? Konuşarak Öğren
olarak AI destekli kurumsal İngilizce pratiği üzerine çalışıyoruz
ve Sağlık sektöründen birkaç referansımız var.

→ CTA: Nasıl çözdüklerini anlattığımız hızlı bir demo ayarlayabilir miyiz?
```

### Personalized Cold Email

> *3-paragraph structure — sector-specific hook, data-backed pain point, low-friction CTA:*

**Subject:** `Memorial Hastaneler Grubu ekibi için İngilizce pratik fikri`

```
Memorial Hastaneler Grubu'ın Sağlık sektöründeki büyümesini
takip ediyorum; özellikle uluslararası iş geliştirme hızınız
dikkat çekici. Bu ölçekte büyüyen ekiplerde İngilizce iletişim
genellikle kritik bir darboğaza dönüşüyor.

Sağlık sektöründe yaptığımız araştırmaya göre çalışanların %68'i
İngilizce konuşma pratiğini en büyük gelişim alanı olarak görüyor —
yazılı İngilizce değil, gerçek zamanlı konuşma güveni. Alandaki biri
olarak bu tablo size de tanıdık geliyor mu?

Konuşarak Öğren olarak AI konuşma pratiği + canlı ders hibrid
modeliyle tam da bu boşluğu kapatıyoruz; 10 dakika konuşabilir miyiz?

Konuşarak Öğren Ekibi
konusarakogren.com
```

**What makes these messages non-generic:**
- Company name embedded in the opening sentence — not a variable, a real observation
- Sector-specific pain point (healthcare ≠ banking ≠ SaaS — each gets its own framing)
- Seniority-aware tone: Director/C-Level → ROI & strategic language; Mid/Senior → practical & field-level
- CTA is low-commitment: "15 minutes" / "quick demo" — not "schedule a 45-minute product walkthrough"

### Analytics Dashboard (`output/pipeline_report.html`)

Open the generated HTML file in any browser — no server required.

**Dashboard sections:**

| Section | What it shows |
|---|---|
| Pipeline Flow | Visual 4-step funnel with actual counts per stage |
| KPI Cards | Total leads · enriched · messages · avg lead score · avg English need |
| Sector Distribution | Animated bar chart — which sectors dominate your lead pool |
| Seniority Breakdown | Decision-maker distribution (C-Level through Junior) |
| Lead Priority Grid | Urgent / High / Medium / Low counts from CRM scoring |
| City Heatmap | Geographic concentration of leads |
| Channel Split | LinkedIn DM vs Cold Email breakdown |
| Top Leads Table | Ranked by lead score, with company, sector, English score, priority badge |

---

## 🔑 Design Decisions

**Why Python over n8n/Make?**
Every step is visible, version-controlled, and testable in isolation. Visual tools hide logic; this pipeline shows exactly what happens at each stage, which matters when iterating on prompt quality or scoring algorithms.

**Why SQLite + CSV dual-write?**
SQLite provides relational query power (JOINs, aggregations, triggers). CSV provides zero-friction shareability — any stakeholder can open it in Excel without touching the codebase.

**Why prompts.py as a separate module?**
Prompts are the core intellectual property of an AI pipeline. Keeping them isolated means the team can iterate on copy and framing without touching business logic. Each prompt is independently version-controllable.

**Why mock mode?**
The pipeline is fully functional without an API key. This means onboarding a new team member, running CI checks, or demoing the architecture costs zero API credits.

---

## 🚀 Bonus: What's Next

The foundation is built. These extensions would take the system to production:

- **LinkedIn account warming** via AdsPower / Multilogin for safe outbound volume
- **Auto-reply classification** — Claude reads incoming replies and labels them: `interested / not_interested / out_of_office / referral`
- **Multi-step sequence** — if no reply in 5 days, generate a follow-up message calibrated to the original
- **Deliverability layer** — domain warm-up, SPF/DKIM setup, sending schedule randomization
- **Real scraping** — replace mock generator with Apollo.io / LinkedIn Sales Navigator / PhantomBuster integration
- **CRM sync** — push qualified leads to HubSpot / Pipedrive via API

---

## 👤 Author

Built in 48 hours for the **Konuşarak Öğren — Growth Automation & AI Ops Intern Challenge**.

*"Asıl ölçmek istediğimiz şey mükemmel kod değil — problem çözme yaklaşımın, sistem kurma becerin ve AI'yı nasıl kullandığın."*

---

<p align="center">
  Made with Claude · Python · and a growth mindset
</p>
