#!/usr/bin/env python3
"""Ingest quarterly financial data from BaoStock into the unified financials table.

Stock list is read from the main myaiagent DB (stocknames table).
Data is fetched stock-by-stock, all 6 BaoStock financial APIs merged into one row.

Usage:
  .venv/bin/python data/ingest_financials.py          # incremental: new quarters only
  .venv/bin/python data/ingest_financials.py --full   # full load (last 10 years)

Monthly cron (1st of month, 09:00 CST = 01:00 UTC):
  0 1 1 * * cd /path/to/myaiagent && .venv/bin/python data/ingest_financials.py >> /var/log/financials_update.log 2>&1

Environment variables:
  DATABASE_URL     Main myaiagent DB (for stock list)
  MARKETDATA_URL   marketdata DB (for writing financials)
  LOCAL_TEST=1     Only process first 50 stocks (for local dev)
"""
import os
import sys
import time
import psycopg2
import baostock as bs
from datetime import date
from dotenv import load_dotenv

load_dotenv()

FULL_MODE = "--full" in sys.argv
LOCAL_TEST = os.getenv("LOCAL_TEST", "0") == "1"
YEARS_OF_HISTORY = 10
SLEEP = 0.1  # seconds between stocks


# ── BaoStock field → DB column mappings ──────────────────────────────────────

PROFIT_FIELDS = [
    ("roeAvg",      "roe_avg"),
    ("npMargin",    "np_margin"),
    ("gpMargin",    "gp_margin"),
    ("netProfit",   "net_profit"),
    ("epsTTM",      "eps_ttm"),
    ("MBRevenue",   "mb_revenue"),
    ("totalShare",  "total_share"),
    ("liqaShare",   "liqa_share"),
]
OPERATION_FIELDS = [
    ("NRTurnRatio",    "nr_turn_ratio"),
    ("NRTurnDays",     "nr_turn_days"),
    ("INVTurnRatio",   "inv_turn_ratio"),
    ("INVTurnDays",    "inv_turn_days"),
    ("CATurnRatio",    "ca_turn_ratio"),
    ("AssetTurnRatio", "asset_turn_ratio"),
]
GROWTH_FIELDS = [
    ("YOYEquity",   "yoy_equity"),
    ("YOYAsset",    "yoy_asset"),
    ("YOYNI",       "yoy_ni"),
    ("YOYEPSBasic", "yoy_eps_basic"),
    ("YOYPNI",      "yoy_pni"),
]
BALANCE_FIELDS = [
    ("currentRatio",     "current_ratio"),
    ("quickRatio",       "quick_ratio"),
    ("cashRatio",        "cash_ratio"),
    ("YOYLiability",     "yoy_liability"),
    ("liabilityToAsset", "liability_to_asset"),
    ("assetToEquity",    "asset_to_equity"),
]
CASHFLOW_FIELDS = [
    ("CAToAsset",            "ca_to_asset"),
    ("NCAToAsset",           "nca_to_asset"),
    ("tangibleAssetToAsset", "tangible_asset_to_asset"),
    ("ebitToInterest",       "ebit_to_interest"),
    ("CFOToOR",              "cfo_to_or"),
    ("CFOToNP",              "cfo_to_np"),
    ("CFOToGr",              "cfo_to_gr"),
]
DUPONT_FIELDS = [
    ("dupontROE",            "dupont_roe"),
    ("dupontAssetStoEquity", "dupont_asset_sto_equity"),
    ("dupontAssetTurn",      "dupont_asset_turn"),
    ("dupontPnitoni",        "dupont_pnitoni"),
    ("dupontNitogr",         "dupont_nitogr"),
    ("dupontTaxBurden",      "dupont_tax_burden"),
    ("dupontIntburden",      "dupont_int_burden"),
    ("dupontEbittogr",       "dupont_ebit_togr"),
]

ALL_METRIC_COLS = (
    PROFIT_FIELDS + OPERATION_FIELDS + GROWTH_FIELDS +
    BALANCE_FIELDS + CASHFLOW_FIELDS + DUPONT_FIELDS
)
DB_METRIC_COLS = [db for _, db in ALL_METRIC_COLS]

INSERT_SQL = f"""
    INSERT INTO financials (code, exchange, pub_date, stat_date, {', '.join(DB_METRIC_COLS)})
    VALUES (%(code)s, %(exchange)s, %(pub_date)s, %(stat_date)s, {', '.join(f'%({c})s' for c in DB_METRIC_COLS)})
    ON CONFLICT (code, stat_date) DO UPDATE SET
        pub_date = EXCLUDED.pub_date,
        {', '.join(f'{c} = EXCLUDED.{c}' for c in DB_METRIC_COLS)}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def val(v):
    """Empty string → None, otherwise float."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def get_main_conn():
    from urllib.parse import urlparse
    url = os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")
    p = urlparse(url)
    return psycopg2.connect(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=p.username or os.getenv("USER", "postgres"),
        password=p.password or "",
        dbname=p.path.lstrip("/") or "myaiagent",
    )


def get_marketdata_conn():
    from urllib.parse import urlparse
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")
    p = urlparse(url)
    dbname = p.path.lstrip("/") or "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    return psycopg2.connect(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=p.username or os.getenv("USER", "postgres"),
        password=p.password or "",
        dbname=dbname,
    )


