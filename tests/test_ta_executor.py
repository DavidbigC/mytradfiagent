"""Unit tests for ta_executor. subprocess and MiniMax are mocked."""
import asyncio
import os
import sys
import subprocess
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Test import allowlist (actually runs a subprocess)
# ---------------------------------------------------------------------------

def _build_wrapper(user_script: str) -> str:
    from tools.ta_executor import _make_wrapper_script
    return _make_wrapper_script(user_script)


def test_allowlist_blocks_forbidden_import():
    wrapper = _build_wrapper("import requests\n")
    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "TA_DATA": "[]", "TA_OUTPUT_PATH": "/tmp/test_block.html"},
    )
    assert result.returncode != 0
    assert "ImportError" in result.stderr or "blocked" in result.stderr.lower()


def test_allowlist_permits_pandas_ta():
    script = "import pandas as pd; import pandas_ta as ta; print('ok')"
    wrapper = _build_wrapper(script)
    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "TA_DATA": "[]", "TA_OUTPUT_PATH": "/tmp/test_allow.html"},
    )
    assert result.returncode == 0
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# Test retry loop (subprocess and fetch_ohlcv mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_on_first_attempt():
    from tools.ta_executor import run_ta_script

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    output_holder = {}

    async def fake_to_thread(fn, *args, **kwargs):
        path = kwargs.get("env", {}).get("TA_OUTPUT_PATH", "/tmp/test.html")
        open(path, "w").close()
        output_holder["path"] = path
        return mock_result

    ohlcv_data = {"bars": [{"ts": "2026-01-01 09:30", "open": 10.0, "high": 11.0,
                             "low": 9.5, "close": 10.5, "volume": 1000, "amount": 10500.0}]}

    with patch("tools.ta_executor.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("tools.ta_executor.fetch_ohlcv", new=AsyncMock(return_value=ohlcv_data)):
        result = await run_ta_script("600036", "pass")

    assert "file" in result
    assert result["file"].endswith(".html")


@pytest.mark.asyncio
async def test_retry_three_times_then_fail():
    from tools.ta_executor import run_ta_script

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "SyntaxError: invalid syntax"

    async def fake_to_thread(fn, *args, **kwargs):
        return mock_result

    async def fake_rewrite(script, error):
        return script

    ohlcv_data = {"bars": []}

    with patch("tools.ta_executor.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("tools.ta_executor.fetch_ohlcv", new=AsyncMock(return_value=ohlcv_data)), \
         patch("tools.ta_executor._rewrite_script", side_effect=fake_rewrite):
        result = await run_ta_script("600036", "bad code !!!!")

    assert "error" in result
    assert "3 attempts" in result["error"]
    assert "last_error" in result


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    from tools.ta_executor import run_ta_script

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.returncode = 1
            r.stderr = "NameError: name 'df' is not defined"
        else:
            r.returncode = 0
            r.stderr = ""
            path = kwargs.get("env", {}).get("TA_OUTPUT_PATH", "/tmp/test.html")
            open(path, "w").close()
        return r

    async def fake_rewrite(script, error):
        return "import pandas as pd\ndf = pd.DataFrame()\n"

    ohlcv_data = {"bars": []}

    with patch("tools.ta_executor.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("tools.ta_executor.fetch_ohlcv", new=AsyncMock(return_value=ohlcv_data)), \
         patch("tools.ta_executor._rewrite_script", side_effect=fake_rewrite):
        result = await run_ta_script("600036", "# script with bug")

    assert call_count == 2
    assert "file" in result
