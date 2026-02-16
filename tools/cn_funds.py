import asyncio
import akshare as ak
from tools.cache import cached

TOOL_TIMEOUT = 30

FETCH_CN_FUND_HOLDINGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_cn_fund_holdings",
        "description": "Fetch Chinese mutual fund holdings. Shows the top stock positions of a Chinese fund. Automatically includes basic quote data for each holding.",
        "parameters": {
            "type": "object",
            "properties": {
                "fund_code": {
                    "type": "string",
                    "description": "Chinese fund code (e.g. '000001' for Hua Xia Growth Fund). You can search for fund codes using web_search.",
                },
                "year": {
                    "type": "string",
                    "description": "Year to query (e.g. '2024')",
                },
            },
            "required": ["fund_code", "year"],
        },
    },
}


def _fetch_cn_fund_holdings_sync(fund_code: str, year: str) -> dict:
    try:
        df = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
        if df.empty:
            return {"error": f"No holdings found for fund {fund_code} in {year}"}

        records = df.head(20).to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                r[k] = _safe_value(v)

        return {"fund_code": fund_code, "year": year, "holdings": records}
    except Exception as e:
        return {"error": f"Failed to fetch fund holdings: {e}"}


@cached(ttl=600)
async def fetch_cn_fund_holdings(fund_code: str, year: str) -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_cn_fund_holdings_sync, fund_code, year),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching fund {fund_code} (>{TOOL_TIMEOUT}s)"}


def _safe_value(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v
