# Changes

## 2026-02-23 — Conversation sharing

**What:** Added per-conversation public sharing via unique URL. Owners toggle sharing on/off; visitors get a read-only view with no login required.

**Files:**
- `db.py` — added `share_token VARCHAR(32) UNIQUE` and `is_public BOOLEAN DEFAULT FALSE` columns to `conversations`
- `api_chat.py` — updated `list_conversations` to return share fields; added `POST /conversations/{conv_id}/share` toggle endpoint; added `GET /share/{share_token}` public endpoint
- `frontend/src/api.ts` — added `toggleConversationShare` and `fetchSharedConversation` functions
- `frontend/src/pages/ChatLayout.tsx` — added `share_token`/`is_public` to `Conversation` interface; added `handleShare` callback; passes `onShare` to Sidebar
- `frontend/src/components/Sidebar.tsx` — added share button (🔗) per conversation row with inline panel (toggle + URL + copy button)
- `frontend/src/App.tsx` — added `/share/:shareToken` route
- `frontend/src/pages/SharedConversationPage.tsx` — created; public read-only conversation view using existing `MessageBubble` component

## 2026-02-23 — Improve chart generation completeness via better prompting

**What:** The `_polish_script` rewriter was silently dropping visual elements (e.g. 笔 stroke lines, 中枢 zones) when simplifying scripts. Added visual-completeness rules and a two-step enumerate-then-rewrite instruction so all requested overlays are always preserved and implemented.

**Files:**
- `tools/ta_executor.py` — modified `_SCRIPT_RULES`, `_polish_script` prompt, `_rewrite_script` prompt

**Details:**
- `_SCRIPT_RULES`: added VISUAL COMPLETENESS RULES section with Plotly trace-type reference for common TA elements (fractal markers, stroke lines with None separators, pivot zone shapes, signals) and explicit "never omit an overlay" rule
- `_polish_script`: added Step 1 (enumerate all visual elements) before Step 2 (rewrite), with instruction to fix broken elements rather than delete them
- `_rewrite_script`: added same preservation instruction — fix the error, do not remove traces/shapes

## 2026-02-23 — Fix messages going to wrong conversation on mobile

**What:** When `POST /api/chat/send` received no `conversation_id`, the backend fell through to `get_active_conversation` which reused the most recent existing conversation. On mobile, tab discards after backgrounding cause the frontend to reload with `activeId = null`, triggering this path. Now a new conversation is created explicitly instead.

**Files:**
- `api_chat.py` — modified `send_message()`: create new conversation when `conversation_id` is null; simplify auto-title to query by `run.conv_id` directly

**Details:**
- Added `else: target_conv_id = await new_conversation(user_id)` branch so `run.conv_id` is always set at `AgentRun` creation
- Auto-title code now queries `WHERE id = $1` using `run.conv_id` instead of `ORDER BY updated_at DESC LIMIT 1` — removes race condition and the now-dead `run.conv_id is None` branch

## 2026-02-23 — Add A-share backtesting rules

**What:** Added A-share specific backtesting rules document, injected it into the planning prompt, and captured `run_ta_script` stdout for returning backtest statistics.

**Files:**
- `data/backtest_rules.md` — created: board detection by code prefix (±10%/±20%/±30%), T+1 rule, long-only, next-bar-open execution, 涨停/跌停 chart markers, required stats output format
- `config.py` — added `_load_backtest_rules()` helper; converted `get_planning_prompt()` to f-string; appended `## 回测规则（A股）` section from file
- `tools/ta_executor.py` — `run_ta_script` now captures `result.stdout` and returns it as `"text"` field alongside the chart file

## 2026-02-23 — Add run_ta_script tool with subprocess sandbox and 3-attempt retry

**What:** Created `tools/ta_executor.py` providing a sandboxed Python execution environment for LLM-generated technical analysis scripts, plus full unit test coverage.

**Files:**
- `tools/ta_executor.py` — created; `run_ta_script` async function + `RUN_TA_SCRIPT_SCHEMA`, `_make_wrapper_script`, `_rewrite_script` helpers
- `tests/test_ta_executor.py` — created; 5 pytest-asyncio tests covering sandbox allowlist, sandbox blocklist, success-on-first-attempt, 3-attempt exhaustion, and success-on-second-attempt
- `requirements.txt` — added `pandas-ta` and `plotly`

**Details:**
- Sandbox uses `sys._getframe(1)` to determine whether an import originates from user code (`<string>`) vs library internals (site-packages path); only user-level imports are checked against the allowlist/blocklist
- `subprocess.run` is wrapped with `asyncio.to_thread` to avoid blocking the uvicorn event loop
- On script failure, `_rewrite_script` calls MiniMax to produce a fixed version; retries up to `_MAX_RETRIES=3` times
- Output path follows the same `output/{user_id}/ta_{code}_{YYYYMMDD}_{4char}.html` convention as `output.py`
- `fetch_ohlcv` is awaited directly inside `run_ta_script` (no `run_until_complete`)

## 2026-02-23 — Add ta_strategies lookup/save/update tools with tests

**What:** Created the TA strategy knowledge base tools (`lookup_ta_strategy`, `save_ta_strategy`, `update_ta_strategy`) backed by the `ta_strategies` Postgres table, plus full unit test coverage with mocked DB pool.

**Files:**
- `tools/ta_strategies.py` — created; implements three async tool functions and their JSON schemas
- `tests/test_ta_strategies.py` — created; 5 pytest-asyncio tests covering found/not-found lookup, save, and update (found/not-found)

**Details:**
- Lookup uses FTS on `name` via `to_tsvector('simple', ...)` plus `= ANY(aliases)` fallback and exact case-insensitive name match (GIN index only covers `name` — alias search done at query time)
- Save uses `INSERT ... ON CONFLICT (name) DO UPDATE` for upsert behaviour
- Update builds dynamic SET clause from an `allowed` whitelist; detects `UPDATE 0` to return `not_found`
- `parameters` JSONB field serialised via `json.dumps` before passing to asyncpg
- Tests mock `get_pool` at the module level; all 5 pass

## 2026-02-22 — Codebase cleanup + server deployment doc

**What:** Removed obsolete files and dead code; rewrote `switchingvps.md` into a comprehensive server deployment guide.

**Files deleted:**
- `.running` — temp file containing stale secrets
- `1` — empty stray file
- `todo.md` — empty
- `test_groq.py` — test artifact, not part of app
- `generate_guide_pdf.py` — one-off script with hardcoded paths
- `archive/bot.py` — old Telegram bot, replaced by web UI

**Code removed:**
- `tools/output.py` — `generate_references_image()` (only used by archived bot) + unused `textwrap` import
- `accounts.py` — `get_or_create_user()` (only used by archived bot)
- `config.py` — `GROK_MODEL_REASONING` (defined but never used anywhere)

**Docs:**
- `switchingvps.md` — rewritten into full deployment guide covering fresh setup, systemd, nginx/SSL, cron jobs, firewall, and server migration

---

## 2026-02-22 — Add fetch_ohlcv tool for 5-min OHLCV / technical analysis

**What:** Created a new tool that queries the local `ohlcv_5m` table in the marketdata DB, returning candlestick bars with pre-computed MA5/MA20/MA60 and chart-ready series for use with `generate_chart`.

**Files:**
- `tools/ohlcv.py` — created; `fetch_ohlcv` + `FETCH_OHLCV_SCHEMA`
- `tools/__init__.py` — registered tool
- `config.py` — added `fetch_ohlcv` to planning prompt tool table and TA guidance

---

## 2026-02-22 — Restrict debate to button-only; clean up field-name translation

**What:** Removed `analyze_trade_opportunity` from the agent's tool list so it can only be triggered by the hypothesis debate button. Also moved the financials column glossary out of config.py and into `data/financials_columns.md`.

**Files:**
- `tools/__init__.py` — removed `ANALYZE_TRADE_SCHEMA` from `TOOL_SCHEMAS` (stays in `TOOL_MAP` for debate path)
- `config.py` — replaced hardcoded field-name table with `_load_file("financials_columns.md")` helper

---

## 2026-02-22 — Fix token-by-token streaming in frontend

**What:** The backend was already emitting `token` SSE events per token, but the frontend SSE reader had no handler for them so they were silently dropped. Wired up proper streaming so text appears incrementally.

**Files:**
- `frontend/src/api.ts` — add `onToken?` to `SSECallbacks`; handle `token` SSE events in `_readSSEStream`
- `frontend/src/components/ChatView.tsx` — add `streamingContent` state; wire `onToken` in both `handleSend` and `reconnect`; render live streaming bubble; clear on `onDone`/`onError`/`handleStop`

---

## 2026-02-22 — Show response elapsed time in chat

**What:** Timed each agent/debate run and displayed elapsed seconds as small muted text at the bottom of every assistant message.

**Files:**
- `api_chat.py` — record `t0` before run, compute elapsed, log it, include `elapsed_seconds` in `done` SSE payload
- `frontend/src/api.ts` — add `elapsed_seconds?: number` to `onDone` callback type
- `frontend/src/components/ChatView.tsx` — thread `elapsedSeconds` through `Message` interface and `MessageBubble` props
- `frontend/src/components/MessageBubble.tsx` — render `<div class="message-elapsed">` when present
- `frontend/src/styles/index.css` — add `.message-elapsed` style (small, muted, right-aligned)

---

## 2026-02-22 — Add Fireworks AI as switchable MiniMax provider

**What:** Added support for running MiniMax via Fireworks AI (drop-in OpenAI-compatible endpoint) with a single env-var toggle to switch between providers.

**Files:**
- `config.py` — added `FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`, `FIREWORKS_MINIMAX_MODEL`, `MINIMAX_PROVIDER` env vars and `get_minimax_config()` helper
- `agent.py` — uses `get_minimax_config()` instead of raw constants
- `tools/subagent.py` — uses `get_minimax_config()` instead of raw constants
- `tools/trade_analyzer.py` — uses `get_minimax_config()` instead of raw constants

**Details:**
- Default provider is `fireworks`; set `MINIMAX_PROVIDER=minimax` to revert to the official API
- Default Fireworks model: `accounts/fireworks/models/minimax-m2p1` (override via `FIREWORKS_MINIMAX_MODEL`)
- Requires `FIREWORKS_API_KEY` in `.env` when using Fireworks provider

## 2026-02-22 — Add fetch_baostock_financials tool; fix marketdata DB connection

**What:** Created a new agent-callable tool to query the local BaoStock `financials` table in the marketdata DB. Fixed a bug where `_get_financial_context` was querying the wrong DB (main myaiagent DB instead of marketdata DB), causing silent failures.

**Files:**
- `config.py` — added `MARKETDATA_URL` constant; added `fetch_baostock_financials` row to planning prompt tool table; added routing notes for DuPont/cash quality analysis; added citation URL
- `db.py` — added `MARKETDATA_URL` import, `marketdata_pool` global, `get_marketdata_pool()` function
- `tools/financials_db.py` — created: `fetch_baostock_financials` tool with full column docs, default column set, validation; queries `financials` table via `get_marketdata_pool()`
- `tools/__init__.py` — registered `fetch_baostock_financials` in TOOL_SCHEMAS and TOOL_MAP
- `tools/sina_reports.py` — fixed `_get_financial_context` to use `get_marketdata_pool()` instead of `get_pool()` (main DB)

**Details:**
- `financials` table lives in the `marketdata` DB (BaoStock source), not the main `myaiagent` DB; the old code was querying the wrong pool and silently returning empty data
- The new tool exposes 30+ columns across 6 categories: profitability, operational efficiency, growth, solvency, cash flow, DuPont decomposition
- Column descriptions from `data/financials_columns.md` are embedded in both the tool schema description and the response `columns_doc` field so the agent always knows what each metric means
- `get_marketdata_pool()` lazily creates a pool on first use (no startup cost if unused)

## 2026-02-22 — Remove report file cache (always fetch live)

**What:** Removed the `output/reports/` disk cache and `report_cache` DB lookups from `fetch_company_report`. Reports are now always fetched fresh from Sina Finance on every call.

**Files:**
- `tools/sina_reports.py` — removed `_REPORTS_BASE`, `_get_cache_path`, `_check_report_cache`, `_save_report_cache`; removed `from pathlib import Path`; stripped cache-check fast-path and file-write from `fetch_company_report`; removed `cache_path` from return dict

## 2026-02-22 — Real-time think-block streaming for all agent LLM calls

**What:** Extended streaming to cover `<think>` content and all non-main-loop LLM calls so users see something immediately even while the model is thinking.

**Files:**
- `agent.py` — updated `_stream_llm_response` with a state-machine that streams `<think>` tokens in real-time via a new `on_thinking_chunk` callback; planning turn now uses `_stream_llm_response`; max-turns summary now uses `_stream_llm_response`

