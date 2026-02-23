# Codebase Structure & Architecture

> Read this before touching any file. It covers every module, the data flows, and key constraints so you don't need to read every script from scratch.

---

## What This System Is

A **Financial Research AI Agent** for Chinese A-share market analysis. Users chat with it; it calls 30+ specialized financial data tools, reasons with multiple LLMs, and optionally runs a multi-model "hypothesis debate" (bull vs bear analysts + judge) for investment questions.

**LLM Stack**:
- **MiniMax** — primary agent loop, planning, debate judge, executive summary
- **Qwen** — debate bear-side arguments
- **Grok** — live web search (`web_search`) + full-report reading (`fetch_company_report`)

---

## Top-Level File Map

```
myaiagent/
├── web.py              # FastAPI app entry point; mounts routers; init_db on startup
├── config.py           # All env vars + get_system_prompt() + get_planning_prompt()
├── agent.py            # Main agent loop (run_agent) + debate entry point (run_debate)
├── api_chat.py         # /api/chat/ routes; SSE streaming; AgentRun buffering; /stop endpoint
├── api_auth.py         # /api/auth/ routes; login, register, JWT
├── api_admin.py        # /api/admin/ routes; DB inspection (admin-only)
├── auth.py             # bcrypt password + JWT helpers
├── db.py               # asyncpg pool + schema SQL + init_db()
├── accounts.py         # Conversation/message DB helpers + per-user locks + summarization
├── start.py            # Server startup script
├── tools/              # All data-fetching and output tools (see below)
├── frontend/           # React 19 + TypeScript SPA (Vite)
├── output/             # Generated PDFs and charts (per-user subdirs)
├── changes.md          # Change log (append after every task — required by CLAUDE.md)
└── CLAUDE.md           # Project instructions for coding agents
```

---

## Environment Variables (`config.py`)

| Variable | Default | Purpose |
|---|---|---|
| `MINIMAX_API_KEY` | — | Primary LLM (required) |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.chat/v1` | |
| `MINIMAX_MODEL` | `MiniMax-M1-80k` | |
| `QWEN_API_KEY` | — | Debate bear arguments |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | |
| `QWEN_MODEL` | `qwen-plus` | |
| `GROK_API_KEY` | — | Web search + report reading. **If missing, Grok silently skips and falls back to keyword extraction. Check logs for "GROK_API_KEY missing"** |
| `GROK_BASE_URL` | `https://api.x.ai/v1` | |
| `GROK_MODEL_noreasoning` | `grok-4-1-fast-non-reasoning` | Note: env var is lowercase `noreasoning` |
| `DATABASE_URL` | `postgresql://localhost/myaiagent` | asyncpg connection string |
| `JWT_SECRET` | `dev-secret-...` | HS256 JWT signing |
| `WEB_PORT` | `8000` | |
| `ADMIN_USERNAME` | `davidc` | Only this user can create accounts |

---

## Database Schema (`db.py`)

```
users                   id, display_name, created_at, last_active_at
platform_accounts       id, user_id, platform, platform_uid, linked_at
web_accounts            id, user_id, username, password_hash, created_at
conversations           id, user_id, title, created_at, updated_at, summary, summary_up_to
messages                id, conversation_id, role, content, tool_calls JSONB, tool_call_id, created_at
files                   id, user_id, conversation_id, filepath, filename, file_type, created_at
report_cache            id, stock_code, report_type, report_year, distilled_markdown, created_at
ta_strategies           id, name, aliases[], description, indicators[], parameters JSONB, source_url, created_at, updated_at
```

**Key `accounts.py` functions**:
- `get_active_conversation(user_id)` — get or create latest conversation
- `load_recent_messages(conv_id)` — last 20 messages; trims orphaned tool results
- `_maybe_summarize(conv_id, messages)` — compresses conversation if >60 messages; keeps recent 20 + LLM summary; stores `summary_up_to` message ID
- `get_user_lock(user_id)` — per-user asyncio lock; prevents concurrent runs
- `save_message()`, `save_file_record()`

