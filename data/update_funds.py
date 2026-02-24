#!/usr/bin/env python3
"""Daily incremental update for fund NAV, ETF prices, and manager changes.

Usage:
  python data/update_funds.py                   # NAV + prices only
  python data/update_funds.py --check-managers  # also detect manager changes
  python data/update_funds.py --check-fees      # also refresh fees (slow ~2h)

Cron (weekdays 20:00 CST = 12:00 UTC):
  0 12 * * 1-5 cd /path/to/myaiagent && .venv/bin/python data/update_funds.py
  0 12 * * 0   cd /path/to/myaiagent && .venv/bin/python data/update_funds.py --check-managers

Environment variables:
  MARKETDATA_URL   PostgreSQL connection string (required)
  CONCURRENCY=5    Parallel workers
  LOOKBACK_DAYS=5  Days of price history to re-fetch on each run
"""
import argparse
import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import akshare as ak
import asyncpg
from dotenv import load_dotenv
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
)

load_dotenv()

CONCURRENCY   = int(os.getenv("CONCURRENCY", "5"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "5"))


def _build_dsn() -> str:
    from urllib.parse import urlparse
    url = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/marketdata")
    p = urlparse(url)
    dbname = p.path.lstrip("/") or "marketdata"
    if dbname in ("myaiagent", "postgres", ""):
        dbname = "marketdata"
    return f"postgresql://{p.username or os.getenv('USER','postgres')}:{p.password or ''}@{p.hostname or 'localhost'}:{p.port or 5432}/{dbname}"