**Details:**
- `_stream_llm_response` now has three states: `pre` (buffering to detect `<think>`), `think` (streaming to `on_thinking_chunk` as tokens arrive), `post` (streaming to `on_token`)
- Planning turn: think content streams to source `"agent_plan_think"` / label `"Planning · Thinking"` in real-time; the resolved plan still emits as `"Research Plan"` thinking block after
- Main agent loop: each turn pre-computes a think label and source; `<think>` content streams in real-time instead of being buffered until `</think>`; removed the now-redundant post-stream `_emit_thinking` call
- Max-turns summary: was a non-streaming call (final answer blocked until complete); now streams tokens via `_emit_token` and think content via `on_thinking_chunk`

## 2026-02-22 — Targeted DB-anchored report analysis (replaces exhaustive summarization)

**What:** Replaced the full-report exhaustive distillation approach with a three-step targeted Q&A flow: pull historical DB financials → generate research questions from trends → answer them from a focused 40k-char chunk of the report.

**Files:**
- `tools/sina_reports.py` — removed `_make_chunks`, `_CHUNK_SIZE`, `_CHUNK_OVERLAP`, `_MAX_PARALLEL`; added `_get_financial_context`, `_generate_research_questions`, `_groq_targeted_analysis`; updated `fetch_company_report` slow path to call the three-step flow; updated `FETCH_COMPANY_REPORT_SCHEMA` description

**Details:**
- `_get_financial_context(code)` queries the `financials` DB table for last 8 quarters (ROE, margins, YoY growth, solvency, cash flow, EPS)
- `_generate_research_questions(...)` sends financial trend data to Groq to generate 4–6 targeted research questions (e.g. why ROE dropped, what drove the margin compression)
- `_groq_targeted_analysis(...)` prepares a 40k-char focused chunk via `_prepare_report_text`, then answers the questions in a single Groq call with an investment conclusion (看多/看空/中性)
- MD output now includes a "历史财务背景" section with the DB data table, followed by "研究问题与分析" with Groq's answers
- `summarized_by` field is now `"groq_targeted"` on success

## 2026-02-22 — Switch report summarizer from Minimax to Groq (PDF-based chunked extraction)

**What:** Replaced Minimax LLM summarization in `sina_reports.py` with Groq `openai/gpt-oss-20b` using full-PDF extraction and parallel chunked processing for higher accuracy and zero hallucination.

**Files:**
- `tools/sina_reports.py` — removed Minimax client; added `_download_pdf`, `_extract_pdf_text`, `_make_chunks`, `_groq_summarize_report`; updated `fetch_company_report` to prefer PDF text over HTML bulletin
- `config.py` — added `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_REPORT_MODEL`
- `requirements.txt` — added `pymupdf`

**Details:**
- PDF downloaded in memory (bytes), text extracted via pymupdf, bytes discarded immediately — no temp file on disk
- Report text chunked at 10k chars with 200-char overlap, processed in parallel (semaphore=4)
- Each chunk uses exhaustive extraction prompt (穷举提取, no output limit, low temp=0.1)
- Synthesis pass merges all chunks into final structured Markdown
- Falls back to HTML body text if no PDF link found, and to keyword extraction if Groq fails

## 2026-02-21 — Market data pipeline (hourly OHLCV for A-shares, plain PostgreSQL)

**What:** Dropped TimescaleDB in favour of plain PostgreSQL 17 (local). Fixed BaoStock API usage (`query_stock_basic()` takes no `fields` arg; `time` field is `YYYYMMDDHHmmssSSS` not `HH:MM:SS`). Pipeline verified end-to-end with 5 stocks.

**Files:**
- `data/setup_db.py` — plain PostgreSQL, BRIN index on ts, btree on (code, ts)
- `data/ingest_ohlcv.py` — fixed stock list query and timestamp parsing
- `data/update_ohlcv.py` — same fixes; added MARKETDATA_URL env var support
- `requirements.txt` — added baostock, psycopg2-binary

**Details:**
- Use `MARKETDATA_URL=postgresql://davidc@localhost:5432/marketdata` in .env
- BaoStock fields: `[code, code_name, ipoDate, outDate, type, status]` — type at index 4, status at index 5
- Time field slicing: `t[8:10]:t[10:12]:t[12:14]` → HH:MM:SS

---

## 2026-02-21 — Market data pipeline (hourly OHLCV for A-shares)

**What:** Added a standalone data pipeline to store 5 years of hourly OHLCV data for 5000+ A-share stocks in a separate PostgreSQL + TimescaleDB `marketdata` database, for use by future backtesting scripts.

**Files:**
- `data/setup_db.py` — created: one-time script to create the `marketdata` DB, enable TimescaleDB, create `ohlcv_1h` hypertable with indexes and 7-day compression policy
- `data/ingest_ohlcv.py` — created: bulk historical load (2020–today), resumable via `.ingest_checkpoint` file, batch inserts with ON CONFLICT DO NOTHING
- `data/update_ohlcv.py` — created: daily incremental update script (designed for cron at 16:30 CST), fetches from last ingested timestamp forward
- `requirements.txt` — modified: added `baostock` and `psycopg2-binary`

**Details:**
- Data source: BaoStock (`frequency="60"` for 60-min bars), no API key required
- Stock list fetched directly from BaoStock (`query_stock_basic`), no dependency on main DB
- ~25M estimated rows (5yr × 244 days × 4 bars × 5000 stocks), ~500MB–1GB compressed
- BaoStock code format: `sh.600036` → stored as `code="600036"`, `exchange="SH"`
- Timestamps stored as `TIMESTAMPTZ` with `+08:00` offset (CST)
- Cron entry in `update_ohlcv.py` comments: `30 8 * * 1-5` (08:30 UTC = 16:30 CST)

## 2026-02-21 — Chitchat routing at planning stage

**What:** Agent now classifies intent at the planning turn and short-circuits for non-financial queries, returning a direct friendly answer without entering the agentic tool loop.

**Files:**
- `config.py` — updated `get_planning_prompt()` to prepend INTENT classification instructions
- `agent.py` — updated `_run_agent_inner()` to parse `INTENT: chitchat` / `INTENT: finance` from the planning response and return early for chitchat

## 2026-02-21 — Speech-to-text (Whisper) + stocknames table

**What:** Added OpenAI Whisper speech-to-text integration (test server) and a `stocknames` table populated daily from SSE, SZSE, and BSE official exchange APIs.

**Files:**
- `tests/test_whisper_web.py` — created: standalone FastAPI test server for Whisper STT
- `tests/test_whisper.py` — created: CLI connectivity test for Whisper API
- `tests/test_exchange_apis.py` — created: inspection script for SSE/SZSE/BSE APIs
- `tools/populate_stocknames.py` — created: fetches ~5500 A-share stocks from all 3 exchanges, upserts into DB
- `db.py` — modified: added `stocknames` table to SCHEMA_SQL
- `web.py` — modified: added `_stocknames_scheduler()` background task (populates on startup if empty, refreshes daily at 19:00)

**Details:**
- SSE fetches 主板A股 + 科创板 via JSON API (requires Referer header)
- SZSE fetches via XLSX download
- BSE fetches from bseinfo.net paginated POST API
- All three fetches run in parallel via `asyncio.gather` + `asyncio.to_thread`
- Upsert is idempotent — safe to re-run or re-populate
- `stocknames` columns: stock_code, exchange (SH/SZ/BJ), stock_name, full_name, sector, industry, list_date

## 2026-02-20 — Fix MiniMax error 2013 (incomplete tool-call sequences)

**What:** Replaced the front-only trim in `load_recent_messages()` with a full-array scan that drops incomplete or orphaned tool-call sequences anywhere in message history.

**Files:**
- `accounts.py` — modified `load_recent_messages()`, added `_repair_tool_call_sequence()`

**Details:**
- Root cause: when user cancels an agent run, the `role:assistant` message with `tool_calls` is saved to DB but the `role:tool` results are not — leaving a corrupt sequence in history
- Old code only trimmed orphaned messages at the front of the window; sequences buried in the middle were passed through intact, triggering MiniMax error 2013
- `_repair_tool_call_sequence()` walks the full array: drops any assistant+tool_calls whose expected IDs don't match the immediately-following tool results, and drops any orphaned tool messages

## 2026-02-20 — Fix TOC parser for real CN annual report format

**What:** Fixed three bugs that caused `_parse_toc()` to return [] on every real annual report, falling back to the 80k hard-cap with no TOC filtering.

**Files:**
- `tools/sina_reports.py` — modified

**Details:**
- Bug 1: `_TOC_ENTRY_RE` used `\s+` (required space) after 章/节, but real reports have no space: `第一章公司简介 ...... 9` not `第一章 公司简介 ...... 9`. Fixed to `\s*`.
- Bug 2: `_CHAPTER_HEADING_RE` also required `[\s\u3000]` after 章/节, so body-text chapter boundaries were never detected. Fixed by removing the space requirement.
- Bug 3: `_parse_toc` didn't handle plain pre-chapter TOC entries (`重要提示 ...... 1`, `董事会致辞 ...... 5` etc.) and didn't anchor on the `目录` marker. Rewrote to: (1) find `目录` in first 600 lines, (2) parse up to 120 lines after it with both `_TOC_ENTRY_RE` and new `_TOC_PLAIN_ENTRY_RE`, (3) fall back to 400-line scan if no `目录` found.
- Added `致辞`, `致词` to `_SKIP_CHAPTER_KEYWORDS` (covers 董事会致辞, 行长致辞 etc.)
- Added `_TOC_PLAIN_ENTRY_RE` regex for plain entries; excludes sub-entries starting with 一、（一） etc.
- Verified against real 上海银行2024年报 TOC: 15/15 chapters detected, all keep/skip flags correct, sub-entries excluded.

## 2026-02-20 — Add structure.md architecture reference

**What:** Created a comprehensive architecture document so future coding agents can understand the full system without reading every source file.

**Files:**
- `structure.md` — created (full architecture reference)
- `CLAUDE.md` — modified (added instruction to read structure.md before writing code)

## 2026-02-20 — Stop button now cancels server-side agent task

**What:** The Stop button now sends a `POST /api/chat/stop` request that cancels the background asyncio task, so the agent actually stops running rather than just disconnecting the SSE stream.

**Files:**
- `api_chat.py` — added `POST /api/chat/stop` endpoint that calls `task.cancel()` and emits a stopped event
- `frontend/src/api.ts` — added `stopAgentRun()` function
- `frontend/src/components/ChatView.tsx` — `handleStop()` now calls `stopAgentRun` before aborting the SSE connection

## 2026-02-20 — Prioritize quarterly reports over yearly when reading filings

**What:** Agent now defaults to the most recent quarterly report (Q3→mid→Q1) and only fetches the yearly report as a parallel companion, never alone.

**Files:**
- `config.py` — updated planning prompt routing rule with explicit priority order and "切勿单独调用年报" constraint
- `tools/sina_reports.py` — updated `FETCH_COMPANY_REPORT_SCHEMA` description to reinforce the same rule at the tool level

## 2026-02-20 — Reduce Grok token cost for report summarization

**What:** Added `_prepare_for_grok` preprocessing step that eliminates ~50–64% of input tokens before sending to Grok, without losing any financial data.

**Files:**
- `tools/sina_reports.py` — added `_prepare_for_grok()`, updated `_grok_summarize_report()` to preprocess input and log reduction ratio

**Details:**
- Removes lines < 4 chars (page numbers, single-char separators, empty cells extracted as "-")
- Deduplicates lines — repeated table column headers, company name stamps, date labels account for ~34% of lines in typical Sina Finance reports
- If text still exceeds 80k chars after dedup (mainly 年报), applies keyword-section extraction then hard cap
- Measured reductions: Q3 reports ~50%, 年报 ~64% (216k → 80k chars confirmed live)
- No capability loss: financial numbers only need to appear once for Grok to read them

## 2026-02-20 — Fix report routing and add Grok findings section

**What:** Agent now correctly routes "看/分析财报" queries to `fetch_company_report` instead of `web_search`; Grok's summary now includes a "值得关注的亮点或异常" section for downstream analysis.

**Files:**
- `config.py` — added routing rule to planning prompt: report queries → `fetch_company_report`, never `web_search`
- `tools/sina_reports.py` — added section 6 to Grok summarization prompt: 2–4 notable findings with data citations

## 2026-02-20 — Use Grok to read and summarize full financial reports

**What:** `fetch_company_report` now feeds the full report HTML text to Grok (2M-token context) for AI-generated structured summaries, replacing the keyword-heuristic extraction.

**Files:**
- `tools/sina_reports.py` — added `_grok_client`, `_grok_summarize_report()`, updated `fetch_company_report()` to try Grok first with keyword-extraction fallback

**Details:**
- `_grok_summarize_report` sends the full scraped text + `focus_keywords` to `grok-4-1-fast-non-reasoning` via `chat.completions`
- Prompt instructs Grok to produce a Markdown report with tables covering: core metrics, balance sheet, cash flow, segment breakdown, risks
- `focus_keywords` (e.g. `['不良率', '净息差', '拨备覆盖率']`) are included in the prompt so Grok pays special attention to them
- Return dict now includes `"summarized_by": "grok" | "keyword_extraction"` for transparency
- Falls back to `_extract_key_sections` if Grok is not configured or the call fails

## 2026-02-20 — Use Grok live search for web_search tool

