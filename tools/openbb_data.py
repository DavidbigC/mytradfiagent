"""OpenBB Platform integration — global market data tool.

Gives the agent access to equity, macro, fixed income, forex, crypto,
ETF, options, news and regulatory data from OpenBB's unified API.

Credentials read from environment:
  FRED_API_KEY   — Federal Reserve Economic Data (free, register at fred.stlouisfed.org)
  FMP_API_KEY    — Financial Modeling Prep (free tier, financialmodelingprep.com)

All other providers used here (yfinance, CBOE, OECD, SEC) require no key.
"""
import asyncio
import os
from functools import lru_cache

from tools.cache import cached

TOOL_TIMEOUT = 60


@lru_cache(maxsize=1)
def _get_obb():
    """Initialize OpenBB once and inject credentials from environment."""
    from openbb import obb  # deferred so import errors surface at call time
    if key := os.getenv("FRED_API_KEY"):
        obb.user.credentials.fred_api_key = key
    if key := os.getenv("FMP_API_KEY"):
        obb.user.credentials.fmp_api_key = key
    return obb


def _call_openbb(command: str, params: dict) -> dict:
    """Navigate obb.<command> and call it with params. Runs in a thread."""
    obb = _get_obb()
    parts = command.strip().split(".")
    obj = obb
    try:
        for part in parts:
            obj = getattr(obj, part)
    except AttributeError:
        raise AttributeError(f"Unknown command path '{command}' (failed at '{part}')")

    result = obj(**params)

    try:
        df = result.to_df()
    except Exception:
        # Some commands return non-DataFrame results
        return {"result": str(result.results)[:8000]}

    if df is None or df.empty:
        return {"result": "No data returned for this query."}

    # Serialize index if it contains dates or other non-string types
    df = df.reset_index()
    for col in df.columns:
        if len(df) > 0 and hasattr(df[col].iloc[0], "isoformat"):
            df[col] = df[col].astype(str)

    rows = len(df)
    display = df.head(150)
    text = display.to_string(index=False)

    return {
        "rows": rows,
        "columns": list(df.columns),
        "data": text if len(text) <= 12000 else text[:12000] + f"\n... (truncated, {rows} total rows)",
    }


@cached(ttl=300)
async def fetch_global_market_data(command: str, params: dict | None = None) -> dict:
    """Fetch data from the OpenBB Platform."""
    if params is None:
        params = {}
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call_openbb, command, params),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"OpenBB call timed out after {TOOL_TIMEOUT}s: {command}"}
    except AttributeError as e:
        return {"error": f"Unknown OpenBB command '{command}': {e}"}
    except Exception as e:
        return {"error": f"OpenBB error ({command}): {e}"}