---

## Backend: Request → Response Flow

### Normal Agent Mode

```
POST /api/chat/send  {message, conversation_id, mode: null}
  └─ api_chat.py::send_message()
       ├─ Checks _active_runs[user_id] — if running, reattaches SSE stream
       ├─ Creates AgentRun (buffers all SSE events so reconnect works)
       ├─ asyncio.create_task(run_in_background())
       └─ Returns StreamingResponse (SSE)

run_in_background()
  └─ agent.py::run_agent(message, user_id, on_status, on_thinking, conversation_id)
       └─ _run_agent_inner()
            ├─ acquire per-user lock
            ├─ load_recent_messages() from DB
            ├─ save user message to DB
            ├─ _maybe_summarize() if >60 messages
            ├─ prepend system prompt (dynamic date + citation rules)
            │
            ├─ PLANNING TURN (tool-free LLM call):
            │   └─ get_planning_prompt() → MiniMax call, no tools
            │      Emits <think> blocks as "agent_plan" thinking events
            │      Appended to messages as context
            │
            ├─ AGENTIC LOOP (max 30 turns):
            │   For each turn:
            │   ├─ LLM call with messages + TOOL_SCHEMAS
            │   ├─ Extract + emit <think> blocks via thinking_callback
            │   ├─ Save assistant message to DB
            │   ├─ If no tool_calls → return final text
            │   ├─ asyncio.gather(*[execute_tool(name,args) for each tool])
            │   ├─ Truncate each result to 40k chars
            │   ├─ Save tool results to DB
            │   └─ Collect any generated file paths
            │
            └─ On max turns → ask LLM for final summary

SSE events emitted:
  "status"   → tool execution progress ("Running: fetch_cn_stock_data...")
  "thinking" → {source, label, content} for ThinkingBlock in frontend
  "done"     → {text, files, references}
  "error"    → {error}
```

### Debate Mode

```
POST /api/chat/send  {message, mode: "debate"}
  └─ agent.py::run_debate() → _run_debate_inner()
       ├─ load_recent_messages() — gather last 20 msgs as context (max 8k chars)
       └─ tools/trade_analyzer.py::run_hypothesis_debate(question, context)
            │
            ├─ PHASE 0 — Hypothesis Formation (MiniMax):
            │   └─ _form_hypothesis() → JSON with:
            │       • hypothesis (testable H₀ statement)
            │       • question_type: single_stock | comparison | sector | general
            │       • entities: [{type, code, name}]
            │       • data_plan: [{tool, args}] — up to 20 tool calls
            │       • pro_framing, con_framing (analyst instructions)
            │       • verdict_options (exactly 3)
            │       • report_title, response_language
            │   Post-processing (code, not LLM):
            │   └─ _latest_quarterly_type() overrides quarterly report_type
            │      based on current calendar month (q3/mid/q1 by filing deadline)
            │
            ├─ PHASE 1 — Data Collection (parallel):
            │   ├─ _collect_data_from_plan() — executes all data_plan tools in parallel
            │   └─ _fetch_community_sentiment() — 股吧 forum posts (if stock question)
            │
            ├─ PHASE 2 — Opening Arguments (4 parallel LLM calls):
            │   ├─ MiniMax Bull #1 + MiniMax Bull #2 (_PRO_OPENING prompt)
            │   └─ Qwen Bear #1 + Qwen Bear #2 (_CON_OPENING prompt)
            │   Each analyst can call tools (up to MAX_DEBATER_TOOL_ROUNDS=3)
            │   Excluded tools: generate_chart, generate_pdf, dispatch_subagents,
            │                   analyze_trade_opportunity, lookup_data_sources, save_data_source
            │
            ├─ PHASE 3 — Rebuttals (4 parallel LLM calls):
            │   └─ Each analyst reads opposing arguments + responds (_REBUTTAL prompt)
            │
            ├─ PHASE 4 — Judge Verdict (MiniMax):
            │   └─ _JUDGE prompt: evaluates analytical breadth + directional accuracy
            │      Data errors flagged but NOT used to reverse verdict
            │      Returns: 判定, 置信度, 判定理由, 核心风险, 反方最强数据点, 时间维度
            │
            └─ PHASE 5 — Executive Summary + Optional Report (MiniMax)
```