**What:** Route `web_search` through Grok's built-in live search (xAI API) when `GROK_API_KEY` is set, with automatic DuckDuckGo fallback.

**Files:**
- `config.py` — added `GROK_API_KEY`, `GROK_BASE_URL`, `GROK_MODEL_NOREASONING`, `GROK_MODEL_REASONING`
- `tools/web.py` — added `_grok_client` (AsyncOpenAI pointing at xAI), `_grok_web_search()`, updated `web_search()` to prefer Grok

**Details:**
- xAI API is OpenAI-compatible; live search enabled via `extra_body={"search_parameters": {"mode": "auto"}}`
- Grok returns the answer in `choices[0].message.content` and citation URLs in a top-level `citations` list
- Falls back to DuckDuckGo silently if Grok is not configured or the call fails
- Uses `grok-4-1-fast-non-reasoning` model (configurable via `GROK_MODEL_noreasoning` env var)

## 2026-02-19 — Frontend reconnect for background agent runs

**What:** Added auto-reconnect logic so the UI reattaches to an in-progress agent run after a network drop or app backgrounding.

**Files:**
- `frontend/src/api.ts` — extracted `_readSSEStream` helper; added `fetchActiveRun` and `subscribeStream` exports
- `frontend/src/components/ChatView.tsx` — added `reconnect` callback, mount effect, and `visibilitychange` effect

**Details:**
- `fetchActiveRun(token)` calls `GET /api/chat/active` to check if an agent run is in progress for the user
- `subscribeStream(token, callbacks)` calls `GET /api/chat/stream` to replay buffered events and stream new ones; returns 404 → `NO_ACTIVE_RUN` error handled silently
- `reconnect` guard: skips if already `sending`, skips if active run belongs to a different conversation
- Triggered on: initial mount (token available) and `document.visibilitychange → visible`

## 2026-02-19 — Fix 400 bad request on invalid tool call JSON args

**What:** MiniMax occasionally returns tool calls with malformed JSON arguments. `_message_to_dict` was storing them raw into conversation history, causing a 400 on the next API call.

**Files:**
- `agent.py` — sanitize `tc.function.arguments` in `_message_to_dict` before adding to history

**Details:**
- `_execute_single_tool` already caught bad JSON (fell back to `{}`), but the raw bad string still got written into `msg_dict["tool_calls"]`
- Fix: `json.loads()` validation in `_message_to_dict`; replaces invalid args with `"{}"` and logs a warning

## 2026-02-19 — Lean system prompt + planning turn

**What:** Replaced the bloated routing-rule system prompt with a lean persona/style/citations prompt (~290 words) plus a dedicated `get_planning_prompt()`. Added a planning turn at the start of every agent run that forces intent resolution and tool mapping before any execution.

**Files:**
- `config.py` — rewrote `get_system_prompt()` (290 words, down from ~1700); added `get_planning_prompt()` with tool capability table and data availability notes
- `agent.py` — added planning turn before main loop; imports `get_planning_prompt`

**Details:**
- System prompt cut ~83% (1700 → 290 words): removed tool priority list, all routing rules, efficiency rules, step-by-step examples — all moved into the planning prompt
- Planning turn: one tool-free LLM call that produces a research plan (intent, term resolution, tool mapping, data limits, parallel groups); plan injected into context + emitted as "Research Plan" thinking block
- Planning failures are non-fatal (logged, agent continues)
- Turn 0 label changed from "Turn 1 · Planning" to "Turn 1 · Analysis" since planning is now separate

## 2026-02-19 — Add 国家队/聪明钱 routing to system prompt

**What:** Added a dedicated routing block for "smart money" queries so the agent maps ambiguous terms (国家队, 汇金, 证金) to the correct tools and data sources before calling anything.

**Files:**
- `config.py` — added "Smart money / 聪明钱 / 国家队" routing section

**Details:**
- Root cause: agent had no routing for 国家队 → fell back to web_search → returned news fluff
- Fix: explicit lookup table mapping each term (北向资金/国家队/主力) to its tool and data frequency
- 国家队 route: fetch_top_shareholders in parallel on 5 known ETFs + 4 large-cap bank stocks; look for 中央汇金/证金公司 in holder names and compare period changes
- Agent must state quarterly disclosure lag when reporting 国家队 data

## 2026-02-19 — Fix system prompt northbound flow description

**What:** Updated `config.py` system prompt to remove stale "discontinued" notes that caused the agent to skip calling `fetch_northbound_flow` entirely.

**Files:**
- `config.py` — updated tool description and routing rule for `fetch_northbound_flow`

**Details:**
- Old text said "net inflow data discontinued" → agent concluded data unavailable and didn't call the tool
- New text reflects article-scraping capability and adds "ALWAYS call this tool"

## 2026-02-19 — Fix northbound flow via EastMoney article listing API

**What:** Replaced the broken `RPT_MUTUAL_DEAL_HISTORY` API with the EastMoney article listing API (column 399 = 北向资金动态), which returns daily summaries with full structured data in each article's `summary` field.

**Files:**
- `tools/cn_capital_flow.py` — replaced implementation; single API call returns N days of data

**Details:**
- Discovered API endpoint from the page's embedded JS vars: `np-listapi.eastmoney.com/comm/web/getNewsByColumns?column=399&biz=web_stock&client=web&req_trace=nb`
- Each article `summary` contains: total 北向 volume (亿), market share %, top-3 stocks for 沪股通 + 深股通 with exact amounts
- Parsed with regex into structured JSON; no per-article fetching needed
- Default `days=5`, max 30

## 2026-02-19 — Show per-turn agent thinking in regular conversations

**What:** Extended thinking block emission to every agent loop iteration (not just the final response), with per-turn unique sources and contextual labels so each thinking step shows as a separate collapsible block.

**Files:**
- `agent.py` — refactored think-extraction to run on every turn; added per-turn source IDs and labels

**Details:**
- Previously: `<think>` tags only extracted on the final no-tool-call turn; all used source `"agent"` so they merged
- Now: extracted from every LLM response before appending to conversation history
- Source is `agent_t{turn+1}` (unique per turn) so frontend shows them as separate blocks
- Labels: "Turn 1 · Planning", "Turn N · After {tool_names}", "Turn N · Synthesis"
- `<think>` content also stripped from `msg_dict["content"]` before it re-enters the message history, so the model doesn't see its own think tags on the next turn

## 2026-02-19 — Dynamic keyword extraction for fetch_company_report

**What:** Made `fetch_company_report` accept optional `focus_keywords` that the LLM passes based on the user's question, so report extraction adapts to any domain rather than relying solely on hardcoded markers.

**Files:**
- `tools/sina_reports.py` — added `focus_keywords` param to schema, `fetch_company_report`, and `_extract_key_sections`

**Details:**
- `focus_keywords` (optional array) is merged with base section markers at extraction time
- Tool description instructs the LLM to always derive and pass keywords from the user's question
- Also added bank-specific base markers (不良率, 净息差, 拨备覆盖率, etc.) as a sensible default for bank stocks
- No extra planning round-trip needed — LLM already has user intent when calling the tool

## 2026-02-19 — Community sentiment via 股吧 integrated into agent flows

**What:** Integrated 股吧 community sentiment into both the debate system and the main agent's deep analysis workflow. Uses scrape_webpage on guba.eastmoney.com (no auth required). Xueqiu was tested and found to be WAF-blocked without session cookies, so dropped. Also fixed missing playwright/JS-domain definitions in web.py.

**Files:**
- `tools/trade_analyzer.py` — modified: added `_fetch_community_sentiment()` function; updated `run_hypothesis_debate` Phase 1 to run sentiment subagent in parallel with data collection for single_stock and comparison question types; sentiment section appended to data_pack before debaters receive it
- `tools/web.py` — fixed: added missing playwright try/except import, `PLAYWRIGHT_AVAILABLE` flag, and `_JS_HEAVY_DOMAINS` list (includes xueqiu.com, guba.eastmoney.com)
- `tools/__init__.py` — modified: removed fetch_eastmoney_forum and fetch_xueqiu_comments from TOOL_SCHEMAS and TOOL_MAP (tools are not exposed to the agent; sentiment handled internally)
- `config.py` — modified: updated forum routing to use scrape_webpage directly; updated deep analysis Step 1 to dispatch a sentiment subagent scraping guba; removed stale tool entries #25/#26 and their citation URLs

**Details:**
- `_fetch_community_sentiment` scrapes all stock entities in parallel, feeds combined text to a single MiniMax LLM call for summarization (~350 words output)
- Result is appended to the debate data_pack so all 4 debaters and the judge see retail sentiment alongside financial data
- For main agent (non-debate) deep analysis: dispatch_subagents handles guba scraping in parallel with financial data calls
- guba URL format: `https://guba.eastmoney.com/list,{6-digit-code}.html` — no SH/SZ prefix, no auth needed

## 2026-02-19 — Lift context window limits for 200k model + forum fallback

**What:** Raised all context/token limits across agents to better utilize a 200k-context MiniMax model; added web_search fallback when both forum sentiment tools fail.

**Files:**
- `agent.py` — modified: SUMMARIZE_THRESHOLD 30→60, SUMMARIZE_KEEP_RECENT 10→20, MAX_TOOL_RESULT_CHARS 15k→40k, summarizer max_tokens 1500→2500
- `tools/subagent.py` — modified: added max_tokens=3000 to subagent LLM calls
- `tools/trade_analyzer.py` — modified: MAX_DEBATER_TOOL_RESULT_CHARS 12k→25k, data_pack cap 60k→100k chars, debater max_tokens 2000→4000, `_llm_call` default max_tokens 2000→3000 (judge/rebuttal)
- `config.py` — modified: forum routing fallback — if both fetch_eastmoney_forum and fetch_xueqiu_comments fail, fall back to web_search for retail sentiment

**Details:**
- Hypothesis formation stays at max_tokens=2000 (JSON output, no headroom needed)
- Summarizer fires less often (60 messages) but produces richer output when it does (2500 tokens)
- Debater increase to 4000 tokens ensures 800-word analyses with data citations are never truncated

## 2026-02-19 — Community sentiment tools (股吧 + 雪球)

**What:** Added two new tools for retail investor sentiment from Eastmoney 股吧 and Xueqiu 雪球 forums; wired them into the deep analysis workflow and system prompt routing.

