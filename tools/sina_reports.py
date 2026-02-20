"""Fetch company financial reports from Sina Finance bulletin pages.

Supports yearly, Q1, mid-year (Q2), and Q3 reports for Chinese A-share stocks.
"""

import re
import logging
import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from config import GROK_API_KEY, GROK_BASE_URL, GROK_MODEL_NOREASONING

logger = logging.getLogger(__name__)
from pathlib import Path

_REPORTS_BASE = Path("output/reports")

# Grok client for full-report reading (2M token context window)
_grok_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL) if GROK_API_KEY else None
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
            "Fetch and summarize a financial report for a Chinese A-share company (Sina Finance). "
            "Uses Grok to read the full report and return a structured Markdown summary with key metrics, "
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


def _prepare_for_grok(full_text: str, focus_keywords: list[str] | None = None, max_chars: int = 80_000) -> str:
    """Reduce token cost before sending to Grok without losing financial data.

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

    # Step 3: Keyword-section extraction + hard cap (fallback for very long reports)
    filtered = _extract_key_sections(text, extra_keywords=focus_keywords)
    if len(filtered) > max_chars:
        filtered = filtered[:max_chars] + "\n\n...[报告过长，已截断至前80000字]"
    return filtered

async def _grok_summarize_report(
    full_text: str,
    title: str,
    report_type_cn: str,
    focus_keywords: list[str] | None = None,
) -> str | None:
    """Preprocess report text then summarize with Grok.

    Returns a structured Markdown string suitable for caching, or None on failure.
    Output includes both Grok narrative AND preserved financial tables (Option B).
    """
    if not _grok_client:
        logger.warning("Grok client not initialised (GROK_API_KEY missing?) — falling back to keyword extraction")
        return None

    # Grok supports 2M-token context (~1.5M chars). Pass a large cap so only
    # TOC section filtering + dedup run; the hard-cap keyword-scramble fallback
    # is reserved for non-Grok paths.
    grok_input = _prepare_for_grok(full_text, focus_keywords, max_chars=1_500_000)
    logger.info(
        f"Grok input: {len(full_text):,} → {len(grok_input):,} chars "
        f"({100 - len(grok_input) * 100 // max(len(full_text), 1)}% reduction)"
    )

    focus_note = ""
    if focus_keywords:
        focus_note = f"\n**重点关注指标**：{', '.join(focus_keywords)}"

    system = (
        "你是一名专业的卖方金融分析师。请仔细阅读以下中文财务报告，输出结构化的Markdown分析报告。"
        "要求：数字精确，注明报告期，关键财务表格必须以Markdown表格格式完整保留。"
        "不要省略任何财务数据、比率或管理层提到的具体数字。"
    )

    prompt = (
        f"**报告**：{title}（{report_type_cn}）{focus_note}\n\n"
        "## 阅读策略\n"
        "本报告文本已按中国上市公司年报/季报标准格式预处理，仅保留财务相关章节：\n"
        "- **已保留**：主要财务指标、管理层讨论与分析、财务报告、业务综述、风险管理\n"
        "- **已过滤**：重要提示、公司简介、公司治理、环境社会责任、重要事项等非财务章节\n\n"
        "## 请按以下结构输出Markdown报告\n\n"
        "### 一、核心财务指标\n"
        "用表格列出：营业收入、净利润（归母）、基本EPS、ROE、总资产、净资产，"
        "以及各项与上期的同比变化（%）。\n\n"
        "### 二、管理层讨论与分析摘要\n"
        "- **总体经营情况**（含具体数字，2–3段）\n"
        "- **分业务/分行业收入结构**：完整保留原始数据表格（Markdown表格格式）\n"
        "- **管理层重点关注问题**：逐条列出管理层在报告中明确提及的重点问题\n\n"
        "### 三、财务报表关键数据\n"
        "完整保留以下数据表格（Markdown表格格式，不要简化）：\n"
        "- 利润表主要项目（营收、毛利、期间费用、净利润）\n"
        "- 资产负债表关键项目（总资产、总负债、净资产、主要负债结构）\n"
        "- 现金流量表摘要（经营/投资/融资活动净现金流）\n"
        "- 行业特定指标（如银行：不良贷款率、净息差、拨备覆盖率、资本充足率；"
        "零售：同店销售、库存周转；房地产：去化率、土储等）\n\n"
        "### 四、风险因素\n"
        "列出管理层在报告中披露的主要风险（逐条，注明原文依据）。\n\n"
        "### 五、亮点与异常发现\n"
        "从报告中找出2–4个最值得深入研究的发现。可以是：超预期或低于预期的指标、"
        "趋势转折点、管理层措辞变化、隐藏风险、与行业对比后的异常。"
        "每条注明具体数据依据。\n\n"
        f"以下是报告内容：\n\n{grok_input}"
    )

    try:
        resp = await _grok_client.chat.completions.create(
            model=GROK_MODEL_NOREASONING,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or None
    except Exception as e:
        logger.warning(f"Grok report summarization failed: {e}")
        return None


async def fetch_company_report(stock_code: str, report_type: str, focus_keywords: list[str] | None = None) -> dict:
    """Fetch the latest financial report for a Chinese A-share company.

    Fast path: check report_cache DB → if hit, read local .md file and return.
    Slow path: fetch from Sina Finance, distil with Grok, save to disk + DB, return.
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

    full_text = body_text
    if tables:
        full_text += "\n\n=== FINANCIAL TABLES ===\n"
        for i, t in enumerate(tables[:20]):
            full_text += f"\n--- Table {i+1} ---\n{t}\n"

    pdf_link = _extract_pdf_link(detail_html)

    logger.info(f"Distilling {len(full_text):,} chars for {latest['title']}")
    summary = await _grok_summarize_report(full_text, latest["title"], rtype_label, focus_keywords)

    if summary:
        distilled_content = summary
        summarized_by = "grok"
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
