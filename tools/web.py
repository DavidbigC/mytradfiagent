import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from config import GROK_API_KEY, GROK_BASE_URL, GROK_MODEL_NOREASONING

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Sites known to require JS rendering for meaningful content
_JS_HEAVY_DOMAINS = [
    "xueqiu.com",
    "guba.eastmoney.com",
    "eastmoney.com/a/",
    "weibo.com",
    "bilibili.com",
]

logger = logging.getLogger(__name__)

# Grok client for live web search — created once at import if key is present
_grok_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL) if GROK_API_KEY else None
)

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Returns source URLs with titles and snippets. "
            "Fast and free for Chinese market data, current events, and factual lookups."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}

SCRAPE_WEBPAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "scrape_webpage",
        "description": "Fetch and extract content from a webpage URL. Returns clean markdown with tables and structured data preserved. Handles Chinese encoding automatically.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
            },
            "required": ["url"],
        },
    },
}


def _ddg_search_sync(query: str, max_results: int = 5) -> dict:
    """Fallback: DuckDuckGo search."""
    if DDGS is None:
        return {"error": "No search backend available"}
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return {
        "answer": None,
        "sources": [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in results],
    }


async def _grok_web_search(query: str) -> dict:
    """Use Grok Responses API with live web_search tool. Falls back to DuckDuckGo on error."""
    try:
        response = await _grok_client.responses.create(
            model=GROK_MODEL_NOREASONING,
            input=[{"role": "user", "content": query}],
            tools=[{"type": "web_search"}],
        )
        # Find the message output item
        content = ""
        sources = []
        for item in response.output:
            if item.type == "message":
                for c in item.content:
                    if c.type == "output_text":
                        content = c.text
                        # Citations come back as url_citation annotations
                        for ann in getattr(c, "annotations", []):
                            if ann.type == "url_citation":
                                sources.append({"url": ann.url, "title": ann.title or ""})
                        break
                break
        logger.info(f"Grok web search: {len(sources)} citations for '{query[:60]}'")
        return {"answer": content, "sources": sources}
    except Exception as e:
        logger.warning(f"Grok web search failed ({e}), falling back to DuckDuckGo")
        return await asyncio.to_thread(_ddg_search_sync, query)


async def web_search(query: str) -> dict:
    """Search the web. Uses Grok live search if configured, otherwise DuckDuckGo."""
    if _grok_client:
        return await _grok_web_search(query)
    return await asyncio.to_thread(_ddg_search_sync, query)


def _has_garbled_text(text: str) -> bool:
    """Detect if text has encoding issues (high ratio of replacement/garbled chars)."""
    if not text:
        return True
    # Count common garbled patterns: replacement char, sequences of '�'
    garbled = text.count("�") + text.count("\ufffd")
    # If more than 5% of chars are garbled, it's bad
    return garbled > len(text) * 0.05


async def _scrape_via_markdown_new(url: str) -> str | None:
    """Use markdown.new to convert a webpage to clean markdown. Returns None on failure."""
    md_url = f"https://markdown.new/{url}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(md_url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                text = resp.text.strip()
                if text and len(text) > 50 and not _has_garbled_text(text):
                    logger.info(f"markdown.new succeeded for {url} ({len(text)} chars)")
                    return text
                elif _has_garbled_text(text):
                    logger.warning(f"markdown.new returned garbled text for {url}, falling back")
                    return None
    except Exception as e:
        logger.warning(f"markdown.new failed for {url}: {e}")
    return None


