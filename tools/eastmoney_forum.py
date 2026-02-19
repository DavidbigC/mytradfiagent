"""Fetch post listings from Eastmoney 股吧 (guba.eastmoney.com) for A-share stocks.

Parses the SSR HTML post list — no SH/SZ prefix needed, just the 6-digit code.
"""

import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://guba.eastmoney.com/",
}

FETCH_EASTMONEY_FORUM_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_eastmoney_forum",
        "description": (
            "Fetch recent discussion posts from Eastmoney 股吧 (guba.eastmoney.com) for a Chinese A-share stock. "
            "Returns post titles, view and reply counts for retail investor sentiment analysis. "
            "Only requires the 6-digit stock code — no SH/SZ prefix needed. "
            "Use as supplementary sentiment signal alongside financial fundamentals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share code, e.g. '603986', '600036', '000858'",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1)",
                    "default": 1,
                },
            },
            "required": ["stock_code"],
        },
    },
}


async def fetch_eastmoney_forum(stock_code: str, page: int = 1) -> dict:
    """Fetch Eastmoney 股吧 post listings for an A-share stock.

    Parses the SSR HTML at https://guba.eastmoney.com/list,{code}.html
    """
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    page = max(1, int(page))
    if page == 1:
        url = f"https://guba.eastmoney.com/list,{code}.html"
    else:
        url = f"https://guba.eastmoney.com/list,{code}_{page}.html"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=_HEADERS)
    except Exception as e:
        return {"error": f"Request failed: {e}", "stock_code": code}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "stock_code": code}

    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []

    # Primary selector: guba uses div[class*="articleh"] with l1-l6 spans
    for item in soup.select("div[class*='articleh']"):
        title_el = item.select_one("span.l4 a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        read_el = item.select_one("span.l2")
        reply_el = item.select_one("span.l3")
        author_el = item.select_one("span.l5 a")
        time_el = item.select_one("span.l6")

        posts.append({
            "title": title,
            "read_count": read_el.get_text(strip=True) if read_el else None,
            "reply_count": reply_el.get_text(strip=True) if reply_el else None,
            "author": author_el.get_text(strip=True) if author_el else None,
            "time": time_el.get_text(strip=True) if time_el else None,
        })

    # Fallback: broader link-based extraction
    if not posts:
        seen = set()
        for a in soup.select("a[href*='/news/']"):
            title = a.get_text(strip=True)
            if len(title) > 8 and title not in seen:
                seen.add(title)
                posts.append({"title": title})

    if not posts:
        return {
            "stock_code": code,
            "page": page,
            "url": url,
            "error": "Could not parse post list — page structure may have changed or content is JS-rendered",
            "posts": [],
        }

    return {
        "stock_code": code,
        "page": page,
        "url": url,
        "post_count": len(posts),
        "posts": posts[:50],
    }
