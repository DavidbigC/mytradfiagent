#!/usr/bin/env python3
"""Daily incremental update: fetch new 5-min bars since last ingestion.

Cron (weekdays at 16:30 CST = 08:30 UTC):
  30 8 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_ohlcv.py >> /var/log/ohlcv_update.log 2>&1
"""
import os
import time
import psycopg2
import baostock as bs
from datetime import date
from dotenv import load_dotenv

load_dotenv()


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


lg = bs.login()
conn = get_marketdata_conn()
cur = conn.cursor()

cur.execute("SELECT MAX(ts) FROM ohlcv_5m")
last_ts = cur.fetchone()[0]
start_date = (last_ts.date() if last_ts else date(2020, 1, 1)).isoformat()
end_date = date.today().isoformat()

if start_date >= end_date:
    print("Already up to date.")
    bs.logout()
    cur.close()
    conn.close()
    exit()

print(f"Updating from {start_date} to {end_date}")

# fields: code, code_name, ipoDate, outDate, type, status
rs = bs.query_stock_basic()
stocks = []
while rs.error_code == "0" and rs.next():
    r = rs.get_row_data()
    if r[4] == "1" and r[5] == "1":
        stocks.append(r[0])

INSERT_SQL = """
    INSERT INTO ohlcv_5m (ts, code, exchange, open, high, low, close, volume, amount)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""

total_rows = 0
for bs_code in stocks:
    exch, code = bs_code.split(".")
    exchange = exch.upper()
    try:
        rs2 = bs.query_history_k_data_plus(
            bs_code,
            fields="date,time,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="5",
            adjustflag="3",
        )
        batch = []
        while rs2.error_code == '0' and rs2.next():
            r = rs2.get_row_data()
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
            cur.executemany(INSERT_SQL, batch)
            conn.commit()
            total_rows += len(batch)
    except Exception as e:
        conn.rollback()
        print(f"ERROR {bs_code}: {e}")
    time.sleep(0.05)

cur.close()
conn.close()
bs.logout()
print(f"Update complete. Inserted {total_rows} new rows.")