async def _scrape_via_bs4(url: str) -> dict:
    """Fallback: scrape with httpx + BeautifulSoup with encoding detection."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

    # Detect encoding — Chinese sites often use GBK/GB2312
    if resp.encoding and resp.encoding.lower() not in ("utf-8", "ascii"):
        text = resp.content.decode(resp.encoding, errors="replace")
    elif b"charset=gb" in resp.content[:2000].lower() or b"charset=\"gb" in resp.content[:2000].lower():
        text = resp.content.decode("gbk", errors="replace")
    else:
        text = resp.text

    soup = BeautifulSoup(text, "html.parser")

    title = soup.title.string if soup.title else ""

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
        tag.decompose()
    for sel in [".nav", ".menu", ".sidebar", ".ad", ".advertisement", ".breadcrumb", ".footer"]:
        for tag in soup.select(sel):
            tag.decompose()

    # Extract tables separately
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            tables.append("\n".join(rows))

    body = soup.get_text(separator="\n", strip=True)
    lines = [line for line in body.split("\n") if line.strip()]
    body = "\n".join(lines)

    if tables:
        body += "\n\n=== EXTRACTED TABLES ===\n"
        for i, t in enumerate(tables):
            body += f"\n--- Table {i+1} ---\n{t}\n"

    return {"title": title, "content": body}


async def _scrape_via_playwright(url: str) -> dict | None:
    """Scrape JS-heavy sites using Playwright browser automation."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available, skipping browser automation")
        return None
    
    try:
        async with async_playwright() as p:
            # Launch browser in headless mode
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            
            # Navigate and wait for content to load
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait a bit more for dynamic content (forums often load posts via JS)
            await asyncio.sleep(2)
            
            # Get page content
            title = await page.title()
            content = await page.content()
            
            await browser.close()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            
            # Remove non-content elements
            for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
                tag.decompose()
            for sel in [".nav", ".menu", ".sidebar", ".ad", ".advertisement", ".breadcrumb", ".footer", ".header"]:
                for tag in soup.select(sel):
                    tag.decompose()
            
            # Extract tables
            tables = []
            for table in soup.find_all("table"):
                rows = []
                for tr in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    tables.append("\n".join(rows))
            
            # Get main text content
            body = soup.get_text(separator="\n", strip=True)
            lines = [line for line in body.split("\n") if line.strip()]
            body = "\n".join(lines)
            
            if tables:
                body += "\n\n=== EXTRACTED TABLES ===\n"
                for i, t in enumerate(tables[:10]):  # Limit tables
                    body += f"\n--- Table {i+1} ---\n{t}\n"
            
            if len(body) < 100:
                logger.warning(f"Playwright returned minimal content for {url}")
                return None
            
            logger.info(f"Playwright succeeded for {url} ({len(body)} chars)")
            return {"title": title, "content": body}
            
    except PlaywrightTimeoutError:
        logger.warning(f"Playwright timeout for {url}")
        return None
    except Exception as e:
        logger.warning(f"Playwright failed for {url}: {e}")
        return None


def _needs_playwright(url: str) -> bool:
    """Check if URL needs Playwright (JS-heavy or known problematic domains)."""
    return any(domain in url for domain in _JS_HEAVY_DOMAINS)


async def scrape_webpage(url: str) -> dict:
    # Check if this site needs Playwright (forums, SPAs, anti-bot protection)
    if _needs_playwright(url) and PLAYWRIGHT_AVAILABLE:
        logger.info(f"Using Playwright for JS-heavy site: {url}")
        playwright_result = await _scrape_via_playwright(url)
        if playwright_result:
            content = playwright_result["content"]
            if len(content) > 15000:
                content = content[:15000] + "\n...[truncated]"
            return {
                "url": url,
                "title": playwright_result["title"],
                "content": content,
                "source": "playwright",
            }
        # If Playwright fails, fall through to other methods
    
    # Primary: markdown.new — cleaner output, handles encoding, preserves structure
    md_content = await _scrape_via_markdown_new(url)
    if md_content:
        # Truncate if needed
        if len(md_content) > 15000:
            md_content = md_content[:15000] + "\n...[truncated]"
        return {"url": url, "content": md_content, "source": "markdown.new"}

    # Fallback: direct scrape with BeautifulSoup
    logger.info(f"Falling back to BS4 scrape for {url}")
    result = await _scrape_via_bs4(url)
    content = result["content"]
    
    # If BS4 got minimal content and Playwright is available, try Playwright as last resort
    if len(content) < 200 and PLAYWRIGHT_AVAILABLE:
        logger.info(f"BS4 got minimal content, trying Playwright for {url}")
        playwright_result = await _scrape_via_playwright(url)
        if playwright_result and len(playwright_result["content"]) > len(content):
            content = playwright_result["content"]
            result["title"] = playwright_result["title"]
            result["source"] = "playwright_fallback"
    
    if len(content) > 15000:
        content = content[:15000] + "\n...[truncated]"
    return {"url": url, "title": result.get("title", ""), "content": content, "source": result.get("source", "bs4_fallback")}
