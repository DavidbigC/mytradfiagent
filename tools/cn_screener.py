import asyncio
import logging
import httpx
from tools.cache import cached

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = 15

SCREEN_CN_STOCKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "screen_cn_stocks",
        "description": (
            "Screen and rank Chinese A-share stocks (SSE + SZSE) using TradingView data. "
            "Returns real-time data for ~5,200 stocks. Use this for:\n"
            "- Market cap rankings: sort_by='market_cap_basic' (市值排名)\n"
            "- Top gainers/losers: sort_by='change' (涨跌幅)\n"
            "- Most active: sort_by='volume' or sort_by='Value.Traded' (成交量/成交额)\n"
            "- High dividend: sort_by='dividend_yield_recent' (高股息)\n"
            "- Screener: combine filters like market_cap > X, PE < Y, dividend > Z\n"
            "- Single stock lookup: use filters with stock code\n"
            "Returns: price, change%, volume, market cap, PE, PB, dividend yield, ROE, ROA, margins, "
            "revenue, net income, free cash flow, total assets, debt, EPS, 52-week range, technicals, sector, industry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "description": (
                        "Field to sort by. Common values: "
                        "market_cap_basic (市值), change (涨跌幅), volume (成交量), "
                        "Value.Traded (成交额), dividend_yield_recent (股息率), "
                        "price_earnings_ttm (市盈率), price_book_ratio (市净率), "
                        "return_on_equity (ROE), gross_margin (毛利率), net_margin (净利率), "
                        "total_assets (总资产), free_cash_flow (自由现金流), "
                        "relative_volume_10d_calc (异常放量), RSI, beta_1_year, "
                        "Perf.W / Perf.1M / Perf.3M / Perf.6M / Perf.Y / Perf.YTD (区间涨幅)"
                    ),
                    "default": "market_cap_basic",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["desc", "asc"],
                    "description": "Sort order. 'desc' for largest/highest first, 'asc' for smallest/lowest first.",
                    "default": "desc",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results (default 10, max 50)",
                    "default": 10,
                },
                "filters": {
                    "type": "array",
                    "description": (
                        "Optional filters. Each filter: {field, op, value}. "
                        "ops: 'greater', 'less', 'equal', 'not_equal', 'in_range'. "
                        "Examples: {field:'market_cap_basic', op:'greater', value:100000000000} for mcap>1000亿, "
                        "{field:'price_earnings_ttm', op:'less', value:15} for PE<15, "
                        "{field:'dividend_yield_recent', op:'greater', value:3} for yield>3%, "
                        "{field:'return_on_equity', op:'greater', value:20} for ROE>20%, "
                        "{field:'sector', op:'equal', value:'Finance'}, "
                        "{field:'sector', op:'not_equal', value:'Finance'} exclude Finance, "
                        "{field:'name', op:'in_range', value:['600519','601398']} specific stocks, "
                        "{field:'exchange', op:'in_range', value:['SSE']} for SSE only"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "op": {"type": "string", "enum": ["greater", "less", "equal", "not_equal", "in_range"]},
                            "value": {},
                        },
                        "required": ["field", "op", "value"],
                    },
                },
            },
            "required": [],
        },
    },
}

# Default columns — comprehensive set covering price, valuation, fundamentals, technicals
_DEFAULT_COLUMNS = [
    "name", "description", "close", "change", "change_abs",
    "volume", "Value.Traded", "market_cap_basic",
    "price_earnings_ttm", "price_book_ratio", "dividend_yield_recent",
    "return_on_equity", "return_on_assets",
    "gross_margin", "operating_margin", "net_margin",
    "total_revenue", "net_income", "gross_profit", "free_cash_flow",
    "total_assets", "total_debt", "debt_to_equity", "current_ratio",
    "earnings_per_share_diluted_ttm",
    "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.Y", "Perf.YTD",
    "price_52_week_high", "price_52_week_low",
    "SMA50", "SMA200", "RSI",
    "sector", "industry",
]

