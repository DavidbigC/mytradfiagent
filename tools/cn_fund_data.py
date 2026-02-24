"""Historical price and NAV data for Chinese funds (ETF, LOF, open-end)."""
import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import akshare as ak
import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI

from config import get_minimax_config
from tools.cache import cached

logger = logging.getLogger(__name__)

load_dotenv()

_MAX_RETRIES = 3
_TIMEOUT_SECONDS = 30
_ALLOWED_IMPORTS = {
    "pandas", "pandas_ta", "plotly", "numpy",
    "json", "os", "pathlib", "math", "datetime",
    "builtins", "sys",
}
_BLOCKED_IMPORTS = {
    "requests", "httpx", "aiohttp", "urllib3",
    "socket", "subprocess", "ftplib", "smtplib",
    "telnetlib", "imaplib", "poplib", "xmlrpc",
}

_mm_api_key, _mm_base_url, _mm_model = get_minimax_config()
_client = AsyncOpenAI(api_key=_mm_api_key, base_url=_mm_base_url)

_BASE_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def _build_dsn() -> str:
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/marketdata")
    p = urlparse(url)
    dbname = p.path.lstrip("/") or "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    return f"postgresql://{p.username or os.getenv('USER', 'postgres')}:{p.password or ''}@{p.hostname or 'localhost'}:{p.port or 5432}/{dbname}"


