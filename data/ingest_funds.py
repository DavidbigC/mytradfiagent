#!/usr/bin/env python3
"""Initial bulk load of fund data into marketdata DB.

Environment variables:
  MARKETDATA_URL   PostgreSQL connection string (required)
  CONCURRENCY=5    Parallel workers for per-fund API calls
  LOCAL_TEST=1     Limit to first 50 ETFs; skip open funds and holdings
  SKIP_OVERVIEW=1  Skip fund_overview_em (fees) — saves ~2h for full load
  PRICE_START      Earliest date for price/NAV history (default 20200101)
  START_YEAR       Earliest year for holdings (default 2023)
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import akshare as ak
import asyncpg
from dotenv import load_dotenv
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)

load_dotenv()

LOCAL_TEST    = os.getenv("LOCAL_TEST", "0") == "1"
SKIP_OVERVIEW = os.getenv("SKIP_OVERVIEW", "0") == "1"
CONCURRENCY   = int(os.getenv("CONCURRENCY", "5"))
PRICE_START   = os.getenv("PRICE_START", "20200101")
PRICE_END     = date.today().strftime("%Y%m%d")
START_YEAR    = int(os.getenv("START_YEAR", "2023"))


def _build_dsn() -> str:
    from urllib.parse import urlparse
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/marketdata")
    p = urlparse(url)
    dbname = p.path.lstrip("/") or "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    return f"postgresql://{p.username or os.getenv('USER','postgres')}:{p.password or ''}@{p.hostname or 'localhost'}:{p.port or 5432}/{dbname}"


def _derive_exchange(code: str) -> str | None:
    if code.startswith("15"):
        return "SZ"
    if code.startswith("5"):
        return "SH"
    return None


def _parse_rate(val) -> float | None:
    if val is None or str(val).strip() in ("", "-", "--"):
        return None
    try:
        return float(str(val).replace("%", "").strip())
    except ValueError:
        return None


def get_etf_codes() -> list[str]:
    df = ak.fund_etf_spot_em()
    return [str(r).strip().zfill(6) for r in df["代码"].tolist()]


# ── 1. Catalog ────────────────────────────────────────────────────────────────

async def load_catalog(pool: asyncpg.Pool) -> list[str]:
    """Load all funds from fund_name_em(). Returns all fund codes."""
    print("Fetching fund catalog...")
    df = ak.fund_name_em()
    rows = []
    for _, r in df.iterrows():
        code = str(r["基金代码"]).strip().zfill(6)
        rows.append((
            code,
            str(r.get("基金简称") or ""),
            str(r.get("基金类型") or ""),
            _derive_exchange(code),
        ))
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO funds (code, name, type, exchange)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (code) DO UPDATE
              SET name=EXCLUDED.name, type=EXCLUDED.type,
                  exchange=COALESCE(funds.exchange, EXCLUDED.exchange),
                  updated_at=now()
        """, rows)
    print(f"  Upserted {len(rows):,} funds")
    return [r[0] for r in rows]


# ── 2. Managers ───────────────────────────────────────────────────────────────

async def load_managers(pool: asyncpg.Pool):
    """Load current manager→fund mappings from fund_manager_em()."""
    print("Fetching fund managers...")
    df = ak.fund_manager_em()
    today = date.today()
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("现任基金代码") or "").strip().zfill(6)
        name = str(r.get("姓名") or "").strip()
        if code and name:
            rows.append((code, name, today))
    async with pool.acquire() as conn:
        existing = {r["code"] for r in await conn.fetch("SELECT code FROM funds")}
        valid = [r for r in rows if r[0] in existing]
        await conn.executemany("""
            INSERT INTO fund_managers (fund_code, manager_name, start_date)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
        """, valid)
    print(f"  Inserted {len(valid):,} manager-fund associations")
