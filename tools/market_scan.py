import asyncio
import logging
import httpx
from tools.cache import cached

logger = logging.getLogger(__name__)

SCAN_MARKET_HOTSPOTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "scan_market_hotspots",
        "description": (
            "Scan major Chinese financial data APIs to find currently trending sectors, "
            "hot concept boards, top gainers/losers, and market indices — all in ONE call. "
            "Returns real-time data from 东方财富 APIs. "
            "ALWAYS use this when user asks about hot topics, trending sectors, 热门题材, "
            "板块轮动, market themes, what stocks are getting attention, 今天什么板块涨得好. "
            "Much faster and more accurate than web_search for market overview queries."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
_EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        resp = await client.get(url, headers=_EM_HEADERS, timeout=10)
        return resp.json()
    except Exception as e:
        logger.warning(f"API fetch failed: {url[:80]}... {e}")
        return None


async def _get_indices(client: httpx.AsyncClient) -> list[dict]:
    """Major market indices: 上证, 深证, 创业板, 科创50."""
    url = (
        f"https://push2.eastmoney.com/api/qt/ulist.np/get?"
        f"fltt=2&fields=f2,f3,f4,f12,f14&secids=1.000001,0.399001,0.399006,1.000688&ut={_EM_UT}"
    )
    data = await _fetch_json(client, url)
    if not data or not data.get("data"):
        return []
    diff = data["data"].get("diff", [])
    return [
        {"name": item.get("f14"), "price": item.get("f2"), "change_pct": item.get("f3"), "change": item.get("f4")}
        for item in diff
    ]


async def _get_concept_boards(client: httpx.AsyncClient, top_n: int = 20) -> list[dict]:
    """Top concept boards by daily change %."""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=1&np=1&ut={_EM_UT}&fltt=2&invt=2&fid=f3&fs=m:90+t:3"
        f"&fields=f2,f3,f4,f8,f12,f14,f20"
    )
    data = await _fetch_json(client, url)
    if not data or not data.get("data"):
        return []
    diff = data["data"].get("diff", {})
    items = list(diff.values()) if isinstance(diff, dict) else diff
    return [
        {
            "name": item.get("f14"),
            "change_pct": item.get("f3"),
            "turnover_pct": item.get("f8"),
            "market_cap_billion": round(item.get("f20", 0) / 1e8, 1) if item.get("f20") else None,
        }
        for item in items[:top_n]
    ]


async def _get_industry_boards(client: httpx.AsyncClient, top_n: int = 15) -> list[dict]:
    """Top industry boards by daily change %."""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=1&np=1&ut={_EM_UT}&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
        f"&fields=f2,f3,f4,f8,f12,f14,f20"
    )
    data = await _fetch_json(client, url)
    if not data or not data.get("data"):
        return []
    diff = data["data"].get("diff", {})
    items = list(diff.values()) if isinstance(diff, dict) else diff
    return [
        {
            "name": item.get("f14"),
            "change_pct": item.get("f3"),
            "turnover_pct": item.get("f8"),
        }
        for item in items[:top_n]
    ]


async def _get_top_gainers(client: httpx.AsyncClient, top_n: int = 10) -> list[dict]:
    """Top gaining individual stocks today."""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=1&np=1&ut={_EM_UT}&fltt=2&invt=2&fid=f3"
        f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        f"&fields=f2,f3,f4,f8,f12,f14"
    )
    data = await _fetch_json(client, url)
    if not data or not data.get("data"):
        return []
    diff = data["data"].get("diff", {})
    items = list(diff.values()) if isinstance(diff, dict) else diff
    return [
        {
            "name": item.get("f14"),
            "code": item.get("f12"),
            "price": item.get("f2"),
            "change_pct": item.get("f3"),
        }
        for item in items[:top_n]
    ]


async def _get_top_losers(client: httpx.AsyncClient, top_n: int = 10) -> list[dict]:
    """Top losing individual stocks today."""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=0&np=1&ut={_EM_UT}&fltt=2&invt=2&fid=f3"
        f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        f"&fields=f2,f3,f4,f8,f12,f14"
    )
    data = await _fetch_json(client, url)
    if not data or not data.get("data"):
        return []
    diff = data["data"].get("diff", {})
    items = list(diff.values()) if isinstance(diff, dict) else diff
    return [
        {
            "name": item.get("f14"),
            "code": item.get("f12"),
            "price": item.get("f2"),
            "change_pct": item.get("f3"),
        }
        for item in items[:top_n]
    ]


@cached(ttl=180)
async def scan_market_hotspots() -> dict:
    """Scan eastmoney APIs in parallel for current market snapshot."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        indices, concepts, industries, gainers, losers = await asyncio.gather(
            _get_indices(client),
            _get_concept_boards(client),
            _get_industry_boards(client),
            _get_top_gainers(client),
            _get_top_losers(client),
        )

    return {
        "instruction": (
            "Below is a real-time market snapshot from 东方财富 APIs. "
            "Synthesize this into a clear answer about current market hotspots. "
            "Highlight which concept/industry boards are surging and why they might be hot. "
            "Mention specific top-gaining stocks and which sectors they belong to. "
            "If user asked in Chinese, respond in Chinese."
        ),
        "market_indices": indices,
        "hot_concept_boards_top20": concepts,
        "hot_industry_boards_top15": industries,
        "top_gainers_today": gainers,
        "top_losers_today": losers,
    }