**Files:**
- `tools/eastmoney_forum.py` — created: fetches and parses the SSR HTML post list from guba.eastmoney.com; returns titles, view/reply counts, authors, timestamps; falls back to link extraction if CSS selectors miss
- `tools/xueqiu.py` — already existed but was unregistered; no code changes
- `tools/__init__.py` — modified: imported and registered `fetch_xueqiu_comments` and `fetch_eastmoney_forum` in both `TOOL_SCHEMAS` and `TOOL_MAP`
- `config.py` — modified: replaced generic scrape_webpage forum guidance with dedicated tool routing; added both tools to the numbered tool list (#25, #26); added `fetch_eastmoney_forum` and `fetch_xueqiu_comments` to deep analysis Step 1 parallel calls; added citation URL mappings for both tools

**Details:**
- Eastmoney guba URL format: `https://guba.eastmoney.com/list,{code}.html` (page 1) / `list,{code}_{N}.html` (page N) — no SH/SZ prefix required
- Xueqiu API format: `https://xueqiu.com/query/v1/symbol/search/status?symbol=SH603986` — auto-detects SH vs SZ from the 6-digit code prefix

## 2026-02-19 — Full company reports in debate + revenue composition analysis

**What:** Removed report truncation so the agent reads entire annual reports. Added revenue composition and macro-sensitivity dimensions to debate prompts. Included `fetch_company_report` in the debate data plan so analysts see segment breakdowns, management discussion, and revenue structure.

**Files:**
- `tools/sina_reports.py` — modified: removed 8000 char cap in `_extract_key_sections`; raised per-section line limit from 60 to 150; added segment/revenue markers (分行业, 分产品, 收入构成, 利息净收入, 经营情况讨论与分析, etc.)
- `tools/trade_analyzer.py` — modified: added `fetch_company_report` (yearly + mid) to single_stock and comparison data plan examples; updated hypothesis formation rules to mandate annual reports; raised data_pack cap from 30k to 60k chars; raised `MAX_DEBATER_TOOL_RESULT_CHARS` from 3k to 12k; added dimensions #1 (收入结构与驱动力) and #2 (宏观敏感性) to `_DIMENSIONS_SINGLE_STOCK` and `_DIMENSIONS_COMPARISON`
- `agent.py` — modified: raised `MAX_TOOL_RESULT_CHARS` from 4k to 15k so full reports reach the LLM

**Details:**
- Root cause: analysts never saw revenue breakdown because (a) `fetch_company_report` wasn't in the debate data plan, (b) report text was truncated to 8000 chars cutting off segment tables, (c) dimension prompts only asked about "revenue growth rate" not "where revenue comes from"
- New dimensions ask analysts to: identify revenue sources by segment/product/region, quantify each segment's growth, assess macro sensitivity (rate/FX/policy exposure), and project which business lines benefit or suffer under current conditions
- Truncation chain raised: tool output 4k→15k, debater tool results 3k→12k, data pack 30k→60k, report extraction unlimited
- MiniMax-M1-80k has sufficient context window for these larger payloads

## 2026-02-19 — Per-user report management system + My Reports browser

**What:** Implemented per-user file isolation, authenticated file serving, persistent file tracking in the database, descriptive file naming, and a "My Reports" panel for browsing/filtering all generated files.

**Files:**
- `db.py` — modified: added `files` table with indexes on conversation_id, user_id, and filepath
- `accounts.py` — modified: added `save_file_record()`, `load_conversation_files()`, `load_user_files()` (with optional type filter + conversation title join)
- `agent.py` — modified: added `user_id_context` contextvar, set it around tool execution in both `_run_agent_inner` and `_run_debate_inner`, save file records to DB after tool results
- `tools/output.py` — modified: replaced static `OUTPUT_DIR` with `_get_output_dir()` that returns per-user subdirectory; added `_safe_filename()` for descriptive names based on title (e.g. `招商银行分析_20260219_a1b2.pdf`)
- `tools/trade_analyzer.py` — modified: same `_get_output_dir()` pattern replacing `_OUTPUT_DIR`
- `auth.py` — modified: added `get_current_user_or_query_token()` supporting both Authorization header and `?token=` query param (for `<img src>`)
- `api_chat.py` — modified: added `GET /api/chat/files` (list all user files with optional `?file_type=` filter); added `GET /api/chat/files/{filepath}` (authenticated serve with path traversal protection); updated `get_messages` to return `{messages, files}`; updated file URL generation to `/api/chat/files/` prefix
- `web.py` — modified: removed public `/output` static mount
- `frontend/src/api.ts` — modified: `fetchMessages` handles `{messages, files}` response; added `fetchUserFiles()`
- `frontend/src/components/ChatView.tsx` — modified: attaches conversation files to last assistant message on load
- `frontend/src/components/MessageBubble.tsx` — modified: images use `?token=` query param auth; PDFs/downloads use fetch + blob URL
- `frontend/src/components/ReportsPanel.tsx` — created: modal panel with type filter tabs (All/PDF/Charts/MD), search, thumbnail previews for images, click-to-download
- `frontend/src/components/Sidebar.tsx` — modified: added "My Reports" button + ReportsPanel toggle
- `frontend/src/i18n.tsx` — modified: added reports panel translation keys
- `frontend/src/styles/index.css` — modified: added reports button + reports panel styles

**Details:**
- Files table stores: user_id, conversation_id, filepath (relative), filename, file_type
- File ownership enforced at DB level — users can only access their own files
- Path traversal protection: resolved path must stay within PROJECT_ROOT
- Filenames now descriptive: `{sanitized_title}_{YYYYMMDD}_{4hex}.{ext}` instead of `report_{8hex}.pdf`
- My Reports panel reuses admin panel overlay/layout, adds search + type filter tabs
- Old flat `/output/` URLs no longer work — only new `/api/chat/files/` URLs are served

## 2026-02-18 — Match debate report language to user input

**What:** Fixed debate analyst outputs appearing in English when user asks in Chinese. Added dynamic `response_language` field to hypothesis and used it across all prompts to enforce consistent output language matching the user's input.

**Files:**
- `tools/trade_analyzer.py` — modified: added `response_language` to hypothesis schema; replaced ambiguous "write in the same language as the data" with explicit `{response_language}` in all 5 prompts (`_PRO_OPENING`, `_CON_OPENING`, `_REBUTTAL`, `_JUDGE`, `_SUMMARY`); translated dimension templates to Chinese

**Details:**
- Root cause: dimension headings were in English (e.g. "VALUATION", "EARNINGS TRAJECTORY"), and the language instruction was ambiguous, so some LLM analysts defaulted to English
- Fix: hypothesis formation now detects user language → `response_language` field (e.g. "中文", "English") → all prompts enforce output in that language
- Dimension templates (`_DIMENSIONS_SINGLE_STOCK`, `_DIMENSIONS_COMPARISON`, `_DIMENSIONS_SECTOR`, `_DIMENSIONS_GENERAL`) translated to Chinese

## 2026-02-18 — Separate debate mode from regular chat

**What:** Moved debate functionality out of the chat input area into a dedicated sidebar button with a modal dialog. Debate now creates a new conversation automatically.

**Files:**
- `frontend/src/components/ChatView.tsx` — modified: removed Debate button from input area, added `pendingDebate`/`onDebateStarted` props to auto-trigger debate from parent
- `frontend/src/pages/ChatLayout.tsx` — modified: added debate modal state, modal overlay with textarea, handles creating new conversation and passing pending debate to ChatView
- `frontend/src/components/Sidebar.tsx` — modified: added `onDebate` prop, added "Hypothesis Debate" button in sidebar header
- `frontend/src/styles/index.css` — modified: removed old `.input-area .debate-btn` styles, added sidebar debate button styles and debate modal overlay/dialog styles

**Details:**
- Debate button now lives in the sidebar header below "+ New Chat"
- Clicking it opens a centered modal with a textarea for the investment question
- Submitting creates a new conversation, sets it active, and auto-starts the debate via `pendingDebate` prop
- Enter submits, Shift+Enter for newline, Escape closes modal
- Modal auto-focuses the textarea on open

## 2026-02-18 — Fix PDF footer overlap, Chinese disclaimer, Songti font

**What:** Fixed PDF report generation: footer no longer overlaps body content, English disclaimer replaced with Chinese, font changed to Songti (宋体) for better readability, body text spacing increased.

**Files:**
- `tools/output.py` — modified: added `_ReportPDF` FPDF subclass with proper `footer()` method (replaces buggy post-hoc page iteration); prioritized Songti.ttc in font search order; replaced English disclaimer with Chinese; increased body text to 10.5pt with 6.5 line height; added Unicode subscript sanitization (₀→0); changed bullet char from U+2022 to U+25CF (CJK-safe); increased auto page break margin to 30mm

**Details:**
- Root cause of overlap: old code looped through pages after content was done and wrote footer text, which collided with content on page boundaries
- Fix: `_ReportPDF.footer()` is called automatically by fpdf2 during page breaks, ensuring correct positioning
- Font priority: Songti.ttc (macOS) → PingFang.ttc → Noto Serif CJK (Linux) → Noto Sans CJK → fallback

## 2026-02-18 — Hypothesis-driven debate engine

**What:** Generalized the debate engine from hardcoded "is stock X worth investing in?" to handle any investment question (comparisons, sector analysis, general market questions) by forming a testable hypothesis (H₀) from the user's question, then having pro/con sides debate it.

**Files:**
- `tools/trade_analyzer.py` — modified: added `_form_hypothesis()` (Phase 0 LLM call to parse question into hypothesis + data plan), `_collect_data_from_plan()` (dynamic tool execution from plan), `run_hypothesis_debate()` (new main entry point); replaced `_BULL_OPENING`/`_BEAR_OPENING` with `_PRO_OPENING`/`_CON_OPENING`; generalized `_REBUTTAL`, `_JUDGE`, `_SUMMARY` prompts to use hypothesis framing; added dimension templates per question type; updated all phase functions to accept hypothesis dict; made `analyze_trade_opportunity()` a backward-compatible wrapper; updated report generation with hypothesis-aware titles and labels
- `agent.py` — modified: simplified `_run_debate_inner()` to pass user question directly to `run_hypothesis_debate()` (removed stock code extraction logic)
- `tools/__init__.py` — modified: added `run_hypothesis_debate` export
- `frontend/src/components/ChatView.tsx` — modified: updated default debate message to "Analyze the question discussed above"
- `changes.md` — modified: appended this entry

**Details:**
- Phase 0 forms hypothesis via LLM with 4 worked examples (single_stock, comparison, sector, general), full tool catalog, max 20 tool calls
- Data collection now executes arbitrary tool plans in parallel instead of hardcoded 7 tools
- Prompts use `{hypothesis}` and `{dimensions_text}` (per question type) instead of stock-specific framing
- Judge verdict options are dynamic from hypothesis (replaces hardcoded BUY/SELL/HOLD)
- Report filenames generated from entity names (e.g. "招商银行_vs_工商银行_20260218_143000.md")
- Backward compatible: `analyze_trade_opportunity(stock_code="600036")` still works, internally calls `run_hypothesis_debate("600036 值得投资吗?")`

## 2026-02-18 — Remove Gemini + fix billion/亿 unit conversion

**What:** Removed Gemini dependency (expensive), DuckDuckGo is now the sole search backend. Fixed critical unit conversion confusion where agents treated "billion" as "亿" (should be 10亿). Added explicit conversion rules to all 5 debate prompts and 3 system messages.

**Files:**
- `tools/web.py` — removed Gemini import, `_gemini_search_sync`, simplified `web_search` to DDG only
- `config.py` — removed `GEMINI_API_KEY`, updated web_search description
- `requirements.txt` — removed `google-genai`
- `tools/trade_analyzer.py` — added `_UNIT_RULE` constant with conversion examples, injected into all 5 prompts (_BULL_OPENING, _BEAR_OPENING, _REBUTTAL, _JUDGE, _SUMMARY) and 2 system messages

## 2026-02-18 — Fix Debate stock extraction + add Sina profit statement tool

**What:** Fixed critical bug where Debate button couldn't find the stock code (was only scanning assistant/tool messages, missing user messages where the stock name lives). Also added `fetch_sina_profit_statement` tool for structured annual profit data from Sina Finance.

**Files:**
- `agent.py` — fixed `_run_debate_inner`: now scans ALL message types (user/assistant/tool) for stock code; tries regex first (fast), falls back to LLM extraction
- `tools/sina_reports.py` — added `fetch_sina_profit_statement()` and `FETCH_SINA_PROFIT_SCHEMA`: scrapes `money.finance.sina.com.cn` profit statement tables by stock code and year
- `tools/__init__.py` — registered new tool in TOOL_SCHEMAS and TOOL_MAP
- `config.py` — added tool #11 description, citation URL mapping, renumbered tools 12-24

## 2026-02-18 — Add dedicated Debate button

**What:** Added a "Debate" button in the chat UI that directly invokes the multi-LLM trade analyzer without going through the agent loop. Extracts stock code from conversation context via a quick LLM call, passes gathered conversation data as context to avoid re-fetching. Works with or without typed input.

**Files:**
- `agent.py` — added `run_debate()` and `_run_debate_inner()`: extracts stock code from conversation, calls `analyze_trade_opportunity` directly with conversation context
- `api_chat.py` — added `mode` field to `SendBody`, routes `mode="debate"` to `run_debate()`
- `frontend/src/api.ts` — added `mode` parameter to `sendMessage()`
- `frontend/src/components/ChatView.tsx` — added Debate button, `handleDebate()`, refactored `handleSend()` to accept mode and override message
- `frontend/src/styles/index.css` — added `.debate-btn` styles (dark slate color)

## 2026-02-18 — Reference prior reports in trade analysis

**What:** Trade analyzer now checks the output/ directory for existing reports on the same stock (within 5 days). If found, the most recent report is included in the data pack as a soft reference — analysts can use data points and arguments from it but are instructed not to treat it as authoritative.

**Files:**
- `tools/trade_analyzer.py` — modified: added `_find_prior_report()` function, wired into `_collect_data()` with clear framing that prior reports are reference-only

## 2026-02-18 — Fix summary timeout + language matching

**What:** Fixed LLM timeout in executive summary phase and made output language match input language instead of hardcoding Chinese.

**Files:**
- `tools/trade_analyzer.py` — modified: increased `_run_summary` timeout to 120s / max_tokens to 3000; replaced all "Write in Chinese (书面语)" with language-matching instructions; added graceful fallback when summary LLM call fails (falls back to verdict instead of showing error string in report)

## 2026-02-17 — Archive Telegram bot, web-only startup

**What:** Moved Telegram bot component to `archive/` since the web app is the primary interface. Simplified `start.py` to web-only.

**Files:**
- `bot.py` → `archive/bot.py` — moved
- `start.py` — modified: removed all Telegram bot logic, removed `TELEGRAM_BOT_TOKEN` import
- `config.py` — modified: removed `TELEGRAM_BOT_TOKEN` env var

**Details:**
- `start.py` now only runs the uvicorn web server (no more dual web+bot mode)
- Bot code preserved in `archive/` for reference if needed later

## 2026-02-17 — EastMoney structured data tools (financials, shareholders, dragon tiger, dividends)

**What:** Added 4 new tools using EastMoney datacenter APIs for structured financial data — financial statements, top shareholders, dragon tiger list, and dividend history. Updated system prompt to use structured APIs instead of web scraping for deep stock analysis.

**Files:**
- `tools/cn_eastmoney.py` — created: 4 tool functions (fetch_stock_financials, fetch_top_shareholders, fetch_dragon_tiger, fetch_dividend_history)
- `tools/__init__.py` — modified: registered 4 new tools + schemas (now 24 tools total)
- `config.py` — modified: added tools #14-17 to priority list, replaced old scrape-based routing for dividends/financials with direct API tools, updated deep analysis step to use structured financials + shareholders + capital flow + dividends in parallel (6 parallel calls), updated comparison routing, added citation URL mappings

**Details:**
- `fetch_stock_financials` — balance sheet, income statement, or cash flow. 10+ years of quarterly data from EastMoney datacenter API. Fields: revenue, net profit, YoY growth, assets, liabilities, debt ratio, operating/investing/financing cash flows.
- `fetch_top_shareholders` — top 10 circulating shareholders (十大流通股东) with holding changes (新进/增持/减持/不变). Grouped by reporting period.
- `fetch_dragon_tiger` — broker-level buy/sell data on exceptional trading days (涨跌停, 振幅>7%). Both buy-side and sell-side entries merged chronologically.
- `fetch_dividend_history` — complete dividend history with cash per 10 shares, bonus shares, ex-dividend dates, distribution progress, and EPS. Includes summary stats.
- Deep analysis now fetches 6 data sources in parallel: income statement (8 periods), balance sheet (4 periods), quote, capital flow (20 days), top shareholders (2 periods), dividend history.
- Old scraping-based routes for dividends/financials replaced with direct API calls.

## 2026-02-17 — Capital flow tools (资金流向)

**What:** Added 3 new tools for tracking institutional vs retail capital flow in Chinese A-shares, using EastMoney APIs.

**Files:**
- `tools/cn_capital_flow.py` — created: 3 tool functions (fetch_stock_capital_flow, fetch_northbound_flow, fetch_capital_flow_ranking)
- `tools/__init__.py` — modified: registered 3 new tools + schemas (now 20 tools total)
- `config.py` — modified: added tools to priority list (#11-13), added routing rules for capital flow queries, updated deep analysis rule to include capital flow, added citation URL mappings

**Details:**
- `fetch_stock_capital_flow` — daily capital flow for a single stock (~120 trading days / 6 months). Breaks down by order size: super-large (>100万, institutional), large (20-100万), medium (4-20万), small (<4万, retail). Includes period summary (total net, buy/sell day count).
- `fetch_northbound_flow` — Stock Connect (沪深港通) daily deal volume. Note: net inflow/outflow data was discontinued after Aug 2024 due to regulatory changes. Deal amount and count still available.
- `fetch_capital_flow_ranking` — top stocks ranked by institutional net inflow or outflow. Shows which stocks institutions are buying/selling most heavily.
- System prompt updated: when user asks about a specific stock ("最近怎么样", "analyze X"), agent now fetches capital flow alongside financial reports and quote data in parallel.
- All APIs are free, no auth, direct HTTP to EastMoney endpoints.

## 2026-02-17 — Code review: bug fixes and simplification

**What:** Fixed critical conversation routing bug, removed broken/dead code, consolidated duplicated code.

**Files:**
- `agent.py` — modified: added `conversation_id` parameter so web UI targets the correct conversation
- `api_chat.py` — modified: passes `conversation_id` through to `run_agent` instead of relying on "most recent" heuristic
- `db.py` — modified: made `init_db()` idempotent (skip if already initialized)
- `config.py` — modified: added `ADMIN_USERNAME` (moved from duplicated hardcoded values)
- `api_auth.py` — modified: import `ADMIN_USERNAME` from config, combined login into single pool acquire
- `api_admin.py` — modified: import `ADMIN_USERNAME` from config
- `tools/output.py` — modified: fixed `generate_references_image` KeyError (refs no longer have 'name' field)
- `tools/utils.py` — created: shared `safe_value()` function
- `tools/cn_market.py` — modified: use shared `safe_value`, removed duplicate definition
- `tools/cn_funds.py` — modified: use shared `safe_value`, removed duplicate definition
- `tools/market_scan.py` — modified: merged `_get_top_gainers`/`_get_top_losers` into single `_get_top_movers`
- `tools/sina_reports.py` — modified: removed dead code (line that was immediately overwritten)
- `start.py` — modified: removed unused `sys` import
- `cli.py` — deleted: was completely broken (wrong `run_agent` signature)

**Details:**
- Critical bug: web UI messages went to wrong conversation because `run_agent` always used "most recent" instead of the selected one
- `generate_references_image` would crash on Telegram with KeyError on `r['name']` since refs were simplified to URL-only
- `_safe_value` was duplicated across cn_market.py and cn_funds.py — moved to tools/utils.py
- `ADMIN_USERNAME` was hardcoded in two files — moved to config.py as env var
- `init_db()` was called twice when using start.py (once directly, once via web lifespan)

## 2026-02-17 — Professional PDF generation with Chinese font support

**What:** Rewrote PDF generation to render Chinese text correctly on Linux servers and produce professionally formatted reports.

**Files:**
- `tools/output.py` — modified: new CJK font resolution (macOS + Linux paths + auto-download fallback), professional layout with navy header band, color hierarchy, proper table rendering with borders/shading/alternating rows, page footers, bullet points, bold stripping
- `deploy.sh` — modified: added `fonts-wqy-microhei` to apt packages
- `.gitignore` — modified: added `fonts/` directory

**Details:**
- Font search order: bundled NotoSansSC → macOS system fonts → Linux packages (noto-cjk, wqy-microhei, wqy-zenhei) → auto-download from Google Fonts as last resort
- PDF styling: dark navy header band with white title, steel blue section headings with underline rules, proper markdown table rendering with calculated column widths, alternating row colors, page number footers
- Tables handle cell overflow by truncating with ellipsis
- Long titles auto-wrap in header band
- Matplotlib Chinese font candidates also updated to include Linux fonts (Noto Sans CJK SC, WenQuanYi)

## 2026-02-15 — Comprehensive TradingView Scanner API field investigation

**What:** Tested 72+ TradingView Scanner API fields across 8 categories, documented all working/null fields, expanded the `screen_cn_stocks` tool with new columns, and rewrote `tradingview_data_sources.md`.

**Files:**
- `tradingview_data_sources.md` — rewritten with complete field catalog (54 verified working fields), filter recipes, industry-specific availability notes
- `tools/cn_screener.py` — expanded default columns (added ROA, margins, gross_profit, free_cash_flow, total_assets, total_debt, debt_to_equity, current_ratio, EPS, 52-week range, Perf.6M/Y), added `not_equal` filter op, updated schema descriptions
- `CLAUDE.md` — created with project guidelines for change logging

**Details:**
- 54 fields confirmed working for China A-shares, 24 fields always null (growth metrics, detailed balance sheet breakdowns, operating cash flow)
- Banks have sparser data (no gross_margin, ebitda); non-bank stocks return most fields
- Verified filters: PE < 10, mcap + PE + dividend combos, sector filtering, stock code lookup, `not_equal` operator
- New default columns give the agent much richer data per query without needing extra API calls

## 2026-02-16 — Footnote citations with reference image

**What:** Added mandatory footnote citations to all agent responses, with references rendered as a separate PNG image sent after the main reply in Telegram.

**Files:**
- `config.py` — added "Citations (MANDATORY)" section to system prompt instructing the LLM to always include `[references]...[/references]` blocks with numbered sources
- `tools/output.py` — added `parse_references()` to extract reference blocks from text, and `generate_references_image()` to render them as a dark-themed PNG with source names and URLs
- `bot.py` — integrated reference parsing: extracts references from agent response, strips the block from text, generates reference image, sends it as the last photo after any charts/PDFs

**Details:**
- References use `[references]...[/references]` delimiters with format `[N] Source Name | URL`
- Image uses dark theme (#1a1a2e background), blue source names, gray monospace URLs
- Supports Chinese text in source names, auto-wraps long URLs
- Reference image is always sent last (after charts and PDFs)
- If the LLM doesn't include references, no image is generated (graceful fallback)

## 2026-02-16 — Fix orphaned tool results in conversation history

**What:** Fixed `tool result's tool id not found` error caused by loading a conversation history window that starts mid-tool-call-sequence.

**Files:**
- `accounts.py` — added trimming logic to `load_recent_messages()` that skips orphaned `tool` and `assistant` (with tool_calls) messages from the front of the loaded window

**Details:**
- When loading the last N messages, the window could start with tool result messages whose parent assistant tool_call message was outside the window
- MiniMax API rejects these orphaned tool results with error 2013
- Fix: trim from the front until we hit a clean `user` or plain `assistant` message

## 2026-02-16 — Web UI for Financial Research Agent

**What:** Added a browser-based chat interface (FastAPI backend + React frontend) so the agent is accessible from anywhere, not just Telegram.

**Files:**
- `config.py` — modified: added `JWT_SECRET`, `WEB_PORT` env vars
- `db.py` — modified: added `web_accounts` table to SCHEMA_SQL
- `requirements.txt` — modified: added `fastapi`, `uvicorn[standard]`, `PyJWT`, `bcrypt`, `python-multipart`
- `auth.py` — created: bcrypt password hashing + JWT token creation/validation
- `api_auth.py` — created: `/api/auth/register`, `/api/auth/login`, `/api/auth/me` endpoints
- `api_chat.py` — created: conversations CRUD + SSE `/api/chat/send` endpoint integrating with `run_agent()`
- `web.py` — created: FastAPI app entry point with CORS, static files, lifespan DB init
- `frontend/` — created: React + Vite + TypeScript SPA
  - `src/api.ts` — HTTP client + SSE POST stream parser
  - `src/store.tsx` — AuthContext with localStorage token persistence
  - `src/App.tsx` — Router with protected routes
  - `src/pages/LoginPage.tsx` — Login/register form
  - `src/pages/ChatLayout.tsx` — Sidebar + chat main layout
  - `src/components/ChatView.tsx` — Message list + input + SSE integration
  - `src/components/MessageBubble.tsx` — Markdown rendering with react-markdown + remark-gfm
  - `src/components/Sidebar.tsx` — Conversation list + new chat + delete
  - `src/components/ReferenceCard.tsx` — Styled reference links (HTML, not PNG)
  - `src/components/StatusIndicator.tsx` — Animated "Thinking..." / "Running: tool" dots
  - `src/styles/index.css` — Dark theme (#0f0f23 bg, #82b1ff accent), responsive mobile
- `.gitignore` — modified: added `frontend/node_modules/`, `frontend/dist/`

**Details:**
- SSE streaming from POST using `fetch()` + `ReadableStream` (not EventSource which is GET-only)
- Auto-sets conversation title from first user message
- References rendered as styled HTML card (not PNG image like Telegram)
- Responsive design: mobile sidebar collapses into hamburger menu overlay
- Token expiry returns 401 which triggers automatic redirect to login
- Telegram bot continues running independently alongside the web server
- Production: `cd frontend && npm run build` then `uvicorn web:app` serves everything on one port

## 2026-02-16 — Fix references display + Sina Finance report tool

**What:** Fixed references not showing in web UI for historical messages, and added a new `fetch_company_report` tool that scrapes Sina Finance for company financial reports (年报/季报). Updated system prompt to always fetch reports when analyzing a specific company.

**Files:**
- `frontend/src/components/ChatView.tsx` — modified: added client-side `parseReferences()` to extract references from historical message content when loading conversations
- `tools/sina_reports.py` — created: `fetch_company_report` tool that scrapes Sina Finance bulletin pages (`vCB_Bulletin`, `vCB_BulletinYi/Zhong/San`) to find the latest report, extracts key financial sections and PDF link
- `tools/__init__.py` — modified: registered `fetch_company_report` + `FETCH_COMPANY_REPORT_SCHEMA` (now 17 tools)
- `config.py` — modified: added `fetch_company_report` to tool priority list (#10), added mandatory routing rule for company analysis (always fetch yearly + latest quarterly report in parallel), added citation URL mapping

**Details:**
- References fix: when loading historical messages, the raw `[references]...[/references]` block was still in the DB content but wasn't being parsed. Added frontend-side regex parsing matching the Python `parse_references()` logic
- Sina report URLs: yearly=`vCB_Bulletin`, Q1=`vCB_BulletinYi`, mid=`vCB_BulletinZhong`, Q3=`vCB_BulletinSan`, all under `vip.stock.finance.sina.com.cn`
- Report tool extracts key financial sections (主要财务数据, 营业收入, 净利润, 资产负债, 现金流, 分红, etc.) and limits to ~8000 chars
- Also extracts PDF download link from report detail page
- System prompt now mandates: when user asks about a specific company, call `fetch_company_report(yearly)` + `fetch_company_report(latest quarter)` + `fetch_cn_stock_data(quote)` in parallel

## 2026-02-16 — Single-command startup + parchment light theme

**What:** Created `start.py` to launch the entire app (web server + Telegram bot) with one command. Redesigned the web UI from dark theme to a warm parchment/light color scheme.

**Files:**
- `start.py` — created: single entry point that auto-builds frontend if stale, runs uvicorn web server + Telegram bot concurrently via asyncio
- `frontend/src/styles/index.css` — rewritten: warm parchment palette (#f5f0e6 bg, #ebe5d7 sidebar, #8b6914 accent), serif font (Georgia/Songti SC), white input field, light assistant bubbles with border

**Details:**
- `python start.py` does everything: installs npm deps if needed, builds frontend if dist/ is stale, inits DB, starts web server on configured port, starts Telegram bot if token is set
- If TELEGRAM_BOT_TOKEN is not set, only the web server runs (no error)
- Frontend auto-builds only when src/ files are newer than dist/
- Parchment theme: warm off-white backgrounds, dark brown text, golden-brown accent (#8b6914), serif typography for a document/research feel

## 2026-02-17 — Research: free APIs for China A-share order flow / capital flow data

**What:** Investigated 6 data sources for buyer/seller order flow (买卖盘, 资金流向, 主力资金) for China A-share stocks, documenting endpoints, data returned, and authentication requirements.

**Files:**
- `changes.md` — modified (this entry)

**Details:**
- Best option for integration: EastMoney push2 direct HTTP API (no auth, JSON, real-time capital flow by order size) or AKShare library (wraps EastMoney/Sina, pip install, no API key)
- Sina Finance hq.sinajs.cn provides free 5-level order book but requires Referer header spoofing
- TradingView Scanner has no capital flow fields for China A-shares
- Tushare requires registration + API token (not truly free/anonymous)
- Full details in research summary provided to user

## 2026-02-17 — Comprehensive EastMoney data sub-pages API endpoint investigation

**What:** Systematically investigated all 20 data sub-pages on EastMoney for individual Chinese A-share stocks, testing API endpoints to find working JSON data sources. Created comprehensive documentation of 14 verified working endpoints across 6 categories.

**Files:**
- `EASTMONEY_API_ENDPOINTS.md` — created: Complete API documentation with endpoint URLs, parameters, response formats, field descriptions, and usage examples

**Details:**
- Tested stock code 600173 (卧龙新能) across 20 different data categories
- Successfully identified 14 working API endpoints:
  - Market Data (5 endpoints): Real-time quote, intraday tick data, K-line/OHLC, main force capital flow, stock fund flow details
  - Trading Intelligence (2 endpoints): Dragon Tiger List buy/sell sides (异动营业部交易)
  - Financial Statements (3 endpoints): Balance sheet, income statement, cash flow statement
  - Shareholding (2 endpoints): Top 10 circulating shareholders, top 10 total shareholders
  - Corporate Actions (1 endpoint): Dividends and share bonus distributions
  - Company Info (1 endpoint): Core themes/concepts classification
- Two API types discovered:
  - `datacenter-web.eastmoney.com/api/data/v1/get` - Structured financial/corporate data with report names
  - `push2.eastmoney.com` / `push2his.eastmoney.com` - Real-time and historical market data
- Financial statements provide 10+ years of quarterly/annual data (104 records for balance sheet)
- Dragon Tiger List tracks major institutional broker buy/sell transactions on exceptional trading days (412+ records)
- Shareholder data shows top 10 holders with holding changes across multiple reporting periods (920+ records)
- Documentation includes: field counts, sample data, value ratings (HIGH/MEDIUM), Python usage examples, stock code format specifications
- Missing/unavailable: 15 data types could not be found via API (announcements, stock calendar, margin trading, block trades, executive holdings, research reports, etc.) - may require scraping or authentication
- Recommended priority: 8 HIGH-value endpoints identified for immediate agent tool integration

## 2026-02-17 — Multi-LLM debate system for trade opportunity analysis

**What:** Added `analyze_trade_opportunity` tool — a structured 4-phase debate system using MiniMax + Qwen to produce buy/sell/hold verdicts with anonymized judging.

**Files:**
- `tools/trade_analyzer.py` — created: multi-LLM debate orchestrator (~440 lines) with 4 phases: data collection, opening arguments, rebuttals, anonymized judge
- `tools/__init__.py` — modified: registered `analyze_trade_opportunity` + `ANALYZE_TRADE_SCHEMA` (now 25 tools total)
- `config.py` — modified: added `QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL` env vars; added tool #22 to priority list; added routing rule for "值得买吗"/"should I buy" triggers; added citation URL mapping

**Details:**
- Phase 1: Parallel data collection via 7 existing tools (income/balance/cashflow statements, quote, capital flow, shareholders, dividends)
- Phase 2: 4 parallel LLM calls — Bull-A (MiniMax), Bull-B (Qwen), Bear-A (MiniMax), Bear-B (Qwen) with structured prompts covering 8 mandatory analysis dimensions
- Phase 3: 4 parallel rebuttal calls — each debater sees opposing arguments + ally's argument, produces targeted counter-arguments
- Phase 4: 1 MiniMax judge call — all 8 arguments shuffled randomly, labeled Analyst 1-8 (no model attribution), produces verdict with confidence score, rationale, risks, dissenting view, time horizon
- Circular import avoided via late import of `execute_tool` in `_execute_tool` wrapper
- Total: ~9 LLM calls + 7 data tool calls per analysis, ~30-60 seconds end-to-end

## 2026-02-17 — Research: TradingAgents multi-agent debate architecture analysis

**What:** Deep analysis of TauricResearch/TradingAgents GitHub repo's multi-agent debate system architecture, covering all agent roles, prompts, debate flow, state management, memory/reflection, and final decision pipeline.

**Files:**
- `changes.md` — modified (this entry)

**Details:**
- Fetched and analyzed 16 source files from the TradingAgents repo covering analysts, researchers, trader, risk management debaters, managers, graph orchestration, conditional logic, reflection, propagation, signal processing, and agent state definitions
- Documented exact prompts for all 10+ agent roles, two-tier debate structure (bull/bear investment debate + 3-way risk debate), state passing via LangGraph TypedDict, memory/reflection learning loop, and signal extraction pipeline
- Key finding: system uses configurable debate rounds (default 1 round each) with round-robin turn-taking controlled by counter-based conditional edges in a LangGraph StateGraph

## 2026-02-18 — Show agent thinking process with model name in frontend

**What:** Added real-time status updates showing which model is working and what phase the trade analyzer is in, replacing generic "Thinking..." with model-tagged progress.

**Files:**
- `agent.py` — modified: added `contextvars.ContextVar` for status callback, changed status to "MiniMax · Thinking...", set/reset contextvar around tool execution
- `tools/trade_analyzer.py` — modified: reads status callback contextvar, emits phase-specific status ("Collecting market data...", "MiniMax + Qwen · Opening arguments...", etc.)
- `frontend/src/components/StatusIndicator.tsx` — modified: parses " · " separator to render model name as styled badge pill
- `frontend/src/styles/index.css` — modified: added `.status-model` pill styling (accent-colored badge)

**Details:**
- Status progression during trade analysis: "Collecting market data..." → "MiniMax + Qwen · Opening arguments (4 analysts)..." → "MiniMax + Qwen · Rebuttals (4 analysts)..." → "MiniMax · Judge rendering verdict..."
- Uses `contextvars.ContextVar` to pass the status callback to tools without changing the `execute_tool` interface
- Frontend parsing is backwards-compatible: status text without " · " renders as before

## 2026-02-18 — Tool-augmented debaters + thinking display

**What:** Debaters in the trade analyzer now have access to research tools (web search, financial data) to strengthen arguments with live evidence. All `<think>` blocks from MiniMax are extracted and displayed as collapsible reasoning blocks in the frontend.

**Files:**
- `agent.py` — modified: added `thinking_callback` contextvar, `on_thinking` param to `run_agent`/`_run_agent_inner`, extract `<think>` content before stripping, set both contextvars around tool execution
- `tools/trade_analyzer.py` — modified: added `_llm_call_with_tools` mini agent loop (max 3 tool rounds, 90s timeout), `_get_debater_tool_schemas` (excludes output/meta/recursive tools), `_msg_to_dict`, `_truncate_tool_result` (3000 char cap), `_extract_and_strip_thinking`, thinking extraction in `_llm_call` (judge), updated prompts with tool-access instruction, wired `status_fn`/`thinking_fn` through all phases
- `api_chat.py` — modified: added `on_thinking` callback that queues `{"event": "thinking", ...}` SSE events, passes to `run_agent`
- `frontend/src/api.ts` — modified: added `onThinking` to `SSECallbacks`, parses `thinking` SSE event type
- `frontend/src/components/ThinkingBlock.tsx` — created: collapsible block with arrow toggle, italic label, pre-wrapped content area (max 300px scroll), border-left accent
- `frontend/src/components/ChatView.tsx` — modified: `thinkingBlocks` state + ref for stale closure safety, `onThinking` merges by source, attaches accumulated blocks to assistant message on done, renders in-progress blocks above status
- `frontend/src/components/MessageBubble.tsx` — modified: accepts `thinking` prop, renders `ThinkingBlock` components above message content
- `frontend/src/styles/index.css` — modified: added `.thinking-blocks`, `.thinking-block`, `.thinking-toggle`, `.thinking-arrow`, `.thinking-label`, `.thinking-content` styles

**Details:**
- Debaters use all data-fetching tools (19 tools) except generate_chart, generate_pdf, dispatch_subagents, analyze_trade_opportunity, lookup_data_sources, save_data_source
- Max 3 tool rounds per debater, then forced text-only on round 4
- Status shows individual tool calls: "Bull Analyst A (MiniMax) · Searching: web_search..."
- Judge stays on plain `_llm_call` with no tool access
- Thinking blocks appear in real-time during streaming, collapse when message finalizes
- Same-source thinking content is appended (merged) to avoid duplicate blocks

## 2026-02-18 — Streaming thinking display + auto MD/PDF reports for trade analysis

**What:** Replaced collapsible thinking blocks with a subtle streaming text display that flows smoothly during processing. Added automatic markdown + PDF report generation for every trade analysis, named `{stock_name}_{timestamp}.md/.pdf`.

**Files:**
- `frontend/src/components/ThinkingBlock.tsx` — rewritten: subtle streaming text with auto-scroll, muted opacity, click-to-expand/collapse, `streaming` prop for live mode
- `frontend/src/styles/index.css` — modified: replaced heavy `.thinking-block` styles with subtle `.thinking-stream` styles (low opacity, no borders, muted text)
- `frontend/src/components/ChatView.tsx` — modified: passes `streaming={true}` to in-progress thinking blocks
- `tools/trade_analyzer.py` — modified: added `_build_report_markdown` (structures debate into sections), `_generate_report` (saves MD + generates PDF via existing `generate_pdf`), returns `files` list in result, new Phase 5 after judge
- `agent.py` — modified: handles `result["files"]` (list) in addition to `result["file"]` (single) when extracting file paths from tool results

**Details:**
- Thinking text streams in at 55% opacity during processing, 70% while active streaming, rises to 80% on hover
- Historical thinking on completed messages starts collapsed, click header to expand
- Reports saved as `{stock_name}_{YYYYMMDD_HHMMSS}.md` and `.pdf` in `output/` dir
- MD report includes: verdict, all 4 opening arguments, all 4 rebuttals, data summary (first 5000 chars)
- PDF generated using existing `generate_pdf` tool then renamed to match naming convention
- Both files served via `/output/` static mount and appear as download links in chat

## 2026-02-18 — Stop generation button

**What:** Added ability to stop the AI mid-response and correct your message. Textarea stays enabled during generation.

**Files:**
- `frontend/src/components/ChatView.tsx` — modified: added `handleStop` (aborts SSE, removes optimistic user message, resets state), Send button swaps to red Stop button while sending, Enter while sending stops generation, textarea no longer disabled during sending
- `frontend/src/styles/index.css` — modified: added `.stop-btn` styles (red background)

**Details:**
- Stop aborts the SSE fetch, clears thinking blocks and status, removes the pending user message so the user can retype
- Textarea stays active during generation so the user can type their correction while waiting
- Enter during generation = stop; Enter again = send the corrected message
- Stop button uses `var(--error)` color to distinguish from Send

## 2026-02-18 — Data-driven debate prompts (remove emotional tone)

**What:** Rewrote all debate prompts and system messages to enforce strictly quantitative, data-only analysis. Eliminated advocacy framing, combative language, and emotional adjectives.

**Files:**
- `tools/trade_analyzer.py` — modified: rewrote `_BULL_OPENING`, `_BEAR_OPENING`, `_REBUTTAL`, `_JUDGE` prompts and all 3 system messages

**Details:**
- Bull/bear analysts reframed as "quantitative equity/risk analyst" instead of "buy-side/risk analyst building a case"
- Explicit ban on subjective adjectives: "禁止使用主观形容词" — no "强劲", "优秀", "令人担忧", "严重"
- Every claim must include a specific number or it's invalid
- Rebuttals reframed from "dismantle their points" to "examine data accuracy and completeness"
- Anti-combative language rule: no "他们忽略了"/"这是错误的", instead "该数据点需补充背景: [具体数据]"
- Both sides must acknowledge when opposing data is correct — no spinning
- Judge evaluates data accuracy/completeness, explicitly told to "disregard emotional language, rhetorical flourish, unsubstantiated predictions"
- System messages changed from "专业的金融分析师" to "量化金融分析师" with "仅基于数据分析" constraint

## 2026-02-18 — Executive summary phase + institutional-quality reports

**What:** Added Phase 5 (executive summary LLM call) after the judge verdict to synthesize the entire debate into a structured, fact-only summary. Rewrote report generation to produce institutional-standard MD/PDF with proper structure.

**Files:**
- `tools/trade_analyzer.py` — modified: added `_SUMMARY` prompt, `_run_summary` function (Phase 5), rewrote `_build_report_markdown` (no raw JSON, proper sections: exec summary → verdict → appendix with full arguments), updated `_generate_report` and `analyze_trade_opportunity` to include summary
- `tools/output.py` — modified: PDF renderer now handles `---` horizontal rules, numbered lists (`1. ...`), disclaimer footer on every page

**Details:**
- New Phase 5: executive summary LLM call produces structured output with: 执行摘要, 关键财务指标 table, 多方/空方核心论据, 争议焦点与数据分歧, 风险因素, 结论与建议
- Summary prompt enforces: every bullet must contain a specific number, no adjectives, 800-1200 words
- Report structure: exec summary up front (what a PM reads), verdict second, full debate in numbered appendix (A.1-A.8)
- Removed raw JSON data dump from report — data now lives only in the summary's key metrics table
- PDF footer: "AI-generated report. For reference only. Not investment advice." + page numbers
- Pipeline is now 6 phases: data collection → openings → rebuttals → judge → summary → report generation

## 2026-02-18 — UI Language Toggle (English / 中文)

**What:** Added a lightweight i18n system with a language toggle so users can switch the UI between English and Chinese.

**Files:**
- `frontend/src/i18n.tsx` — created: translations dict (~40 keys), `LanguageProvider` context, `useT()` hook, defaults to Chinese, persists choice in localStorage
- `frontend/src/main.tsx` — modified: wrapped app with `<LanguageProvider>`
- `frontend/src/pages/LoginPage.tsx` — modified: replaced hardcoded strings with `t(...)` calls
- `frontend/src/pages/ChatLayout.tsx` — modified: replaced debate modal strings with `t(...)`
- `frontend/src/components/Sidebar.tsx` — modified: replaced strings with `t(...)`, added language toggle button
- `frontend/src/components/ChatView.tsx` — modified: replaced strings with `t(...)`
- `frontend/src/components/AdminPanel.tsx` — modified: replaced strings with `t(...)`
- `frontend/src/components/ThinkingBlock.tsx` — modified: replaced "show"/"hide" with `t(...)`
- `frontend/src/components/ReferenceCard.tsx` — modified: replaced "References" with `t(...)`
- `frontend/src/styles/index.css` — modified: added `.lang-toggle` button styles

**Details:**
- No external i18n library — custom React context with ~40 translation keys for 2 languages
- Default language is Chinese (`zh`), persisted in `localStorage` under key `lang`
- Toggle button in sidebar footer shows "EN" when in Chinese mode, "中" when in English mode
- All user-facing strings translated: login, sidebar, chat, debate modal, thinking blocks, references, admin panel

## 2026-02-18 — Fix conversation isolation + add conversation summarization

**What:** Fixed multiple state management bugs causing conversations to interfere under concurrent load. Added automatic conversation summarization for long conversations.

**Files:**
- `tools/cache.py` — modified: added `asyncio.Lock` to protect global `_cache` dict mutations; `set_cached` is now async; `get_cached` no longer mutates dict without lock
- `accounts.py` — modified: `_user_locks` now stores `(lock, last_used_time)` tuples with TTL-based cleanup (1hr); added `get_conversation_summary()`, `save_conversation_summary()`, `load_messages_for_summarization()` for summarization support
- `tools/sources.py` — modified: added `fcntl` file locking (`LOCK_SH` for reads, `LOCK_EX` for writes) to prevent concurrent write corruption on `sources.json`
- `db.py` — modified: added `summary` (TEXT) and `summary_up_to` (INTEGER) columns to conversations table for persisting conversation summaries
- `agent.py` — modified: added `_maybe_summarize()` function and `_SUMMARIZE_PROMPT`; wired summarization into `_run_agent_inner` after loading messages and before prepending system prompt; imports new accounts functions

**Details:**
- **Cache fix**: The global `_cache` dict was shared across all concurrent requests. Dict mutations during `_evict_expired()` and `set_cached()` could corrupt under concurrent access. Now protected by `asyncio.Lock`. Cache keys remain user-agnostic (market data is the same for all users) — this is intentional.
- **User locks fix**: `_user_locks` dict grew unbounded. Now each entry tracks last-used time, and stale locks (unused >1hr, not currently held) are cleaned up every 5 minutes.
- **Sources fix**: `_load_sources`/`_save_sources` had a classic read-modify-write race condition. Two concurrent `save_data_source` calls could lose one write. Now uses `fcntl.flock` for exclusive write locking and shared read locking.
- **Conversation summarization**: When a conversation exceeds 30 user+assistant messages, older messages are summarized into a single dense paragraph via an LLM call. The summary is persisted in the `conversations.summary` column and prepended to the message list on future requests. Recent 10 messages are always kept unsummarized. Full history remains in the `messages` table untouched. Follows the same pattern as LangGraph checkpointers and OpenAI's conversation state API.

## 2026-02-20 — Add report_cache table schema

**What:** Added the `report_cache` table to `SCHEMA_SQL` in `db.py` to cache distilled financial report metadata and file paths.

**Files:**
- `db.py` — modified (appended `report_cache` table + lookup index to `SCHEMA_SQL`)

**Details:**
- Table stores one row per (stock_code, report_type, report_year) with a UNIQUE constraint on that triple
- Columns: `id`, `stock_code` (CHAR 6), `report_type` (yearly/q1/mid/q3), `report_year` (SMALLINT), `report_date` (filing date string), `title`, `filepath` (relative path to distilled .md), `source_url`, `created_at`
- `idx_report_cache_lookup` index added on (stock_code, report_type, report_year) for fast lookups
- No migration tooling needed; `init_db()` applies the schema via `CREATE TABLE IF NOT EXISTS` on next server start

## 2026-02-20 — TOC parser and chapter classifier for CN annual reports

**What:** Added constants, regex patterns, `_should_keep_chapter()`, and `_parse_toc()` to `tools/sina_reports.py` so callers can filter boilerplate sections from Chinese annual reports before sending text to an LLM.

**Files:**
- `tools/sina_reports.py` — modified (added constants and two functions after `_extract_key_sections`)

**Details:**
- `_KEEP_CHAPTER_KEYWORDS` and `_SKIP_CHAPTER_KEYWORDS` drive classification; keep-keywords are checked first so mixed-title chapters like "公司简介和主要财务指标" are correctly retained
- `_TOC_ENTRY_RE` matches TOC lines of the form "第N节 Title ...... pagenum"
- `_CHAPTER_HEADING_RE` matches chapter headings in body text (available for future use)
- `_parse_toc()` scans the first 400 lines; returns `[]` when no TOC is detected (callers treat that as "no filter")
- Unknown chapters default to keep (True) to avoid accidental data loss

## 2026-02-20 — Add TOC-based section filter for report pre-processing

**What:** Added `_filter_sections_by_toc()` to `tools/sina_reports.py` to physically remove skip-chapters from report text using TOC-detected chapter boundaries.

**Files:**
- `tools/sina_reports.py` — modified (added `_filter_sections_by_toc` immediately after `_parse_toc`)

**Details:**
- Scans body lines from position 50 onwards to skip the TOC block itself
- Matches chapter headings via `_CHAPTER_HEADING_RE` and looks up keep/skip status from the parsed chapters list using the first 6 chars of each chapter name
- Collects kept chapter blocks into a result list; falls back to full original text if no boundaries found or if input is large (>10000 chars) and filtered output is suspiciously small (<1000 chars)
- Safety threshold uses `len(text) > 10000 and len(filtered) < 1000` so small/test inputs are not incorrectly fallen back

## 2026-02-20 — Integrate TOC-based pre-filter into _prepare_for_grok

**What:** Wired `_parse_toc()` and `_filter_sections_by_toc()` as Step 1 in `_prepare_for_grok()`, so skip-chapters (重要提示, 公司治理, 环境社会责任, etc.) are dropped before deduplication and keyword extraction.

**Files:**
- `tools/sina_reports.py` — modified (_prepare_for_grok body replaced)

**Details:**
- New Step 1 calls `_parse_toc(full_text)`; if chapters are found, calls `_filter_sections_by_toc()` and logs the character reduction percentage and chapter count
- If no TOC is detected, falls back to full text with an info log message
- Step 2 (deduplication) and Step 3 (keyword-section extraction + hard cap) are unchanged in logic, but now operate on already-filtered text
- TOC filtering typically removes 40–60% of annual report text before the remaining steps run

## 2026-02-20 — Improve Grok prompt for structured Option-B report distillation

**What:** Replaced `_grok_summarize_report()` in `tools/sina_reports.py` with an Option-B prompt that produces both a full narrative and preserved financial tables as Markdown tables.

**Files:**
- `tools/sina_reports.py` — modified (replaced `_grok_summarize_report` function body)

**Details:**
- New docstring clarifies the function returns a structured Markdown string (Option B: narrative + tables).
- System prompt now explicitly instructs Grok to preserve all financial tables in Markdown table format and not omit any figures or ratios.
- User prompt restructured into five labelled sections: 核心财务指标 (with a table), 管理层讨论与分析摘要 (including segmented revenue tables), 财务报表关键数据 (P&L, balance sheet, cash flow, industry-specific KPIs), 风险因素, and 亮点与异常发现.
- Added a pre-processing context block ("阅读策略") explaining which report sections were retained vs. filtered.
- `focus_note` label changed from "请特别关注以下指标" to "**重点关注指标**" for Markdown emphasis.
- Division-by-zero guard added: `max(len(full_text), 1)` in the reduction-percentage log line.

## 2026-02-20 — Add cache path helper and report year extraction

**What:** Added `_get_cache_path()` and `_extract_report_year()` helper functions to `tools/sina_reports.py`, along with the `_REPORTS_BASE` path constant and `pathlib.Path` import, to support future report caching.

**Files:**
- `tools/sina_reports.py` — modified (added `from pathlib import Path`, `_REPORTS_BASE`, `_get_cache_path()`, `_extract_report_year()`)

**Details:**
- `_REPORTS_BASE = Path("output/reports")` defines the root cache directory.
- `_get_cache_path(stock_code, report_year, report_type)` returns a structured path: `output/reports/{stock_code}/{year}_{code}_{type}.md`.
- `_extract_report_year(title, report_date)` parses the 4-digit year from a Chinese report title (e.g. `2024年`) and falls back to the year portion of `report_date` if no year is found in the title.
- Both functions inserted after `_SKIP_CHAPTER_KEYWORDS` block, before `_TOC_ENTRY_RE`.

## 2026-02-20 — Add report cache DB lookup and write helpers

**What:** Added `_check_report_cache()` and `_save_report_cache()` async functions to `tools/sina_reports.py` for DB-backed caching of distilled annual/quarterly reports.

**Files:**
- `tools/sina_reports.py` — modified (two async functions inserted after `_extract_report_year`)

**Details:**
- `_check_report_cache` queries the `report_cache` table by `(stock_code, report_type, report_year)` and validates the cached filepath exists on disk before returning it; returns `None` on any miss or error.
- `_save_report_cache` upserts a row into `report_cache`, updating `filepath`, `report_date`, `title`, and `source_url` on conflict; silently swallows exceptions so cache failures never break the main flow.
- Both functions import `db.get_pool` lazily inside the function body to avoid circular imports at module load time.

## 2026-02-20 — Wire report cache into fetch_company_report

**What:** Replaced `fetch_company_report()` with a new version that adds a fast cache path (DB check before any network fetch) and saves distilled reports to disk + DB on cache miss.

**Files:**
- `tools/sina_reports.py` — modified (fetch_company_report replaced entirely)

**Details:**
- Fast path: calls `_extract_report_year` + `_check_report_cache`; on hit, reads the local `.md` file and returns immediately with `summarized_by: "cache"`
- Slow path (cache miss): fetches detail page, extracts text/tables, calls `_grok_summarize_report`, builds a Markdown document with a metadata header, writes it via `_get_cache_path` + `_save_report_cache`
- Return dict now includes `cache_path` field on both paths
- `pdf_url` field retained in slow-path return; omitted on cache-hit path (not re-parsed)

## 2026-02-20 — Annual report distillation and cache system

**What:** Added TOC-aware pre-filtering, structured Grok prompt (Option B), and a local Markdown cache for distilled annual reports — eliminating redundant Sina/Grok fetches and fixing the 80k-char truncation that was cutting off 第十节财务报告.

**Files:**
- `db.py` — modified: added `report_cache` table and index to SCHEMA_SQL
- `tools/sina_reports.py` — modified: added `_KEEP/SKIP_CHAPTER_KEYWORDS`, `_TOC_ENTRY_RE`, `_CHAPTER_HEADING_RE`, `_should_keep_chapter`, `_parse_toc`, `_filter_sections_by_toc`, `_get_cache_path`, `_extract_report_year`, `_check_report_cache`, `_save_report_cache`; replaced `_prepare_for_grok`, `_grok_summarize_report`, `fetch_company_report`
- `output/reports/` — created at runtime per-request via `Path.mkdir(parents=True, exist_ok=True)`
- `docs/plans/2026-02-20-report-cache.md` — created: implementation plan

**Details:**
- TOC filter parses the 目录 block (first 400 lines) and removes skip-chapters (公司治理, 环境社会责任, etc.) by chapter name keywords before deduplication — typically 40–60% reduction for yearly reports
- Keep-keywords checked before skip-keywords so "公司简介和主要财务指标" is correctly kept
- Grok prompt now requests 5-section structured Markdown with full financial tables preserved (Option B)
- `fetch_company_report` gains a fast path: cache hit → read local .md file, no HTTP/Grok calls
- Cache stored at `output/reports/{stock_code}/{year}_{code}_{type}.md`; DB entry in `report_cache` table
- All cache operations are best-effort (silently fail, never crash the fetch)
- 第十节财务报告 (previously truncated at 80k chars) now reaches Grok intact

## 2026-02-21 — Voice input (STT) on main chat page

**What:** Added a mic button to the chat input area that records audio, sends it to Whisper, and fills the textarea with the transcription.

**Files:**
- `api_chat.py` — added `POST /api/chat/stt` endpoint (authenticated, calls Whisper whisper-1, zh language)
- `frontend/src/components/ChatView.tsx` — added `voiceState`, `handleVoiceToggle`, and mic button in `input-area`
- `frontend/src/styles/index.css` — added `.mic-btn` and `.mic-btn.recording` styles with pulse animation
- `frontend/dist/` — rebuilt

**Details:**
- Mic button sits between textarea and send button; shows 🎤 / ⏹ / … states
- Recording stops on second click; transcription fills textarea for user review before sending
- Button disabled during transcription or while agent is running

## 2026-02-21 — STT stock resolution pipeline shared + wired into production

**What:** Extracted GPT extraction + fuzzy pinyin matching into a shared module; wired it into the production STT endpoint so the main app resolves stock names on voice input.

**Files:**
- `tools/stt_stocks.py` — created; shared module with `to_pinyin`, `levenshtein`, `extract_and_find_stocks`
- `api_chat.py` — STT endpoint now calls full pipeline, returns `matched_stocks` alongside `text`
- `tests/test_whisper_web.py` — refactored to import from `tools/stt_stocks` instead of duplicating logic
- `frontend/src/components/ChatView.tsx` — voice handler appends confident matches (distance ≤ 1) to textarea text
- `frontend/dist/` — rebuilt

**Details:**
- Confident matches (edit distance ≤ 1) are appended as e.g. `风语筑(300873.SZ)` so agent gets exact stock code
- Higher-distance matches are returned from API but not auto-appended (user can still edit textarea)

## 2026-02-21 — Unified theme + comfort redesign

**What:** Aligned the landing page and main app to share the same visual identity. Refined the main app with a "comfort touch" — warmer message bubbles, better typography, sidebar brand header, and softer styling throughout.

**Files:**
- `frontend/src/styles/index.css` — full redesign: Google Fonts import, DM Sans UI font, softer message bubble shadows, refined spacing, sidebar brand, accent-gold status dots, warmer empty state
- `frontend/src/styles/landing.css` — warmed all dark backgrounds from cold #09080a → #0c0907 family (warm dark brown), features section and footer updated to match
- `frontend/src/components/Sidebar.tsx` — added `.sidebar-brand` block with "金融研究智能体" in Noto Serif SC gold (matching landing nav logo); converted sidebar-links from inline styles to CSS class

**Details:**
- Both pages now share Playfair Display + Noto Serif SC + DM Sans font trio (same @import in both CSS files)
- Sidebar brand "金融研究智能体" in Noto Serif SC creates direct visual continuity with landing page logo
- Assistant messages: removed harsh border, replaced with subtle box-shadow for paper-like warmth
- User messages: more padding, softer rounded corners (14px)
- Input textarea: Georgia/Noto Serif SC for writing feel; focus ring instead of just border
- Status dots now use --accent-gold (#c9a227) matching landing page accent
- Debate modal: warmer backdrop, softer border-radius
- Added `--accent-gold` and `--shadow-soft` CSS variables for consistency

## 2026-02-21 — Dark/light theme toggle

**What:** Added a persistent dark/light theme toggle to the main app and landing page.

**Files:**
- `frontend/src/i18n.tsx` — added `ThemeProvider` + `useTheme` hook; applies `data-theme` attribute to `<html>` and persists to localStorage
- `frontend/src/main.tsx` — wrapped app in `ThemeProvider`
- `frontend/src/styles/index.css` — added `:root[data-theme="dark"]` CSS variable overrides + specific dark mode rules for hardcoded `#fff` inputs
- `frontend/src/components/Sidebar.tsx` — added 🌙/☀ toggle button in the sidebar footer
- `frontend/src/pages/LandingPage.tsx` — added 🌙/☀ toggle button in the landing nav (sets preference before login)

**Details:**
- Dark theme reuses the same warm dark palette as the landing page (#0c0907 background, #c9a227 gold accent)
- Preference persists in localStorage as "theme"
- `data-theme="dark"` on `<html>` allows CSS variable overrides without JS class manipulation
- Hardcoded `#fff` input backgrounds are overridden for dark mode via `[data-theme="dark"]` selectors

## 2026-02-22 — CSS: mode badge, header indicator, and mode picker styles

**What:** Added CSS styles for three new UI elements supporting per-conversation mode selection.

**Files:**
- `frontend/src/styles/index.css` — modified (added `position: relative` to `.chat-view`; appended styles for `.conv-mode-badge`, `.mode-indicator`, `.mode-indicator.debate`, `.mode-picker-overlay`, `.mode-picker`, `.mode-picker-prompt`, `.mode-picker-buttons`, `.mode-picker-btn`, `.mode-picker-btn.debate`, `.mode-picker-btn.normal`, `.mode-picker-cancel`)

**Details:**
- `.chat-view` now has `position: relative` so the `.mode-picker-overlay` (`position: absolute; inset: 0`) has a positioned ancestor
- `.conv-mode-badge` is a small inline tag in the sidebar conversation list for debate-mode conversations
- `.mode-indicator` is a thin strip below the chat header showing the current conversation mode; `.mode-indicator.debate` applies a warm gold tint
- `.mode-picker-*` is an inline overlay prompt that appears in the chat area on first send, asking the user to choose debate vs normal mode

## 2026-02-22 — Conversation mode indicator

**What:** Added per-conversation debate/normal mode badge in sidebar and header strip in chat area; follow-up messages in debate conversations prompt for mode choice.

**Files:**
- `db.py` — added `mode TEXT DEFAULT 'normal'` column migration
- `accounts.py` — `_create_conversation` and `new_conversation` accept `mode` param
- `api_chat.py` — `list_conversations` returns `mode`; `create_conversation` accepts mode body
- `frontend/src/api.ts` — `createConversation` sends mode in request body
- `frontend/src/pages/ChatLayout.tsx` — derives `activeMode`; passes to Sidebar + ChatView; renders mode strip
- `frontend/src/components/Sidebar.tsx` — renders `[辩论]`/`[Debate]` badge per conversation
- `frontend/src/components/ChatView.tsx` — intercepts send in debate convos with messages; shows mode picker
- `frontend/src/styles/index.css` — styles for badge, mode strip, and mode picker overlay

**Details:**
- Mode stored in DB; all existing conversations default to 'normal'
- Debate conversations created with mode='debate' upfront (not inferred from title)
- Mode picker only triggers in debate conversations with existing messages; first message in any conversation sends directly
- Cancel in mode picker restores the typed message to input

## 2026-02-23 — Async OHLCV ingest with rich progress

**What:** Rewrote ingest_ohlcv.py to use asyncio + ProcessPoolExecutor for parallel BaoStock fetching and asyncpg for async DB writes, with a rich progress bar.

**Files:**
- `data/ingest_ohlcv.py` — rewritten: asyncio main loop, ProcessPoolExecutor workers (each with own BaoStock login), asyncpg pool replaces psycopg2, rich Progress bar with ETA/count/rows
- `requirements.txt` — added `rich`

**Details:**
- CONCURRENCY env var (default 3) controls parallel BaoStock workers; each subprocess has its own bs.login() session
- Main process only logs into BaoStock to fetch the stock list, then logs out; workers handle all data fetching
- Removed time.sleep(0.1) per stock; rate limiting now implicit via semaphore + process count
- Progress bar shows: N/M complete, bar, %, elapsed, ETA, current stock + row count
- ON CONFLICT DO NOTHING preserved for safe re-runs after interruption

## 2026-02-23 — OpenBB global market data tool

**What:** Added fetch_global_market_data tool wrapping the full OpenBB Platform API for on-demand access to global financial data.

**Files:**
- `tools/openbb_data.py` — created: tool implementation + comprehensive schema covering all OpenBB namespaces
- `tools/__init__.py` — registered new tool in TOOL_SCHEMAS and TOOL_MAP
- `requirements.txt` — added openbb

**Details:**
- Single dynamic tool: command string (e.g. "equity.price.historical") + params dict
- OpenBB initialized once at import via lru_cache; FRED_API_KEY and FMP_API_KEY injected via direct attribute assignment on obb.user.credentials
- Covers: equity (prices, fundamentals, filings), economy (GDP, CPI, calendar), fixed income (yield curve, treasury rates), forex, crypto, ETF, index, options, news, SEC/CFTC regulators
- Primary providers: fmp (equity, ETF, index, forex, crypto), fred/federal_reserve (rates, fixed income), oecd (macro/GDP), sec (filings)
- yfinance excluded (blocked on server); all providers confirmed working
- 60s timeout, 5min cache, 150-row / 12k-char output cap

## 2026-02-23 — Update planning and system prompts for TA strategy tools

**What:** Added TA strategy tool entries to the planning prompt tool table and replaced the old K-line guidance bullet with a step-by-step TA workflow; added citation mappings for the new tools in the system prompt.

**Files:**
- `config.py` — modified (planning prompt table, TA guidance section, system prompt citation mapping)

**Details:**
- Tool table: added rows for `lookup_ta_strategy`, `save_ta_strategy`, `update_ta_strategy`, `run_ta_script` after `fetch_ohlcv`.
- TA guidance: replaced single bullet with a 4-step workflow covering knowledge-base lookup, optional web_search + save, OHLCV fetch, and pandas-ta script execution via `run_ta_script`.
- Citation mapping: added `run_ta_script → https://pypi.org/project/pandas-ta/` and a no-citation note for the three knowledge-base tools.

## 2026-02-23 — TA Strategy System

**What:** Added TA strategy knowledge base and sandboxed code-execution tool for pandas-ta + Plotly chart generation.

**Files:**
- `db.py` — modified: added `ta_strategies` table + FTS index to SCHEMA_SQL
- `tools/ta_strategies.py` — created: lookup_ta_strategy, save_ta_strategy, update_ta_strategy tools
- `tools/ta_executor.py` — created: run_ta_script tool (subprocess sandbox, 3-attempt retry via MiniMax)
- `tools/__init__.py` — modified: registered 4 new tools in TOOL_SCHEMAS and TOOL_MAP
- `config.py` — modified: updated planning prompt with TA workflow guidance; updated system prompt citation mapping
- `frontend/src/components/MessageBubble.tsx` — modified: HTML chart opens in new tab
- `frontend/src/components/ReportsPanel.tsx` — modified: html filter tab + open-in-tab handler
- `structure.md` — modified: documented new tools and ta_strategies DB table
- `requirements.txt` — modified: added pandas-ta, plotly
- `tests/test_ta_strategies.py` — created: 5 unit tests (mocked DB)
- `tests/test_ta_executor.py` — created: 5 unit tests (mocked subprocess + MiniMax)

**Details:**
- Strategies stored in myaiagent Postgres (not marketdata DB)
- Import sandbox uses frame inspection (sys._getframe) to only restrict user script imports, not library internals
- Subprocess timeout: 30 seconds; asyncio.to_thread prevents blocking uvicorn event loop
- On failure: MiniMax rewrites script, up to 3 total attempts
- run_ta_script returns {"file": path} — picked up by agent.py line 492 automatically
- Strategy alterations via update_ta_strategy (patches fields, never deletes)
- Plotly .html charts open in new browser tab from both chat and ReportsPanel

## 2026-02-23 — Add HTML Plotly chart support to frontend (Task 3b)

**What:** Updated MessageBubble and ReportsPanel to render interactive Plotly HTML charts, and added the corresponding i18n key.

**Files:**
- `frontend/src/components/MessageBubble.tsx` — modified: added `.html` case that renders a link opening the chart in a new tab
- `frontend/src/components/ReportsPanel.tsx` — modified: renamed `handleDownload` to `handleOpen`, added html case that opens chart in new tab, added "html" filter tab, updated icon to show 📊 for html files
- `frontend/src/i18n.tsx` — modified: added `"reports.charts_interactive"` translation key (en: "Charts", zh: "互动图表")

**Details:**
- HTML charts open via `window.open` with the token as a query param (no Authorization header needed since the file is served directly).
- The new filter tab appears after "Markdown" in ReportsPanel.
- TypeScript check (`tsc --noEmit`) passed with zero errors.
