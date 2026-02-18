# Changes

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
