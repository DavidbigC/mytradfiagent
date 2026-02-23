#!/usr/bin/env python3
"""Bulk load 5 years of 5-min OHLCV data from BaoStock into marketdata DB.

Environment variables:
  MARKETDATA_URL   PostgreSQL connection string for the marketdata DB (required)
  CONCURRENCY=3    Parallel BaoStock fetch workers (default 3)
  LOCAL_TEST=1     Limit to 100 stocks per exchange for local dev
"""
import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone, timedelta

import asyncpg
import baostock as bs
from dotenv import load_dotenv
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

load_dotenv()

START_DATE = "2020-01-01"
END_DATE = date.today().isoformat()
BATCH_SIZE = 2000
LOCAL_TEST = os.getenv("LOCAL_TEST", "0") == "1"
LOCAL_LIMIT_PER_EXCHANGE = 100
CONCURRENCY = int(os.getenv("CONCURRENCY", "3"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_dsn() -> str:
    from urllib.parse import urlparse
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")
    p = urlparse(url)
    dbname = p.path.lstrip("/") if p.path and p.path != "/" else "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    user = p.username or os.getenv("USER", "postgres")
    password = p.password or ""
    host = p.hostname or "localhost"
    port = p.port or 5432
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


_CST = timezone(timedelta(hours=8))

def _parse_ts(date_str: str, time_str: str) -> datetime:
    y, mo, d = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    h, m, s = int(time_str[8:10]), int(time_str[10:12]), int(time_str[12:14])
    return datetime(y, mo, d, h, m, s, tzinfo=_CST)


# ── Worker (subprocess — has its own BaoStock login) ──────────────────────────

def _worker_init():
    """Called once per worker process to establish BaoStock session."""
    bs.login()


def _fetch_stock(bs_code: str) -> tuple[str, list]:
    """Fetch and parse all 5-min OHLCV rows for one stock. Runs in subprocess."""
    rs = bs.query_history_k_data_plus(
        bs_code,
        fields="date,time,open,high,low,close,volume,amount",
        start_date=START_DATE,
        end_date=END_DATE,
        frequency="5",
        adjustflag="3",
    )
    exch, code = bs_code.split(".")
    exchange = exch.upper()
    rows = []
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        if not r[2]:
            continue
        date_s, time_s, o, h, l, c, vol, amt = r
        rows.append((
            _parse_ts(date_s, time_s),
            code,
            exchange,
            float(o), float(h), float(l), float(c),
            int(float(vol)),
            float(amt) if amt else None,
        ))
    return bs_code, rows


# ── DB ────────────────────────────────────────────────────────────────────────

_INSERT_SQL = """
    INSERT INTO ohlcv_5m (ts, code, exchange, open, high, low, close, volume, amount)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT DO NOTHING
"""


async def _write(pool: asyncpg.Pool, rows: list) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(_INSERT_SQL, rows)
    return len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    # Use main process BaoStock session only to get stock list, then log out
    lg = bs.login()
    print(f"BaoStock login: {lg.error_msg}")

    rs = bs.query_stock_basic()
    buckets: dict[str, list] = {"SH": [], "SZ": [], "BJ": []}
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        if r[4] != "1" or r[5] != "1":   # type=1 stock, status=1 active
            continue
        exch = r[0].split(".")[0].upper()
        if exch in buckets:
            buckets[exch].append(r[0])
    bs.logout()

    all_stocks = buckets["SH"] + buckets["SZ"] + buckets["BJ"]
    if LOCAL_TEST:
        print(f"LOCAL_TEST: capping at {LOCAL_LIMIT_PER_EXCHANGE} per exchange")
        all_stocks = (
            buckets["SH"][:LOCAL_LIMIT_PER_EXCHANGE] +
            buckets["SZ"][:LOCAL_LIMIT_PER_EXCHANGE] +
            buckets["BJ"][:LOCAL_LIMIT_PER_EXCHANGE]
        )

    pool = await asyncpg.create_pool(_build_dsn(), min_size=2, max_size=CONCURRENCY + 1)
    rows_in_db = await pool.fetch("SELECT DISTINCT LOWER(exchange) || '.' || code FROM ohlcv_5m")
    done = {r[0] for r in rows_in_db}
    todo = [s for s in all_stocks if s not in done]
    print(f"Total: {len(all_stocks):,} | In DB: {len(done):,} | Remaining: {len(todo):,} | Workers: {CONCURRENCY}")

    if not todo:
        print("Nothing to do.")
        return

    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(CONCURRENCY)

    errors: list[tuple[str, str]] = []
    total_rows = 0

    with Progress(
        SpinnerColumn(),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA:"),
        TimeRemainingColumn(),
        TextColumn("[cyan]{task.description}"),
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task("starting...", total=len(todo))

        with ProcessPoolExecutor(max_workers=CONCURRENCY, initializer=_worker_init) as executor:

            async def process_one(bs_code: str):
                nonlocal total_rows
                async with sem:
                    try:
                        code_out, rows = await loop.run_in_executor(executor, _fetch_stock, bs_code)
                        n = await _write(pool, rows)
                        total_rows += n
                        progress.update(task, advance=1, description=f"{code_out}  {n:,} rows  ({total_rows:,} total)")
                    except Exception as e:
                        errors.append((bs_code, str(e)))
                        progress.update(task, advance=1, description=f"[red]ERR {bs_code}: {e}")

            await asyncio.gather(*[process_one(s) for s in todo])

    await pool.close()

    print(f"\n✓ Complete. {total_rows:,} rows inserted. {len(errors)} error(s).")
    for code, err in errors:
        print(f"  ✗ {code}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
