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
from pathlib import Path

_REPORTS_BASE = Path("output/reports")

# Groq client for PDF report reading (113k context window, chunked parallel)
_groq_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL) if GROQ_API_KEY else None
)

_CHUNK_SIZE    = 10_000
_CHUNK_OVERLAP = 200
_MAX_PARALLEL  = 4

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
            "Fetch and summarize a financial report for a Chinese A-share company (Sina Finance). "
            "Reads the full report and returns a structured Markdown summary with key metrics, "
            "balance sheet, cash flow, segment breakdown, and notable findings. "
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


def _get_cache_path(stock_code: str, report_year: int, report_type: str) -> Path:
    """Return the .md file path for a cached distilled report.

    Structure: output/reports/{stock_code}/{year}_{code}_{type}.md
    Example:   output/reports/600036/2024_600036_yearly.md
    One subfolder per stock code — max ~40 files per directory for a 10-year window.
    """
    return _REPORTS_BASE / stock_code / f"{report_year}_{stock_code}_{report_type}.md"


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


async def _check_report_cache(stock_code: str, report_type: str, report_year: int) -> str | None:
    """Check if a distilled report already exists in DB and on disk.

    Returns the filepath string if valid, None if cache miss or file missing.
    """
    try:
        from db import get_pool
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT filepath FROM report_cache "
            "WHERE stock_code=$1 AND report_type=$2 AND report_year=$3",
            stock_code, report_type, report_year,
        )
        if not row:
            return None
        filepath = row["filepath"]
        if not Path(filepath).exists():
            logger.warning(f"Cache DB entry exists but file missing: {filepath}")
            return None
        return filepath
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
        return None


