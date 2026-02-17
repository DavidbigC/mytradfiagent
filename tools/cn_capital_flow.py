"""Capital flow data for Chinese A-share stocks via EastMoney APIs.

Provides:
- Individual stock capital flow (daily, ~120 trading days)
- Northbound/southbound flow via Stock Connect (full history since 2014)
- Capital flow rankings (top stocks by institutional net buying)
"""

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
            "Fetch historical northbound (沪深港通) capital flow — foreign money entering/leaving "
            "A-shares via Stock Connect. Shows daily deal amount and deal count for Shanghai Connect "
            "and Shenzhen Connect. Note: net inflow/outflow data was discontinued after Aug 2024 "
            "due to regulatory changes; deal volume is still available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to return (default 30)",
                    "default": 30,
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


async def fetch_northbound_flow(days: int = 30) -> dict:
    """Fetch northbound (Stock Connect) daily flow history."""
    days = min(max(days, 1), 500)

    _DC_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    async def _fetch_type(client: httpx.AsyncClient, mutual_type: str) -> list[dict]:
        params = {
            "reportName": "RPT_MUTUAL_DEAL_HISTORY",
            "columns": "ALL",
            "filter": f'(MUTUAL_TYPE="{mutual_type}")',
            "pageSize": days,
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "p": 1,
            "pageNo": 1,
            "source": "WEB",
            "client": "WEB",
        }
        resp = await client.get(_DC_BASE, params=params, headers={
            **_UA, "Referer": "https://data.eastmoney.com/"
        })
        resp.raise_for_status()
        data = resp.json()
        items = data.get("result", {}).get("data", []) if data.get("result") else []
        records = []
        for item in reversed(items):  # reverse to chronological order
            records.append({
                "date": item["TRADE_DATE"][:10],
                "deal_amount_万": round(item.get("DEAL_AMT") or 0, 2),
                "deal_count": item.get("DEAL_NUM"),
                "lead_stock": f"{item.get('LEAD_STOCKS_NAME', '')}({item.get('LEAD_STOCKS_CODE', '')})",
                "index_change": f"{item.get('INDEX_CHANGE_RATE', '')}%",
            })
        return records

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # 001=combined northbound, 003=Shenzhen Connect, 005=Shanghai Connect...
            # Actually: 001=沪股通(northbound SH), 003=深股通(northbound SZ)
            sh_data = await _fetch_type(client, "001")
            sz_data = await _fetch_type(client, "003")
    except Exception as e:
        return {"error": f"Failed to fetch northbound flow: {e}"}

    # Combine into summary
    total_deal = sum(r["deal_amount_万"] for r in sh_data) + sum(r["deal_amount_万"] for r in sz_data)

    return {
        "note": "Net inflow/outflow data discontinued after Aug 2024 due to regulatory changes. Deal volume and count still available.",
        "period": f"Last {max(len(sh_data), len(sz_data))} trading days",
        "total_deal_amount": _fmt_yuan(total_deal * 1e4),
        "shanghai_connect": sh_data,
        "shenzhen_connect": sz_data,
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
