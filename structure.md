# Codebase Structure & Architecture

> Read this before touching any file. It covers every module, the data flows, key constraints, and tool calling mechanics so you don't need to read every script from scratch.

---

## What This System Is

A **Financial Research AI Agent** for Chinese A-share (and US) market analysis. Users chat with it; it calls 33+ specialised financial data tools, reasons with multiple LLMs, and optionally runs a multi-model "hypothesis debate" (bull vs bear analysts + judge) for investment questions.

**LLM Stack**:
- **MiniMax** (`MiniMax-M1-80k` via Fireworks or official API) — primary agent loop, planning, debate judge & bull-side, executive summary
- **Qwen** (`qwen-plus`) — debate bear-side arguments
- **Grok** (`grok-4-1-fast-non-reasoning`) — fast mode (built-in web search), fallback web search

---

## Top-Level File Map

```
myaiagent/
├── web.py              # FastAPI entry point; mounts routers; init_db on startup
├── config.py           # All env vars + get_system_prompt() + get_planning_prompt() + get_fast_system_prompt()
├── agent.py            # run_agent (normal), run_debate (debate), run_agent_fast (fast/Grok)
├── api_chat.py         # /api/chat/ routes; SSE streaming; AgentRun buffering; /stop; STT; sharing
├── api_auth.py         # /api/auth/ routes; login, create-account (admin only)
├── api_admin.py        # /api/admin/ routes; DB inspection (admin-only), read-only SQL
├── auth.py             # bcrypt + JWT helpers
├── db.py               # asyncpg pool + full schema SQL + init_db()
├── accounts.py         # Conversation/message DB helpers + per-user locks + summarisation
├── start.py            # Server startup script
├── tools/              # All tool implementations (see below)
├── frontend/           # React 19 + TypeScript SPA (Vite)
├── output/             # Generated PDFs and charts (per-user subdirs)
├── data/               # DB setup + ingestion scripts (marketdata DB)
│   ├── setup_db.py     # One-time schema creation for marketdata DB
│   └── ingest_funds.py # Bulk fund data ingestion (NAV, rank, ratings, catalog)
├── changes.md          # Change log (append after every task — required)
└── CLAUDE.md           # Project instructions for coding agents
```

---

## Environment Variables (`config.py`)

| Variable | Default | Purpose |
|---|---|---|
| `MINIMAX_API_KEY` | — | MiniMax official API |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.chat/v1` | |
| `MINIMAX_MODEL` | `MiniMax-M1-80k` | |
| `MINIMAX_PROVIDER` | `fireworks` | `"fireworks"` or `"minimax"` |
| `FIREWORKS_API_KEY` | — | Fireworks drop-in (OpenAI-compatible) |
| `FIREWORKS_MINIMAX_MODEL` | `accounts/fireworks/models/minimax-m2p1` | |
| `QWEN_API_KEY` | — | Debate bear arguments |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | |
| `QWEN_MODEL` | `qwen-plus` | |
| `GROK_API_KEY` | — | Fast mode + web search fallback. **Missing = fast mode disabled, web_search falls back to DuckDuckGo** |
| `GROK_BASE_URL` | `https://api.x.ai/v1` | |
| `GROK_MODEL_NOREASONING` | `grok-4-1-fast-non-reasoning` | Note: env var is lowercase `noreasoning` |
| `TAVILY_API_KEY` | — | Primary web search (web_search tool). Falls back to Grok → DuckDuckGo |
| `OPENAI_API_KEY` | — | Whisper STT transcription |
| `DATABASE_URL` | `postgresql://localhost/myaiagent` | Main app DB |
| `MARKETDATA_URL` | `postgresql://localhost/marketdata` | Market data DB (OHLCV, funds, financials) |
| `JWT_SECRET` | `dev-secret-...` | HS256 JWT signing |
| `WEB_PORT` | `8000` | |
| `ADMIN_USERNAME` | `davidc` | Only this user can create accounts |

---

## Database Schema

### Main DB (`myaiagent`) — `db.py`

**Users & Auth**:
```
users               id UUID, display_name TEXT, created_at, last_active_at
platform_accounts   id, user_id, platform, platform_uid, linked_at
web_accounts        id, user_id, username UNIQUE, password_hash, created_at
```