async def _save_report_cache(
    stock_code: str,
    report_type: str,
    report_year: int,
    report_date: str,
    title: str,
    filepath: str,
    source_url: str,
) -> None:
    """Upsert a cache entry. Silently ignores failures (cache is best-effort)."""
    try:
        from db import get_pool
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO report_cache
                (stock_code, report_type, report_year, report_date, title, filepath, source_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (stock_code, report_type, report_year) DO UPDATE
                SET filepath    = EXCLUDED.filepath,
                    report_date = EXCLUDED.report_date,
                    title       = EXCLUDED.title,
                    source_url  = EXCLUDED.source_url
            """,
            stock_code, report_type, report_year,
            report_date, title, filepath, source_url,
        )
        logger.info(f"Cache DB entry saved: {stock_code} {report_type} {report_year}")
    except Exception as e:
        logger.warning(f"Cache DB write failed: {e}")


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

def _make_chunks(text: str) -> list[str]:
    """Split text into overlapping chunks for parallel LLM processing."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        chunks.append(text[start:end + _CHUNK_OVERLAP])
        start += _CHUNK_SIZE
    return chunks


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
    """Extract plain text from PDF bytes using pymupdf. No file written to disk."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text("text") for page in doc if page.get_text("text").strip()]
    doc.close()
    text = "\n".join(pages)
    logger.info(f"PDF text extracted: {len(text):,} chars from {len(pages)} pages")
    return text


_SYSTEM_EXTRACT = """你是一名专业的卖方金融分析师，任务是从财务报告片段中进行无损数据提取。

核心原则：
1. 穷举提取——本片段中出现的每一个数字、比率、金额、百分比、增减变化都必须提取，一个都不能遗漏。
2. 数字必须100%来自原文，严禁编造、推算或四舍五入后不标注。
3. 所有表格必须以完整Markdown表格格式保留，包括每一行每一列，绝对不得省略。
4. 每个数据必须标明报告期（年度、季度、具体日期）。
5. 管理层原话中的关键判断、前瞻性表述、行业分析也必须完整引用，不得压缩。
6. 若本片段确实无财务数据，简短说明后停止，不要填充废话。
7. 输出长度不设上限——有多少数据就输出多少，宁多勿缺。"""

_SYSTEM_SYNTHESIS = """你是一名资深卖方金融分析师，将多份片段提取报告整合为一份极度详尽的深度研报。

核心原则：
1. 保留所有数据——每一个出现在片段中的数字、表格、比率都必须出现在最终报告中，严禁丢失。
2. 合并同类数据，消除重复，但保留所有不同报告期的对比数据。
3. 严禁编造，严禁在片段数据之外添加任何数字。
4. 输出不设长度限制，以数据完整性为第一优先级。
5. 排版清晰：大量使用Markdown表格，数据密集段落用表格而非文字呈现。"""


async def _groq_summarize_report(
    full_text: str,
    title: str,
    report_type_cn: str,
    focus_keywords: list[str] | None = None,
) -> str | None:
    """Chunk report text and summarize in parallel with Groq.

    Returns a structured Markdown string suitable for caching, or None on failure.
    PDF bytes are never written to disk — text is extracted in memory only.
    """
    if not _groq_client:
        logger.warning("Groq client not initialised (GROQ_API_KEY missing?) — falling back to keyword extraction")
        return None

    prepared = _prepare_report_text(full_text, focus_keywords, max_chars=999_999)
    chunks = _make_chunks(prepared)
    focus_note = f"**重点关注指标**：{', '.join(focus_keywords)}\n\n" if focus_keywords else ""

    logger.info(
        f"Groq input: {len(full_text):,} → {len(prepared):,} chars, "
        f"{len(chunks)} chunks of ~{_CHUNK_SIZE} chars"
    )

    sem = asyncio.Semaphore(_MAX_PARALLEL)

    async def _process_chunk(idx: int, chunk: str) -> str:
        prompt = (
            f"**报告**：{title}（{report_type_cn}）\n"
            f"{focus_note}"
            f"这是报告文本的第 {idx + 1}/{len(chunks)} 片段。请对本片段做穷举式数据提取，不遗漏任何数字。\n\n"
            "## 提取结构\n\n"
            "### 一、财务数据全量提取\n"
            "列出本片段中出现的每一个财务数字，包括：收入、利润、资产、负债、比率、增减幅度、每股数据等。\n"
            "遇到表格：完整复现为Markdown表格，一行一列都不能省。\n"
            "遇到散列数字：逐条列出，格式：[指标名] [数值] [报告期]。\n\n"
            "### 二、管理层表述全量提取\n"
            "本片段中管理层对经营情况、战略、行业、风险的所有原话或核心表述，逐条引用，不压缩。\n\n"
            "### 三、风险与异常全量提取\n"
            "本片段中所有风险提示、异常数据、同比大幅变动的指标，逐条列出并附原文数据。\n\n"
            f"--- 片段内容 ---\n\n{chunk}"
        )
        async with sem:
            try:
                resp = await _groq_client.chat.completions.create(
                    model=GROQ_REPORT_MODEL,
                    messages=[
                        {"role": "system", "content": _SYSTEM_EXTRACT},
                        {"role": "user",   "content": prompt},
                    ],
                    max_tokens=8192,
                    temperature=0.1,
                )
                content = resp.choices[0].message.content or ""
                logger.info(f"Groq chunk {idx + 1}/{len(chunks)} done: {len(content)} chars")
                return f"## 片段 {idx + 1}\n\n{content}"
            except Exception as e:
                logger.warning(f"Groq chunk {idx + 1} failed: {e}")
                return f"## 片段 {idx + 1}\n\n> 处理失败: {e}"

    results = await asyncio.gather(*[_process_chunk(i, c) for i, c in enumerate(chunks)])
    combined = "\n\n---\n\n".join(results)

    # Synthesis pass
    logger.info("Starting synthesis pass...")
    final_prompt = (
        f"**任务**：生成《{title}》的最终深度研报汇总。\n\n"
        "以下是从原始PDF各片段并行提取的子报告集合。请整合、去重、润色，输出统一结构化报告。\n\n"
        "## 输出结构（Markdown）\n\n"
        "### 一、核心财务指标汇总\n"
        "合并所有财务数据，以Markdown表格呈现，注明报告期。\n\n"
        "### 二、经营情况与管理层分析\n"
        "按逻辑提炼整体经营情况、业务结构、核心战略。\n\n"
        "### 三、关键财务明细表\n"
        "整合营收结构、贷款/存款明细、分部数据等关键表格。\n\n"
        "### 四、银行/行业特定指标\n"
        "净息差、不良率、拨备覆盖率、资本充足率等专项指标及同比变化。\n\n"
        "### 五、风险因素\n"
        "管理层披露的关键风险，去重整理。\n\n"
        "### 六、亮点与异常发现\n"
        "全篇最核心的超预期/低于预期指标及趋势判断，附具体数据。\n\n"
        "**重要提示：以上六个部分必须全部输出，每个部分尽可能详尽，不设长度限制。**\n\n"
        f"--- 片段提取集合 ---\n\n{combined}"
    )
    try:
        final_resp = await _groq_client.chat.completions.create(
            model=GROQ_REPORT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_SYNTHESIS},
                {"role": "user",   "content": final_prompt},
            ],
            max_tokens=8192,
            temperature=0.15,
        )
        final_content = final_resp.choices[0].message.content or ""
        logger.info(f"Synthesis done: {len(final_content)} chars")
        return final_content
    except Exception as e:
        logger.warning(f"Synthesis failed, returning combined chunk output: {e}")
        return combined


async def fetch_company_report(stock_code: str, report_type: str, focus_keywords: list[str] | None = None) -> dict:
    """Fetch the latest financial report for a Chinese A-share company.

    Fast path: check report_cache DB → if hit, read local .md file and return.
    Slow path: fetch from Sina Finance, distil with Minimax, save to disk + DB, return.
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

    # ── Step 2: Cache check ───────────────────────────────────────────────────
    report_year = _extract_report_year(latest["title"], latest["date"])
    cached_filepath = await _check_report_cache(code, report_type, report_year)
    if cached_filepath:
        logger.info(f"Cache hit: {cached_filepath}")
        content = Path(cached_filepath).read_text(encoding="utf-8")
        return {
            "stock_code": code,
            "report_type": rtype_label,
            "title": latest["title"],
            "date": latest["date"],
            "report_url": latest["url"],
            "content": content,
            "summarized_by": "cache",
            "cache_path": cached_filepath,
            "all_reports": [{"date": r["date"], "title": r["title"]} for r in reports[:5]],
        }

    # ── Step 3: Cache miss — fetch and distil ─────────────────────────────────
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

    logger.info(f"Distilling {len(full_text):,} chars for {latest['title']}")
    summary = await _groq_summarize_report(full_text, latest["title"], rtype_label, focus_keywords)

    if summary:
        distilled_content = summary
        summarized_by = "groq"
    else:
        distilled_content = _extract_key_sections(full_text, extra_keywords=focus_keywords)
        summarized_by = "keyword_extraction"

    # ── Step 4: Build full MD with metadata header and save to cache ──────────
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

    cache_path = _get_cache_path(code, report_year, report_type)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(full_md, encoding="utf-8")
        await _save_report_cache(
            code, report_type, report_year,
            latest["date"], latest["title"], str(cache_path), latest["url"],
        )
        logger.info(f"Report cached to {cache_path}")
    except Exception as e:
        logger.warning(f"Failed to write cache: {e}")

    return {
        "stock_code": code,
        "report_type": rtype_label,
        "title": latest["title"],
        "date": latest["date"],
        "report_url": latest["url"],
        "pdf_url": pdf_link,
        "content": full_md,
        "summarized_by": summarized_by,
        "cache_path": str(cache_path),
        "all_reports": [{"date": r["date"], "title": r["title"]} for r in reports[:5]],
    }
