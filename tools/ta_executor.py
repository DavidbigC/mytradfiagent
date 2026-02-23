"""Sandboxed Python code execution for technical analysis chart generation."""
import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime

from openai import AsyncOpenAI
from config import get_minimax_config
from tools.ohlcv import fetch_ohlcv

logger = logging.getLogger(__name__)

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
    # Only enforce sandbox for imports that originate from user code ("<string>").
    # Library internals (site-packages paths) are allowed to import freely.
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
    "  DATA        — list of OHLCV dicts: [{ts, open, high, low, close, volume, amount}]\n"
    "                ts is already a formatted string (e.g. '2024-01-15 09:30') — use it as-is.\n"
    "  OUTPUT_PATH — str, absolute path to write the Plotly .html file\n"
    "Allowed imports: pandas, pandas_ta, plotly, numpy, json, os, pathlib, math, datetime.\n"
    "MANDATORY Plotly rules:\n"
    "  1. Always call fig.update_xaxes(type='category') — eliminates off-hours/weekend gaps.\n"
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
    "  - Plotly trace types for common TA elements:\n"
    "      Fractal points / signals  → go.Scatter(mode='markers', x=ts_vals, y=price_vals)\n"
    "      Stroke / Bi lines         → go.Scatter(mode='lines', x=[ts_a,ts_b], y=[p_a,p_b])\n"
    "        For multiple strokes loop and add one trace per stroke, or build x/y lists with\n"
    "        None separators: x=[ts_a,ts_b,None,ts_c,ts_d,...], y=[p_a,p_b,None,p_c,p_d,...]\n"
    "      Pivot zone / 中枢 rect    → fig.add_shape(type='rect', x0=ts_start, x1=ts_end,\n"
    "                                    y0=low, y1=high, xref='x', yref='y',\n"
    "                                    fillcolor='rgba(255,165,0,0.15)', line_width=1)\n"
    "      Support / resistance line → fig.add_hline(y=price) or go.Scatter(mode='lines')\n"
    "      Buy/sell arrows           → go.Scatter(mode='markers+text') with marker_symbol\n"
    "  - Every trace must have a descriptive name= for the legend.\n"
    "  - Use None separators in a single go.Scatter trace (not one trace per segment) when\n"
    "    drawing many line segments of the same type (e.g. all 笔 in one trace)."
)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end]).strip()
    return text


async def _call_rewriter(prompt: str) -> str:
    """Call the configured LLM and return stripped code content."""
    response = await _client.chat.completions.create(
        model=_mm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
    )
    return _strip_fences(response.choices[0].message.content)


async def _polish_script(script: str) -> str:
    """Pass the agent-drafted script through MiniMax M2.5 for an initial quality pass.
    This runs before the first execution attempt so M2.5 always writes the actual script."""
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
        # Polish produced bad syntax — return original and let the retry loop handle it
        logger.warning("_polish_script produced invalid syntax, using original draft")
        return script


async def _rewrite_script(script: str, error: str) -> str:
    """Ask MiniMax M2.5 to fix a failing script. Validates syntax internally and retries
    the rewrite (not the subprocess) if MiniMax returns syntactically invalid code."""
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
    for attempt in range(3):  # up to 3 rewrite attempts before returning whatever we have
        fixed = await _call_rewriter(prompt)
        try:
            compile(fixed, "<string>", "exec")
            return fixed  # syntactically valid — done
        except SyntaxError as e:
            logger.warning(f"_rewrite_script attempt {attempt + 1} produced invalid syntax: {e}")
            last_fixed = fixed
            # Feed the syntax error back so MiniMax can fix its own output
            prompt = (
                f"Your previous fix still has a syntax error: {e}\n\n"
                f"Fix ONLY the syntax error. Return ONLY valid Python code, no fences:\n\n{fixed}"
            )

    logger.warning("_rewrite_script exhausted internal retries, returning last output as-is")
    return last_fixed