**Conversations & Messages**:
```
conversations   id UUID, user_id, title, created_at, updated_at,
                summary TEXT, summary_up_to INT,
                mode TEXT (normal|debate|fast),
                share_token TEXT UNIQUE, is_public BOOLEAN DEFAULT false
messages        id SERIAL, conversation_id, role, content,
                tool_calls JSONB, tool_call_id, created_at
files           id, user_id, conversation_id, filepath, filename, file_type, created_at
```

**Knowledge Bases**:
```
stocknames      stock_code CHAR(6), exchange CHAR(2), stock_name, full_name,
                sector, industry, list_date, pinyin, updated_at
                -- FTS on pinyin + name; used by STT for injection prevention

ta_strategies   id, name TEXT UNIQUE, aliases TEXT[], description,
                indicators TEXT[], parameters JSONB, source_url,
                created_at, updated_at
                -- FTS index on name; searchable via lookup_ta_strategy

report_cache    stock_code CHAR(6), report_type VARCHAR, report_year SMALLINT,
                title, filepath, source_url, created_at
                UNIQUE (code, type, year)
```

### Market Data DB (`marketdata`) — `data/setup_db.py`

**Price Data**:
```
ohlcv_5m        ts TIMESTAMPTZ, code CHAR(6), exchange CHAR(2),
                open/high/low/close REAL, volume BIGINT, amount DOUBLE PRECISION
                -- Partitioned by year (2020–2026); indexes: (code, ts DESC), BRIN on ts
                -- UNIQUE (ts, code, exchange)
```

**Financials**:
```
financials      code, exchange, pub_date, stat_date,
                -- Profitability: roe_avg, np_margin, gp_margin, net_profit, eps_ttm, mb_revenue, total_share, liqa_share
                -- Operations: nr_turn_ratio/days, inv_turn_ratio/days, ca_turn_ratio, asset_turn_ratio
                -- Growth: yoy_equity, yoy_asset, yoy_ni, yoy_eps_basic, yoy_pni
                -- Solvency: current_ratio, quick_ratio, cash_ratio, yoy_liability, liability_to_asset, asset_to_equity
                -- Cash flow: ca_to_asset, nca_to_asset, tangible_asset_to_asset, ebit_to_interest, cfo_to_or/np/gr
                -- DuPont: dupont_roe, dupont_asset_sto_equity, dupont_asset_turn, dupont_pnitoni, dupont_nitogr,
                           dupont_tax_burden, dupont_int_burden, dupont_ebit_togr
                UNIQUE (code, stat_date)
```

**Fund Tables**:
```
funds               code TEXT PK, name, full_name, type, exchange,
                    inception_date, tracking_index, mgmt_company, custodian, updated_at

fund_managers       fund_code → funds, manager_name, start_date, end_date
                    PK (fund_code, manager_name, start_date)

fund_manager_profiles  manager_name TEXT PK, company, tenure_days, total_aum,
                       best_return_pct, updated_at

fund_fees           fund_code → funds, mgmt_rate, custody_rate, sales_svc_rate,
                    subscription_rate, effective_date, end_date
                    UNIQUE (fund_code, effective_date)

fund_nav            fund_code TEXT, date DATE,
                    unit_nav NUMERIC(12,4), accum_nav NUMERIC(12,4),
                    daily_return_pct NUMERIC(8,4),
                    sub_status TEXT,      -- 申购状态 (e.g. 开放申购, 封闭期, 场内买入)
                    redeem_status TEXT,   -- 赎回状态
                    PK (fund_code, date)
                    -- Source: fund_etf_fund_info_em (all fund types, not ETF-only)
                    -- On re-run: skips fund_codes already present in DB

fund_price          fund_code, date, open/high/low/close NUMERIC(12,4),
                    volume BIGINT, amount NUMERIC(20,2),
                    turnover_rate, premium_discount_pct NUMERIC(8,4)
                    PK (fund_code, date)

fund_holdings       fund_code, quarter, holding_type, security_code, security_name,
                    pct_of_nav, shares BIGINT, market_value NUMERIC(20,2)
                    PK (fund_code, quarter, holding_type, security_code)

fund_rank           fund_code TEXT, date DATE,
                    rank INT, name TEXT,
                    unit_nav, accum_nav NUMERIC(12,4),
                    daily_return_pct NUMERIC(8,4),
                    return_1w, return_1m, return_3m, return_6m,
                    return_1y, return_2y, return_3y,
                    return_ytd, return_since_inception, return_custom NUMERIC,
                    fee TEXT, updated_at
                    PK (fund_code, date)
                    -- Source: fund_open_fund_rank_em(symbol="全部"), ~19k funds

fund_rating         fund_code TEXT PK,
                    name, managers, company TEXT,
                    five_star_count INT,
                    rating_shzq, rating_zszq, rating_jajx, rating_morningstar NUMERIC(4,1),
                    fee NUMERIC(8,6), type TEXT, updated_at
                    -- Source: fund_rating_all(), ~15k funds
```