---

## Tools (`tools/`)

### Registry (`tools/__init__.py`)
- `TOOL_SCHEMAS` — list passed to LLM (defines what the agent can call)
- `TOOL_MAP` — `{name: async_function}` dispatch table
- `execute_tool(name, args)` — main entry; returns `{"error": ...}` for unknown tools

### Tool Files

| File | Tools | Data Source |
|---|---|---|
| `cn_market.py` | `fetch_cn_stock_data`, `fetch_multiple_cn_stocks`, `fetch_cn_bond_data` | Tencent Finance (qt.gtimg.cn), EastMoney |
| `cn_capital_flow.py` | `fetch_stock_capital_flow`, `fetch_northbound_flow`, `fetch_capital_flow_ranking` | EastMoney APIs |
| `cn_eastmoney.py` | `fetch_stock_financials`, `fetch_top_shareholders`, `fetch_dividend_history`, `fetch_dragon_tiger` | EastMoney datacenter |
| `cn_screener.py` | `screen_cn_stocks` | EastMoney (filters/ranks all ~5200 A-shares) |
| `market_scan.py` | `scan_market_hotspots` | EastMoney (indices, sectors, movers) |
| `stocks.py` | `fetch_stock_data`, `fetch_multiple_stocks` | Yahoo Finance (US/HK stocks) |
| `funds.py` | `fetch_fund_holdings` | SEC 13F |
| `cn_funds.py` | `fetch_cn_fund_holdings` | EastMoney fund data |
| `web.py` | `web_search`, `scrape_webpage` | Grok live search (primary) / DuckDuckGo (fallback) |
| `sina_reports.py` | `fetch_company_report`, `fetch_sina_profit_statement` | Sina Finance + Grok (2M context) |
| `eastmoney_forum.py` | `fetch_eastmoney_forum` | Guba.eastmoney.com (stock forum sentiment) |
| `subagent.py` | `dispatch_subagents` | Spawns parallel MiniMax sub-agents |
| `output.py` | `generate_chart`, `generate_pdf`, `parse_references` | Local (matplotlib, weasyprint) |
| `sources.py` | `lookup_data_sources`, `save_data_source` | Local knowledge base (known financial URLs) |
| `cache.py` | `@cache(ttl)` decorator | In-memory LRU (5 min TTL, 200 entry cap) |
| `trade_analyzer.py` | `analyze_trade_opportunity`, `run_hypothesis_debate` | Orchestrates all of the above |
| `ohlcv.py` | `fetch_ohlcv` | marketdata Postgres `ohlcv` table |
| `ta_strategies.py` | `lookup_ta_strategy`, `save_ta_strategy`, `update_ta_strategy` | myaiagent Postgres `ta_strategies` table |
| `ta_executor.py` | `run_ta_script` | subprocess (pandas-ta + plotly); MiniMax for retry rewrites |
| `utils.py` | Shared HTTP helpers, encoding detection | — |

### Critical Tool Notes

**`fetch_company_report` (`sina_reports.py`)**:
- Fetches HTML from Sina Finance bulletin pages, extracts text + tables
- Sends to Grok (2M token context) for structured Markdown summary
- **If `GROK_API_KEY` missing**: logs WARNING and falls back to `_extract_key_sections()` (keyword-based, loses narrative content)
- Long report pipeline: deduplicate lines → if >80k chars → keyword-section extraction → hard cap 80k chars
- Quarterly type is determined by `_latest_quarterly_type()` in `trade_analyzer.py` post-processing (not the LLM)

**`web_search` (`web.py`)**:
- Uses Grok Responses API with `{"type": "web_search"}` tool if `GROK_API_KEY` set
- Falls back to DuckDuckGo otherwise

