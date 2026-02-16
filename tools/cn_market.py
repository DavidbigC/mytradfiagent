import asyncio
import httpx
import akshare as ak
from tools.cache import cached

TOOL_TIMEOUT = 30


def _tencent_quote_batch(codes: list[str]) -> dict[str, dict]:
    """Fast batch quote from Tencent finance API — returns PE, PB, dividend yield, price."""
    symbols = ",".join(
        f"sh{c}" if c.startswith(("6", "5")) else f"sz{c}" for c in codes
    )
    resp = httpx.get(
        f"https://qt.gtimg.cn/q={symbols}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    results = {}
    for line in resp.text.strip().split("\n"):
        parts = line.split("~")
        if len(parts) < 50:
            continue
        code = parts[2]
        results[code] = {
            "股票名称": parts[1],
            "股票代码": code,
            "最新价": _to_float(parts[3]),
            "昨收": _to_float(parts[4]),
            "涨跌额": _to_float(parts[31]),
            "涨跌幅": _to_float(parts[32]),
            "最高": _to_float(parts[33]),
            "最低": _to_float(parts[34]),
            "成交量": _to_int(parts[36]),
            "成交额(万)": _to_float(parts[37]),
            "市盈率(动态)": _to_float(parts[39]),
            "市净率": _to_float(parts[46]),
            "股息率(%)": _to_float(parts[64]) if len(parts) > 64 else None,
            "52周最高": _to_float(parts[47]) if len(parts) > 47 else None,
            "52周最低": _to_float(parts[48]) if len(parts) > 48 else None,
            "流通市值(亿)": _to_float(parts[44]) if len(parts) > 44 else None,
            "总市值(亿)": _to_float(parts[45]) if len(parts) > 45 else None,
        }
    return results


def _to_float(s: str):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _to_int(s: str):
    try:
        return int(s)
    except (ValueError, TypeError):
        return None

FETCH_CN_STOCK_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_cn_stock_data",
        "description": "Fetch Chinese A-share stock data. Gets real-time quotes or historical prices.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Chinese stock code (e.g. '600519' for Kweichow Moutai, '000858' for Wuliangye)"},
                "info_type": {
                    "type": "string",
                    "enum": ["quote", "history"],
                    "description": "'quote' for current data, 'history' for historical prices",
                },
                "period": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "Frequency for historical data (default 'daily')",
                    "default": "daily",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to return for history (default 60)",
                    "default": 60,
                },
            },
            "required": ["symbol", "info_type"],
        },
    },
}

FETCH_MULTIPLE_CN_STOCKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_multiple_cn_stocks",
        "description": (
            "Fetch Chinese A-share data for multiple stock codes at once in PARALLEL. "
            "ALWAYS use this instead of fetch_cn_stock_data when comparing 2+ stocks. "
            "Returns price, PE, change%, volume, market cap for each stock. "
            "Common codes: 招商银行=600036, 工商银行=601398, 上海银行=601229, 建设银行=601939, "
            "农业银行=601288, 中国银行=601988, 贵州茅台=600519, 五粮液=000858, 中国平安=601318."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Chinese stock codes (e.g. ['600036', '601398', '601229'])",
                },
                "info_type": {
                    "type": "string",
                    "enum": ["quote", "history"],
                    "description": "'quote' for current price+fundamentals, 'history' for price history",
                },
            },
            "required": ["symbols", "info_type"],
        },
    },
}

FETCH_CN_BOND_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_cn_bond_data",
        "description": "Fetch Chinese bond market data including government bond yields.",
        "parameters": {
            "type": "object",
            "properties": {
                "bond_type": {
                    "type": "string",
                    "enum": ["treasury_yield", "corporate"],
                    "description": "'treasury_yield' for China government bond yields, 'corporate' for corporate bond data",
                },
            },
            "required": ["bond_type"],
        },
    },
}


