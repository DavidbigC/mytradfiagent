"""Capital flow data for Chinese A-share stocks via EastMoney APIs.

Provides:
- Individual stock capital flow (daily, ~120 trading days)
- Northbound flow via scraping daily EastMoney summary articles
- Capital flow rankings (top stocks by institutional net buying)
"""

import re
import logging
import httpx

logger = logging.getLogger(__name__)

_BASE = "https://push2.eastmoney.com/api/qt"
_BASE_HIS = "https://push2his.eastmoney.com/api/qt"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 15


def _secid(code: str) -> str:
    """Convert 6-digit stock code to EastMoney secid format."""
    if code.startswith("6") or code.startswith("5"):
        return f"1.{code}"
    return f"0.{code}"


def _fmt_yuan(v) -> str | None:
    """Format yuan value to readable string (亿/万)."""
    if v is None or v == "-":
        return None
    try:
        v = float(v)
    except (ValueError, TypeError):
        return None
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


# ── Tool schemas ─────────────────────────────────────────────────────

FETCH_STOCK_CAPITAL_FLOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_stock_capital_flow",
        "description": (
            "Fetch historical daily capital flow data for a Chinese A-share stock. "
            "Shows main force (institutional) vs retail net buying/selling broken down by order size: "
            "super-large (>100万), large (20-100万), medium (4-20万), small (<4万). "
            "Returns ~120 trading days (~6 months). Use this to understand who is buying/selling a stock."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600519', '000001', '002028'",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to return (default 20, max ~120)",
                    "default": 20,
                },
            },
            "required": ["stock_code"],
        },
    },
}

FETCH_NORTHBOUND_FLOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_northbound_flow",
        "description": (
            "Fetch recent northbound (北向资金/沪深港通) capital flow data by scraping EastMoney's "
            "daily summary articles. Returns total northbound trading volume as % of market, "
            "plus the top-3 most-traded stocks for Shanghai Connect (沪股通) and Shenzhen Connect "
            "(深股通) with exact trade amounts. More accurate than the old API which discontinued "
            "net inflow/outflow data after Aug 2024."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to return (default 5, max 20)",
                    "default": 5,
                },
            },
            "required": [],
        },
    },
}

FETCH_CAPITAL_FLOW_RANKING_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_capital_flow_ranking",
        "description": (
            "Fetch today's capital flow ranking — top stocks by institutional (main force) "
            "net inflow or outflow. Shows which stocks institutions are buying or selling most heavily. "
            "Use this for market-wide sentiment: 'what are institutions buying today?'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["inflow", "outflow"],
                    "description": "Rank by net inflow (institutions buying) or outflow (institutions selling). Default: inflow.",
                    "default": "inflow",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of stocks to return (default 20, max 50)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
}


# ── Tool implementations ─────────────────────────────────────────────

