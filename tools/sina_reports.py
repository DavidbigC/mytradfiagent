"""Fetch company financial reports from Sina Finance bulletin pages.

Supports yearly, Q1, mid-year (Q2), and Q3 reports for Chinese A-share stocks.
"""

import asyncio
import re
import logging
import httpx
import fitz  # pymupdf
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from config import GROQ_API_KEY, GROQ_BASE_URL, GROQ_REPORT_MODEL

logger = logging.getLogger(__name__)


# Groq client for PDF report reading (113k context window, chunked parallel)
_groq_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL) if GROQ_API_KEY else None
)


SINA_BASE = "https://vip.stock.finance.sina.com.cn"

# Bulletin listing URL patterns by report type
REPORT_URLS = {
    "yearly": "/corp/go.php/vCB_Bulletin/stockid/{code}/page_type/ndbg.phtml",
    "q1":     "/corp/go.php/vCB_BulletinYi/stockid/{code}/page_type/yjdbg.phtml",
    "mid":    "/corp/go.php/vCB_BulletinZhong/stockid/{code}/page_type/zqbg.phtml",
    "q3":     "/corp/go.php/vCB_BulletinSan/stockid/{code}/page_type/sjdbg.phtml",
}

FETCH_COMPANY_REPORT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_company_report",
        "description": (
            "Fetch and analyse a financial report for a Chinese A-share company (Sina Finance). "
            "Uses the stock's historical DB financials to generate targeted research questions, "
            "then answers those questions from a focused chunk of the actual report. "
            "Returns a structured Markdown analysis with question-by-question findings and an "
            "investment conclusion (看多/看空/中性). "
            "PRIORITY: Always call with the most recent quarterly report first (q3 > mid > q1). "
            "If yearly context is also needed, call this tool TWICE in parallel — once for the quarterly "
            "and once for yearly. Never call with yearly alone. "
            "IMPORTANT: Always pass focus_keywords derived from the user's question. "
            "E.g. banks: ['不良率', '净息差', '拨备覆盖率']; tech: ['研发', '毛利率', '增长']; "
            "retail: ['同店', '库存', '门店', '毛利']."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '002028', '600036', '601398'",
                },
                "report_type": {
                    "type": "string",
                    "enum": ["yearly", "q1", "mid", "q3"],
                    "description": "Report type: yearly=年报, q1=一季报, mid=中报, q3=三季报",
                },
                "focus_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Keywords derived from the user's question to focus extraction on. "
                        "These are merged with base financial markers. Pass terms the user "
                        "explicitly asked about, e.g. ['不良率', '净息差', '拨备覆盖率'] for "
                        "bank asset quality analysis."
                    ),
                },
            },
            "required": ["stock_code", "report_type"],
        },
    },
}


def _decode_response(resp: httpx.Response) -> str:
    """Decode response with Chinese encoding detection."""
    raw = resp.content
    lower_head = raw[:2000].lower()
    if b"charset=gb" in lower_head or b'charset="gb' in lower_head:
        return raw.decode("gbk", errors="replace")
    if resp.encoding and resp.encoding.lower() not in ("utf-8", "ascii"):
        return raw.decode(resp.encoding, errors="replace")
    return resp.text