---

## Backend: Request → Response Flow

### Agent Modes

| Mode | Function | LLM | Tools | Max Turns |
|---|---|---|---|---|
| `normal` | `run_agent` | MiniMax | All 33+ | 30 |
| `debate` | `run_debate` → `run_hypothesis_debate` | MiniMax + Qwen | Subset | 6 phases |
| `fast` | `run_agent_fast` | Grok | None (built-in web search) | 1 |

### Normal Agent Mode (`agent.py::run_agent`)

```
POST /api/chat/send  {message, conversation_id, mode: "normal"}
  └─ api_chat.py::send_message()
       ├─ Checks _active_runs[user_id] — if running, reattaches SSE stream
       ├─ Creates AgentRun (buffers all SSE events for reconnect)
       ├─ asyncio.create_task(run_in_background())
       └─ Returns StreamingResponse (SSE)

run_in_background() → agent.py::run_agent()
  └─ _run_agent_inner()
       ├─ acquire per-user lock (one run at a time per user)
       ├─ load_recent_messages() from DB (last 20)
       ├─ save user message to DB
       ├─ _maybe_summarize() if >60 messages
       ├─ prepend system prompt (dynamic date + citation rules)
       │
       ├─ PLANNING TURN (tool-free LLM call):
       │   └─ get_planning_prompt() → MiniMax, no tools
       │      Emits <think> blocks as "agent_plan" thinking events
       │      If chitchat detected → returns direct answer, no tools
       │
       └─ AGENTIC LOOP (max 30 turns):
           For each turn:
           ├─ LLM call with messages + TOOL_SCHEMAS (streaming)
           ├─ Extract + emit <think> blocks via thinking_callback
           ├─ Save assistant message to DB (with tool_calls JSONB)
           ├─ If no tool_calls → return final answer
           ├─ asyncio.gather(*[execute_tool(name, args) for each call])  ← PARALLEL
           ├─ Truncate each result to 40k chars
           ├─ Save tool results to DB
           └─ Repeat until no tool_calls or max turns hit

SSE events:
  "status"   → tool execution progress ("Running: fetch_cn_stock_data...")
  "thinking" → {source, label, content}
  "token"    → streaming response text
  "done"     → {text, files, references}
  "error"    → {error}
```

### Debate Mode (`tools/trade_analyzer.py::run_hypothesis_debate`)

```
POST /api/chat/send  {message, mode: "debate"}

Phase 0 — Hypothesis Formation (MiniMax, no tools):
  └─ Parses question into structured JSON:
     • hypothesis (testable H₀)
     • question_type: single_stock | comparison | sector | general
     • entities: [{type, code, name}]
     • data_plan: [{tool, args}]  ← up to 20 tool calls, programmatic
     • pro_framing, con_framing, verdict_options (exactly 3)
     Post-processing: _latest_quarterly_type() overrides report_type by calendar month

Phase 1 — Data Collection (parallel):
  ├─ _collect_data_from_plan() — executes data_plan tools in parallel (NO LLM)
  └─ _fetch_community_sentiment() — 股吧 forum scraping (if stock question)
  Data pack capped at 30k chars

Phase 2 — Opening Arguments (4 parallel LLM calls):
  ├─ MiniMax Bull #1 + Qwen Bull #2  (_PRO_OPENING prompt)
  └─ MiniMax Bear #1 + Qwen Bear #2  (_CON_OPENING prompt)
  Each analyst: up to MAX_DEBATER_TOOL_ROUNDS=3 tool rounds
  Excluded tools: generate_chart, generate_pdf, dispatch_subagents,
                  analyze_trade_opportunity, lookup_data_sources, save_data_source

Phase 3 — Rebuttals (4 parallel LLM calls):
  Each analyst reads opposing arguments + responds

Phase 4 — Judge Verdict (MiniMax):
  Arguments shuffled randomly (anonymised)
  Returns: 判定, 置信度 (1-10), 判定理由, 核心风险, 反方最强数据点, 时间维度

Phase 5 — Executive Summary (MiniMax):
  Synthesises all arguments → institutional 2-min read + metrics table

Phase 6 — Report Generation:
  Generates .md + .pdf files in output/{user_id}/
```

