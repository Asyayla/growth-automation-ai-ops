# Konuşarak Öğren — Growth Automation & AI Ops Pipeline

An end-to-end outbound growth system for identifying, enriching, and engaging HR
professionals across Turkey. Developed as a 48-hour technical challenge for the
*Growth Automation & AI Ops Intern* position at Konuşarak Öğren.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Claude API](https://img.shields.io/badge/Claude-Sonnet_4-D97706?style=flat-square)](https://anthropic.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)

---

## Project Overview

Konuşarak Öğren is Turkey's leading AI-powered corporate English training platform,
selling bulk HR licenses to companies. This pipeline automates the complete workflow
from lead generation to personalized outreach, eliminating manual research and
copy-paste messaging at every stage.

**Core capabilities delivered:**

- Generates a structured database of 100 Turkish HR professionals drawn from
  real companies across ten industry verticals
- Enriches each lead using Claude AI, producing company sector classification,
  estimated headcount, English training pain points, and a composite lead quality
  score (65–95 range)
- Writes two distinct outreach messages per lead — a LinkedIn DM and a cold email —
  each calibrated to the lead's company, sector, and seniority level
- Tracks every lead through a four-stage CRM pipeline and produces a static HTML
  analytics dashboard with no runtime dependencies

**Business rationale:** A single `python run_pipeline.py` replaces what would
otherwise require hours of manual LinkedIn research, CRM data entry, and
copywriting per lead. The system is designed to scale horizontally: swap the mock
data generator for a real Apollo.io or PhantomBuster CSV export and the remaining
three stages run without modification.

---

## Architecture and Data Pipeline

The system is organized as four independent, sequentially-executed pipeline stages
orchestrated by a single entry-point script.

```
run_pipeline.py  (Orchestrator)
│
├── Stage 01 — Data Generation          01_data_generator.py
│   Input:  none (mock) or leads_external.csv (Apollo / PhantomBuster)
│   Output: leads table, data/raw/leads_raw.csv
│
├── Stage 02 — Lead Enrichment          02_enricher.py
│   Input:  leads table
│   Claude API call per lead:
│     - Company sector and sub-sector classification
│     - Headcount estimation
│     - English training pain point (company-specific)
│     - English need score (1–10)
│     - Composite lead score (65–95)
│   Output: enrichments table, data/enriched/leads_enriched.csv
│
├── Stage 03 — Outreach Writer          03_outreach_writer.py
│   Input:  leads + enrichments JOIN
│   Claude API calls per lead (two):
│     - LinkedIn DM  (max 4 sentences, seniority-aware tone)
│     - Cold Email   (3-paragraph structure, sector-specific hook)
│   Output: messages table, data/outreach/messages_ready.csv
│
└── Stage 04 — CRM Tracker + Report     04_crm_tracker.py + report_generator.py
    Input:  all tables
    Output: crm_status table, output/pipeline_report.html
```

### Dual-Write Storage Architecture

Every pipeline stage writes to two destinations simultaneously: a SQLite relational
database for querying and cross-stage joins, and a CSV file for human-readable
inspection and sharing. This design decision has two practical motivations.

First, SQLite enables the JOIN queries that Stage 03 and Stage 04 depend on —
pulling enrichment scores alongside lead contact data in a single read. Second,
CSV files mean any stakeholder can inspect the pipeline output in a spreadsheet
without installing or configuring anything.

**Database schema:**

| Table | Primary purpose |
|---|---|
| `leads` | Identity, contact information, pipeline status |
| `enrichments` | AI-generated sector, size, pain point, lead score |
| `messages` | Generated LinkedIn DM and cold email per lead |
| `crm_status` | Pipeline stage, priority classification, follow-up dates |

Foreign key constraints and SQLite WAL mode are enabled on every connection.
All four tables are created idempotently via `IF NOT EXISTS` — running the pipeline
multiple times on an existing database is safe.

### Intelligent Mock Layer

When no `ANTHROPIC_API_KEY` is present, the system operates in mock mode.
This is not a static fixture. A dedicated knowledge base module (`ai/mock_data.py`)
maps 80+ named Turkish companies to precise sub-sector labels (e.g., Papara →
"Fintech / Payment Infrastructure", Getir → "Quick Delivery / Q-Commerce",
KPMG Turkey → "Consulting / Audit & Advisory (Big4)") and drives all downstream
outputs:

- Sector classification is company-specific, not keyword-guessed
- Lead scores are computed from four weighted factors: sector English-use intensity,
  seniority multiplier, estimated company size, and a deterministic per-company
  jitter — producing a realistic 65–95 distribution across 20+ distinct values
- Pain point text is drawn from a sector-specific template pool with company name
  interpolated, ensuring no two leads in the same sector receive identical copy
- Outreach messages use sector-family hooks so a banking lead and a fintech lead
  receive structurally different opening sentences

The result is a mock pipeline whose output is analytically indistinguishable from
real API output at the distribution level. When a real API key is provided, the
only change is that Claude generates these values from live reasoning rather than
the knowledge base.

### Project Structure

```
konusurak-ogren-growth/
│
├── run_pipeline.py               Entry point — orchestrates all stages
├── .env                          API keys and runtime configuration
├── requirements.txt
│
├── src/
│   ├── pipeline/
│   │   ├── 01_data_generator.py  Lead generation (mock or external CSV)
│   │   ├── 02_enricher.py        AI enrichment with rate-limit handling
│   │   ├── 03_outreach_writer.py Personalized message generation
│   │   ├── 04_crm_tracker.py     CRM sync, scoring, follow-up scheduling
│   │   └── report_generator.py   Static HTML dashboard (zero JS dependencies)
│   │
│   ├── ai/
│   │   ├── claude_client.py      Anthropic API wrapper (retry, mock fallback)
│   │   ├── prompts.py            All system and user prompt templates
│   │   └── mock_data.py          Intelligent mock knowledge base
│   │
│   ├── db/
│   │   ├── database.py           SQLite connection manager and CRUD layer
│   │   └── models.py             Dataclasses and CREATE TABLE statements
│   │
│   └── utils/
│       ├── config.py             Singleton configuration from .env
│       └── logger.py             Loguru setup with stdlib fallback
│
├── data/
│   ├── raw/                      leads_raw.csv
│   ├── enriched/                 leads_enriched.csv
│   └── outreach/                 messages_ready.csv
│
├── output/
│   └── pipeline_report.html      Generated analytics dashboard
│
└── logs/
    └── pipeline.log
```

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Rapid iteration, extensive data tooling |
| AI Engine | Anthropic Claude (Sonnet 4) | Reliable structured JSON output, strong Turkish-context reasoning |
| Database | SQLite 3 | Zero-configuration, relational, version-controllable alongside code |
| Data processing | Pandas | CSV I/O and DataFrame operations across pipeline stages |
| API client | `anthropic` SDK | Native retry logic, type safety, streaming support |
| Logging | Loguru with stdlib fallback | Single-line setup, log rotation, color output |
| Configuration | python-dotenv | 12-factor compliant secret management |
| Reporting | Pure HTML/CSS | No build step, no server, opens in any browser |

**On the choice of Python over n8n or Make:** Every processing step is visible,
version-controlled, and unit-testable in isolation. Visual workflow tools abstract
away the logic that matters most when iterating on prompt quality, scoring
algorithms, or data normalization rules. Python makes the system inspectable.

---

## Installation and Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/Asyayla/konusurak-ogren-growth.git
cd konusurak-ogren-growth
pip install -r requirements.txt
```

**requirements.txt**
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
# Required for live AI enrichment and outreach generation
ANTHROPIC_API_KEY=sk-ant-...

# Optional overrides
CLAUDE_MODEL=claude-sonnet-4-20250514
LEADS_TARGET_COUNT=100
BATCH_SIZE=10
ENRICH_DELAY_SEC=0.5
OUTREACH_TYPE=both
```

If `ANTHROPIC_API_KEY` is absent, the pipeline runs in mock mode automatically.
All four stages execute, all output files are generated, and the analytics dashboard
is fully populated. No API credits are required for a complete end-to-end run.

### 3. Run the pipeline

```bash
# Quick test — 3 leads through all 4 stages (default)
python run_pipeline.py

# Full run — all 100 leads
python run_pipeline.py --all

# Controlled test — specific lead count
python run_pipeline.py --limit 10

# Resume from a specific stage
python run_pipeline.py --stage 2 --all

# Reset all state and start from scratch
python run_pipeline.py --fresh --all

# Regenerate the HTML report without re-running the pipeline
python run_pipeline.py --report-only
```

**Expected output:**

```
╔══════════════════════════════════════════════════════════╗
║   KONUŞARAK ÖĞREN — GROWTH PIPELINE                    ║
║   Growth Automation & AI Ops Intern Challenge           ║
╚══════════════════════════════════════════════════════════╝
  Date   : 04.06.2026 18:12:00
  Model  : claude-sonnet-4-20250514
  Mode   : Mock (no API key)
  Limit  : all leads

  Stage 1 / 4 — Data Generation
  Stage 2 / 4 — Lead Enrichment
  Stage 3 / 4 — Outreach Writer
  Stage 4 / 4 — CRM Tracking + Report

  Result : 5/5 stages successful  |  Total runtime: 5.7s
  Report : output/pipeline_report.html
```

### 4. Run individual stages

Each stage module is independently executable, which is useful during development
and prompt iteration:

```bash
PYTHONPATH=src python src/pipeline/01_data_generator.py
PYTHONPATH=src python src/pipeline/02_enricher.py --limit 5
PYTHONPATH=src python src/pipeline/03_outreach_writer.py --type linkedin --limit 5
PYTHONPATH=src python src/pipeline/04_crm_tracker.py

# Validate an external CSV without writing to the database
PYTHONPATH=src python src/pipeline/01_data_generator.py --validate path/to/export.csv
```

---

## Sample Outputs

### Lead Enrichment

For a lead such as **Esra Çelik** (Senior HR Specialist, KPMG Turkey), the
enrichment stage produces:

```json
{
  "industry": "Consulting / Audit & Advisory (Big4)",
  "company_size": "500+",
  "company_size_est": 2800,
  "pain_point": "Consultants at KPMG Turkey working on international project
                 teams cannot produce global methodology documents, case studies,
                 and client presentations in fluent English, which directly
                 affects project quality and career progression.",
  "english_need_score": 9,
  "english_need_reason": "KPMG Turkey: all project deliverables, management
                          presentations, and global firm standards require English.",
  "outreach_angle": "Frame the conversation around global methodology accreditation
                     or international client acquisition — these are the highest-value
                     English use cases in a consulting context.",
  "lead_score": 83
}
```

### LinkedIn DM

```
Merhaba Esra, KPMG Türkiye'ın global proje portföyünü ve yeni pazar
kazanımlarını takip ediyorum. Bu süreçte ekibinizin İngilizce müzakere
ve yazışma kapasitesi operasyonel bir darboğaz oluyor mu? Konuşarak
Öğren olarak Danışmanlık sektöründen referans vakalarımızla AI destekli
kurumsal İngilizce pratiği sunuyoruz.

CTA: Kısa bir görüşmede nasıl çözdüklerini aktarabilir miyim?
```

### Cold Email

**Subject:** `KPMG Türkiye yabancı müşteri pitch'i için bir fikir`

```
KPMG Türkiye'ın global proje portföyünü ve yeni pazar kazanımlarını takip
ediyorum; bu ölçekte büyüyen danışmanlık firmalarında İngilizce proje
yürütme kapasitesi doğrudan gelir yaratıyor.

Yabancı müşteri toplantılarında ve global pitch süreçlerinde KPMG Türkiye
danışmanlarının gerçek zamanlı İngilizce iletişim güveni, kazanma oranını
doğrudan belirliyor. Danışmanlık sektöründe yaptığımız araştırmaya göre
çalışanların %78'i İngilizce konuşma pratiğini en öncelikli gelişim alanı
olarak görüyor.

Konuşarak Öğren olarak bu boşluğu AI konuşma pratiği + canlı ders hibrid
modeliyle kapatıyoruz; 15 dakikalık bir görüşmede somut vaka çalışmalarını
paylaşabilir miyim?

Konuşarak Öğren Ekibi
konusarakogren.com
```

**What distinguishes these messages from generic outreach:**

- The opening sentence references the company's specific market activity, not a
  generic greeting
- Sector-specific pain point framing: a consulting message and a banking message
  use structurally different arguments
- Seniority-aware CTA: Director and above receive a strategic framing; Mid/Senior
  receive a practical, low-commitment call to action
- No filler phrases, no feature lists, no product names in the first two sentences

### Analytics Dashboard

`output/pipeline_report.html` opens in any browser with no server or build step.

| Section | Contents |
|---|---|
| Pipeline funnel | Four-stage count visualization from generation through CRM |
| KPI summary | Total leads, enrichment rate, message count, average lead score |
| Sector distribution | Animated bar chart across all industry verticals |
| Seniority breakdown | Decision-maker distribution from C-Level through Junior |
| Priority grid | Lead count by Urgent / High / Medium / Low classification |
| City distribution | Geographic concentration across Turkish cities |
| Channel split | LinkedIn DM versus cold email volume |
| Top leads table | Ranked by lead score with company, sector, and priority badge |

---

## Design Decisions

**Prompt isolation in `prompts.py`:** All system and user prompt templates are
separated from business logic. This means copy and framing can be iterated without
touching pipeline code, and prompt versions can be tracked independently in version
control.

**Mock mode as a first-class concern:** The pipeline is fully functional without an
API key. This was a deliberate design decision — it means new team members can run
the complete system on day one, CI environments never incur API costs, and demos
can be conducted without credential management.

**Modular stage design:** Each pipeline stage exposes a single `run()` function
with a consistent signature. The orchestrator loads stages dynamically using
`importlib`, which handles the numeric prefix in filenames (`01_`, `02_`) without
requiring package restructuring.

**Exponential backoff in the API client:** The `ClaudeClient` wrapper implements
three-attempt retry logic with delays of 1, 3, and 7 seconds. Rate limit responses
(HTTP 429) and transient server errors (500, 529) are retried; authentication and
validation errors are raised immediately.

---

## Extension Points

The current implementation provides a complete prototype. The following integrations
would move it toward production without requiring architectural changes:

- **Real lead data:** Replace the mock generator by placing an Apollo.io or
  PhantomBuster CSV export at `leads_external.csv` in the project root. The pipeline
  auto-detects the file and routes to the external loader, which handles both export
  formats and normalizes column names automatically.
- **Sending layer:** Add a `05_sender.py` stage that reads `messages_ready.csv` and
  dispatches via LinkedIn API or a transactional email provider (SendGrid, Postmark).
- **Reply classification:** A follow-up stage that reads incoming replies and labels
  them `interested / not_interested / out_of_office / referral` using a short Claude
  prompt, then updates `crm_status.outcome`.
- **Multi-step sequences:** If `crm_status.contact_attempts == 1` and no reply
  after N days, generate a follow-up message calibrated to the original.
- **CRM sync:** Push qualified leads (score >= threshold) to HubSpot or Pipedrive
  via their REST APIs, using `crm_status` as the source of truth.
- **Deliverability infrastructure:** Domain warm-up, SPF/DKIM configuration,
  sending schedule randomization to protect sender reputation.

---

## Project Context

Built in 48 hours for the Konuşarak Öğren Growth Automation & AI Ops Intern
Challenge. The evaluation criterion stated: *"We are not looking for perfect code.
We want to see your problem-solving approach, your ability to build systems, your
automation thinking, and your capacity to own a process end-to-end."*

This submission addresses all four dimensions: a real problem (outbound growth for
an English training platform), a complete system (four stages, two databases, one
orchestrator), automated reasoning (AI enrichment and message generation), and
end-to-end ownership (from raw data to a deliverable HTML report in a single
command).

---

*Made with Python, Claude, and a growth mindset.*
