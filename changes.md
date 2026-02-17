# Changes

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