def get_stock_list():
    """Read SH and SZ stocks from myaiagent stocknames table. BJ excluded — BaoStock doesn't support it."""
    conn = get_main_conn()
    cur = conn.cursor()
    cur.execute("SELECT stock_code, exchange FROM stocknames WHERE exchange IN ('SH','SZ') ORDER BY exchange, stock_code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()
    if LOCAL_TEST:
        stocks = stocks[:50]
        print(f"LOCAL_TEST: using first {len(stocks)} stocks")
    return stocks  # list of (code, exchange) e.g. ('600000', 'SH')


def get_quarters_to_fetch(cur):
    """Return list of (year, quarter) to fetch."""
    today = date.today()
    end_year = today.year
    end_q = (today.month - 1) // 3 + 1

    if FULL_MODE:
        start_year = today.year - YEARS_OF_HISTORY
        start_q = 1
    else:
        # Find latest stat_date already in DB
        cur.execute("SELECT MAX(stat_date) FROM financials")
        latest = cur.fetchone()[0]
        if latest is None:
            print("No existing data — running full load")
            start_year = today.year - YEARS_OF_HISTORY
            start_q = 1
        else:
            # Start from the quarter after the latest one
            latest_q = (latest.month - 1) // 3 + 1
            if latest_q == 4:
                start_year, start_q = latest.year + 1, 1
            else:
                start_year, start_q = latest.year, latest_q + 1

    quarters = []
    y, q = start_year, start_q
    while (y, q) <= (end_year, end_q):
        quarters.append((y, q))
        q += 1
        if q > 4:
            q, y = 1, y + 1
    return quarters


def fetch_one_stock(bs_code, year, quarter):
    """Fetch all 6 financial APIs for one stock/quarter. Returns merged dict or None."""
    apis = [
        (bs.query_profit_data,     PROFIT_FIELDS),
        (bs.query_operation_data,  OPERATION_FIELDS),
        (bs.query_growth_data,     GROWTH_FIELDS),
        (bs.query_balance_data,    BALANCE_FIELDS),
        (bs.query_cash_flow_data,  CASHFLOW_FIELDS),
        (bs.query_dupont_data,     DUPONT_FIELDS),
    ]

    merged = {}
    pub_date = None
    stat_date = None

    for fn, field_map in apis:
        rs = fn(code=bs_code, year=year, quarter=quarter)
        if rs.error_code != "0" or not rs.next():
            continue
        r = rs.get_row_data()
        row = dict(zip(rs.fields, r))
        if not stat_date:
            stat_date = row.get("statDate") or None
            pub_date = row.get("pubDate") or None
        for bs_col, db_col in field_map:
            merged[db_col] = val(row.get(bs_col))

    if not stat_date:
        return None

    merged["pub_date"] = pub_date
    merged["stat_date"] = stat_date
    return merged


# ── Worker (runs in its own process) ─────────────────────────────────────────

def worker(chunk_id, stocks_chunk, quarters, counter, lock):
    """Each worker: own BaoStock login + own DB connection."""
    import baostock as bs_local
    bs_local.login()
    conn = get_marketdata_conn()
    cur = conn.cursor()
    inserted = 0

    for code, exchange in stocks_chunk:
        bs_code = f"{exchange.lower()}.{code}"
        for year, quarter in quarters:
            try:
                row = fetch_one_stock(bs_code, year, quarter)
                if row is not None:
                    row["code"] = code
                    row["exchange"] = exchange
                    cur.execute(INSERT_SQL, row)
                    conn.commit()
                    inserted += 1
            except Exception as e:
                conn.rollback()
                print(f"  [W{chunk_id}] ERROR {bs_code} {year}Q{quarter}: {e}", flush=True)

            with lock:
                counter.value += 1
                done = counter.value
                pct = done / counter.total * 100
                elapsed = time.time() - counter.t_start
                eta_s = (elapsed / done) * (counter.total - done) if done > 1 else 0
                print(f"[{done}/{counter.total} {pct:.1f}%] W{chunk_id} {bs_code} {year}Q{quarter} | ETA: {int(eta_s//60)}m{int(eta_s%60):02d}s", flush=True)

            time.sleep(SLEEP)

    cur.close()
    conn.close()
    bs_local.logout()
    return inserted


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from multiprocessing import Pool, Manager, Value
    import ctypes

    # Use a temp BaoStock login just to get quarter range from DB
    bs.login()
    print(f"BaoStock: connected")
    print(f"Mode: {'FULL ({} years)'.format(YEARS_OF_HISTORY) if FULL_MODE else 'incremental'} | LOCAL_TEST: {LOCAL_TEST}")

    mkt_conn = get_marketdata_conn()
    mkt_cur = mkt_conn.cursor()
    quarters = get_quarters_to_fetch(mkt_cur)
    mkt_cur.close()
    mkt_conn.close()
    bs.logout()

    if not quarters:
        print("Already up to date.")
        exit()

    start_y, start_q = quarters[0]
    end_y, end_q = quarters[-1]
    print(f"Quarters: {start_y}Q{start_q} → {end_y}Q{end_q} ({len(quarters)} quarters)")

    stocks = get_stock_list()
    print(f"Stocks: {len(stocks)}")

    WORKERS = 6
    chunks = [stocks[i::WORKERS] for i in range(WORKERS)]
    total_ops = len(stocks) * len(quarters)
    print(f"Workers: {WORKERS} | Total API calls: {total_ops}")

    with Manager() as manager:
        counter = manager.Namespace()
        counter.value = 0
        counter.total = total_ops
        counter.t_start = time.time()
        lock = manager.Lock()

        with Pool(WORKERS) as pool:
            results = pool.starmap(
                worker,
                [(i, chunks[i], quarters, counter, lock) for i in range(WORKERS)]
            )

    print(f"Done. Total inserted/updated: {sum(results)} rows.")