_COLUMN_LABELS = {
    "name": "代码",
    "description": "名称",
    "close": "最新价",
    "change": "涨跌幅(%)",
    "change_abs": "涨跌额",
    "volume": "成交量",
    "Value.Traded": "成交额",
    "market_cap_basic": "总市值(亿)",
    "price_earnings_ttm": "市盈率",
    "price_book_ratio": "市净率",
    "dividend_yield_recent": "股息率(%)",
    "return_on_equity": "ROE(%)",
    "return_on_assets": "ROA(%)",
    "gross_margin": "毛利率(%)",
    "operating_margin": "营业利润率(%)",
    "net_margin": "净利率(%)",
    "total_revenue": "营收(亿)",
    "net_income": "净利润(亿)",
    "gross_profit": "毛利润(亿)",
    "free_cash_flow": "自由现金流(亿)",
    "total_assets": "总资产(亿)",
    "total_debt": "总负债(亿)",
    "debt_to_equity": "资产负债率",
    "current_ratio": "流动比率",
    "earnings_per_share_diluted_ttm": "每股收益",
    "Perf.W": "周涨幅(%)",
    "Perf.1M": "月涨幅(%)",
    "Perf.3M": "季涨幅(%)",
    "Perf.6M": "半年涨幅(%)",
    "Perf.Y": "年涨幅(%)",
    "Perf.YTD": "年初至今(%)",
    "price_52_week_high": "52周最高",
    "price_52_week_low": "52周最低",
    "SMA50": "MA50",
    "SMA200": "MA200",
    "RSI": "RSI",
    "sector": "板块",
    "industry": "行业",
}

# Fields that should be converted from raw CNY to 亿
_YI_FIELDS = {
    "market_cap_basic", "total_revenue", "net_income", "Value.Traded",
    "gross_profit", "free_cash_flow", "total_assets", "total_debt",
}


def _format_value(col: str, val):
    if val is None:
        return None
    if col in _YI_FIELDS and isinstance(val, (int, float)):
        return round(val / 1e8, 2)
    if isinstance(val, float):
        return round(val, 2)
    return val


def _screen_sync(
    sort_by: str = "market_cap_basic",
    sort_order: str = "desc",
    limit: int = 10,
    filters: list | None = None,
) -> dict:
    limit = min(max(limit, 1), 50)

    api_filters = [
        {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    ]
    if filters:
        for f in filters:
            api_filters.append({
                "left": f["field"],
                "operation": f["op"],
                "right": f["value"],
            })

    payload = {
        "columns": _DEFAULT_COLUMNS,
        "filter": api_filters,
        "ignore_unknown_fields": True,
        "options": {"lang": "zh"},
        "range": [0, limit],
        "sort": {"sortBy": sort_by, "sortOrder": sort_order},
        "symbols": {"query": {"types": ["stock"]}},
        "markets": ["china"],
    }

    resp = httpx.post(
        "https://scanner.tradingview.com/china/scan",
        json=payload,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=TOOL_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    stocks = []
    for item in data.get("data", []):
        row = {}
        for i, col in enumerate(_DEFAULT_COLUMNS):
            label = _COLUMN_LABELS.get(col, col)
            raw = item["d"][i] if i < len(item["d"]) else None
            row[label] = _format_value(col, raw)
        stocks.append(row)

    return {
        "total_matches": data.get("totalCount", 0),
        "sort_by": sort_by,
        "sort_order": sort_order,
        "stocks": stocks,
    }


@cached(ttl=120)
async def screen_cn_stocks(
    sort_by: str = "market_cap_basic",
    sort_order: str = "desc",
    limit: int = 10,
    filters: list | None = None,
) -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_screen_sync, sort_by, sort_order, limit, filters),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout screening stocks (>{TOOL_TIMEOUT}s)"}
    except Exception as e:
        logger.error(f"Screen failed: {e}")
        return {"error": str(e)}