RUN_TA_SCRIPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_ta_script",
        "description": (
            "Execute a Python script that computes technical analysis indicators using pandas-ta "
            "and generates an interactive Plotly chart saved as .html. "
            "OHLCV data is fetched automatically at the requested timeframe before the script runs. "
            "If the script fails, it is automatically rewritten and retried up to 3 times. "
            "Always call lookup_ta_strategy before this tool. "
            "MANDATORY in every script: (1) include a candlestick (go.Candlestick) as the top subplot — never omit price, "
            "(2) call fig.update_xaxes(type='category') to eliminate off-hours gaps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share stock code, e.g. '600036'",
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Self-contained Python script. Must save a Plotly figure to OUTPUT_PATH as .html. "
                        "DATA is pre-loaded as a list of OHLCV dicts: [{ts, open, high, low, close, volume, amount}]. "
                        "Start with: import pandas as pd; df = pd.DataFrame(DATA). "
                        "MANDATORY: fig.update_xaxes(type='category') to skip off-hours gaps. "
                        "MANDATORY: use template='plotly_white' or 'simple_white' — never dark themes."
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["5m", "1h", "1d", "1w"],
                    "description": (
                        "Bar timeframe for OHLCV data. Match to analysis horizon: "
                        "'5m' intraday (default), '1h' swing, '1d' daily TA/MA200, '1w' multi-year trend."
                    ),
                },
                "bars": {
                    "type": "integer",
                    "description": (
                        "Number of bars to fetch (default 500). Max 2000. "
                        "For MA200 on daily: use bars=300. For multi-year weekly: use bars=500."
                    ),
                },
            },
            "required": ["stock_code", "script"],
        },
    },
}


async def run_ta_script(stock_code: str, script: str, timeframe: str = "5m", bars: int = 500) -> dict:
    ohlcv = await fetch_ohlcv(stock_code, bars=min(int(bars), 2000), timeframe=timeframe)
    if "error" in ohlcv:
        return {"error": f"Failed to fetch OHLCV data: {ohlcv['error']}"}

    bars_data = ohlcv.get("bars", [])
    data_json = json.dumps(bars_data)

    output_dir = _get_output_dir()
    ts = datetime.now().strftime("%Y%m%d")
    short_id = uuid.uuid4().hex[:4]
    filename = f"ta_{stock_code}_{ts}_{short_id}.html"
    output_path = os.path.join(output_dir, filename)

    # Pre-flight: let MiniMax M2.5 polish the agent-drafted script before first run
    logger.info(f"run_ta_script pre-flight polish for {stock_code}")
    current_script = await _polish_script(script)
    last_error = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        # Fast syntax check — if invalid, fix before spawning subprocess (doesn't burn an attempt)
        try:
            compile(current_script, "<string>", "exec")
        except SyntaxError as e:
            last_error = f"SyntaxError: {e}"
            logger.warning(f"run_ta_script pre-check syntax error on attempt {attempt} for {stock_code}: {e}")
            current_script = await _rewrite_script(current_script, last_error)
            # _rewrite_script validates internally; if still broken, subprocess will catch it
            try:
                compile(current_script, "<string>", "exec")
            except SyntaxError as e2:
                last_error = f"SyntaxError after rewrite: {e2}"
                logger.warning(f"run_ta_script rewrite still invalid for {stock_code}: {e2}")
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
                env={**os.environ, "TA_DATA": data_json, "TA_OUTPUT_PATH": output_path, "PYTHONWARNINGS": "ignore::FutureWarning"},
            )
        except subprocess.TimeoutExpired:
            last_error = f"Script timed out after {_TIMEOUT_SECONDS}s"
            logger.warning(f"run_ta_script attempt {attempt} timed out for {stock_code}")
            if attempt < _MAX_RETRIES:
                current_script = await _rewrite_script(current_script, last_error)
            continue

        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"run_ta_script succeeded for {stock_code} on attempt {attempt}")
            out = {
                "file": output_path,
                "message": "TA chart generated successfully. The interactive chart link appears automatically in the UI — do not include the file path in your response.",
                "stock_code": stock_code,
                "bars_used": len(bars_data),
            }
            if result.stdout and result.stdout.strip():
                out["text"] = result.stdout.strip()
            return out

        last_error = result.stderr or result.stdout or "Script exited with non-zero code"
        logger.warning(f"run_ta_script attempt {attempt} failed for {stock_code}: {last_error[:200]}")

        if attempt < _MAX_RETRIES:
            current_script = await _rewrite_script(current_script, last_error)

    return {
        "error": f"Could not generate TA chart after {_MAX_RETRIES} attempts",
        "last_error": last_error[:1000],
        "stock_code": stock_code,
    }