def _parse_rate(val) -> float | None:
    if val is None or str(val).strip() in ("", "-", "--", "---"):
        return None
    s = str(val).strip()
    if "%" not in s and not re.match(r"^[-+]?\d+\.?\d*$", s):
        return None
    m = re.search(r"[-+]?\d+\.?\d*", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _detect_nav_cols(df: pd.DataFrame) -> tuple[str | None, str | None, date | None]:
    """Return (nav_col, accum_col, nav_date) from a date-prefixed column DataFrame."""
    nav_col   = next((c for c in df.columns if c.endswith("-单位净值")), None)
    accum_col = next((c for c in df.columns if c.endswith("-累计净值")), None)
    nav_date  = None
    if nav_col:
        try:
            nav_date = date.fromisoformat(nav_col.replace("-单位净值", ""))
        except ValueError:
            nav_date = date.today()
    return nav_col, accum_col, nav_date


# ── 1. NAV bulk update ────────────────────────────────────────────────────────

async def update_navs(pool: asyncpg.Pool):
    print("Updating NAV (open funds + ETFs)...")
    today = date.today()
    rows: list[tuple] = []

    # Open-ended funds: date-prefixed NAV columns + 日增长率
    df_open = ak.fund_open_fund_daily_em()
    nav_col, accum_col, nav_date = _detect_nav_cols(df_open)
    nav_date = nav_date or today
    for _, r in df_open.iterrows():
        code = str(r["基金代码"]).strip().zfill(6)
        try:
            rows.append((
                code, nav_date,
                float(r[nav_col])   if nav_col   and pd.notna(r.get(nav_col))   else None,
                float(r[accum_col]) if accum_col and pd.notna(r.get(accum_col)) else None,
                _parse_rate(r.get("日增长率")),
            ))
        except Exception:
            continue

    # ETFs: date-prefixed NAV columns + 增长率
    df_etf = ak.fund_etf_fund_daily_em()
    nav_col_e, accum_col_e, nav_date_e = _detect_nav_cols(df_etf)
    nav_date_e = nav_date_e or today
    for _, r in df_etf.iterrows():
        code = str(r["基金代码"]).strip().zfill(6)
        try:
            rows.append((
                code, nav_date_e,
                float(r[nav_col_e])   if nav_col_e   and pd.notna(r.get(nav_col_e))   else None,
                float(r[accum_col_e]) if accum_col_e and pd.notna(r.get(accum_col_e)) else None,
                _parse_rate(r.get("增长率")),
            ))
        except Exception:
            continue

    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO fund_nav (fund_code, date, unit_nav, accum_nav, daily_return_pct)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT DO NOTHING
        """, rows)
    print(f"  NAV: {len(rows):,} rows upserted")


# ── 2. ETF price incremental ──────────────────────────────────────────────────

def _fetch_recent_price(code: str, start: str, end: str) -> tuple[str, list]:
    try:
        df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                  start_date=start, end_date=end, adjust="")
        rows = []
        for _, r in df.iterrows():
            try:
                raw_d = r["日期"]
                if hasattr(raw_d, "date") and callable(raw_d.date):
                    d = raw_d.date()
                else:
                    d = date.fromisoformat(str(raw_d))
                rows.append((
                    code, d,
                    float(r["开盘"])        if r["开盘"]   else None,
                    float(r["最高"])        if r["最高"]   else None,
                    float(r["最低"])        if r["最低"]   else None,
                    float(r["收盘"])        if r["收盘"]   else None,
                    int(float(r["成交量"])) if r["成交量"] else None,
                    float(r["成交额"])      if r["成交额"] else None,
                    float(r["换手率"])      if r["换手率"] else None,
                    None,  # premium_discount_pct
                ))
            except Exception:
                continue
        return code, rows
    except Exception:
        return code, []


async def update_etf_prices(pool: asyncpg.Pool):
    print("Updating ETF prices...")
    try:
        df = ak.fund_etf_spot_em()
        etf_codes = [str(r).strip().zfill(6) for r in df["代码"].tolist()]
    except Exception:
        df = ak.fund_etf_fund_daily_em()
        etf_codes = [str(r).strip().zfill(6) for r in df["基金代码"].tolist()]
    yesterday = date.today() - timedelta(days=1)
    start = (yesterday - timedelta(days=LOOKBACK_DAYS - 1)).strftime("%Y%m%d")
    end   = yesterday.strftime("%Y%m%d")

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    total = 0

    with Progress(SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
                  TaskProgressColumn(), TimeElapsedColumn(),
                  TextColumn("[cyan]{task.description}"), refresh_per_second=4) as progress:
        task = progress.add_task("ETF prices...", total=len(etf_codes))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str):
                nonlocal total
                async with sem:
                    code_out, rows = await loop.run_in_executor(
                        executor, _fetch_recent_price, code, start, end)
                    if rows:
                        async with pool.acquire() as conn:
                            await conn.executemany("""
                                INSERT INTO fund_price
                                  (fund_code, date, open, high, low, close, volume, amount, turnover_rate, premium_discount_pct)
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                                ON CONFLICT DO NOTHING
                            """, rows)
                        total += len(rows)
                    progress.update(task, advance=1, description=f"{code_out}")
            await asyncio.gather(*[process_one(c) for c in etf_codes])
    print(f"  ETF prices: {total:,} rows")


# ── 3. Manager change detection (SCD type 2) ─────────────────────────────────

async def update_managers(pool: asyncpg.Pool):
    print("Checking manager changes...")
    today = date.today()
    fresh_df = ak.fund_manager_em()

    fresh: dict[str, set] = {}
    for _, r in fresh_df.iterrows():
        raw_code = str(r.get("现任基金代码") or "").strip()
        name = str(r.get("姓名") or "").strip()
        if raw_code and name:
            code = raw_code.zfill(6)
            fresh.setdefault(code, set()).add(name)

    async with pool.acquire() as conn:
        db_rows = await conn.fetch(
            "SELECT fund_code, manager_name FROM fund_managers WHERE end_date IS NULL"
        )
        db: dict[str, set] = {}
        for row in db_rows:
            db.setdefault(row["fund_code"], set()).add(row["manager_name"])

        added = removed = 0
        for code in set(fresh) | set(db):
            for name in fresh.get(code, set()) - db.get(code, set()):
                await conn.execute("""
                    INSERT INTO fund_managers (fund_code, manager_name, start_date)
                    VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
                """, code, name, today)
                added += 1
            for name in db.get(code, set()) - fresh.get(code, set()):
                await conn.execute("""
                    UPDATE fund_managers SET end_date = $3
                    WHERE fund_code=$1 AND manager_name=$2 AND end_date IS NULL
                """, code, name, today)
                removed += 1

    print(f"  Managers: +{added} new, -{removed} departed")


# ── 4. Manager profiles refresh ──────────────────────────────────────────────

async def update_manager_profiles(pool: asyncpg.Pool):
    print("Refreshing manager profiles...")
    df = ak.fund_manager_em()
    rows: dict[str, tuple] = {}
    for _, r in df.iterrows():
        name = str(r.get("姓名") or "").strip()
        if not name:
            continue
        rows[name] = (
            name,
            str(r.get("所属公司") or "").strip() or None,
            int(r["累计从业时间"])        if pd.notna(r.get("累计从业时间"))        else None,
            float(r["现任基金资产总规模"]) if pd.notna(r.get("现任基金资产总规模")) else None,
            float(r["现任基金最佳回报"])   if pd.notna(r.get("现任基金最佳回报"))   else None,
        )
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO fund_manager_profiles
              (manager_name, company, tenure_days, total_aum, best_return_pct)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (manager_name) DO UPDATE SET
              company         = EXCLUDED.company,
              tenure_days     = EXCLUDED.tenure_days,
              total_aum       = EXCLUDED.total_aum,
              best_return_pct = EXCLUDED.best_return_pct,
              updated_at      = now()
        """, list(rows.values()))
    print(f"  Manager profiles: {len(rows):,} upserted")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace):
    pool = await asyncpg.create_pool(_build_dsn(), min_size=2, max_size=CONCURRENCY + 2)

    await update_navs(pool)
    await update_etf_prices(pool)

    if args.check_managers or args.check_fees:
        await update_managers(pool)
        await update_manager_profiles(pool)

    if args.check_fees:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from ingest_funds import load_fees, get_etf_codes
        etf_codes = get_etf_codes()
        print(f"\nRefreshing fees ({len(etf_codes)} ETFs)...")
        await load_fees(pool, etf_codes)

    await pool.close()
    print("Update complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-managers", action="store_true",
                        help="Detect and record manager changes (SCD type 2)")
    parser.add_argument("--check-fees", action="store_true",
                        help="Re-fetch fund_overview_em for all ETFs (slow ~2h)")
    asyncio.run(main(parser.parse_args()))
