"""Unit tests for ta_strategies tools. DB pool is mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool(fetchrow_return=None, execute_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=execute_return)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_lookup_found():
    from tools.ta_strategies import lookup_ta_strategy
    row = {
        "name": "volume price trend",
        "aliases": ["VPT"],
        "description": "Tracks cumulative volume weighted by price change.",
        "indicators": ["volume", "close"],
        "parameters": {},
        "source_url": "https://example.com",
    }
    pool, _ = _make_pool(fetchrow_return=row)
    with patch("tools.ta_strategies.get_pool", AsyncMock(return_value=pool)):
        result = await lookup_ta_strategy("volume price trend")
    assert result["found"] is True
    assert result["name"] == "volume price trend"


@pytest.mark.asyncio
async def test_lookup_not_found():
    from tools.ta_strategies import lookup_ta_strategy
    pool, _ = _make_pool(fetchrow_return=None)
    with patch("tools.ta_strategies.get_pool", AsyncMock(return_value=pool)):
        result = await lookup_ta_strategy("unknown exotic strategy xyz")
    assert result["found"] is False


@pytest.mark.asyncio
async def test_save_strategy():
    from tools.ta_strategies import save_ta_strategy
    pool, conn = _make_pool()
    with patch("tools.ta_strategies.get_pool", AsyncMock(return_value=pool)):
        result = await save_ta_strategy(
            name="MACD crossover",
            description="Bullish when MACD crosses above signal line.",
            indicators=["MACD", "signal"],
            aliases=["macd cross"],
            parameters={"fast": 12, "slow": 26, "signal": 9},
            source_url="https://investopedia.com/macd",
        )
    assert result["status"] == "saved"
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_update_strategy_found():
    from tools.ta_strategies import update_ta_strategy
    pool, conn = _make_pool()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    with patch("tools.ta_strategies.get_pool", AsyncMock(return_value=pool)):
        result = await update_ta_strategy(
            name="MACD crossover",
            updates={"description": "Updated.", "indicators": ["MACD", "signal", "ATR"]},
        )
    assert result["status"] == "updated"


@pytest.mark.asyncio
async def test_update_strategy_not_found():
    from tools.ta_strategies import update_ta_strategy
    pool, conn = _make_pool()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    with patch("tools.ta_strategies.get_pool", AsyncMock(return_value=pool)):
        result = await update_ta_strategy(
            name="nonexistent strategy",
            updates={"description": "foo"},
        )
    assert result["status"] == "not_found"
