#!/usr/bin/env python3
"""Bulk load 5 years of 5-min OHLCV data from BaoStock into marketdata DB.

Environment variables:
  MARKETDATA_URL   PostgreSQL connection string for the marketdata DB (required)
  LOCAL_TEST=1     Limit to 100 stocks per exchange (SH/SZ/BJ) for local dev
"""
import os
import time
import psycopg2
import baostock as bs
from datetime import date
from dotenv import load_dotenv

load_dotenv()

CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), ".ingest_checkpoint")
START_DATE = "2020-01-01"
END_DATE = date.today().isoformat()
BATCH_SIZE = 1000
LOCAL_TEST = os.getenv("LOCAL_TEST", "0") == "1"
LOCAL_LIMIT_PER_EXCHANGE = 100


def get_marketdata_conn():
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


def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE) as f:
        return set(line.strip() for line in f if line.strip())


def save_checkpoint(code):
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(code + "\n")


def parse_ts(date_str, time_str):
    # BaoStock time field is "YYYYMMDDHHmmssSSS" e.g. "20250102093000000"
    h, m, s = time_str[8:10], time_str[10:12], time_str[12:14]
    return f"{date_str} {h}:{m}:{s}+08:00"


def fetch_stock(bs_code, start, end):
    rs = bs.query_history_k_data_plus(
        bs_code,
        fields="date,time,open,high,low,close,volume,amount",
        start_date=start,
        end_date=end,
        frequency="5",
        adjustflag="3",  # unadjusted
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return rows


def get_stock_list():
    # fields: code, code_name, ipoDate, outDate, type, status
    rs = bs.query_stock_basic()
    stocks = {"SH": [], "SZ": [], "BJ": []}
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        if r[4] != "1" or r[5] != "1":  # type=1: stock, status=1: active
            continue
        exch = r[0].split(".")[0].upper()  # sh/sz/bj → SH/SZ/BJ
        if exch in stocks:
            stocks[exch].append(r[0])

    if LOCAL_TEST:
        print(f"LOCAL_TEST mode: capping at {LOCAL_LIMIT_PER_EXCHANGE} stocks per exchange")
        return (
            stocks["SH"][:LOCAL_LIMIT_PER_EXCHANGE] +
            stocks["SZ"][:LOCAL_LIMIT_PER_EXCHANGE] +
            stocks["BJ"][:LOCAL_LIMIT_PER_EXCHANGE]
        )

    return stocks["SH"] + stocks["SZ"] + stocks["BJ"]


# --- Main ---

lg = bs.login()
print(f"BaoStock login: {lg.error_msg}")

done = load_checkpoint()
all_stocks = get_stock_list()
stocks = [s for s in all_stocks if s not in done]
print(f"Stocks to ingest: {len(stocks)} (skipping {len(done)} already done)")

conn = get_marketdata_conn()
cur = conn.cursor()

INSERT_SQL = """
    INSERT INTO ohlcv_5m (ts, code, exchange, open, high, low, close, volume, amount)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""

for i, bs_code in enumerate(stocks):
    exch, code = bs_code.split(".")
    exchange = exch.upper()
    try:
        rows = fetch_stock(bs_code, START_DATE, END_DATE)
        batch = []
        for r in rows:
            date_s, time_s, o, h, l, c, vol, amt = r
            if not o or o == "":
                continue
            batch.append((
                parse_ts(date_s, time_s), code, exchange,
                float(o), float(h), float(l), float(c),
                int(float(vol)),
                float(amt) if amt else None,
            ))
        if batch:
            for j in range(0, len(batch), BATCH_SIZE):
                cur.executemany(INSERT_SQL, batch[j:j + BATCH_SIZE])
            conn.commit()
        save_checkpoint(bs_code)
        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(stocks)+len(done)}] {bs_code}: {len(batch)} rows")
    except Exception as e:
        conn.rollback()
        print(f"ERROR {bs_code}: {e}")
    time.sleep(0.1)

cur.close()
conn.close()
bs.logout()
print("Ingestion complete.")