def _fetch_cn_stock_data_sync(symbol: str, info_type: str, period: str = "daily", days: int = 60) -> dict:
    if info_type == "quote":
        # Primary: Tencent API — fast, returns PE/PB/dividend yield
        try:
            quotes = _tencent_quote_batch([symbol])
            if symbol in quotes:
                return quotes[symbol]
        except Exception:
            pass
        # Fallback: akshare
        try:
            df = ak.stock_individual_info_em(symbol=symbol)
            if df.empty:
                return {"error": f"Stock {symbol} not found"}
            info = dict(zip(df["item"], df["value"]))
            return {str(k): _safe_value(v) for k, v in info.items()}
        except Exception as e:
            return {"error": f"Failed to fetch quote: {e}"}

    if info_type == "history":
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq")
            if df.empty:
                return {"error": f"No history for {symbol}"}
            df = df.tail(days)
            records = df.to_dict(orient="records")
            for r in records:
                for k, v in r.items():
                    r[k] = _safe_value(v)
            return {"symbol": symbol, "period": period, "data": records}
        except Exception as e:
            return {"error": f"Failed to fetch history: {e}"}

    return {"error": f"Unknown info_type: {info_type}"}


def _fetch_cn_bond_data_sync(bond_type: str) -> dict:
    if bond_type == "treasury_yield":
        try:
            df = ak.bond_zh_us_rate(start_date="20240101")
            if df.empty:
                return {"error": "No treasury yield data"}
            df = df.tail(30)
            records = df.to_dict(orient="records")
            for r in records:
                for k, v in r.items():
                    r[k] = _safe_value(v)
            return {"type": "china_treasury_yields", "data": records}
        except Exception as e:
            return {"error": f"Failed to fetch treasury yields: {e}"}

    if bond_type == "corporate":
        try:
            df = ak.bond_china_close_return_map()
            if df.empty:
                return {"error": "No corporate bond data"}
            records = df.to_dict(orient="records")
            for r in records:
                for k, v in r.items():
                    r[k] = _safe_value(v)
            return {"type": "corporate_bonds", "data": records}
        except Exception as e:
            return {"error": f"Failed to fetch corporate bond data: {e}"}

    return {"error": f"Unknown bond_type: {bond_type}"}


@cached(ttl=300)
async def fetch_cn_stock_data(symbol: str, info_type: str, period: str = "daily", days: int = 60) -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_cn_stock_data_sync, symbol, info_type, period, days),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching {symbol} (>{TOOL_TIMEOUT}s)"}


@cached(ttl=300)
async def fetch_multiple_cn_stocks(symbols: list[str], info_type: str) -> dict:
    if info_type == "quote":
        # Single HTTP call for all quotes via Tencent API
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_tencent_quote_batch, symbols),
                timeout=TOOL_TIMEOUT,
            )
            # Fill in any missing symbols with akshare fallback
            missing = [s for s in symbols if s not in result]
            if missing:
                for sym in missing:
                    try:
                        r = await asyncio.wait_for(
                            asyncio.to_thread(_fetch_cn_stock_data_sync, sym, "quote"),
                            timeout=TOOL_TIMEOUT,
                        )
                        result[sym] = r
                    except asyncio.TimeoutError:
                        result[sym] = {"error": f"Timeout fetching {sym}"}
            return result
        except asyncio.TimeoutError:
            return {s: {"error": "Timeout"} for s in symbols}

    # For history, parallel fetch
    async def _fetch_one(sym):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_cn_stock_data_sync, sym, info_type),
                timeout=TOOL_TIMEOUT,
            )
            return sym, result
        except asyncio.TimeoutError:
            return sym, {"error": f"Timeout fetching {sym}"}

    results = await asyncio.gather(*[_fetch_one(s) for s in symbols])
    return {sym: data for sym, data in results}


@cached(ttl=300)
async def fetch_cn_bond_data(bond_type: str) -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_cn_bond_data_sync, bond_type),
            timeout=TOOL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching bond data (>{TOOL_TIMEOUT}s)"}


def _safe_value(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v
