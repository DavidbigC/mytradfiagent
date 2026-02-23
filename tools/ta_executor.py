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

{user_script}
"""


async def _rewrite_script(script: str, error: str) -> str:
    prompt = (
        f"The following Python script for technical analysis failed with this error:\n\n"
        f"ERROR:\n{error[:2000]}\n\n"
        f"SCRIPT:\n{script}\n\n"
        f"Fix the script. Return ONLY the corrected Python code, no explanation, no markdown fences. "
        f"The script has access to: DATA (list of OHLCV dicts with keys ts/open/high/low/close/volume/amount), "
        f"OUTPUT_PATH (str, where to write the Plotly .html file). "
        f"Allowed imports: pandas, pandas_ta, plotly, numpy, json, os, pathlib, math, datetime."
    )
    response = await _client.chat.completions.create(
        model=_mm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    fixed = response.choices[0].message.content.strip()
    if fixed.startswith("```"):
        lines = fixed.split("\n")
        fixed = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return fixed


RUN_TA_SCRIPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_ta_script",
        "description": (
            "Execute a Python script that computes technical analysis indicators using pandas-ta "
            "and generates an interactive Plotly chart saved as .html. "
            "The script receives DATA (list of OHLCV dicts) and OUTPUT_PATH (where to save). "
            "If the script fails, it is automatically rewritten and retried up to 3 times. "
            "Always call lookup_ta_strategy before this tool."
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
                        "DATA is pre-loaded as a list of dicts: [{ts, open, high, low, close, volume, amount}]. "
                        "Use: import pandas as pd; df = pd.DataFrame(DATA)"
                    ),
                },
                "bars": {
                    "type": "integer",
                    "description": "Number of 5-min bars to fetch (default 500 ≈ 2 trading weeks). Max 1000.",
                },
            },
            "required": ["stock_code", "script"],
        },
    },
}


async def run_ta_script(stock_code: str, script: str, bars: int = 500) -> dict:
    ohlcv = await fetch_ohlcv(stock_code, bars=min(int(bars), 1000))
    if "error" in ohlcv:
        return {"error": f"Failed to fetch OHLCV data: {ohlcv['error']}"}

    bars_data = ohlcv.get("bars", [])
    data_json = json.dumps(bars_data)

    output_dir = _get_output_dir()
    ts = datetime.now().strftime("%Y%m%d")
    short_id = uuid.uuid4().hex[:4]
    filename = f"ta_{stock_code}_{ts}_{short_id}.html"
    output_path = os.path.join(output_dir, filename)

    current_script = script
    last_error = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        wrapper = _make_wrapper_script(current_script)

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", wrapper],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env={**os.environ, "TA_DATA": data_json, "TA_OUTPUT_PATH": output_path},
            )
        except subprocess.TimeoutExpired:
            last_error = f"Script timed out after {_TIMEOUT_SECONDS}s"
            logger.warning(f"run_ta_script attempt {attempt} timed out for {stock_code}")
            if attempt < _MAX_RETRIES:
                current_script = await _rewrite_script(current_script, last_error)
            continue

        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"run_ta_script succeeded for {stock_code} on attempt {attempt}")
            return {
                "file": output_path,
                "message": f"TA chart saved: {filename}",
                "stock_code": stock_code,
                "bars_used": len(bars_data),
            }

        last_error = result.stderr or result.stdout or "Script exited with non-zero code"
        logger.warning(f"run_ta_script attempt {attempt} failed for {stock_code}: {last_error[:200]}")

        if attempt < _MAX_RETRIES:
            current_script = await _rewrite_script(current_script, last_error)

    return {
        "error": f"Could not generate TA chart after {_MAX_RETRIES} attempts",
        "last_error": last_error[:1000],
        "stock_code": stock_code,
    }