async def fetch_stock_capital_flow(stock_code: str, days: int = 20) -> dict:
    """Fetch daily capital flow history for a single stock."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    days = min(max(days, 1), 120)
    secid = _secid(code)

    url = f"{_BASE_HIS}/stock/fflow/daykline/get"
    params = {
        "lmt": 0,  # fetch all available
        "klt": 101,  # daily
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=_UA)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch capital flow: {e}"}

    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return {"error": f"No capital flow data for {code}", "stock_code": code}

    name = data.get("data", {}).get("name", code)

    # Parse kline data — take the most recent N days
    records = []
    for line in klines[-days:]:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        records.append({
            "date": parts[0],
            "main_net_inflow": _fmt_yuan(parts[1]),       # 主力净流入
            "main_net_ratio": f"{parts[6]}%",              # 主力净比
            "super_large_net": _fmt_yuan(parts[4]),        # 超大单净流入 >100万
            "large_net": _fmt_yuan(parts[5]),              # 大单净流入 20-100万
            "medium_net": _fmt_yuan(parts[2]),             # 中单净流入 4-20万
            "small_net": _fmt_yuan(parts[3]),              # 小单净流入 <4万
            "close": parts[11] if len(parts) > 11 else None,
        })

    # Summary stats for the period
    raw_main = []
    for line in klines[-days:]:
        parts = line.split(",")
        try:
            raw_main.append(float(parts[1]))
        except (ValueError, IndexError):
            pass

    total_main = sum(raw_main) if raw_main else 0
    buy_days = sum(1 for v in raw_main if v > 0)
    sell_days = sum(1 for v in raw_main if v < 0)

    return {
        "stock_code": code,
        "stock_name": name,
        "period": f"Last {len(records)} trading days",
        "summary": {
            "total_main_net_inflow": _fmt_yuan(total_main),
            "buy_days": buy_days,
            "sell_days": sell_days,
            "trend": "net_buying" if total_main > 0 else "net_selling",
        },
        "daily_flow": records,
    }


# EastMoney article listing API — column 399 = 北向资金动态
_NB_LIST_API = (
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    "?column=399&biz=web_stock&client=web&req_trace=nb&pageSize={size}&pageIndex=1"
)

# Parses the article summary, e.g.:
# "交易所最新数据显示，2月13日北向资金共成交2696.41亿元，占两市总成交额的13.60%。
#  紫金矿业、贵州茅台、寒武纪位列沪股通成交前三，成交额分别为25.26亿、21.84亿、18.75亿；
#  宁德时代、天孚通信、中际旭创位列深股通成交前三，成交额分别为38.95亿、34.96亿、27.09亿。"
_DESC_RE = re.compile(
    r"(\d+月\d+日)北向资金共成交([\d.]+)亿元，占两市总成交额的([\d.]+)%。"
    r"(.+?)、(.+?)、(.+?)位列沪股通成交前三，成交额分别为([\d.]+)亿、([\d.]+)亿、([\d.]+)亿；"
    r"(.+?)、(.+?)、(.+?)位列深股通成交前三，成交额分别为([\d.]+)亿、([\d.]+)亿、([\d.]+)亿"
)


def _parse_nb_summary(summary: str) -> dict | None:
    m = _DESC_RE.search(summary)
    if not m:
        return None
    date, total, pct, sh1, sh2, sh3, sha1, sha2, sha3, sz1, sz2, sz3, sza1, sza2, sza3 = m.groups()
    return {
        "date": date,
        "total_amount_亿": float(total),
        "market_share_pct": float(pct),
        "shanghai_connect_top3": [
            {"name": sh1.strip(), "amount_亿": float(sha1)},
            {"name": sh2.strip(), "amount_亿": float(sha2)},
            {"name": sh3.strip(), "amount_亿": float(sha3)},
        ],
        "shenzhen_connect_top3": [
            {"name": sz1.strip(), "amount_亿": float(sza1)},
            {"name": sz2.strip(), "amount_亿": float(sza2)},
            {"name": sz3.strip(), "amount_亿": float(sza3)},
        ],
    }


async def fetch_northbound_flow(days: int = 5) -> dict:
    """Fetch northbound capital flow from EastMoney daily summary articles."""
    days = min(max(days, 1), 30)
    url = _NB_LIST_API.format(size=days)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={**_UA, "Referer": "https://stock.eastmoney.com/"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch northbound articles: {e}"}

    articles = (data.get("data") or {}).get("list") or []
    if not articles:
        return {"error": "No northbound articles returned", "raw": data}

    collected = []
    for a in articles:
        parsed = _parse_nb_summary(a.get("summary", ""))
        if parsed:
            parsed["title"] = a.get("title", "")
            parsed["published"] = a.get("showTime", "")[:10]
            parsed["url"] = a.get("uniqueUrl", "")
            collected.append(parsed)

    if not collected:
        return {"error": "Articles found but summaries did not match expected format", "sample": articles[0] if articles else None}

    return {
        "source": "EastMoney 北向资金动态 (column 399)",
        "days_found": len(collected),
        "data": collected,
    }


async def fetch_capital_flow_ranking(direction: str = "inflow", limit: int = 20) -> dict:
    """Fetch today's capital flow ranking across all A-shares."""
    limit = min(max(limit, 1), 50)
    # po=1 for descending (top inflow), po=0 for ascending (top outflow)
    po = "1" if direction == "inflow" else "0"

    url = f"{_BASE}/clist/get"
    params = {
        "fid": "f62",  # sort by main force net inflow
        "po": po,
        "pz": limit,
        "pn": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # all A-shares
        "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=_UA)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch flow ranking: {e}"}

    diffs = data.get("data", {}).get("diff", [])
    if not diffs:
        return {"error": "No ranking data available (market may be closed)"}

    records = []
    for d in diffs:
        records.append({
            "stock_code": d.get("f12"),
            "stock_name": d.get("f14"),
            "price": d.get("f2"),
            "change_pct": f"{d.get('f3')}%" if d.get("f3") is not None else None,
            "main_net_inflow": _fmt_yuan(d.get("f62")),
            "main_net_ratio": f"{d.get('f184')}%" if d.get("f184") is not None else None,
            "super_large_net": _fmt_yuan(d.get("f66")),
            "large_net": _fmt_yuan(d.get("f72")),
            "small_net": _fmt_yuan(d.get("f84")),
        })

    return {
        "direction": direction,
        "description": "Top stocks by institutional net inflow" if direction == "inflow" else "Top stocks by institutional net outflow",
        "count": len(records),
        "ranking": records,
    }
