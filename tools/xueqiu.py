"""Fetch Xueqiu (雪球) forum comments for A-share stocks via public API."""

import logging
import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://xueqiu.com/query/v1/symbol/search/status"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://xueqiu.com/",
    "Accept": "application/json",
}

FETCH_XUEQIU_COMMENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_xueqiu_comments",
        "description": (
            "Fetch recent discussion comments for a Chinese A-share stock from Xueqiu (雪球) forum. "
            "Returns user posts, sentiment, and topical themes. Use as supplementary sentiment data — "
            "do NOT rely heavily; fundamentals and financial data are primary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share code, e.g. '603986', '600036', '000858'",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of comments to fetch (default 20)",
                    "default": 20,
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


def _to_xueqiu_symbol(code: str) -> str:
    """Convert 6-digit code to Xueqiu symbol (SH/SZ prefix)."""
    code = code.strip()
    if code.startswith("6") or code.startswith("5"):
        return f"SH{code}"
    return f"SZ{code}"


async def fetch_xueqiu_comments(
    stock_code: str,
    count: int = 20,
    page: int = 1,
) -> dict:
    """Fetch Xueqiu forum comments for an A-share stock.

    Returns a dict with comments, or error if API blocks (WAF) or fails.
    """
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    symbol = _to_xueqiu_symbol(code)
    params = {"symbol": symbol, "count": count, "page": page}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(_API_BASE, params=params, headers=_HEADERS)
    except Exception as e:
        return {"error": f"Request failed: {e}", "stock_code": code}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "stock_code": code}

    text = resp.text.strip()

    # Check for WAF block (xueqiu returns garbled JSON when blocked)
    if "_waf_" in text or (text.startswith("{") and "list" not in text[:500]):
        logger.warning(f"Xueqiu API may have returned WAF block for {code}")
        return {"error": "Xueqiu API blocked or unavailable", "stock_code": code}

    try:
        data = resp.json()
    except Exception:
        return {"error": "Invalid JSON response", "stock_code": code, "raw_preview": text[:200]}

    # API returns {"list": [{"text": "...", "user": {...}, "created_at": ...}, ...]}
    items = data.get("list", data.get("data", []))
    if not items:
        return {"stock_code": code, "symbol": symbol, "comments": [], "count": 0}

    comments = []
    for item in items[:count]:
        text_content = item.get("text", item.get("content", ""))
        user = item.get("user", {})
        screen_name = user.get("screen_name", user.get("name", ""))

        comments.append({
            "text": text_content[:500] if text_content else "",
            "user": screen_name,
            "created_at": item.get("created_at"),
            "retweet_count": item.get("retweet_count"),
            "reply_count": item.get("reply_count"),
        })

    return {
        "stock_code": code,
        "symbol": symbol,
        "comments": comments,
        "count": len(comments),
        "url": f"https://xueqiu.com/S/{symbol}",
    }
