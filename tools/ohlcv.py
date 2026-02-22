"""Fetch 5-minute OHLCV bars from the local marketdata DB for technical analysis."""

import logging
from datetime import datetime, timezone, timedelta

from db import get_marketdata_pool

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

FETCH_OHLCV_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_ohlcv",
        "description": (
            "Fetch 5-minute OHLCV (candlestick) bars for a Chinese A-share stock from the local "
            "market database. Use for technical analysis, price trend charts, support/resistance levels, "
            "or intraday pattern analysis. Returns OHLCV bars plus pre-computed MA5/MA20/MA60 on close "
            "price. Data is available from 2020 onward. Timestamps are in CST (UTC+8). "
            "After fetching, use generate_chart with the returned chart_series to visualise the data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share stock code, e.g. '600036', '000001'",
                },
                "bars": {
                    "type": "integer",
                    "description": (
                        "Number of most-recent 5-min bars to return (default 200 ≈ ~1 trading week). "
                        "Max 1000. Increase for longer-term trend analysis."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional start date filter, ISO format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end date filter, ISO format YYYY-MM-DD (inclusive).",
                },
            },
            "required": ["stock_code"],
        },
    },
}


def _ma(values: list[float], n: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(values)):
        if i < n - 1:
            result.append(None)
        else:
            result.append(round(sum(values[i - n + 1 : i + 1]) / n, 4))
    return result


async def fetch_ohlcv(
    stock_code: str,
    bars: int = 200,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code '{code}'. Must be 6 digits e.g. '600036'."}

    bars = min(max(int(bars), 1), 1000)

    try:
        pool = await get_marketdata_pool()

        if start_date or end_date:
            # Date-range query — fetch all matching bars, newest first, then reverse
            conditions = ["code = $1"]
            params: list = [code]
            if start_date:
                conditions.append(f"ts >= ${len(params) + 1}::timestamptz")
                params.append(start_date)
            if end_date:
                conditions.append(f"ts < (${len(params) + 1}::date + interval '1 day')::timestamptz")
                params.append(end_date)
            where = " AND ".join(conditions)
            rows = await pool.fetch(
                f"SELECT ts, open, high, low, close, volume, amount "
                f"FROM ohlcv_5m WHERE {where} ORDER BY ts ASC LIMIT ${ len(params) + 1}",
                *params, bars,
            )
        else:
            # Most-recent N bars
            rows = await pool.fetch(
                "SELECT ts, open, high, low, close, volume, amount "
                "FROM ohlcv_5m WHERE code = $1 ORDER BY ts DESC LIMIT $2",
                code, bars,
            )
            rows = list(reversed(rows))

    except Exception as e:
        logger.error(f"fetch_ohlcv failed for {code}: {e}")
        return {"error": f"DB query failed: {e}"}

    if not rows:
        return {"stock_code": code, "bars": [], "message": "No OHLCV data found for this stock/date range."}

    # Convert to CST and build bar list
    bar_list = []
    for r in rows:
        ts_cst = r["ts"].astimezone(_CST)
        bar_list.append({
            "ts": ts_cst.strftime("%Y-%m-%d %H:%M"),
            "open":   round(float(r["open"]),   3),
            "high":   round(float(r["high"]),   3),
            "low":    round(float(r["low"]),    3),
            "close":  round(float(r["close"]),  3),
            "volume": int(r["volume"]),
            "amount": round(float(r["amount"]) / 1e4, 2),  # convert to 万元
        })

    closes = [b["close"] for b in bar_list]
    volumes = [b["volume"] for b in bar_list]
    timestamps = [b["ts"] for b in bar_list]

    ma5  = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)

    # Summary stats
    latest = bar_list[-1]
    first  = bar_list[0]
    period_high = max(b["high"] for b in bar_list)
    period_low  = min(b["low"]  for b in bar_list)
    avg_volume  = round(sum(volumes) / len(volumes))
    price_change_pct = round((latest["close"] - first["open"]) / first["open"] * 100, 2)

    # Chart-ready series (non-None MA values only, aligned by timestamp)
    def _series(name, values):
        xs, ys = [], []
        for ts, v in zip(timestamps, values):
            if v is not None:
                xs.append(ts)
                ys.append(v)
        return {"name": name, "x": xs, "y": ys}

    chart_series = [
        _series("收盘价", closes),
        _series("MA5",  ma5),
        _series("MA20", ma20),
        _series("MA60", ma60),
    ]

    return {
        "stock_code": code,
        "bar_count": len(bar_list),
        "period": {"from": bar_list[0]["ts"], "to": bar_list[-1]["ts"]},
        "summary": {
            "latest_close":       latest["close"],
            "period_high":        period_high,
            "period_low":         period_low,
            "price_change_pct":   price_change_pct,
            "avg_volume_per_bar": avg_volume,
            "latest_ma5":         ma5[-1],
            "latest_ma20":        ma20[-1],
            "latest_ma60":        ma60[-1],
        },
        "bars": bar_list,
        "chart_series": chart_series,
        "note": (
            "Timestamps in CST (UTC+8). amount is in 万元. "
            "Use chart_series with generate_chart (type='line') to plot price + MAs."
        ),
    }
