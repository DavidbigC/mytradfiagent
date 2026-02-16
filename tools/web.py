import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from config import GEMINI_API_KEY

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

logger = logging.getLogger(__name__)

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web using Google (via Gemini). Returns a synthesized answer with source URLs. "
            "Powered by Gemini + Google Search grounding — fast and accurate for Chinese market data, "
            "current events, and factual lookups."
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


GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]


def _gemini_search_sync(query: str) -> dict:
    """Use Gemini with Google Search grounding for fast, sourced answers."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Try models in order until one works
    last_error = None
    for model in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0,
                ),
            )
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Gemini model {model} failed: {e}")
            continue
    else:
        raise last_error

    result = {"answer": response.text}

    # Extract source URLs from grounding metadata
    sources = []
    candidate = response.candidates[0] if response.candidates else None
    if candidate and candidate.grounding_metadata and candidate.grounding_metadata.grounding_chunks:
        for chunk in candidate.grounding_metadata.grounding_chunks:
            if chunk.web:
                sources.append({"title": chunk.web.title, "url": chunk.web.uri})
    result["sources"] = sources
    return result


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


async def web_search(query: str) -> dict:
    # Primary: Gemini with Google Search grounding
    if GEMINI_API_KEY:
        try:
            return await asyncio.to_thread(_gemini_search_sync, query)
        except Exception as e:
            logger.warning(f"Gemini search failed, falling back to DDG: {e}")

    # Fallback: DuckDuckGo
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


async def scrape_webpage(url: str) -> dict:
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
    if len(content) > 15000:
        content = content[:15000] + "\n...[truncated]"
    return {"url": url, "title": result["title"], "content": content, "source": "bs4_fallback"}