FETCH_GLOBAL_MARKET_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_global_market_data",
        "description": """Access global financial market data via the OpenBB Platform. Use this for any data
outside the Chinese A-share market: US/global equities, macroeconomic indicators, fixed income,
forex, crypto, ETFs, options, SEC filings, and financial news.

━━ COMMAND REFERENCE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EQUITY (global stocks — use fetch_cn_stock_data for A-shares)
  equity.price.historical   — OHLCV history. params: symbol, start_date, end_date, interval ("1d"/"1wk"), provider ("yfinance")
  equity.price.quote        — Live quote + fundamentals. params: symbol, provider ("yfinance"/"fmp")
  equity.fundamental.income — Income statement. params: symbol, period ("annual"/"quarterly"), provider ("fmp")
  equity.fundamental.balance— Balance sheet. params: symbol, period, provider ("fmp")
  equity.fundamental.cash   — Cash flow statement. params: symbol, period, provider ("fmp")
  equity.fundamental.filings— SEC filings list. params: symbol, form_type ("10-K"/"10-Q"/"8-K"), provider ("sec"/"fmp")
  equity.fundamental.overview — Company overview/profile. params: symbol, provider ("fmp"/"yfinance")
  equity.fundamental.metrics — Key financial ratios/metrics. params: symbol, period, provider ("fmp")
  equity.fundamental.dividends— Dividend history. params: symbol, provider ("fmp"/"yfinance")
  equity.search             — Search stocks by name. params: query, provider ("sec"/"fmp")
  equity.screener.screen    — Screen stocks by criteria. params: provider ("fmp"), metric filters

MACRO / ECONOMY
  economy.gdp.real          — Real GDP by country. params: country ("united_states"/"china"/etc.), start_date, end_date, provider ("oecd"/"fred")
  economy.gdp.nominal       — Nominal GDP. params: country, provider ("oecd")
  economy.cpi               — Inflation / CPI. params: country, start_date, end_date, frequency ("monthly"/"annual"), provider ("fred"/"oecd")
  economy.calendar          — Economic events calendar. params: start_date, end_date, provider ("fmp")
  economy.unemployment      — Unemployment rate. params: country, start_date, end_date, provider ("oecd"/"fred")
  economy.composite_leading_indicator — CLI leading indicator by country. params: country, provider ("oecd")
  economy.short_interest    — Short interest data. params: symbol, provider ("finra")

FIXED INCOME / RATES
  fixedincome.government.treasury_rates — US treasury rates (3m/6m/1y/2y/5y/10y/30y). params: start_date, end_date, provider ("fred")
  fixedincome.government.yield_curve    — Yield curve snapshot by date. params: date (YYYY-MM-DD), country ("us"), provider ("fred")
  fixedincome.government.tips_yields    — TIPS (inflation-protected) yields. params: maturity ("5y"/"10y"/"30y"), start_date, end_date, provider ("fred")
  fixedincome.government.treasury_auctions — Treasury auction data. params: start_date, end_date, provider ("government_us")
  fixedincome.corporate.ice_bofa        — ICE BofA bond indices. params: start_date, end_date, index_type, provider ("fred")
  fixedincome.corporate.moody           — Moody's bond indices. params: start_date, end_date, provider ("fred")
  fixedincome.corporate.spot_rates      — Corporate spot rates. params: start_date, end_date, provider ("fred")
  fixedincome.spreads.treasury_effr     — T-Bill minus Fed Funds Rate spread. params: maturity, start_date, end_date, provider ("fred")

CURRENCY / FOREX
  currency.price.historical — Exchange rate history. params: symbol ("EURUSD"/"USDCNY"/"USDJPY"), start_date, end_date, provider ("yfinance"/"fmp")
  currency.snapshots        — Live rate snapshot for many pairs. params: base ("USD"), provider ("fmp")
  currency.search           — Search available currency pairs. params: provider ("fmp")

CRYPTOCURRENCY
  crypto.price.historical   — Crypto OHLCV. params: symbol ("BTC-USD"/"ETH-USD"), start_date, end_date, provider ("yfinance"/"fmp")
  crypto.search             — Available crypto pairs. params: query, provider ("fmp")

ETF
  etf.historical            — ETF price history. params: symbol, start_date, end_date, provider ("yfinance"/"fmp")
  etf.info                  — ETF description, AUM, expense ratio. params: symbol, provider ("fmp")
  etf.holdings              — ETF top holdings. params: symbol, provider ("fmp")
  etf.price_performance     — Returns over multiple periods. params: symbol, provider ("fmp")
  etf.search                — Search ETFs by name/keyword. params: query, provider ("fmp")

INDEX
  index.historical          — Index OHLCV history. params: symbol ("^GSPC"/"^DJI"/"^IXIC"/"^HSI"), start_date, end_date, provider ("yfinance"/"fmp")
  index.constituents        — Index member stocks. params: index ("sp500"/"nasdaq100"/"dowjones"), provider ("fmp")

DERIVATIVES / OPTIONS
  derivatives.options.chains   — Full options chain with Greeks. params: symbol, provider ("cboe")
  derivatives.options.unusual  — Unusual options activity. params: provider ("intrinio")
  derivatives.futures.curve    — Futures term structure. params: symbol, provider ("yfinance")
  derivatives.futures.historical — Historical futures prices. params: symbol, start_date, end_date, provider ("yfinance")

NEWS
  news.company              — Company-specific news with sentiment. params: symbols (comma-separated), limit (int), provider ("fmp")
  news.world                — Global financial news. params: limit, provider ("fmp")

SEC / REGULATORS
  regulators.sec.filings    — Search SEC EDGAR filings. params: symbol, form_type, provider ("sec")
  regulators.sec.institutions_search — Search registered institutions. params: query, provider ("sec")
  regulators.cftc.cot       — Commitment of Traders report. params: id, provider ("nasdaq")

━━ PROVIDER NOTES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Free / no-key: yfinance, cboe, oecd, sec, government_us, finra
Free key set:  fred (macro, rates, fixed income), fmp (equity fundamentals, news)
Default when no provider specified: usually yfinance or fmp.

━━ SYMBOL FORMATS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
US stocks:     AAPL, MSFT, TSLA
HK stocks:     9988.HK, 0700.HK
Indices:       ^GSPC (S&P500), ^DJI (Dow), ^IXIC (Nasdaq), ^HSI (Hang Seng)
Forex:         EURUSD, USDCNY, GBPUSD (no dash for currency.price.historical)
Crypto:        BTC-USD, ETH-USD (with dash)
Countries:     united_states, china, germany, japan, united_kingdom, france""",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "OpenBB command path, e.g. 'equity.price.historical' or 'economy.cpi' or 'fixedincome.government.yield_curve'",
                },
                "params": {
                    "type": "object",
                    "description": "Command-specific parameters as key-value pairs. Always include 'provider' if you know the best one. Common keys: symbol, start_date (YYYY-MM-DD), end_date, period, country, limit, interval, provider.",
                    "default": {},
                },
            },
            "required": ["command"],
        },
    },
}