def _run_async(coro):
    """Run an async coroutine using a new event loop (for sync context in a thread)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db_query_price(dsn: str, fund_code: str, start: date, end: date, bars: int):
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT date, open, high, low, close, volume, amount "
            "FROM fund_price WHERE fund_code = $1 AND date >= $2 AND date <= $3 "
            "ORDER BY date ASC LIMIT $4",
            fund_code, start, end, bars,
        )
        name_row = await conn.fetchrow(
            "SELECT name, type FROM funds WHERE code = $1", fund_code,
        )
        return rows, name_row
    finally:
        await conn.close()


async def _db_query_nav(dsn: str, fund_code: str, start: date, end: date, bars: int):
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT date, unit_nav, accum_nav, daily_return_pct "
            "FROM fund_nav WHERE fund_code = $1 AND date >= $2 AND date <= $3 "
            "ORDER BY date ASC LIMIT $4",
            fund_code, start, end, bars,
        )
        name_row = await conn.fetchrow(
            "SELECT name, type FROM funds WHERE code = $1", fund_code,
        )
        return rows, name_row
    finally:
        await conn.close()


def _fund_name_from_akshare(fund_code: str) -> tuple[str, str]:
    """Return (name, type) from ak.fund_name_em()."""
    try:
        df_names = ak.fund_name_em()
        row = df_names[df_names.iloc[:, 0] == fund_code]
        if not row.empty:
            name = str(row.iloc[0, 1]) if len(row.columns) > 1 else fund_code
            ftype = str(row.iloc[0, 2]) if len(row.columns) > 2 else ""
            return name, ftype
    except Exception:
        pass
    return fund_code, ""


def _parse_dates(start_date: str | None, end_date: str | None) -> tuple[date, date]:
    today = date.today()
    yesterday = today - timedelta(days=1)
    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            end = yesterday
    else:
        end = yesterday
    if start_date:
        try:
            start = date.fromisoformat(start_date)
        except ValueError:
            start = end - timedelta(days=200)
    else:
        start = end - timedelta(days=200)
    return start, end


def _build_price_result(fund_code: str, fund_name: str, fund_type: str,
                         bars_list: list, source: str) -> dict:
    dates = [b["ts"] for b in bars_list]
    closes = [b["close"] for b in bars_list]
    chart_series = [{"name": "收盘价", "x": dates, "y": closes}]
    latest = bars_list[-1]
    first = bars_list[0]
    period_high = max(b["high"] for b in bars_list)
    period_low = min(b["low"] for b in bars_list)
    change_pct = round((latest["close"] - first["close"]) / first["close"] * 100, 2) if first["close"] else 0
    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "fund_type": fund_type,
        "data_type": "price",
        "bar_count": len(bars_list),
        "period": {"from": bars_list[0]["ts"], "to": bars_list[-1]["ts"]},
        "summary": {
            "latest_close": latest["close"],
            "period_high": period_high,
            "period_low": period_low,
            "change_pct": change_pct,
        },
        "bars": bars_list,
        "chart_series": chart_series,
        "source": source,
    }


def _build_nav_result(fund_code: str, fund_name: str, fund_type: str,
                       bars_list: list, source: str) -> dict:
    dates = [b["ts"] for b in bars_list]
    unit_navs = [b["unit_nav"] for b in bars_list]
    accum_navs = [b["accum_nav"] for b in bars_list]
    chart_series = [
        {"name": "单位净值", "x": dates, "y": unit_navs},
        {"name": "累计净值", "x": dates, "y": accum_navs},
    ]
    latest = bars_list[-1]
    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "fund_type": fund_type,
        "data_type": "nav",
        "bar_count": len(bars_list),
        "period": {"from": bars_list[0]["ts"], "to": bars_list[-1]["ts"]},
        "summary": {
            "latest_unit_nav": latest["unit_nav"],
            "latest_accum_nav": latest["accum_nav"],
        },
        "bars": bars_list,
        "chart_series": chart_series,
        "source": source,
    }


def _fetch_fund_data_sync(
    fund_code: str,
    data_type: str,
    start_date: str | None,
    end_date: str | None,
    bars: int,
) -> dict:
    start, end = _parse_dates(start_date, end_date)
    dsn = _build_dsn()

    # ── price (OHLCV) ────────────────────────────────────────────────────────
    if data_type == "price":
        db_rows = []
        fund_name = fund_code
        fund_type = ""
        try:
            rows, name_row = _run_async(_db_query_price(dsn, fund_code, start, end, bars))
            db_rows = list(rows)
            if name_row:
                fund_name = name_row["name"] or fund_code
                fund_type = name_row["type"] or ""
        except Exception as e:
            logger.warning(f"fetch_cn_fund_data DB price query failed for {fund_code}: {e}")

        if len(db_rows) >= 5:
            bars_list = []
            for r in db_rows:
                try:
                    d = r["date"]
                    d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
                    bars_list.append({
                        "ts": d_str,
                        "open": round(float(r["open"]), 4),
                        "high": round(float(r["high"]), 4),
                        "low": round(float(r["low"]), 4),
                        "close": round(float(r["close"]), 4),
                        "volume": int(r["volume"]),
                        "amount": round(float(r["amount"]), 2),
                    })
                except Exception:
                    continue
            if bars_list:
                return _build_price_result(fund_code, fund_name, fund_type, bars_list, "db")

        # Fallback to AKShare
        try:
            df = ak.fund_etf_hist_em(
                symbol=fund_code, period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
            )
            if df.empty:
                return {"error": f"No price data found for fund {fund_code}"}

            col_map = {}
            for c in df.columns:
                cl = c.lower()
                if "日期" in c or cl == "date":
                    col_map[c] = "date"
                elif "开盘" in c or cl == "open":
                    col_map[c] = "open"
                elif "最高" in c or cl == "high":
                    col_map[c] = "high"
                elif "最低" in c or cl == "low":
                    col_map[c] = "low"
                elif "收盘" in c or cl == "close":
                    col_map[c] = "close"
                elif "成交量" in c or cl == "volume":
                    col_map[c] = "volume"
                elif "成交额" in c or cl == "amount":
                    col_map[c] = "amount"
            df = df.rename(columns=col_map).tail(bars)

            bars_list = []
            for _, row in df.iterrows():
                try:
                    d = row.get("date", "")
                    d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    bars_list.append({
                        "ts": d_str,
                        "open": round(float(row.get("open", 0)), 4),
                        "high": round(float(row.get("high", 0)), 4),
                        "low": round(float(row.get("low", 0)), 4),
                        "close": round(float(row.get("close", 0)), 4),
                        "volume": int(row.get("volume", 0)),
                        "amount": round(float(row.get("amount", 0)), 2),
                    })
                except Exception:
                    continue

            if not bars_list:
                return {"error": f"No price data parsed for fund {fund_code}"}

            if fund_name == fund_code:
                fund_name, fund_type = _fund_name_from_akshare(fund_code)
            return _build_price_result(fund_code, fund_name, fund_type, bars_list, "akshare")

        except Exception as e:
            return {"error": f"Failed to fetch price data for fund {fund_code}: {e}"}

    # ── nav ──────────────────────────────────────────────────────────────────
    elif data_type == "nav":
        db_rows = []
        fund_name = fund_code
        fund_type = ""
        try:
            rows, name_row = _run_async(_db_query_nav(dsn, fund_code, start, end, bars))
            db_rows = list(rows)
            if name_row:
                fund_name = name_row["name"] or fund_code
                fund_type = name_row["type"] or ""
        except Exception as e:
            logger.warning(f"fetch_cn_fund_data DB nav query failed for {fund_code}: {e}")

        if len(db_rows) >= 5:
            bars_list = []
            for r in db_rows:
                try:
                    d = r["date"]
                    d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
                    daily_ret = r.get("daily_return_pct")
                    bars_list.append({
                        "ts": d_str,
                        "unit_nav": round(float(r["unit_nav"]), 4),
                        "accum_nav": round(float(r["accum_nav"]), 4),
                        "daily_return_pct": float(daily_ret) if daily_ret is not None else None,
                    })
                except Exception:
                    continue
            if bars_list:
                return _build_nav_result(fund_code, fund_name, fund_type, bars_list, "db")

        # Fallback to AKShare
        try:
            df = ak.fund_etf_fund_info_em(
                fund=fund_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if df.empty:
                return {"error": f"No NAV data found for fund {fund_code}"}

            bars_list = []
            for _, row in df.iterrows():
                try:
                    d = row.get("净值日期", row.get("date", None))
                    # Skip NaT rows
                    if d is None or str(d) in ("NaT", "nat"):
                        continue
                    import pandas as pd
                    if isinstance(d, type(pd.NaT)) or (hasattr(d, '__class__') and d.__class__.__name__ == 'NaTType'):
                        continue
                    d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    unit_nav = float(row.get("单位净值", row.get("unit_nav", 0)) or 0)
                    accum_nav = float(row.get("累计净值", row.get("accum_nav", unit_nav)) or unit_nav)
                    daily_ret = row.get("日增长率", row.get("daily_return_pct", None))
                    try:
                        daily_ret = float(daily_ret) if daily_ret is not None else None
                    except (TypeError, ValueError):
                        daily_ret = None
                    bars_list.append({
                        "ts": d_str,
                        "unit_nav": round(unit_nav, 4),
                        "accum_nav": round(accum_nav, 4),
                        "daily_return_pct": daily_ret,
                    })
                except Exception:
                    continue

            bars_list = bars_list[-bars:]
            if not bars_list:
                return {"error": f"No NAV data parsed for fund {fund_code}"}

            if fund_name == fund_code:
                fund_name, fund_type = _fund_name_from_akshare(fund_code)
            return _build_nav_result(fund_code, fund_name, fund_type, bars_list, "akshare")

        except Exception as e:
            return {"error": f"Failed to fetch NAV data for fund {fund_code}: {e}"}

    return {"error": f"Invalid data_type '{data_type}'. Must be 'price' or 'nav'."}


# ── Schemas ──────────────────────────────────────────────────────────────────

FETCH_CN_FUND_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_cn_fund_data",
        "description": (
            "Fetch historical price (OHLCV) or NAV data for a Chinese fund (ETF, LOF, open-end, money market). "
            "Returns data ready to pass directly to generate_chart. "
            "Use data_type='price' for ETF/LOF market price history. "
            "Use data_type='nav' for any fund's net asset value history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "description": "6-digit fund code e.g. '510050'"},
                "data_type": {
                    "type": "string",
                    "enum": ["price", "nav"],
                    "description": "price=OHLCV (ETF/LOF), nav=unit+accum NAV (all types)",
                },
                "start_date": {"type": "string", "description": "YYYY-MM-DD, defaults to 200 days ago"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, defaults to yesterday"},
                "bars": {"type": "integer", "description": "Max data points to return, default 200"},
            },
            "required": ["fund_code", "data_type"],
        },
    },
}

RUN_FUND_CHART_SCRIPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_fund_chart_script",
        "description": (
            "Execute a Python script with pandas-ta + Plotly to generate an interactive TA chart "
            "for a Chinese ETF or LOF using daily OHLCV price data. "
            "Call fetch_cn_fund_data(data_type='price') first to check data availability. "
            "Script receives DATA as a list of daily OHLCV dicts [{ts, open, high, low, close, volume, amount}]. "
            "MANDATORY: include candlestick as first subplot, fig.update_xaxes(type='category'), "
            "use template='plotly_white'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "description": "6-digit ETF or LOF code e.g. '510050'"},
                "script": {
                    "type": "string",
                    "description": (
                        "Self-contained Python script. DATA pre-loaded as [{ts,open,high,low,close,volume,amount}]. "
                        "Start: import pandas as pd; df = pd.DataFrame(DATA). "
                        "Save Plotly fig to OUTPUT_PATH."
                    ),
                },
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "bars": {"type": "integer", "description": "Data points to fetch, default 200, max 500"},
            },
            "required": ["fund_code", "script"],
        },
    },
}


# ── Sandbox helpers (copied from ta_executor.py) ─────────────────────────────

def _get_output_dir() -> str:
    try:
        from agent import user_id_context
        uid = user_id_context.get(None)
        if uid:
            d = os.path.join(_BASE_OUTPUT, str(uid))
            os.makedirs(d, exist_ok=True)
            return d
    except (ImportError, LookupError):
        pass
    os.makedirs(_BASE_OUTPUT, exist_ok=True)
    return _BASE_OUTPUT


def _make_wrapper_script(user_script: str) -> str:
    allowed_repr = repr(_ALLOWED_IMPORTS)
    blocked_repr = repr(_BLOCKED_IMPORTS)
    return f"""\
