import asyncio
import yfinance as yf
from tools.cache import cached

TOOL_TIMEOUT = 30  # seconds

FETCH_STOCK_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_stock_data",
        "description": "Fetch stock data from Yahoo Finance. Can get current price, fundamentals, and historical prices for US and global stocks.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock ticker symbol (e.g. AAPL, MSFT, 9988.HK)"},
                "info_type": {
                    "type": "string",
                    "enum": ["quote", "history", "financials"],
                    "description": "Type of data: 'quote' for current price/fundamentals, 'history' for historical prices, 'financials' for income statement/balance sheet",
                },
                "period": {
                    "type": "string",
                    "description": "History period (e.g. '1mo', '3mo', '1y', '5y'). Only used when info_type is 'history'.",
                    "default": "3mo",
                },
            },
            "required": ["symbol", "info_type"],
        },
    },
}

FETCH_MULTIPLE_STOCKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_multiple_stocks",
        "description": "Fetch stock data for multiple symbols at once. Much faster than calling fetch_stock_data multiple times. Use this when you need data for 2 or more stocks.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of stock ticker symbols (e.g. ['AAPL', 'MSFT', 'GOOGL'])",
                },
                "info_type": {
                    "type": "string",
                    "enum": ["quote", "history"],
                    "description": "Type of data to fetch for all symbols",
                },
                "period": {
                    "type": "string",
                    "description": "History period (only for info_type='history')",
                    "default": "3mo",
                },
            },
            "required": ["symbols", "info_type"],
        },
    },
}


def _fetch_stock_data_sync(symbol: str, info_type: str, period: str = "3mo") -> dict:
    ticker = yf.Ticker(symbol)

    if info_type == "quote":
        info = ticker.info
        keys = [
            "shortName", "symbol", "currency", "currentPrice", "previousClose",
            "marketCap", "trailingPE", "forwardPE", "dividendYield",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "sector", "industry",
            "country", "website",
        ]
        return {k: info.get(k) for k in keys if info.get(k) is not None}

    if info_type == "history":
        hist = ticker.history(period=period)
        if hist.empty:
            return {"error": f"No history found for {symbol}"}
        records = hist.reset_index().tail(60).to_dict(orient="records")
        for r in records:
            if hasattr(r.get("Date"), "isoformat"):
                r["Date"] = r["Date"].isoformat()
        return {"symbol": symbol, "period": period, "data": records}

    if info_type == "financials":
        inc = ticker.financials
        if inc is None or inc.empty:
            return {"error": f"No financials found for {symbol}"}
        inc.index = inc.index.astype(str)
        inc.columns = [c.isoformat() if hasattr(c, "isoformat") else str(c) for c in inc.columns]
        return {"symbol": symbol, "income_statement": inc.to_dict()}

    return {"error": f"Unknown info_type: {info_type}"}


@cached(ttl=300)
async def fetch_stock_data(symbol: str, info_type: str, period: str = "3mo") -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_stock_data_sync, symbol, info_type, period),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching {symbol} (>{TOOL_TIMEOUT}s)"}


@cached(ttl=300)
async def fetch_multiple_stocks(symbols: list[str], info_type: str, period: str = "3mo") -> dict:
    async def _fetch_one(sym):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_stock_data_sync, sym, info_type, period),
                timeout=TOOL_TIMEOUT,
            )
            return sym, result
        except asyncio.TimeoutError:
            return sym, {"error": f"Timeout fetching {sym}"}

    results = await asyncio.gather(*[_fetch_one(s) for s in symbols])
    return {sym: data for sym, data in results}
