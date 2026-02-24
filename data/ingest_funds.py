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

import pandas as pd
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
        raw_code = str(r.get("基金代码") or "").strip()
        if not raw_code:
            continue
        code = raw_code.zfill(6)
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
        raw_code = str(r.get("现任基金代码") or "").strip()
        name = str(r.get("姓名") or "").strip()
        if not raw_code or not name:
            continue
        rows.append((raw_code.zfill(6), name, today))
    async with pool.acquire() as conn:
        existing = {r["code"] for r in await conn.fetch("SELECT code FROM funds")}
        valid = [r for r in rows if r[0] in existing]
        await conn.executemany("""
            INSERT INTO fund_managers (fund_code, manager_name, start_date)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
        """, valid)
    print(f"  Inserted {len(valid):,} manager-fund associations")


# ── 3. ETF price history ──────────────────────────────────────────────────────

def _fetch_etf_price(code: str) -> tuple[str, list]:
    try:
        df = ak.fund_etf_hist_em(
            symbol=code, period="daily",
            start_date=PRICE_START, end_date=PRICE_END, adjust="",
        )
        rows = []
        for _, r in df.iterrows():
            try:
                d = r["日期"] if isinstance(r["日期"], date) else date.fromisoformat(str(r["日期"]))
                rows.append((
                    code, d,
                    float(r["开盘"])   if r["开盘"]   else None,
                    float(r["最高"])   if r["最高"]   else None,
                    float(r["最低"])   if r["最低"]   else None,
                    float(r["收盘"])   if r["收盘"]   else None,
                    int(float(r["成交量"])) if r["成交量"] else None,
                    float(r["成交额"]) if r["成交额"] else None,
                    float(r["换手率"]) if r["换手率"] else None,
                    None,  # premium_discount_pct — not in this endpoint
                ))
            except Exception:
                continue
        return code, rows
    except Exception:
        return code, []


async def load_etf_prices(pool: asyncpg.Pool, etf_codes: list[str]):
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    total_rows = 0
    errors: list[str] = []
    with Progress(
        SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
        TaskProgressColumn(), TimeElapsedColumn(), TextColumn("ETA:"),
        TimeRemainingColumn(), TextColumn("[cyan]{task.description}"),
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task("ETF prices...", total=len(etf_codes))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str):
                nonlocal total_rows
                async with sem:
                    code_out, rows = await loop.run_in_executor(executor, _fetch_etf_price, code)
                    if rows:
                        async with pool.acquire() as conn:
                            await conn.executemany("""
                                INSERT INTO fund_price
                                  (fund_code, date, open, high, low, close, volume, amount, turnover_rate, premium_discount_pct)
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                                ON CONFLICT DO NOTHING
                            """, rows)
                        total_rows += len(rows)
                    else:
                        errors.append(code_out)
                    progress.update(task, advance=1,
                        description=f"{code_out} {len(rows)} rows ({total_rows:,} total)")
            await asyncio.gather(*[process_one(c) for c in etf_codes])
    print(f"  ETF prices: {total_rows:,} rows. {len(errors)} codes returned no data.")


# ── 4. NAV ────────────────────────────────────────────────────────────────────

def _fetch_etf_nav(code: str) -> tuple[str, list]:
    try:
        df = ak.fund_etf_fund_info_em(fund=code, start_date=PRICE_START, end_date=PRICE_END)
        rows = []
        for _, r in df.iterrows():
            try:
                d = r["净值日期"] if isinstance(r["净值日期"], date) else date.fromisoformat(str(r["净值日期"]))
                rows.append((
                    code, d,
                    float(r["单位净值"])  if pd.notna(r.get("单位净值"))  else None,
                    float(r["累计净值"])  if pd.notna(r.get("累计净值"))  else None,
                    _parse_rate(r.get("日增长率")),
                ))
            except Exception:
                continue
        return code, rows
    except Exception:
        return code, []


async def load_etf_navs(pool: asyncpg.Pool, etf_codes: list[str]):
    """Load NAV history for all ETFs from fund_etf_fund_info_em."""
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    total_rows = 0
    errors: list[str] = []
    with Progress(
        SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        TextColumn("[cyan]{task.description}"), refresh_per_second=4,
    ) as progress:
        task = progress.add_task("ETF NAV...", total=len(etf_codes))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str):
                nonlocal total_rows
                async with sem:
                    code_out, rows = await loop.run_in_executor(executor, _fetch_etf_nav, code)
                    if rows:
                        async with pool.acquire() as conn:
                            await conn.executemany("""
                                INSERT INTO fund_nav (fund_code, date, unit_nav, accum_nav, daily_return_pct)
                                VALUES ($1,$2,$3,$4,$5)
                                ON CONFLICT DO NOTHING
                            """, rows)
                        total_rows += len(rows)
                    else:
                        errors.append(code_out)
                    progress.update(task, advance=1,
                        description=f"{code_out} {len(rows)} rows ({total_rows:,} total)")
            await asyncio.gather(*[process_one(c) for c in etf_codes])
    print(f"  ETF NAVs: {total_rows:,} rows. {len(errors)} codes returned no data.")


async def load_open_fund_navs(pool: asyncpg.Pool):
    """Bulk load today's NAV for all open-ended funds (single API call).

    fund_open_fund_daily_em returns date-prefixed NAV columns, e.g.
    '2026-02-13-单位净值' and '2026-02-13-累计净值'. We detect the most
    recent date prefix from the column names at runtime.
    """
    print("Fetching open fund NAV bulk...")
    df = ak.fund_open_fund_daily_em()
    # Detect date-prefixed NAV columns (format: YYYY-MM-DD-单位净值)
    unit_col = next((c for c in df.columns if c.endswith("-单位净值")), None)
    accum_col = next((c for c in df.columns if c.endswith("-累计净值")), None)
    if unit_col is None and accum_col is None:
        print("  WARNING: no NAV columns detected in fund_open_fund_daily_em response")
        return
    nav_date = date.fromisoformat(unit_col[:-len("-单位净值")]) if unit_col else date.today()
    rows = []
    for _, r in df.iterrows():
        raw_code = str(r.get("基金代码") or "").strip()
        if not raw_code:
            continue
        try:
            rows.append((
                raw_code.zfill(6), nav_date,
                float(r[unit_col])  if unit_col and pd.notna(r.get(unit_col))  else None,
                float(r[accum_col]) if accum_col and pd.notna(r.get(accum_col)) else None,
                _parse_rate(r.get("日增长率")),
            ))
        except Exception:
            continue
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO fund_nav (fund_code, date, unit_nav, accum_nav, daily_return_pct)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT DO NOTHING
        """, rows)
    print(f"  Open fund NAV: {len(rows):,} rows")
