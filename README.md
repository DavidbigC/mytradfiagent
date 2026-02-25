# Financial Research AI Agent

A full-stack AI-powered financial research platform for Chinese A-share and US market analysis. Users chat with the system; it calls 33+ specialised financial data tools, reasons with multiple LLMs, and optionally runs a structured multi-model **hypothesis debate** (bull vs bear analysts + judge) for investment questions.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [LLM Stack](#llm-stack)
- [Agent Modes](#agent-modes)
- [Tools Reference](#tools-reference)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Installation](#installation)
- [Running Locally](#running-locally)
- [Production Deployment](#production-deployment)
- [Data Ingestion](#data-ingestion)
- [Scheduled Jobs (Cron)](#scheduled-jobs-cron)
- [API Reference](#api-reference)
- [Frontend](#frontend)

---

## Features

- **Conversational AI agent** with access to 33+ real-time financial data tools
- **Three agent modes**: Normal (deep research), Debate (bull vs bear hypothesis testing), Fast (sub-5s Grok with web search)
- **Chinese A-share focus**: real-time quotes, financials, capital flow, fund data, OHLCV bars
- **Multi-model debate engine**: MiniMax + Qwen debaters, structured verdict, auto-generated PDF reports
- **Technical analysis sandbox**: runs pandas-ta scripts in a subprocess with a 40+ indicator library
- **Voice input**: Whisper STT with fuzzy A-share stock name matching
- **Conversation sharing**: public share links for conversations
- **Fund research**: NAV history, holdings, rankings, ratings, manager profiles
- **OHLCV database**: 5-minute bars for all ~5200 A-shares from 2020, with daily incremental updates
- **10-year quarterly financials**: income, balance sheet, cashflow, DuPont decomposition for all A-shares

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                     React 19 Frontend                       │
│         (TypeScript, Vite, React Router, SSE streaming)     │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼─────────────────────────────────┐
│                   FastAPI Backend (web.py)                   │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────┐    │
│  │  api_chat.py │  │  api_auth.py  │  │ api_admin.py  │    │
│  └──────┬───────┘  └───────────────┘  └───────────────┘    │
│         │                                                    │
│  ┌──────▼────────────────────────────────────────────────┐  │
│  │                    agent.py                            │  │
│  │  run_agent (normal) │ run_debate │ run_agent_fast      │  │
│  └──────┬────────────────────────────────────────────────┘  │
│         │ asyncio.gather (parallel tool calls)               │
│  ┌──────▼────────────────────────────────────────────────┐  │
│  │              tools/ (33+ tools)                        │  │
│  │  cn_market · stocks · cn_eastmoney · ohlcv · funds    │  │
│  │  web · ta_executor · output · subagent · ...          │  │
│  └──────┬────────────────────────────────────────────────┘  │
└─────────┼──────────────────────────────────────────────────-┘
          │
┌─────────▼──────────────────────────────────────────────────┐
│              PostgreSQL (2 databases)                        │
│  myaiagent  — users, conversations, messages, ta_strategies  │
│  marketdata — ohlcv_5m, financials, funds, fund_nav, ...    │
└────────────────────────────────────────────────────────────-┘
```

---

## LLM Stack

| Model | Provider | Role |
|---|---|---|
| **MiniMax-M1-80k** | Fireworks AI (default) or MiniMax official | Primary agent loop, planning, debate judge, bull arguments, executive summary |
| **qwen-plus** | Alibaba DashScope | Debate bear-side arguments |
| **grok-4-1-fast-non-reasoning** | X.ai | Fast mode (built-in web search), web search fallback |

> **Note:** MiniMax defaults to Fireworks (`MINIMAX_PROVIDER=fireworks`). Set `MINIMAX_PROVIDER=minimax` to use the official MiniMax SDK instead. The Grok client is created at import time — restart the server after adding `GROK_API_KEY`.

---

## Agent Modes

### Normal Mode
Full agentic research loop using MiniMax with access to all 33+ tools.

**Flow:**
1. **Planning turn** (tool-free): MiniMax reads the question and forms a research plan, emitting `<think>` blocks
2. **Agentic loop** (max 30 turns):
   - LLM receives messages + tool schemas → returns tool calls
   - All tool calls for that turn execute **in parallel** via `asyncio.gather()`
   - Each result truncated to 40k chars, appended to messages
   - Repeats until no tool calls or 30 turns exceeded
3. Final response with citations and references

**Best for:** Deep research questions, financial analysis, multi-stock comparisons, TA analysis

---

### Debate Mode
Structured investment hypothesis testing with multiple AI analysts taking opposing sides.

**Flow:**

| Phase | What Happens |
|---|---|
| **0 — Hypothesis Formation** | MiniMax parses question into testable H₀ + data plan (JSON) |
| **1 — Data Collection** | Up to 20 tool calls executed in parallel (no LLM) |
| **2 — Opening Arguments** | 4 parallel LLM calls: MiniMax Bull + Qwen Bull + MiniMax Bear + Qwen Bear (each gets up to 3 tool rounds) |
| **3 — Rebuttals** | Each analyst reads opposing arguments + responds (4 parallel calls) |
| **4 — Judge Verdict** | MiniMax judges anonymised, shuffled arguments → verdict + confidence (1–10) + risks |
| **5 — Executive Summary** | MiniMax synthesises all arguments → institutional 2-minute read |
| **6 — Report Generation** | Auto-generates `.md` + `.pdf` report saved to `output/{user_id}/` |

**Best for:** Investment decisions, bull-vs-bear analysis, stock valuation questions like "Is 600900 worth investing in?"

---

### Fast Mode
Single-turn Grok call with built-in web search. No tool loop, no planning turn.

- Response in under 5 seconds
- Max 1500 tokens
- Uses Grok's native `web_search` tool
- Saved to conversation history
- Requires `GROK_API_KEY`; falls back to DuckDuckGo if missing

**Best for:** Quick factual lookups, current news, market summaries

---

## Tools Reference

### Web & Search

| Tool | Data Source | Description |
|---|---|---|
| `web_search` | Tavily → Grok → DuckDuckGo (fallback chain) | Web search with automatic failover |
| `scrape_webpage` | BeautifulSoup + Playwright | Scrape any webpage; Playwright for JS-heavy sites |

### Chinese A-Share Market Data

| Tool | Data Source | Description |
|---|---|---|
| `fetch_cn_stock_data` | Tencent Finance (qt.gtimg.cn) + AKShare fallback | Real-time quote, PE/PB, 52-week range, price history |
| `fetch_multiple_cn_stocks` | Tencent batch API | Batch quotes for up to N stocks |
| `fetch_cn_bond_data` | EastMoney | Treasury yield curve, corporate bond indices |
| `fetch_stock_financials` | EastMoney datacenter | 10+ years quarterly financials (income, balance, cashflow) |
| `fetch_top_shareholders` | EastMoney | Top 10 shareholders with period-over-period change direction |
| `fetch_dividend_history` | EastMoney (分红送配) | Full dividend and stock split history |
| `fetch_dragon_tiger` | EastMoney (龙虎榜) | Daily limit-up/limit-down seat data |

### US Market Data

| Tool | Data Source | Description |
|---|---|---|
| `fetch_stock_data` | Yahoo Finance | Single US/HK stock — quote, history, fundamentals |
| `fetch_multiple_stocks` | Yahoo Finance batch | Multiple US/HK stocks in one call |

### Capital Flow & Market Intelligence

| Tool | Data Source | Description |
|---|---|---|
| `fetch_stock_capital_flow` | EastMoney | Capital flow breakdown by order size (主力/大单/散户) |
| `fetch_northbound_flow` | EastMoney | Top northbound (北向资金) stock inflows/outflows |
| `fetch_capital_flow_ranking` | EastMoney | Today's capital flow rankings across all A-shares |
| `scan_market_hotspots` | EastMoney | Market indices, sector performance, top movers |

### Screening

| Tool | Data Source | Description |
|---|---|---|
| `screen_cn_stocks` | EastMoney (~5200 A-shares) | Filter and sort stocks by any financial metric |

### Company Reports

| Tool | Data Source | Description |
|---|---|---|
| `fetch_company_report` | Sina Finance + Grok (2M context window) | Full annual/quarterly reports, parsed and summarised |
| `fetch_sina_profit_statement` | Sina Finance | Detailed profit statement by year |

### Fund & ETF Data

| Tool | Data Source | Description |
|---|---|---|
| `fetch_cn_fund_data` | AKShare | Fund NAV history, ETF price history, fund status (申购/赎回) |
| `fetch_cn_fund_holdings` | EastMoney | Fund equity holdings by quarter |
| `fetch_fund_holdings` | SEC 13F filings | US institutional fund holdings |
| `run_fund_chart_script` | AKShare → Plotly | Generate fund performance charts |

### OHLCV & Technical Analysis

| Tool | Data Source | Description |
|---|---|---|
| `fetch_ohlcv` | Local `marketdata` DB (`ohlcv_5m`) | 5-min bars with MA5/MA20/MA60. Supports 5m/1h/1d/1w via SQL aggregation |
| `run_ta_script` | Subprocess sandbox (pandas-ta + Plotly) | Execute TA scripts with 40+ indicators in an isolated environment |

### TA Strategy Knowledge Base

| Tool | Description |
|---|---|
| `lookup_ta_strategy` | Full-text search for trading strategies by name or alias |
| `save_ta_strategy` | Persist a new trading strategy to the knowledge base |
| `update_ta_strategy` | Update an existing strategy |

### Output & Reporting

| Tool | Description |
|---|---|
| `generate_chart` | Generate matplotlib charts (line, bar, comparison) as PNG |
| `generate_pdf` | Render markdown content to a downloadable PDF |

### Data Source Management

| Tool | Description |
|---|---|
| `lookup_data_sources` | Look up known data source URLs from local knowledge base |
| `save_data_source` | Save a new data source URL to the knowledge base |

### Advanced

| Tool | Description |
|---|---|
| `dispatch_subagents` | Spawn up to 8 parallel MiniMax sub-agents (max 8 turns each) for independent research tasks |
| `analyze_trade_opportunity` | Entry point for the full hypothesis debate engine |

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and **npm**
- **PostgreSQL 14+** (two databases: `myaiagent` and `marketdata`)
- **Playwright** browsers (for JS-heavy scraping): `playwright install chromium`

---

## Environment Variables

Create a `.env` file in the project root:

```bash
# ── MiniMax (Primary Agent) ──────────────────────────────────────────────────
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_PROVIDER=fireworks              # "fireworks" (default) or "minimax"
MINIMAX_BASE_URL=https://api.minimaxi.chat/v1
MINIMAX_MODEL=MiniMax-M1-80k

# ── Fireworks (MiniMax via Fireworks) ───────────────────────────────────────
FIREWORKS_API_KEY=your_fireworks_api_key
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MINIMAX_MODEL=accounts/fireworks/models/minimax-m2p1

# ── Qwen (Debate Bear Side) ─────────────────────────────────────────────────
QWEN_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# ── Grok (Fast Mode + Web Search Fallback) ───────────────────────────────────
# Optional but required for fast mode; web search falls back to DuckDuckGo if missing
GROK_API_KEY=your_grok_api_key
GROK_BASE_URL=https://api.x.ai/v1
GROK_MODEL_noreasoning=grok-4-1-fast-non-reasoning

# ── Web Search ──────────────────────────────────────────────────────────────
# Optional; falls back to Grok → DuckDuckGo if missing
TAVILY_API_KEY=your_tavily_api_key

# ── Speech-to-Text ──────────────────────────────────────────────────────────
# Optional; enables voice input (Whisper)
OPENAI_API_KEY=your_openai_api_key

# ── Databases ───────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://user:password@localhost/myaiagent
MARKETDATA_URL=postgresql://user:password@localhost/marketdata

# ── Server ──────────────────────────────────────────────────────────────────
JWT_SECRET=change-this-to-a-random-secret
WEB_PORT=8000
ADMIN_USERNAME=your_admin_username      # Only this user can create new accounts
```

### Minimum Required Keys

For the system to function at all:

| Key | Required For |
|---|---|
| `MINIMAX_API_KEY` + `FIREWORKS_API_KEY` | Normal and debate mode (or just `MINIMAX_API_KEY` with `MINIMAX_PROVIDER=minimax`) |
| `DATABASE_URL` | All conversation storage |
| `JWT_SECRET` | Authentication |

Everything else degrades gracefully: missing `GROK_API_KEY` disables fast mode and falls back web search to DuckDuckGo; missing `TAVILY_API_KEY` falls back to Grok then DuckDuckGo; missing `OPENAI_API_KEY` disables voice input; missing `MARKETDATA_URL` means OHLCV tools return errors.

---

## Database Setup

### 1. Create the main app database

The main database (`myaiagent`) schema is created **automatically** when the server starts via `db.py::init_db()`. You only need to create the empty database:

```sql
CREATE DATABASE myaiagent;
```

### 2. Create the market data database

The `marketdata` database schema must be created manually before ingestion:

```bash
python data/setup_db.py
```

This creates all tables including:

| Table | Description |
|---|---|
| `ohlcv_5m` | 5-minute OHLCV bars, partitioned by year (2020–2026), indexed on `(code, ts DESC)` |
| `financials` | Quarterly financials for all A-shares (profitability, operations, growth, solvency, cashflow, DuPont) |
| `funds` | Fund catalog (ETF, open-end, LOF) |
| `fund_nav` | Daily NAV history with subscription/redemption status |
| `fund_price` | ETF/LOF market price history |
| `fund_holdings` | Fund equity holdings by quarter |
| `fund_managers` | Fund manager history per fund |
| `fund_manager_profiles` | Aggregated manager performance stats |
| `fund_fees` | Fee schedules |
| `fund_rank` | Fund ranking snapshots |
| `fund_rating` | Morningstar + broker ratings |

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd myaiagent

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Playwright browser for JS-heavy scraping
playwright install chromium

# 5. Install frontend dependencies
cd frontend && npm install && cd ..

# 6. Copy and fill in environment variables
cp .env.example .env   # edit .env with your keys

# 7. Create PostgreSQL databases
createdb myaiagent
createdb marketdata

# 8. Set up marketdata schema
python data/setup_db.py
```

---

## Running Locally

```bash
# Development (starts server + auto-builds frontend if src/ changed)
python start.py

# Or manually build frontend first, then start server
cd frontend && npm run build && cd ..
python web.py
```

The server starts on `http://localhost:8000` (or `WEB_PORT`).

On first run, `init_db()` creates all main app tables automatically.

> **First login:** Use the `ADMIN_USERNAME` account. Only the admin can create additional user accounts via the API.

---

## Production Deployment

### Systemd Service (Linux)

Create `/etc/systemd/system/myaiagent.service`:

```ini
[Unit]
Description=Financial Research AI Agent
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/myaiagent
EnvironmentFile=/path/to/myaiagent/.env
ExecStart=/path/to/myaiagent/.venv/bin/python start.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable myaiagent
sudo systemctl start myaiagent

# View logs
sudo journalctl -u myaiagent -f
```

### Deploying Updates

```bash
git pull

# Rebuild frontend if UI changed
cd frontend && npm run build && cd ..

# Restart service
sudo systemctl restart myaiagent
```

---

## Data Ingestion

All ingestion scripts live in `data/`. Run these once on initial setup (some take hours):

### Step 1: OHLCV Price History

Downloads 5-minute bars for all ~5200 active A-shares from 2020 to today via BaoStock.

```bash
python data/update_ohlcv.py
```

> This does the initial bulk load on first run (empty DB). Subsequent runs are incremental — each stock fetches only from its own latest timestamp. Runtime: ~30 minutes with 10 parallel workers.

### Step 2: Fund Data

```bash
python data/ingest_funds.py
```

Fetches: fund catalog, manager profiles, NAV history, ETF prices, holdings, rankings, ratings. Runtime: several hours (parallel with 15 workers).

### Step 3: Quarterly Financials

```bash
# Full historical load (10 years, all A-shares) — run once
python data/ingest_financials.py --full

# Incremental update (new quarters only)
python data/ingest_financials.py
```

---

## Scheduled Jobs (Cron)

Add these to your crontab (`crontab -e`):

```bash
# Daily OHLCV update — weekdays at 16:30 CST (08:30 UTC), after market close
30 8 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_ohlcv.py >> /var/log/ohlcv_update.log 2>&1

# Daily fund NAV + ETF prices — weekdays at 20:00 CST (12:00 UTC)
0 12 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_funds.py >> /var/log/fund_update.log 2>&1

# Weekly fund manager change detection — Sundays at 20:00 CST (12:00 UTC)
0 12 * * 0 cd /path/to/myaiagent && .venv/bin/python data/update_funds.py --check-managers >> /var/log/fund_managers.log 2>&1

# Monthly financials update — 1st of each month at 09:00 CST (01:00 UTC)
0 1 1 * * cd /path/to/myaiagent && .venv/bin/python data/ingest_financials.py >> /var/log/financials.log 2>&1
```

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Login with username/password → JWT token |
| `POST` | `/api/auth/create-account` | Create account (admin only) |
| `GET` | `/api/auth/me` | Current user info |

All authenticated endpoints require `Authorization: Bearer <token>` header.

### Chat

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat/send` | Send message; returns SSE stream |
| `GET` | `/api/chat/stream` | Reattach to a running SSE stream |
| `POST` | `/api/chat/stop` | Cancel a running agent |
| `GET` | `/api/chat/active` | Check if agent is running |
| `GET` | `/api/chat/conversations` | List conversations |
| `POST` | `/api/chat/conversations` | Create conversation (`{"mode": "normal\|debate\|fast"}`) |
| `GET` | `/api/chat/conversations/{id}/messages` | Load conversation history |
| `DELETE` | `/api/chat/conversations/{id}` | Delete conversation |
| `PATCH` | `/api/chat/conversations/{id}/mode` | Switch conversation mode |
| `POST` | `/api/chat/conversations/{id}/share` | Toggle public sharing |
| `GET` | `/api/chat/share/{token}` | Public conversation view |
| `POST` | `/api/chat/stt` | Audio → text (Whisper + stock name matching) |

### SSE Event Types

The `/api/chat/send` endpoint streams Server-Sent Events:

| Event | Payload | Description |
|---|---|---|
| `status` | `"Running: fetch_cn_stock_data..."` | Tool execution progress |
| `thinking` | `{source, label, content}` | LLM reasoning (`<think>` blocks) |
| `token` | streaming text | Response tokens |
| `done` | `{text, files, references}` | Final response + generated files |
| `error` | `{error}` | Error message |

### Admin (Admin Only)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/tables` | List all DB tables |
| `GET` | `/api/admin/tables/{name}` | Table schema + row count |
| `GET` | `/api/admin/tables/{name}/rows` | Paginated rows |
| `POST` | `/api/admin/query` | Read-only SQL (SELECT/WITH/EXPLAIN only) |

---

## Frontend

**Stack:** React 19 · TypeScript · Vite 6 · React Router 7

```
frontend/src/
├── main.tsx              App entry point
├── store.tsx             AuthContext (JWT in localStorage)
├── api.ts                All fetch/SSE calls
├── i18n.tsx              English/Chinese string map
├── pages/
│   ├── ChatLayout.tsx    Main shell: sidebar + chat view
│   ├── LoginPage.tsx     Login form
│   ├── ShowcasePage.tsx  Public demo conversations
│   └── GuidancePage.tsx  Help documentation
└── components/
    ├── ChatView.tsx       Core chat component with SSE handling
    ├── MessageBubble.tsx  Markdown message rendering
    ├── ThinkingBlock.tsx  Collapsible <think> block display
    ├── StatusIndicator.tsx Tool execution progress indicator
    ├── Sidebar.tsx        Conversation list + new chat buttons
    └── ReportsPanel.tsx   Generated file browser + download
```

```bash
# Development (with hot reload, proxies API to :8000)
cd frontend && npm run dev

# Production build
cd frontend && npm run build
# Output: frontend/dist/ — served by FastAPI at /
```

The `start.py` script automatically rebuilds the frontend if any `src/` files have changed since the last build.