### Fast Mode (`agent.py::run_agent_fast`)

```
POST /api/chat/send  {message, mode: "fast"}
  └─ Single Grok call with built-in web_search tool
     Max 1500 tokens; no tool loop; saved to conversation history
```

---

## Tool Calling Architecture

### How It Works

**Definition** (`tools/__init__.py`):
- `TOOL_SCHEMAS` — list of JSON schema dicts passed to the LLM on every turn
- `TOOL_MAP` — `{name: async_function}` dispatch table
- `execute_tool(name, args)` — main entry; returns `{"error": ...}` for unknown tools

**Flow** (normal agent loop):
1. LLM receives messages + `TOOL_SCHEMAS` and responds with `tool_calls: [{name, args}]`
2. Agent loop extracts all tool calls from the response
3. **All tool calls for that turn are executed in parallel** via `asyncio.gather()`
4. Each result is truncated to 40k chars
5. Results are appended to messages as `tool` role entries
6. LLM sees results and either calls more tools or returns final answer

**Programmatic Tool Calling** (debate mode):
- `_collect_data_from_plan()` executes `data_plan` tools directly in Python — no LLM deciding per-call
- LLM only produces the plan (Phase 0); execution is deterministic
- This is the key pattern for pre-fetching known data needs

**Caching** (`tools/cache.py`):
- In-memory LRU, default TTL 300s, cap 200 entries
- Key: `MD5(function_name + sorted_args_json)`
- Applied via `@cache(ttl)` decorator on tool functions
- Errors are NOT cached

**Context Vars** (used by tools deep in call stack):
```python
status_callback    # ContextVar → emits "status" SSE events
thinking_callback  # ContextVar → emits "thinking" SSE events
user_id_context    # ContextVar → used by output.py for file paths
```

### Tool Registry (33 tools)

| File | Tool Name | Data Source |
|---|---|---|
| `cn_market.py` | `fetch_cn_stock_data` | Tencent Finance (qt.gtimg.cn) + AKShare fallback |
| `cn_market.py` | `fetch_multiple_cn_stocks` | Tencent batch |
| `cn_market.py` | `fetch_cn_bond_data` | EastMoney |
| `stocks.py` | `fetch_stock_data` | Yahoo Finance |
| `stocks.py` | `fetch_multiple_stocks` | Yahoo Finance batch |
| `cn_eastmoney.py` | `fetch_stock_financials` | EastMoney datacenter (10+ yrs quarterly) |
| `cn_eastmoney.py` | `fetch_top_shareholders` | EastMoney (top 10 + change direction) |
| `cn_eastmoney.py` | `fetch_dividend_history` | EastMoney (分红送配) |
| `cn_eastmoney.py` | `fetch_dragon_tiger` | EastMoney 龙虎榜 |
| `sina_reports.py` | `fetch_company_report` | Sina Finance + Grok (2M context window) |
| `sina_reports.py` | `fetch_sina_profit_statement` | Sina Finance |
| `cn_capital_flow.py` | `fetch_stock_capital_flow` | EastMoney (主力/散户 by order size) |
| `cn_capital_flow.py` | `fetch_northbound_flow` | EastMoney articles (top 3 northbound stocks) |
| `cn_capital_flow.py` | `fetch_capital_flow_ranking` | EastMoney today's rankings |
| `cn_screener.py` | `screen_cn_stocks` | EastMoney (~5200 A-shares, filters + sort) |
| `market_scan.py` | `scan_market_hotspots` | EastMoney (indices, sectors, movers) |
| `cn_funds.py` | `fetch_cn_fund_data` | AKShare (price or NAV history) |
| `cn_funds.py` | `fetch_cn_fund_holdings` | EastMoney fund equity holdings |
| `funds.py` | `fetch_fund_holdings` | SEC 13F (US funds) |
| `ohlcv.py` | `fetch_ohlcv` | marketdata DB `ohlcv_5m` (MA5/20/60 computed) |
| `web.py` | `web_search` | Tavily → Grok → DuckDuckGo fallback chain |
| `web.py` | `scrape_webpage` | BeautifulSoup + Playwright (JS-heavy sites) |
| `sources.py` | `lookup_data_sources` | Local knowledge base JSON |
| `sources.py` | `save_data_source` | Appends to knowledge base |
| `ta_strategies.py` | `lookup_ta_strategy` | myaiagent DB `ta_strategies` (FTS) |
| `ta_strategies.py` | `save_ta_strategy` | Inserts into `ta_strategies` |
| `ta_strategies.py` | `update_ta_strategy` | Updates `ta_strategies` |
| `ta_executor.py` | `run_ta_script` | Subprocess sandbox (pandas-ta + Plotly) |
| `output.py` | `generate_chart` | matplotlib PNG |
| `output.py` | `generate_pdf` | FPDF markdown → PDF |
| `output.py` | `run_fund_chart_script` | AKShare fund data → Plotly chart |
| `subagent.py` | `dispatch_subagents` | Spawns parallel MiniMax sub-agents (8 turns max) |
| `trade_analyzer.py` | `analyze_trade_opportunity` | Deprecated wrapper → run_hypothesis_debate |