import builtins as _builtins, json as _json, os as _os, sys as _sys
_ALLOWED = {allowed_repr}
_BLOCKED = {blocked_repr}
_orig_import = _builtins.__import__
def _safe_import(name, *args, **kwargs):
    _frame = _sys._getframe(1)
    if _frame.f_code.co_filename == '<string>':
        base = name.split('.')[0]
        if base in _BLOCKED or base not in _ALLOWED:
            raise ImportError(f"Import '{{name}}' is blocked by the TA sandbox")
    return _orig_import(name, *args, **kwargs)
_builtins.__import__ = _safe_import

DATA = _json.loads(_os.environ['TA_DATA'])
OUTPUT_PATH = _os.environ['TA_OUTPUT_PATH']

# Patch plotly to always embed JS inline — avoids slow external CDN requests
import plotly.io as _pio
_orig_write_html = _pio.write_html
def _patched_write_html(fig, file, **kwargs):
    kwargs.setdefault('include_plotlyjs', True)
    return _orig_write_html(fig, file, **kwargs)
_pio.write_html = _patched_write_html
# Also patch the Figure method which delegates to pio.write_html
try:
    import plotly.basedatatypes as _bdt
    _orig_fig_write_html = _bdt.BaseFigure.write_html
    def _patched_fig_write_html(self, file, **kwargs):
        kwargs.setdefault('include_plotlyjs', True)
        return _orig_fig_write_html(self, file, **kwargs)
    _bdt.BaseFigure.write_html = _patched_fig_write_html