async def _fetch_page(url: str) -> str:
    """Fetch a page with Chinese encoding support."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": SINA_BASE,
        })
        resp.raise_for_status()
    return _decode_response(resp)


def _parse_bulletin_list(html: str) -> list[dict]:
    """Parse bulletin listing page to extract report links.

    Returns list of {"date": "2025-04-19", "title": "...", "url": "/corp/view/..."}
    """
    soup = BeautifulSoup(html, "html.parser")
    reports = []

    # Find all links to report detail pages
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "vCB_AllBulletinDetail" not in href:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue

        # Find the date — usually in a preceding text node or sibling
        date = ""
        prev = a.previous_sibling
        if prev and isinstance(prev, str):
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", prev)
            if date_match:
                date = date_match.group(1)
        if not date:
            parent_text = a.parent.get_text() if a.parent else ""
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", parent_text)
            if date_match:
                date = date_match.group(1)

        # Normalize URL
        if href.startswith("/"):
            href = SINA_BASE + href
        elif not href.startswith("http"):
            href = SINA_BASE + "/" + href

        reports.append({"date": date, "title": title, "url": href})

    return reports


def _extract_key_sections(text: str, extra_keywords: list[str] | None = None) -> str:
    """Extract key financial sections from a long report text.

    Focuses on: financial highlights, income statement, balance sheet summary,
    key metrics, dividend info, business overview.
    """
    # Key section markers (Chinese)
    section_markers = [
        "主要财务数据", "主要会计数据", "财务摘要",
        "营业收入", "营业总收入", "净利润", "归属于",
        "每股收益", "基本每股",
        "资产负债", "总资产", "净资产",
        "经营活动", "现金流",
        "分红", "派息", "股利",
        "主营业务", "业务概要", "经营情况",
        "研发投入", "研发费用",
        # Revenue composition / segment breakdown
        "分行业", "分产品", "分地区", "分业务",
        "收入构成", "收入结构", "营收构成", "营收结构",
        "业务收入", "各业务", "各板块",
        "利息净收入", "手续费", "佣金", "投资收益",
        "经营情况讨论与分析", "管理层讨论",
        "行业格局", "竞争", "市场地位",
        # Bank-specific metrics
        "不良贷款", "不良率", "净息差", "拨备覆盖率", "拨贷比",
        "贷款总额", "存款总额", "贷款余额", "存款余额",
        "资产质量", "核心一级资本", "资本充足率",
        "净利息收入", "净利差", "利息支出", "利息收入",
        "信用减值", "贷款减值", "拨备计提",
    ]

    if extra_keywords:
        section_markers = section_markers + [k for k in extra_keywords if k not in section_markers]

    lines = text.split("\n")
    kept_lines = []
    in_section = False
    section_lines = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if in_section:
                kept_lines.append("")
            continue

        # Check if this line starts/contains a key section
        is_marker = any(m in stripped for m in section_markers)

        if is_marker:
            in_section = True
            section_lines = 0
            kept_lines.append(stripped)
        elif in_section:
            kept_lines.append(stripped)
            section_lines += 1
            if section_lines > 150:  # Limit per section
                in_section = False
        else:
            # Also keep lines with numbers that look like financial data
            if re.search(r"[\d,]+\.\d{2}", stripped) and len(stripped) < 200:
                kept_lines.append(stripped)

    result = "\n".join(kept_lines)

    # If we got too little from section extraction, fall back to full text
    if len(result) < 500:
        result = text

    return result


# Keywords that identify financially important chapter names
_KEEP_CHAPTER_KEYWORDS = [
    "主要财务指标", "财务指标", "会计数据", "财务数据", "财务摘要", "财务概要",
    "管理层讨论", "经营情况", "经营分析", "管理层报告",
    "财务报告", "财务报表", "审计报告",
    "业务综述", "主营业务",
    "风险管理", "各类风险",
]

# Keywords that identify boilerplate/governance chapters to skip
_SKIP_CHAPTER_KEYWORDS = [
    "重要提示", "目录", "释义", "备查",
    "公司简介", "公司概况",
    "公司治理",
    "环境", "社会责任",
    "重要事项",
    "优先股",
    "债券相关",
    "股份变动", "股东情况",
    "致辞", "致词",  # board/president speeches (e.g. 董事会致辞, 行长致辞)
]


def _extract_report_year(title: str, report_date: str) -> int:
    """Extract the reporting period year from report title or filing date.

    Title like '招商银行2024年年度报告' → 2024
    Title like '某公司2024年三季度报告' → 2024
    Falls back to the year of report_date if no year found in title.
    """
    m = re.search(r"(\d{4})年", title)
    if m:
        return int(m.group(1))
    if report_date and len(report_date) >= 4:
        return int(report_date[:4])
    return 2024  # should never reach here


# Regex to match TOC entries with 第X章/节 prefix.
# NOTE: real reports have NO space between 章/节 and the title:
#   "第一章公司简介 ...... 9"  (not "第一章 公司简介 ...... 9")
# So \s* (zero or more) is required here, not \s+.
_TOC_ENTRY_RE = re.compile(
    r"^第[一二三四五六七八九十百]+[章节]\s*(.+?)[\s\.·。…]+\d+\s*$"
)

# Regex to match plain TOC entries without 第X章 prefix, within the 目录 block.
# e.g. "重要提示 ...... 1", "董事会致辞 ...... 5", "行长致辞 ...... 7"
# Excludes sub-entries starting with Chinese numerals (一、二、) or brackets (（一）).
_TOC_PLAIN_ENTRY_RE = re.compile(
    r"^([^\d\s（(一二三四五六七八九十].{1,25}?)[\s\.·。…]{3,}\d+\s*$"
)

# Regex to detect chapter headings in the body text.
# NOTE: same no-space format as TOC — "第一章公司简介" not "第一章 公司简介".
# Match any line starting with 第X章 or 第X节 (space after is optional).
_CHAPTER_HEADING_RE = re.compile(r"^第[一二三四五六七八九十百]+[章节]")


def _should_keep_chapter(name: str) -> bool:
    """Classify a chapter by name: True = financially relevant, False = skip.

    Keep-keywords are checked before skip-keywords so that chapters like
    "公司简介和主要财务指标" (contains both) are correctly kept.
    """
    if any(kw in name for kw in _KEEP_CHAPTER_KEYWORDS):
        return True
    if any(kw in name for kw in _SKIP_CHAPTER_KEYWORDS):
        return False
    return True  # unknown chapters: keep rather than risk losing data


def _parse_toc(text: str) -> list[dict]:
    """Parse the table of contents from a report.

    Strategy:
    1. Find the '目录' marker in the first 600 lines to anchor the TOC block.
    2. Parse up to 120 lines after the marker using two patterns:
       - 第X章/节 entries (e.g. "第一章公司简介 ...... 9")
       - Plain entries without prefix (e.g. "重要提示 ...... 1",
         "董事会致辞 ...... 5") — only when the 目录 anchor was found
    3. If no 目录 marker found, fall back to scanning the first 400 lines
       with just the 第X章/节 pattern.

    Returns [] if nothing is detected (callers treat [] as "no filter").
    """
    lines = text.split("\n")

    # Step 1: Find the 目录 marker
    toc_start = -1
    for i, line in enumerate(lines[:600]):
        stripped = line.strip()
        if stripped in ("目录", "目  录", "目   录"):
            toc_start = i + 1
            break

    # Step 2: Choose search range
    if toc_start >= 0:
        search_lines = lines[toc_start: toc_start + 120]
        use_plain = True
    else:
        search_lines = lines[:400]
        use_plain = False

    chapters = []
    for line in search_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Pattern 1: 第X章/节 entries
        m = _TOC_ENTRY_RE.match(stripped)
        if m:
            name = re.sub(r"[\s（(）)、，,。\.…·]+$", "", m.group(1).strip())
            chapters.append({"name": name, "keep": _should_keep_chapter(name)})
            continue

        # Pattern 2: plain entries (only within an anchored 目录 block)
        if use_plain:
            m2 = _TOC_PLAIN_ENTRY_RE.match(stripped)
            if m2:
                name = m2.group(1).strip()
                chapters.append({"name": name, "keep": _should_keep_chapter(name)})

    return chapters


def _filter_sections_by_toc(text: str, chapters: list[dict]) -> str:
    """Remove skip-chapters from report text using TOC-detected chapter boundaries.

    Scans lines from position 50 onwards (skipping the TOC block itself) for
    chapter headings, assigns each block to a chapter, and discards skip-chapters.

    Returns the original text unchanged if no chapter boundaries are found
    (safe fallback — better to send too much than too little).
    """
    if not chapters:
        return text

    lines = text.split("\n")
    boundaries: list[tuple[int, bool]] = []  # (line_index, keep)

    # Search body text (skip first 50 lines = TOC area)
    for i, line in enumerate(lines[50:], start=50):
        stripped = line.strip()
        if not _CHAPTER_HEADING_RE.match(stripped):
            continue
        # Match to known chapter by checking if any chapter name starts this line
        keep = True  # default
        for ch in chapters:
            # Compare first 6 chars of chapter name — distinctive enough
            if ch["name"][:6] and ch["name"][:6] in stripped:
                keep = ch["keep"]
                break
        boundaries.append((i, keep))

    if not boundaries:
        return text  # no chapter headings found — return unchanged

    result: list[str] = []
    for idx, (pos, keep) in enumerate(boundaries):
        next_pos = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        if keep:
            result.extend(lines[pos:next_pos])

    filtered = "\n".join(result)
    # Safety: if filter removed too aggressively, fall back to original
    if len(text) > 10000 and len(filtered) < 1000:
        logger.warning("TOC filter produced <1000 chars — falling back to full text")
        return text
    return filtered

def _extract_pdf_link(html: str) -> str | None:
    """Extract PDF download link from report detail page."""
    # Pattern: file.finance.sina.com.cn/.../*.PDF
    match = re.search(r'(https?://file\.finance\.sina\.com\.cn[^\s"\'<>]+\.PDF)', html, re.IGNORECASE)
    if match:
        return match.group(1)
    # Also try without protocol
    match = re.search(r'(//file\.finance\.sina\.com\.cn[^\s"\'<>]+\.PDF)', html, re.IGNORECASE)
    if match:
        return "https:" + match.group(1)
    return None


FETCH_SINA_PROFIT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_sina_profit_statement",
        "description": (
            "Fetch the detailed profit statement (利润表) for a Chinese A-share stock from Sina Finance. "
            "Returns quarterly income data for the given year: revenue, interest income/expense, "
            "fee income, investment income, operating costs, operating profit, net profit, EPS, etc. "
            "Useful when EastMoney financials are insufficient or you need Sina's format."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600000', '002028'",
                },
                "year": {
                    "type": "integer",
                    "description": "Year to fetch, e.g. 2025, 2024. Defaults to current year.",
                },
            },
            "required": ["stock_code"],
        },
    },
}


async def fetch_sina_profit_statement(stock_code: str, year: int | None = None) -> dict:
    """Fetch structured profit statement from Sina Finance for a given year."""
    from datetime import datetime as _dt
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    if year is None:
        year = _dt.now().year

    url = f"https://money.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/{year}/displaytype/4.phtml"

    try:
        html = await _fetch_page(url)
    except Exception as e:
        return {"error": f"Failed to fetch profit statement: {e}", "url": url}

    soup = BeautifulSoup(html, "html.parser")

    # Find the main data table
    table = soup.find("table", id="ProfitStatementNewTable0")
    if not table:
        # Fallback: find the largest table
        tables = soup.find_all("table")
        table = max(tables, key=lambda t: len(t.find_all("tr")), default=None)

    if not table:
        return {"error": "Could not find profit statement table", "url": url}

    # Parse the table
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells and any(c for c in cells):
            rows.append(cells)

    if not rows:
        return {"error": "Table found but contains no data", "url": url}

    # First row is usually the header (report dates)
    headers = rows[0] if rows else []
    data_rows = []
    for row in rows[1:]:
        if len(row) >= 2:
            data_rows.append({"item": row[0], "values": row[1:]})

    return {
        "stock_code": code,
        "year": year,
        "url": url,
        "headers": headers,
        "data": data_rows,
        "row_count": len(data_rows),
    }


def _prepare_report_text(full_text: str, focus_keywords: list[str] | None = None, max_chars: int = 80_000) -> str:
    """Reduce input size before sending to LLM without losing financial data.

    Steps:
    1. Parse TOC and drop skip-chapters (重要提示, 公司治理, 环境社会责任, etc.)
       This alone typically removes 40–60% of text from annual reports.
    2. Deduplicate lines (repeated headers, company names, date stamps).
    3. If still over max_chars, apply keyword-section extraction then hard-cap.
    """
    # Step 1: TOC-based section filter
    chapters = _parse_toc(full_text)
    if chapters:
        text = _filter_sections_by_toc(full_text, chapters)
        logger.info(
            f"TOC filter: {len(full_text):,} → {len(text):,} chars "
            f"({100 - len(text) * 100 // max(len(full_text), 1)}% reduction, "
            f"{len(chapters)} chapters parsed)"
        )
    else:
        text = full_text
        logger.info("TOC not detected — using full text")

    # Step 2: Deduplicate lines
    seen: set[str] = set()
    deduped: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 4:
            continue
        if s in seen:
            continue
        seen.add(s)
        deduped.append(s)

    text = "\n".join(deduped)

    if len(text) <= max_chars:
        return text

    # Step 3: Keyword-section extraction + hard cap (fallback for non-Grok paths)
    filtered = _extract_key_sections(text, extra_keywords=focus_keywords)
    if len(filtered) > max_chars:
        filtered = filtered[:max_chars] + "\n\n...[报告过长，已截断至前80000字]"
    return filtered


async def _download_pdf(url: str) -> bytes:
    """Download PDF bytes from Sina Finance file server."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": SINA_BASE,
        })
        resp.raise_for_status()
    logger.info(f"PDF downloaded: {len(resp.content):,} bytes from {url}")
    return resp.content


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pymupdf, preserving table structure.

    Uses find_tables() to extract tables as labelled Markdown rows, then extracts
    non-table text blocks separately to avoid duplication and unlabelled numbers.
    Returns empty string if the PDF appears to be image-based (< 300 chars/page avg).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts: list[str] = []

    for page in doc:
        parts: list[str] = []
        table_rects: list[fitz.Rect] = []

        # Extract tables with proper row/column structure
        try:
            tabs = page.find_tables()
            for tab in tabs.tables:
                table_rects.append(fitz.Rect(tab.bbox))
                rows = tab.extract()
                if rows:
                    md_lines = [
                        " | ".join(str(c or "").strip() for c in row)
                        for row in rows
                        if any(str(c or "").strip() for c in row)
                    ]
                    if md_lines:
                        parts.append("\n".join(md_lines))
        except Exception:
            pass  # find_tables not available or failed — text-only fallback below

        # Extract text blocks outside table areas to avoid duplication
        for block in page.get_text("blocks"):
            if block[6] != 0:  # skip image blocks
                continue
            block_rect = fitz.Rect(block[:4])
            if any(not block_rect.intersect(tr).is_empty for tr in table_rects):
                continue  # covered by a table already extracted above
            text = block[4].strip()
            if text:
                parts.append(text)

        if parts:
            page_texts.append("\n".join(parts))

    doc.close()
    full_text = "\n\n".join(page_texts)
    n_pages = len(doc)
    avg_chars = len(full_text) / max(n_pages, 1)
    logger.info(
        f"PDF text extracted: {len(full_text):,} chars from {len(page_texts)} pages "
        f"(avg {avg_chars:.0f} chars/page)"
    )
    return full_text


