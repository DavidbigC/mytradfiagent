"""Fetch OHLCV bars from the local marketdata DB for technical analysis.

Supports multiple timeframes via SQL aggregation:
  5m  — raw 5-minute bars (default)
  1h  — hourly   (aggregated server-side, ~3 months per 500 bars)
  1d  — daily    (aggregated server-side, ~2 years per 500 bars)
  1w  — weekly   (aggregated server-side, ~10 years per 500 bars)
"""

import logging
from datetime import datetime, timezone, timedelta

from db import get_marketdata_pool

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# Maps timeframe param → date_trunc unit (None = no aggregation)
_TRUNC = {"5m": None, "1h": "hour", "1d": "day", "1w": "week"}
# Timestamp format for each timeframe
_TS_FMT = {"5m": "%Y-%m-%d %H:%M", "1h": "%Y-%m-%d %H:%M", "1d": "%Y-%m-%d", "1w": "%Y-%m-%d"}

FETCH_OHLCV_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_ohlcv",
        "description": (
            "Fetch OHLCV (candlestick) bars for a Chinese A-share stock from the local market database. "
            "Use for technical analysis, price trends, support/resistance, and TA script data. "
            "Supports multiple timeframes via server-side SQL aggregation — choose based on the analysis horizon:\n"
            "  timeframe='5m'  → intraday (default). 500 bars ≈ 2 trading weeks.\n"
            "  timeframe='1h'  → hourly. 500 bars ≈ 3 months.\n"
            "  timeframe='1d'  → daily. 500 bars ≈ 2 years. Use for daily MA, trend, longer TA.\n"
            "  timeframe='1w'  → weekly. 500 bars ≈ 10 years. Use for multi-year trend analysis.\n"
            "Data available from 2020 onward. Timestamps in CST (UTC+8). "
            "Returns bars + pre-computed MA5/MA20/MA60 on close price."
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
                        "Number of most-recent bars to return (default 200). Max 1000. "
                        "For daily TA indicators like MA200, use bars=250. "
                        "For multi-year weekly charts, use bars=500."
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["5m", "1h", "1d", "1w"],
                    "description": (
                        "Bar timeframe. '5m' = raw 5-min bars (default). "
                        "'1h' hourly, '1d' daily, '1w' weekly — all aggregated in SQL. "
                        "Use '1d' or '1w' for any longer-term TA."
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
    timeframe: str = "5m",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code '{code}'. Must be 6 digits e.g. '600036'."}

    if timeframe not in _TRUNC:
        return {"error": f"Invalid timeframe '{timeframe}'. Must be one of: 5m, 1h, 1d, 1w."}

    bars = min(max(int(bars), 1), 1000)
    trunc_unit = _TRUNC[timeframe]
    ts_fmt = _TS_FMT[timeframe]

    try:
        pool = await get_marketdata_pool()

        if trunc_unit is None:
            # ── Raw 5-minute bars (original behaviour) ──────────────────────
            if start_date or end_date:
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
                    f"FROM ohlcv_5m WHERE {where} ORDER BY ts ASC LIMIT ${len(params) + 1}",
                    *params, bars,
                )
            else:
                rows = await pool.fetch(
                    "SELECT ts, open, high, low, close, volume, amount "
                    "FROM ohlcv_5m WHERE code = $1 ORDER BY ts DESC LIMIT $2",
                    code, bars,
                )
                rows = list(reversed(rows))
        else:
            # ── Aggregated bars (1h / 1d / 1w) ──────────────────────────────
            # open  = first bar's open in the bucket  (array_agg ORDER BY ts ASC)[1]
            # close = last  bar's close in the bucket (array_agg ORDER BY ts DESC)[1]
            # high/low/volume/amount aggregated normally
            agg_select = (
                "date_trunc($2, ts AT TIME ZONE 'Asia/Shanghai') AS bucket, "
                "(array_agg(open  ORDER BY ts ASC))[1]  AS open, "
                "MAX(high)                               AS high, "
                "MIN(low)                                AS low, "
                "(array_agg(close ORDER BY ts DESC))[1] AS close, "
                "SUM(volume)                             AS volume, "
                "SUM(amount)                             AS amount"
            )

            if start_date or end_date:
                conditions = ["code = $1"]
                params = [code, trunc_unit]
                if start_date:
                    conditions.append(f"ts >= ${len(params) + 1}::timestamptz")
                    params.append(start_date)
                if end_date:
                    conditions.append(f"ts < (${len(params) + 1}::date + interval '1 day')::timestamptz")
                    params.append(end_date)
                where = " AND ".join(conditions)
                rows = await pool.fetch(
                    f"SELECT {agg_select} FROM ohlcv_5m WHERE {where} "
                    f"GROUP BY bucket ORDER BY bucket ASC LIMIT ${len(params) + 1}",
                    *params, bars,
                )
            else:
                rows = await pool.fetch(
                    f"SELECT {agg_select} FROM ohlcv_5m WHERE code = $1 "
                    f"GROUP BY bucket ORDER BY bucket DESC LIMIT $3",
                    code, trunc_unit, bars,
                )
                rows = list(reversed(rows))

    except Exception as e:
        logger.error(f"fetch_ohlcv failed for {code} ({timeframe}): {e}")
        return {"error": f"DB query failed: {e}"}

    if not rows:
        return {"stock_code": code, "bars": [], "message": "No OHLCV data found for this stock/date range."}

    # ── Build bar list ───────────────────────────────────────────────────────
    ts_key = "bucket" if trunc_unit else "ts"
    bar_list = []
    for r in rows:
        raw_ts = r[ts_key]
        # 5m bars: tz-aware (TIMESTAMPTZ) → convert to CST
        # aggregated: naive datetime from AT TIME ZONE (already CST)
        if trunc_unit is None:
            ts_str = raw_ts.astimezone(_CST).strftime(ts_fmt)
        else:
            ts_str = raw_ts.strftime(ts_fmt)

        bar_list.append({
            "ts":     ts_str,
            "open":   round(float(r["open"]),   3),
            "high":   round(float(r["high"]),   3),
            "low":    round(float(r["low"]),    3),
            "close":  round(float(r["close"]),  3),
            "volume": int(r["volume"]),
            "amount": round(float(r["amount"]) / 1e4, 2),  # 万元
        })

    closes     = [b["close"]  for b in bar_list]
    volumes    = [b["volume"] for b in bar_list]
    timestamps = [b["ts"]     for b in bar_list]

    ma5  = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)

    latest = bar_list[-1]
    first  = bar_list[0]
    period_high      = max(b["high"] for b in bar_list)
    period_low       = min(b["low"]  for b in bar_list)
    avg_volume       = round(sum(volumes) / len(volumes))
    price_change_pct = round((latest["close"] - first["open"]) / first["open"] * 100, 2)

    def _series(name, values):
        xs, ys = [], []
        for ts, v in zip(timestamps, values):
            if v is not None:
                xs.append(ts)
                ys.append(v)
        return {"name": name, "x": xs, "y": ys}

    chart_series = [
        _series("收盘价", closes),
        _series("MA5",   ma5),
        _series("MA20",  ma20),
        _series("MA60",  ma60),
    ]

    return {
        "stock_code": code,
        "timeframe":  timeframe,
        "bar_count":  len(bar_list),
        "period":     {"from": bar_list[0]["ts"], "to": bar_list[-1]["ts"]},
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
        "bars":         bar_list,
        "chart_series": chart_series,
        "note": (
            f"Timeframe: {timeframe}. Timestamps in CST (UTC+8). amount in 万元. "
            "Use chart_series with generate_chart (type='line') to plot price + MAs, "
            "or pass bars to run_ta_script for pandas-ta indicators."
        ),
    }
