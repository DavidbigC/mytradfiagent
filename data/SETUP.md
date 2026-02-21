# Market Data Pipeline — Setup Guide

Hourly OHLCV data for 5000+ A-share stocks, stored in a dedicated `marketdata` PostgreSQL database. Used for backtesting.

---

## Prerequisites

- Python 3.10+ with a `.venv` virtual environment at the project root
- PostgreSQL 14+ installed and running
- Project `.env` file in the project root

---

## Step 1: Install PostgreSQL

### Mac (local dev)
PostgreSQL is available via Homebrew and should already be running if the main app works.
```bash
brew install postgresql@17
brew services start postgresql@17
```

### Linux (remote server)
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

---

## Step 2: Install Python dependencies

```bash
cd /path/to/myaiagent
.venv/bin/pip install baostock psycopg2-binary
```

---

## Step 3: Configure environment

Add to your `.env` file at the project root:

```
MARKETDATA_URL=postgresql://<user>@localhost:5432/marketdata
```

- **Mac:** `<user>` is your macOS username (e.g. `davidc`), no password needed for local connections
- **Linux:** typically `postgres` user with a password, e.g.:
  ```
  MARKETDATA_URL=postgresql://postgres:yourpassword@localhost:5432/marketdata
  ```

To find your PostgreSQL superuser on Linux:
```bash
sudo -u postgres psql -c "\du"
```

---

## Step 4: Create the database and schema

Run once:
```bash
.venv/bin/python data/setup_db.py
```

Expected output:
```
Created database: marketdata
Table ohlcv_1h ready
Indexes created
Setup complete.
```

This creates:
- Database: `marketdata`
- Table: `ohlcv_1h` with columns `ts, code, exchange, open, high, low, close, volume, amount`
- UNIQUE constraint on `(ts, code, exchange)` — safe to re-run ingestion
- BRIN index on `ts` — compact, ideal for append-only time-ordered inserts
- Btree index on `(code, ts DESC)` — fast per-stock range queries

---

## Step 5: Bulk historical ingest (one-time, ~2–4 hours)

```bash
.venv/bin/python data/ingest_ohlcv.py
```

- Downloads 5 years of hourly bars (2020-01-01 → today) for all active A-shares
- ~5000 stocks × 244 trading days × 4 bars = ~25M rows
- Progress is logged every 100 stocks
- **Resumable**: completed stocks are saved to `data/.ingest_checkpoint`
  - If interrupted, re-run the same command — already-done stocks are skipped automatically
  - To start fresh: `rm data/.ingest_checkpoint`

---

## Step 6: Daily incremental update (cron)

Run after market close (16:30 CST = 08:30 UTC):
```bash
.venv/bin/python data/update_ohlcv.py
```

Add to crontab (`crontab -e`):
```
30 8 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_ohlcv.py >> /var/log/ohlcv_update.log 2>&1
```

---

## Verify the data

```bash
# Connect to the marketdata DB
psql -U <user> -d marketdata

# Row count
SELECT count(*) FROM ohlcv_1h;

# Date range
SELECT min(ts), max(ts) FROM ohlcv_1h;

# Sample rows for one stock
SELECT * FROM ohlcv_1h WHERE code = '600036' ORDER BY ts DESC LIMIT 10;

# Rows per exchange
SELECT exchange, count(*) FROM ohlcv_1h GROUP BY exchange;
```

---

## BaoStock API notes

- No API key required — free public data source
- `query_stock_basic()` returns fields: `[code, code_name, ipoDate, outDate, type, status]`
  - `type == '1'` → stock (not index/ETF)
  - `status == '1'` → currently listed
- `frequency="60"` → 60-minute bars
- `adjustflag="3"` → unadjusted prices
- The `time` field is formatted as `YYYYMMDDHHmmssSSS` (e.g. `20250102103000000`)
  — time is extracted by slicing `[8:10]`, `[10:12]`, `[12:14]`
- BaoStock code format: `sh.600036` → stored as `code="600036"`, `exchange="SH"`

---

## File reference

| File | Purpose |
|---|---|
| `data/setup_db.py` | One-time: create DB and schema |
| `data/ingest_ohlcv.py` | One-time: bulk load 5yr history |
| `data/update_ohlcv.py` | Daily: incremental update via cron |
| `data/.ingest_checkpoint` | Auto-generated: tracks ingestion progress (gitignored) |

---

## Troubleshooting

**`role "X" does not exist`**
Your `MARKETDATA_URL` user doesn't exist in PostgreSQL. Check with `psql -c "\du"` and update the URL.

**`connection refused` on port 5432**
PostgreSQL isn't running. On Mac: `brew services start postgresql@17`. On Linux: `sudo systemctl start postgresql`.

**`query_stock_basic() got unexpected keyword argument 'fields'`**
BaoStock doesn't support field filtering on this call. Use `query_stock_basic()` with no arguments.

**Ingestion is slow**
Normal — 0.1s sleep between stocks to avoid hammering BaoStock. Full ingest takes 2–4 hours. Run in a `screen` or `tmux` session on the server so it survives SSH disconnection:
```bash
tmux new -s ingest
.venv/bin/python data/ingest_ohlcv.py
# Ctrl+B then D to detach; tmux attach -t ingest to reattach
```