async def _get_financial_context(code: str) -> str:
    """Pull last 8 quarters of financial metrics from DB for a stock.

    Returns a compact text summary of the trend data for use in question generation.
    """
    try:
        from db import get_marketdata_pool
        pool = await get_marketdata_pool()
        rows = await pool.fetch(
            """
            SELECT stat_date, pub_date,
                   roe_avg, np_margin, gp_margin, net_profit, mb_revenue,
                   yoy_ni, yoy_pni, yoy_asset,
                   current_ratio, liability_to_asset, asset_to_equity,
                   cfo_to_np, cfo_to_or,
                   eps_ttm, dupont_roe, dupont_asset_turn, dupont_ebit_togr
            FROM financials
            WHERE code = $1
            ORDER BY stat_date DESC
            LIMIT 8
            """,
            code,
        )
        if not rows:
            return "（数据库中暂无该股票财务数据）"

        lines = ["季度财务数据（最近8期，最新在前）：\n"]
        lines.append(
            f"{'报告期':<12} {'ROE':>6} {'净利率':>7} {'毛利率':>7} "
            f"{'净利润YoY':>9} {'收入YoY':>9} {'资产负债率':>9} "
            f"{'经营现金/净利':>12} {'EPS_TTM':>8}"
        )
        lines.append("-" * 90)
        for r in rows:
            def fmt(v):
                return f"{v*100:.1f}%" if v is not None else "N/A"
            def fmtv(v):
                return f"{v:.3f}" if v is not None else "N/A"
            lines.append(
                f"{str(r['stat_date']):<12} {fmt(r['roe_avg']):>6} {fmt(r['np_margin']):>7} "
                f"{fmt(r['gp_margin']):>7} {fmt(r['yoy_ni']):>9} {fmt(r['yoy_asset']):>9} "
                f"{fmt(r['liability_to_asset']):>9} {fmtv(r['cfo_to_np']):>12} "
                f"{fmtv(r['eps_ttm']) if r['eps_ttm'] is not None else 'N/A':>8}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch financial context from DB: {e}")
        return "（财务数据查询失败）"