except Exception:
    pass

{user_script}
"""


_SCRIPT_RULES = (
    "The script has access to:\n"
    "  DATA        — list of daily OHLCV dicts: [{ts, open, high, low, close, volume, amount}]\n"
    "                ts is a date string 'YYYY-MM-DD' — use it as-is for Plotly x-axis.\n"
    "  OUTPUT_PATH — str, absolute path to write the Plotly .html file\n"
    "Allowed imports: pandas, pandas_ta, plotly, numpy, json, os, pathlib, math, datetime.\n"
    "MANDATORY Plotly rules:\n"
    "  1. Always call fig.update_xaxes(type='category') — eliminates weekend/holiday gaps.\n"
    "  2. Always use template='plotly_white' or 'simple_white' — light background, never dark.\n"
    "  3. Always include a candlestick chart (go.Candlestick) as the first/top subplot using\n"
    "     open/high/low/close from the DATA. NEVER produce a chart without price candlesticks.\n"
    "TIMESTAMP RULES (critical — violations cause runtime crashes):\n"
    "  - NEVER call .strftime() on a pd.Timestamp or datetime column — it raises an error.\n"
    "  - The ts column in DATA is already a pre-formatted string. Do NOT convert it with\n"
    "    pd.to_datetime() unless you need it for arithmetic (e.g. date diff, resample).\n"
    "  - If you must convert: use df['ts'] = pd.to_datetime(df['ts']) for arithmetic only,\n"
    "    then pass the original string column to Plotly x-axis (not the datetime column).\n"
    "  - For Plotly x-axis always use the string ts values, never Timestamp objects.\n"
    "VISUAL COMPLETENESS RULES:\n"
    "  - Implement EVERY visual element the analysis requires. Never omit an overlay because\n"
    "    it is complex — simplify the algorithm if needed but always draw the result.\n"
    "  - Every trace must have a descriptive name= for the legend.\n"
    "  - Use None separators in a single go.Scatter trace (not one trace per segment) when\n"
    "    drawing many line segments of the same type."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end]).strip()
    return text


async def _call_rewriter(prompt: str) -> str:
    response = await _client.chat.completions.create(
        model=_mm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
    )
    return _strip_fences(response.choices[0].message.content)


async def _polish_script(script: str) -> str:
    prompt = (
        f"Rewrite this Python technical analysis script to be correct and production-quality.\n\n"
        f"STEP 1 — Before rewriting, identify every visual element the script attempts to draw "
        f"(e.g. candlesticks, fractal markers, stroke lines, pivot zones, signals, annotations). "
        f"STEP 2 — Rewrite the script so that every element from Step 1 is implemented correctly "
        f"and present in the output. Fix bugs but do NOT remove any trace, shape, marker, or "
        f"annotation — if an implementation is broken, fix it; never delete it.\n\n"
        f"DRAFT SCRIPT:\n{script}\n\n"
        f"REQUIREMENTS:\n{_SCRIPT_RULES}\n\n"
        f"Return ONLY the improved Python code. No markdown fences. No explanation."
    )
    polished = await _call_rewriter(prompt)
    try:
        compile(polished, "<string>", "exec")
        return polished
    except SyntaxError:
        logger.warning("_polish_script produced invalid syntax, using original draft")
        return script


async def _rewrite_script(script: str, error: str) -> str:
    base_prompt = (
        f"This Python technical analysis script failed. Fix the error without removing any "
        f"visual elements — if a trace or shape is broken, fix it; do not delete it.\n\n"
        f"ERROR:\n{error[:2000]}\n\n"
        f"ORIGINAL SCRIPT:\n{script}\n\n"
        f"REQUIREMENTS:\n{_SCRIPT_RULES}\n\n"
        f"CRITICAL: Return ONLY valid Python code. "
        f"No markdown fences. No explanation. "
        f"Ensure all strings are terminated and all brackets/parentheses are closed."
    )
    prompt = base_prompt
    last_fixed = script
    for attempt in range(3):
        fixed = await _call_rewriter(prompt)
        try:
            compile(fixed, "<string>", "exec")
            return fixed
        except SyntaxError as e:
            logger.warning(f"_rewrite_script attempt {attempt + 1} produced invalid syntax: {e}")
            last_fixed = fixed
            prompt = (
                f"Your previous fix still has a syntax error: {e}\n\n"
                f"Fix ONLY the syntax error. Return ONLY valid Python code, no fences:\n\n{fixed}"
            )
    logger.warning("_rewrite_script exhausted internal retries, returning last output as-is")
    return last_fixed


# ── Public async tools ───────────────────────────────────────────────────────

@cached(ttl=300)
async def fetch_cn_fund_data(
    fund_code: str,
    data_type: str = "price",
    start_date: str | None = None,
    end_date: str | None = None,
    bars: int = 200,
) -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_fund_data_sync, fund_code, data_type, start_date, end_date, bars),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching fund {fund_code}"}


async def run_fund_chart_script(
    fund_code: str,
    script: str,
    start_date: str | None = None,
    end_date: str | None = None,
    bars: int = 200,
) -> dict:
    # 1. Fetch price data
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_fund_data_sync, fund_code, "price", start_date, end_date, min(bars, 500)
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return {"error": f"Timeout fetching price data for fund {fund_code}"}

    if "error" in data:
        return {"error": f"Failed to fetch price data: {data['error']}"}

    bars_data = data["bars"]
    data_json = json.dumps(bars_data)

    # 2. Output path
    output_dir = _get_output_dir()
    ts_str = datetime.now().strftime("%Y%m%d")
    filename = f"fund_ta_{fund_code}_{ts_str}_{uuid.uuid4().hex[:4]}.html"
    output_path = os.path.join(output_dir, filename)

    # 3. Polish + execute
    logger.info(f"run_fund_chart_script pre-flight polish for {fund_code}")
    current_script = await _polish_script(script)
    last_error = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            compile(current_script, "<string>", "exec")
        except SyntaxError as e:
            last_error = f"SyntaxError: {e}"
            logger.warning(f"run_fund_chart_script pre-check syntax error on attempt {attempt} for {fund_code}: {e}")
            current_script = await _rewrite_script(current_script, last_error)
            try:
                compile(current_script, "<string>", "exec")
            except SyntaxError as e2:
                last_error = f"SyntaxError after rewrite: {e2}"
                logger.warning(f"run_fund_chart_script rewrite still invalid for {fund_code}: {e2}")
                if attempt >= _MAX_RETRIES:
                    break
                continue

        wrapper = _make_wrapper_script(current_script)

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", wrapper],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env={
                    **os.environ,
                    "TA_DATA": data_json,
                    "TA_OUTPUT_PATH": output_path,
                    "PYTHONWARNINGS": "ignore::FutureWarning",
                },
            )
        except subprocess.TimeoutExpired:
            last_error = f"Script timed out after {_TIMEOUT_SECONDS}s"
            logger.warning(f"run_fund_chart_script attempt {attempt} timed out for {fund_code}")
            if attempt < _MAX_RETRIES:
                current_script = await _rewrite_script(current_script, last_error)
            continue

        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"run_fund_chart_script succeeded for {fund_code} on attempt {attempt}")
            out = {
                "file": output_path,
                "message": "Fund TA chart generated successfully. The interactive chart link appears automatically in the UI — do not include the file path in your response.",
                "fund_code": fund_code,
                "bars_used": len(bars_data),
            }
            if result.stdout and result.stdout.strip():
                out["text"] = result.stdout.strip()
            return out

        last_error = result.stderr or result.stdout or "Script exited with non-zero code"
        logger.warning(f"run_fund_chart_script attempt {attempt} failed for {fund_code}: {last_error[:200]}")

        if attempt < _MAX_RETRIES:
            current_script = await _rewrite_script(current_script, last_error)

    return {
        "error": f"Could not generate fund TA chart after {_MAX_RETRIES} attempts",
        "last_error": last_error[:1000],
        "fund_code": fund_code,
    }