**`dispatch_subagents` (`subagent.py`)**:
- Each sub-agent gets full system prompt + tool access
- Useful for multi-stock comparisons, parallel research branches

**`generate_pdf` / `generate_chart` (`output.py`)**:
- Output goes to `output/{user_id}/` directory (user_id from `user_id_context` contextvar)
- Naming: `{title}_{YYYYMMDD}_{4char}.{ext}`
- Files recorded in DB `files` table, served via `/api/chat/files/{filepath}`

---

## Agent Constants

```python
# agent.py
MAX_TURNS = 30                    # Max agentic reasoning turns per query
SUMMARIZE_THRESHOLD = 60          # Trigger conversation compression
SUMMARIZE_KEEP_RECENT = 20        # Messages kept verbatim after summarization
MAX_TOOL_RESULT_CHARS = 40000     # Tool result truncation limit

# trade_analyzer.py
MAX_DEBATER_TOOL_ROUNDS = 3       # Tool calls allowed per debater
MAX_DEBATER_TOOL_RESULT_CHARS = 25000
PRIOR_REPORT_MAX_AGE_DAYS = 5     # Cache debate reports
```

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
  ChatView.tsx      → Core chat; sends via SSE; handleStop() calls POST /api/chat/stop
  MessageBubble.tsx → Renders user/assistant messages (markdown)
  ThinkingBlock.tsx → Collapsible <think> block visualization
  StatusIndicator.tsx → Tool execution progress display
  Sidebar.tsx       → Conversation list; new/debate buttons
  ReportsPanel.tsx  → Generated file browser
```

**SSE event handling in `api.ts::_readSSEStream()`**:
- `status` → `onStatus(text)` — progress
- `thinking` → `onThinking({source, label, content})` — thinking blocks
- `done` → `onDone({text, files, references})` — final response
- `error` → `onError(message)`

**Stop flow**: `ChatView::handleStop()` → `api.stopAgentRun(token)` (POST `/api/chat/stop`) → `abortRef.current.abort()`. The backend cancels the asyncio task immediately.

---

## Key Constraints & Gotchas

1. **Unit conversion**: 1 billion = 10亿 (NOT 1亿). All debate prompts contain `_UNIT_RULE` reminding models of this. Raw EastMoney data uses raw numbers.

2. **Quarterly report selection**: `_latest_quarterly_type()` in `trade_analyzer.py` overrides whatever the LLM puts in the data_plan based on Chinese filing deadlines:
   - Jan–Apr → `q3` (prior year Q3 is most recent)
   - May–Aug → `q1`
   - Sep–Oct → `mid`
   - Nov–Dec → `q3`

3. **Per-user locks**: `get_user_lock(user_id)` in `accounts.py`. Only one agent run at a time per user. The SSE reconnect (GET `/api/chat/stream`) reattaches to the buffered `AgentRun` without starting a new one.

4. **Grok client created at import time**: `_grok_client` in `sina_reports.py` and `web.py` is `None` if `GROK_API_KEY` is missing at startup. Restarting the server is required after adding the key.

5. **Common stock code confusions** (LLM-level): 中国石油 = PetroChina = 601857; 中国石化 = Sinopec = 600028. The hypothesis prompt contains a disambiguation list for well-known companies.

6. **Tool exclusions in debate**: `generate_chart`, `generate_pdf`, `dispatch_subagents`, `analyze_trade_opportunity`, `lookup_data_sources`, `save_data_source` are blocked for debaters to prevent recursion and side-effects.

7. **Context vars for callbacks**: `status_callback`, `thinking_callback`, `user_id_context` in `agent.py` are `contextvars.ContextVar`s. Tools deep in the call stack (e.g., `trade_analyzer.py`) read these to emit status/thinking events without needing them passed explicitly.

8. **System prompt vs planning prompt**: `get_system_prompt()` is prepended to every agent turn (response style, citations, tool→URL mapping). `get_planning_prompt()` is used only for the tool-free planning turn at the start.

9. **CLAUDE.md rule**: After every task, append an entry to `changes.md`. Format is specified in CLAUDE.md.
