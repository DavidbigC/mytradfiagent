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
]

# Regex to match TOC entries like "第三节 管理层讨论与分析 ...... 19"
_TOC_ENTRY_RE = re.compile(
    r"^第[一二三四五六七八九十百]+[章节]\s+(.+?)[\s\.·。…]+\d+\s*$"
)

# Regex to detect chapter headings in the body text
_CHAPTER_HEADING_RE = re.compile(r"^第[一二三四五六七八九十百]+[章节][\s\u3000]")


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
    """Parse the table of contents from the first 400 lines of a report.

    Returns a list of {'name': str, 'keep': bool} for each chapter found.
    Returns [] if no TOC is detected (safe — callers treat [] as "no filter").
    """
    chapters = []
    for line in text.split("\n")[:400]:
        m = _TOC_ENTRY_RE.match(line.strip())
        if not m:
            continue
        name = m.group(1).strip()
        # Strip trailing punctuation noise
        name = re.sub(r"[\s（(）)、，,。\.…·]+$", "", name)
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

    Returns None if Grok is unavailable or the call fails.
    """
    if not _grok_client:
        logger.warning("Grok client not initialised (GROK_API_KEY missing?) — falling back to keyword extraction")
        return None

    grok_input = _prepare_for_grok(full_text, focus_keywords)
    logger.info(
        f"Grok input: {len(full_text):,} → {len(grok_input):,} chars "
        f"({100 - len(grok_input)*100//len(full_text)}% reduction)"
    )

    focus_note = ""
    if focus_keywords:
        focus_note = f"\n请特别关注以下指标：{', '.join(focus_keywords)}"

    system = (
        "你是一名专业的卖方金融分析师。请阅读以下中文财务报告全文，用中文撰写结构化摘要。"
        "格式：Markdown，关键数据用表格，数字精确，注明所属报告期。不要省略关键财务数据。"
    )
    prompt = (
        f"报告：{title}（{report_type_cn}）{focus_note}\n\n"
        "请提取并整理：\n"
        "1. 核心财务指标（营收、净利润、EPS 及同比变化）\n"
        "2. 资产负债摘要（总资产、净资产、关键比率）\n"
        "3. 现金流摘要\n"
        "4. 业务分部/分行业收入结构（如有）\n"
        "5. 主要风险或重要变化\n"
        "6. **值得关注的亮点或异常**：从整份报告中找出最值得深入研究的2–4个发现。"
        "可以是：超预期或低于预期的指标、趋势转折点、管理层措辞变化、隐藏的风险、"
        "与行业对比后的异常、值得跟进的潜在机会。用简洁的中文列出，每条注明数据依据。\n\n"
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
    """Fetch the latest financial report for a Chinese A-share company."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits like '002028'."}

    if report_type not in REPORT_URLS:
        return {"error": f"Invalid report_type: {report_type}. Must be one of: yearly, q1, mid, q3"}

    # Step 1: Fetch bulletin listing page
    listing_path = REPORT_URLS[report_type].format(code=code)
    listing_url = SINA_BASE + listing_path

    try:
        listing_html = await _fetch_page(listing_url)
    except Exception as e:
        return {"error": f"Failed to fetch bulletin listing: {e}", "url": listing_url}

    # Step 2: Parse to find the latest report
    reports = _parse_bulletin_list(listing_html)
    if not reports:
        return {
            "error": f"No {report_type} reports found for stock {code}",
            "listing_url": listing_url,
        }

    latest = reports[0]  # First one is the latest
    logger.info(f"Found latest {report_type} report for {code}: {latest['title']} ({latest['date']})")

    # Step 3: Fetch the report detail page
    try:
        detail_html = await _fetch_page(latest["url"])
    except Exception as e:
        return {
            "error": f"Failed to fetch report detail: {e}",
            "report_url": latest["url"],
            "date": latest["date"],
            "title": latest["title"],
        }

    # Step 4: Extract content
    soup = BeautifulSoup(detail_html, "html.parser")

    # Remove scripts/styles
    for tag in soup(["script", "style", "nav", "footer", "header", "iframe"]):
        tag.decompose()

    # Get text content
    body_text = soup.get_text(separator="\n", strip=True)

    # Extract tables
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any(c for c in cells):
                rows.append(" | ".join(cells))
        if rows:
            tables.append("\n".join(rows))

    # Combine text with tables
    full_text = body_text
    if tables:
        full_text += "\n\n=== FINANCIAL TABLES ===\n"
        for i, t in enumerate(tables[:20]):  # Limit to 20 tables
            full_text += f"\n--- Table {i+1} ---\n{t}\n"

    # Extract PDF link
    pdf_link = _extract_pdf_link(detail_html)

    report_type_cn = {"yearly": "年报", "q1": "一季报", "mid": "中报", "q3": "三季报"}
    rtype_label = report_type_cn.get(report_type, report_type)

    # Try Grok first: deduplicate + summarize the report
    logger.info(f"Grok summarization: {len(full_text):,} raw chars ({latest['title']})")
    summary = await _grok_summarize_report(full_text, latest["title"], rtype_label, focus_keywords)

    if summary:
        content = summary
        summarized_by = "grok"
    else:
        # Fallback: keyword-based section extraction
        content = _extract_key_sections(full_text, extra_keywords=focus_keywords)
        summarized_by = "keyword_extraction"

    return {
        "stock_code": code,
        "report_type": rtype_label,
        "title": latest["title"],
        "date": latest["date"],
        "report_url": latest["url"],
        "pdf_url": pdf_link,
        "content": content,
        "summarized_by": summarized_by,
        "all_reports": [{"date": r["date"], "title": r["title"]} for r in reports[:5]],
    }