async def _generate_research_questions(
    financial_context: str,
    title: str,
    focus_keywords: list[str] | None = None,
) -> list[str]:
    """Use Groq to analyze financial trend data and produce targeted research questions.

    Returns a list of 4-6 specific questions to answer from the report.
    """
    if not _groq_client:
        return []

    keyword_note = f"\n用户额外关注：{', '.join(focus_keywords)}" if focus_keywords else ""

    prompt = (
        f"你是一名买方分析师，正在研究《{title}》。\n"
        f"以下是该股票数据库中的历史季度财务数据：\n\n"
        f"{financial_context}\n"
        f"{keyword_note}\n\n"
        "请基于以上数据中观察到的趋势、异常或需要核实的点，生成4到6个具体的研究问题。\n"
        "这些问题将用于在原始财报中查找答案。\n"
        "要求：\n"
        "- 每个问题必须具体，可以在财报中找到答案（如管理层讨论、财务报表附注）\n"
        "- 优先关注数据库显示的异常趋势（如毛利率下滑、现金质量恶化、杠杆上升）\n"
        "- 如果数据库无数据，提出行业通用的关键问题\n"
        "- 直接输出问题列表，每行一个问题，不要编号或前缀\n"
    )

    try:
        resp = await _groq_client.chat.completions.create(
            model=GROQ_REPORT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or ""
        questions = [q.strip() for q in raw.strip().splitlines() if q.strip()]
        logger.info(f"Generated {len(questions)} research questions")
        return questions
    except Exception as e:
        logger.warning(f"Research question generation failed: {e}")
        return []


async def _groq_targeted_analysis(
    report_text: str,
    title: str,
    report_type_cn: str,
    questions: list[str],
    focus_keywords: list[str] | None = None,
) -> str | None:
    """Send a focused chunk of the report to Groq and answer specific research questions.

    Much faster and more accurate than exhaustive summarization.
    """
    if not _groq_client:
        return None

    # Cap at 40k chars — enough for the key sections, fits easily in 113k context
    prepared = _prepare_report_text(report_text, focus_keywords, max_chars=40_000)
    logger.info(f"Targeted analysis: {len(report_text):,} → {len(prepared):,} chars prepared")

    questions_block = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
    keyword_note = f"\n**额外关注指标**：{', '.join(focus_keywords)}" if focus_keywords else ""

    system = (
        "你是一名专业的买方分析师。根据提供的财务报告原文，回答以下研究问题。\n"
        "要求：\n"
        "1. 只使用报告中实际存在的数据，严禁编造。\n"
        "2. 每个问题单独回答，附上原文数据或引用。\n"
        "3. 若报告中找不到某问题的答案，明确说明'报告中未披露'。\n"
        "4. 在最后给出一个简短的综合投资结论（看多/看空/中性 + 核心理由）。"
    )

    prompt = (
        f"**报告**：{title}（{report_type_cn}）{keyword_note}\n\n"
        f"## 研究问题\n{questions_block}\n\n"
        f"## 报告原文\n\n{prepared}"
    )

    try:
        resp = await _groq_client.chat.completions.create(
            model=GROQ_REPORT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        logger.info(f"Targeted analysis done: {len(content)} chars")
        return content
    except Exception as e:
        logger.warning(f"Targeted analysis failed: {e}")
        return None


async def fetch_company_report(stock_code: str, report_type: str, focus_keywords: list[str] | None = None) -> dict:
    """Fetch the latest financial report for a Chinese A-share company.

    Always fetches live from Sina Finance: downloads the PDF (or falls back to HTML),
    generates targeted research questions from DB financial history, and answers them
    with Groq on a focused chunk of the report.
    """
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits like '002028'."}
    if report_type not in REPORT_URLS:
        return {"error": f"Invalid report_type: {report_type}. Must be one of: yearly, q1, mid, q3"}

    report_type_cn_map = {"yearly": "年报", "q1": "一季报", "mid": "中报", "q3": "三季报"}
    rtype_label = report_type_cn_map.get(report_type, report_type)

    # ── Step 1: Fetch bulletin listing to get latest report metadata ──────────
    listing_url = SINA_BASE + REPORT_URLS[report_type].format(code=code)
    try:
        listing_html = await _fetch_page(listing_url)
    except Exception as e:
        return {"error": f"Failed to fetch bulletin listing: {e}", "url": listing_url}

    reports = _parse_bulletin_list(listing_html)
    if not reports:
        return {"error": f"No {report_type} reports found for stock {code}", "listing_url": listing_url}

    latest = reports[0]
    logger.info(f"Latest {report_type} report for {code}: {latest['title']} ({latest['date']})")

    # ── Step 2: Fetch report detail page ─────────────────────────────────────
    try:
        detail_html = await _fetch_page(latest["url"])
    except Exception as e:
        return {
            "error": f"Failed to fetch report detail: {e}",
            "report_url": latest["url"],
            "date": latest["date"],
            "title": latest["title"],
        }

    soup = BeautifulSoup(detail_html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "iframe"]):
        tag.decompose()

    body_text = soup.get_text(separator="\n", strip=True)

    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any(c for c in cells):
                rows.append(" | ".join(cells))
        if rows:
            tables.append("\n".join(rows))

    pdf_link = _extract_pdf_link(detail_html)

    # Prefer PDF text (full report) over HTML body (usually just a summary bulletin)
    if pdf_link:
        try:
            pdf_bytes = await _download_pdf(pdf_link)
            full_text = _extract_pdf_text(pdf_bytes)
            del pdf_bytes  # discard bytes immediately — no disk file written
            # Sanity check: image-based or unreadable PDFs yield very little text
            if len(full_text.strip()) < 3000:
                logger.warning(
                    f"PDF extraction too sparse ({len(full_text.strip())} chars) — "
                    "likely image-based PDF, falling back to HTML text"
                )
                pdf_link = None
        except Exception as e:
            logger.warning(f"PDF download/extraction failed ({e}), falling back to HTML text")
            pdf_link = None

    if not pdf_link:
        # HTML fallback: body text + small embedded tables
        full_text = body_text
        small_tables = [t for t in tables if len(t) <= 50_000]
        if small_tables:
            full_text += "\n\n=== FINANCIAL TABLES ===\n"
            for i, t in enumerate(small_tables[:20]):
                full_text += f"\n--- Table {i+1} ---\n{t}\n"

    logger.info(f"Analysing {len(full_text):,} chars for {latest['title']}")

    # Step 1: pull historical financials from DB to anchor questions
    financial_context = await _get_financial_context(code)

    # Step 2: generate targeted research questions based on trends/anomalies
    questions = await _generate_research_questions(financial_context, latest["title"], focus_keywords)

    # Step 3: answer those questions from a focused chunk of the report
    summary = await _groq_targeted_analysis(full_text, latest["title"], rtype_label, questions, focus_keywords)

    # ── Step 4: Build MD with metadata header ────────────────────────────────
    report_year = _extract_report_year(latest["title"], latest["date"])
    if summary:
        distilled_content = (
            f"## 历史财务背景\n\n```\n{financial_context}\n```\n\n"
            f"## 研究问题与分析\n\n{summary}"
        )
        summarized_by = "groq_targeted"
    else:
        distilled_content = _extract_key_sections(full_text, extra_keywords=focus_keywords)
        summarized_by = "keyword_extraction"

    md_header = (
        f"# {latest['title']}\n\n"
        f"**报告期**: {report_year} {rtype_label}  \n"
        f"**股票代码**: {code}  \n"
        f"**发布日期**: {latest['date']}  \n"
        f"**来源**: {latest['url']}  \n"
        f"**PDF**: {pdf_link or '暂无'}  \n\n"
        f"---\n\n"
    )
    full_md = md_header + distilled_content

    return {
        "stock_code": code,
        "report_type": rtype_label,
        "title": latest["title"],
        "date": latest["date"],
        "report_url": latest["url"],
        "pdf_url": pdf_link,
        "content": full_md,
        "summarized_by": summarized_by,
        "all_reports": [{"date": r["date"], "title": r["title"]} for r in reports[:5]],
    }