---

## API Endpoints

### Chat (`api_chat.py`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/chat/send` | Send message; returns SSE stream (status/token/thinking/done/error) |
| GET | `/api/chat/stream` | Reattach to running SSE stream |
| POST | `/api/chat/stop` | Cancel running agent |
| GET | `/api/chat/active` | Check if agent is running |
| GET | `/api/chat/conversations` | List user conversations |
| POST | `/api/chat/conversations` | Create conversation (`{mode}`) |
| GET | `/api/chat/conversations/{id}/messages` | Load history + files |
| DELETE | `/api/chat/conversations/{id}` | Delete conversation |
| PATCH | `/api/chat/conversations/{id}/mode` | Switch mode |
| POST | `/api/chat/conversations/{id}/share` | Toggle public sharing (generates share_token) |
| GET | `/api/chat/share/{token}` | Public conversation view |
| GET | `/api/chat/files` | List downloadable files |
| GET | `/api/chat/files/{filepath}` | Serve file (auth via header or query token) |
| POST | `/api/chat/stt` | Audio → text (Whisper + fuzzy stock name matching) |

### Auth (`api_auth.py`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Returns JWT token |
| POST | `/api/auth/create-account` | Admin-only account creation |
| GET | `/api/auth/me` | Current user info |

### Admin (`api_admin.py`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/tables` | List all tables |
| GET | `/api/admin/tables/{name}` | Schema + row count |
| GET | `/api/admin/tables/{name}/rows` | Paginated rows |
| POST | `/api/admin/query` | Read-only SQL (SELECT/WITH/EXPLAIN only) |

---

## Data Ingestion (`data/ingest_funds.py`)

Bulk ingestion script for the `marketdata` fund tables. Run once for initial load; incremental on re-runs.

**Flow**:
1. `load_catalog` — `fund_name_em()` → `funds` table; returns all fund codes
2. `load_managers` — `fund_manager_em()` → `fund_managers`
3. `load_manager_profiles` — per-manager detail → `fund_manager_profiles`
4. `load_fund_navs(all_codes)` — `fund_etf_fund_info_em` per fund → `fund_nav`
   - Skips fund_codes already present in DB (queries `DISTINCT fund_code` first)
   - Works for ALL fund types (open, ETF, LOF), not ETF-only
   - Parallel with `CONCURRENCY` (default 15) workers
5. `load_fund_rank` — `fund_open_fund_rank_em(symbol="全部")` → `fund_rank` (~19k rows)
6. `load_fund_ratings` — `fund_rating_all()` → `fund_rating` (~15k rows)

**Env vars**: `MARKETDATA_URL`, `CONCURRENCY`, `LOCAL_TEST`, `PRICE_START`

---

## Key Constraints & Gotchas

1. **Unit conversion**: 1 billion = 10亿 (NOT 1亿). All prompts contain `_UNIT_RULE`. Raw EastMoney data uses raw numbers (divide by 1e8 for 亿).

