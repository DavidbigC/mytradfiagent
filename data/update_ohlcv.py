#!/usr/bin/env python3
"""Daily incremental update: fetch new 5-min bars since last ingestion.

Checks each stock's individual latest timestamp so no stock is skipped.
Runs 10 parallel worker processes; each owns its own baostock login + DB connection.

Cron (weekdays at 16:30 CST = 08:30 UTC):
  30 8 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_ohlcv.py >> /var/log/ohlcv_update.log 2>&1
"""
import os
import time
import psycopg2
import baostock as bs
from multiprocessing import Pool
from datetime import date
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

WORKERS = 10
DEFAULT_START = date(2020, 1, 1).isoformat()
INSERT_SQL = """
    INSERT INTO ohlcv_5m (ts, code, exchange, open, high, low, close, volume, amount)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""

# Process-level globals (set once per worker process in _proc_init)
_conn = None
_cur = None


def _get_marketdata_conn():
    from urllib.parse import urlparse
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")
    p = urlparse(url)
    dbname = p.path.lstrip("/") if p.path and p.path != "/" else "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    return psycopg2.connect(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=p.username or os.getenv("USER", "postgres"),
        password=p.password or "",
        dbname=dbname,
    )


def _proc_init():
    """Called once per worker process: open baostock session + DB connection."""
    load_dotenv()
    global _conn, _cur
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    _conn = _get_marketdata_conn()
    _cur = _conn.cursor()


def _process_stock(args: tuple) -> tuple[str, int, str | None]:
    """Fetch + insert bars for one stock. Returns (bs_code, rows_inserted, error_or_None)."""
    bs_code, start_date, end_date = args
    exch, code = bs_code.split(".")
    exchange = exch.upper()
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            fields="date,time,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="5",
            adjustflag="3",
        )
        batch = []
        while rs.error_code == "0" and rs.next():
            r = rs.get_row_data()
            date_s, time_s, o, h, l, c, vol, amt = r
            if not o or o == "":
                continue
            h2, m, s = time_s[8:10], time_s[10:12], time_s[12:14]
            batch.append((
                f"{date_s} {h2}:{m}:{s}+08:00", code, exchange,
                float(o), float(h), float(l), float(c),
                int(float(vol)),
                float(amt) if amt else None,
            ))
        if batch:
            _cur.executemany(INSERT_SQL, batch)
            _conn.commit()
        return bs_code, len(batch), None
    except Exception as e:
        _conn.rollback()
        return bs_code, 0, str(e)
    finally:
        time.sleep(0.05)


def main():
    end_date = date.today().isoformat()

    # --- fetch stock universe (main process) ---
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")

    rs = bs.query_stock_basic()
    all_stocks = []
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        if r[4] == "1" and r[5] == "1":
            all_stocks.append(r[0])
    bs.logout()

    if not all_stocks:
        print("No active stocks found.")
        return

    # --- fetch per-stock latest dates ---
    conn = _get_marketdata_conn()
    cur = conn.cursor()
    cur.execute("SELECT code, MAX(ts)::date FROM ohlcv_5m GROUP BY code")
    latest = {row[0]: row[1].isoformat() for row in cur.fetchall()}
    cur.close()
    conn.close()

    # build work list: skip stocks already up to date
    work = []
    for bs_code in all_stocks:
        _, code = bs_code.split(".")
        start = latest.get(code, DEFAULT_START)
        if start < end_date:
            work.append((bs_code, start, end_date))

    if not work:
        print("All stocks already up to date.")
        return

    print(f"Updating {len(work)} stocks to {end_date} with {WORKERS} workers")

    # --- parallel execution ---
    total_rows = 0
    errors = []

    with Pool(processes=WORKERS, initializer=_proc_init) as pool:
        for bs_code, rows, err in tqdm(
            pool.imap_unordered(_process_stock, work),
            total=len(work),
            unit="stock",
        ):
            total_rows += rows
            if err:
                errors.append((bs_code, err))

    print(f"\nUpdate complete. Inserted {total_rows} new rows.")
    if errors:
        print(f"{len(errors)} errors:")
        for code, msg in errors:
            print(f"  {code}: {msg}")


if __name__ == "__main__":
    main()