2. **Quarterly report selection**: `_latest_quarterly_type()` in `trade_analyzer.py` overrides LLM-chosen report type based on Chinese filing deadlines:
   - Jan–Apr → `q3` (prior year)
   - May–Aug → `q1`
   - Sep–Oct → `mid`
   - Nov–Dec → `q3`

3. **Per-user locks**: `get_user_lock(user_id)` in `accounts.py`. One agent run at a time per user. SSE reconnect reattaches to buffered `AgentRun` without starting a new one.

4. **Grok client created at import time**: `_grok_client` in `sina_reports.py` and `web.py` is `None` if `GROK_API_KEY` missing at startup. Must restart server after adding key.

5. **Fireworks vs MiniMax provider**: `MINIMAX_PROVIDER=fireworks` (default) uses OpenAI-compatible client with Fireworks endpoint. `MINIMAX_PROVIDER=minimax` uses official MiniMax SDK.

6. **Tool exclusions in debate**: `generate_chart`, `generate_pdf`, `dispatch_subagents`, `analyze_trade_opportunity`, `lookup_data_sources`, `save_data_source` blocked for debaters to prevent recursion and side effects.

7. **Context vars for callbacks**: `status_callback`, `thinking_callback`, `user_id_context` in `agent.py` are `contextvars.ContextVar`. Tools deep in the stack read these without explicit passing.

8. **System prompt vs planning prompt**: `get_system_prompt()` prepended to every turn (style, citations, tool→URL mapping). `get_planning_prompt()` used only for the tool-free planning turn at the start.

9. **Conversation summarisation**: Triggered at >60 messages; summarises oldest, keeps 20 recent verbatim. `summary_up_to` stores message ID watermark to avoid double-summarisation.

10. **STT stock name injection**: `api_chat.py::stt()` uses fuzzy matching against `stocknames` table to identify company names in audio transcriptions before passing to agent.

11. **TA executor sandbox**: User-generated TA scripts run in subprocess. Import whitelist: pandas, pandas_ta, plotly, numpy, json, os, pathlib, math, datetime. Blocked: requests, httpx, socket, subprocess.

12. **`fund_nav` sub_status/redeem_status**: Populated from `fund_etf_fund_info_em` (申购状态/赎回状态 columns). Rows inserted via `fund_open_fund_rank_em` bulk path will have NULL for these columns.

---

## Frontend (`frontend/src/`)

**Stack**: React 19, TypeScript, Vite, React Router, react-markdown

```
main.tsx            → App.tsx (AuthProvider + Router)
store.tsx           → AuthContext; useAuth() hook; localStorage JWT
api.ts              → All fetch calls + SSE stream parser (sendMessage, stopAgentRun, etc.)
i18n.tsx            → Simple en/zh string map; useT() hook

pages/
  ChatLayout.tsx    → Main shell: sidebar + ChatView; debate modal; conversation management
  LoginPage.tsx     → Login form; stores JWT to localStorage
  ShowcasePage.tsx  → Demo/immutable conversations
  GuidancePage.tsx  → Help docs

components/
  ChatView.tsx      → Core chat; sends via SSE; handleStop() → POST /api/chat/stop
  MessageBubble.tsx → Renders user/assistant messages (markdown)
  ThinkingBlock.tsx → Collapsible <think> block visualisation
  StatusIndicator.tsx → Tool execution progress display
  Sidebar.tsx       → Conversation list; new/debate buttons
  ReportsPanel.tsx  → Generated file browser
```

**SSE event handling** (`api.ts::_readSSEStream()`):
- `status` → `onStatus(text)`
- `thinking` → `onThinking({source, label, content})`
- `token` → streaming text tokens
- `done` → `onDone({text, files, references})`
- `error` → `onError(message)`

---

## Agent Constants

```python
# agent.py
MAX_TURNS = 30                    # Max agentic reasoning turns per query
SUMMARIZE_THRESHOLD = 60          # Trigger conversation compression
SUMMARIZE_KEEP_RECENT = 20        # Messages kept verbatim after summarisation
MAX_TOOL_RESULT_CHARS = 40000     # Tool result truncation limit

# trade_analyzer.py
MAX_DEBATER_TOOL_ROUNDS = 3       # Tool rounds per debater per phase
MAX_DEBATER_TOOL_RESULT_CHARS = 25000
PRIOR_REPORT_MAX_AGE_DAYS = 5     # Cache debate reports (report_cache table)
```
