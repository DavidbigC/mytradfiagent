#!/usr/bin/env python3
"""Initial bulk load of fund data into marketdata DB.

Environment variables:
  MARKETDATA_URL   PostgreSQL connection string (required)
  CONCURRENCY=5    Parallel workers for per-fund API calls
  LOCAL_TEST=1     Limit to first 50 funds
  PRICE_START      Earliest date for NAV history (default 20200101)
"""
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
    TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)

load_dotenv()

LOCAL_TEST  = os.getenv("LOCAL_TEST", "0") == "1"
CONCURRENCY = int(os.getenv("CONCURRENCY", "15"))
PRICE_START   = os.getenv("PRICE_START", "20200101")
PRICE_END     = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
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
    if val is None or str(val).strip() in ("", "-", "--", "---"):
        return None
    s = str(val).strip()
    # Only parse if value looks like a percentage or plain number — not a Chinese description
    if "%" not in s and not re.match(r"^[-+]?\d+\.?\d*$", s):
        return None
    m = re.search(r"[-+]?\d+\.?\d*", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None




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


# ── 2b. Manager profiles ──────────────────────────────────────────────────────

async def load_manager_profiles(pool: asyncpg.Pool):
    """Cache fund_manager_em() data into fund_manager_profiles for fast local lookup."""
    print("Loading manager profiles...")
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
    print(f"  Manager profiles: {len(rows):,} rows upserted")





# ── 4. NAV ────────────────────────────────────────────────────────────────────

def _fetch_etf_nav(code: str, start: str) -> tuple[str, list]:
    try:
        df = ak.fund_etf_fund_info_em(fund=code, start_date=start, end_date=PRICE_END)
        rows = []
        for _, r in df.iterrows():
            try:
                raw_d = r["净值日期"]
                if raw_d is None or raw_d is pd.NaT or not pd.notna(raw_d):
                    continue
                d = raw_d.date() if hasattr(raw_d, "date") else date.fromisoformat(str(raw_d))
                if not isinstance(d, date):
                    continue
                rows.append((
                    code, d,
                    float(r["单位净值"])  if pd.notna(r.get("单位净值"))  else None,
                    float(r["累计净值"])  if pd.notna(r.get("累计净值"))  else None,
                    _parse_rate(r.get("日增长率")),
                    str(r["申购状态"]) if pd.notna(r.get("申购状态")) else None,
                    str(r["赎回状态"]) if pd.notna(r.get("赎回状态")) else None,
                ))
            except Exception:
                continue
        return code, rows
    except Exception:
        return code, []


async def load_fund_navs(pool: asyncpg.Pool, fund_codes: list[str], *, progress: Progress | None = None):
    """Load NAV history for all funds via fund_etf_fund_info_em."""
    async with pool.acquire() as conn:
        existing = {r["fund_code"] for r in await conn.fetch("SELECT DISTINCT fund_code FROM fund_nav")}
    new_codes = [c for c in fund_codes if c not in existing]
    print(f"  {len(existing):,} funds already in DB, fetching {len(new_codes):,} new")
    if not new_codes:
        return

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    total_rows = 0
    errors: list[str] = []

    async def _run(prog: Progress) -> None:
        nonlocal total_rows
        task = prog.add_task("Fund NAV...", total=len(new_codes))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str):
                nonlocal total_rows
                start = PRICE_START
                async with sem:
                    code_out, rows = await loop.run_in_executor(executor, _fetch_etf_nav, code, start)
                    if rows:
                        async with pool.acquire() as conn:
                            await conn.executemany("""
                                INSERT INTO fund_nav (fund_code, date, unit_nav, accum_nav, daily_return_pct, sub_status, redeem_status)
                                VALUES ($1,$2,$3,$4,$5,$6,$7)
                                ON CONFLICT DO NOTHING
                            """, rows)
                        total_rows += len(rows)
                    else:
                        errors.append(code_out)
                    prog.update(task, advance=1,
                        description=f"nav  {code_out} {len(rows)}r ({total_rows:,} total)")
            await asyncio.gather(*[process_one(c) for c in new_codes])

    if progress is not None:
        await _run(progress)
    else:
        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
            TaskProgressColumn(), TimeElapsedColumn(),
            TextColumn("[cyan]{task.description}"), refresh_per_second=4,
        ) as prog:
            await _run(prog)
    print(f"  Fund NAVs: {total_rows:,} rows. {len(errors)} codes returned no data.")


# ── 5. Fund rank (fund_open_fund_rank_em) ─────────────────────────────────────

async def load_fund_rank(pool: asyncpg.Pool):
    """Snapshot of all open fund rankings and performance metrics."""
    print("Fetching fund rank snapshot...")
    df = ak.fund_open_fund_rank_em(symbol="全部")
    today = date.today()
    rows = []
    for _, r in df.iterrows():
        raw_code = str(r.get("基金代码") or "").strip()
        if not raw_code:
            continue
        raw_date = r.get("日期")
        try:
            nav_date = raw_date.date() if hasattr(raw_date, "date") else date.fromisoformat(str(raw_date))
        except Exception:
            nav_date = today
        rows.append((
            raw_code.zfill(6),
            nav_date,
            int(r["序号"])             if pd.notna(r.get("序号"))   else None,
            str(r["基金简称"])          if pd.notna(r.get("基金简称")) else None,
            float(r["单位净值"])        if pd.notna(r.get("单位净值")) else None,
            float(r["累计净值"])        if pd.notna(r.get("累计净值")) else None,
            float(r["日增长率"])        if pd.notna(r.get("日增长率")) else None,
            float(r["近1周"])           if pd.notna(r.get("近1周"))   else None,
            float(r["近1月"])           if pd.notna(r.get("近1月"))   else None,
            float(r["近3月"])           if pd.notna(r.get("近3月"))   else None,
            float(r["近6月"])           if pd.notna(r.get("近6月"))   else None,
            float(r["近1年"])           if pd.notna(r.get("近1年"))   else None,
            float(r["近2年"])           if pd.notna(r.get("近2年"))   else None,
            float(r["近3年"])           if pd.notna(r.get("近3年"))   else None,
            float(r["今年来"])          if pd.notna(r.get("今年来"))   else None,
            float(r["成立来"])          if pd.notna(r.get("成立来"))   else None,
            float(r["自定义"])          if pd.notna(r.get("自定义"))   else None,
            str(r["手续费"])            if pd.notna(r.get("手续费"))   else None,
        ))
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO fund_rank (
                fund_code, date, rank, name,
                unit_nav, accum_nav, daily_return_pct,
                return_1w, return_1m, return_3m, return_6m,
                return_1y, return_2y, return_3y,
                return_ytd, return_since_inception, return_custom, fee
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
            ON CONFLICT (fund_code, date) DO UPDATE SET
                rank=EXCLUDED.rank, unit_nav=EXCLUDED.unit_nav,
                accum_nav=EXCLUDED.accum_nav, daily_return_pct=EXCLUDED.daily_return_pct,
                return_1w=EXCLUDED.return_1w, return_1m=EXCLUDED.return_1m,
                return_3m=EXCLUDED.return_3m, return_6m=EXCLUDED.return_6m,
                return_1y=EXCLUDED.return_1y, return_2y=EXCLUDED.return_2y,
                return_3y=EXCLUDED.return_3y, return_ytd=EXCLUDED.return_ytd,
                return_since_inception=EXCLUDED.return_since_inception,
                return_custom=EXCLUDED.return_custom, fee=EXCLUDED.fee,
                updated_at=now()
        """, rows)
    print(f"  Fund rank: {len(rows):,} rows")


# ── 6. Fund ratings (fund_rating_all) ─────────────────────────────────────────

async def load_fund_ratings(pool: asyncpg.Pool):
    """Load multi-agency fund ratings snapshot."""
    print("Fetching fund ratings...")
    df = ak.fund_rating_all()
    rows = []
    for _, r in df.iterrows():
        raw_code = str(r.get("代码") or "").strip()
        if not raw_code:
            continue
        rows.append((
            raw_code.zfill(6),
            str(r["简称"])       if pd.notna(r.get("简称"))    else None,
            str(r["基金经理"])    if pd.notna(r.get("基金经理")) else None,
            str(r["基金公司"])    if pd.notna(r.get("基金公司")) else None,
            int(r["5星评级家数"]) if pd.notna(r.get("5星评级家数")) else None,
            float(r["上海证券"]) if pd.notna(r.get("上海证券")) else None,
            float(r["招商证券"]) if pd.notna(r.get("招商证券")) else None,
            float(r["济安金信"]) if pd.notna(r.get("济安金信")) else None,
            float(r["晨星评级"]) if pd.notna(r.get("晨星评级")) else None,
            float(r["手续费"])   if pd.notna(r.get("手续费"))  else None,
            str(r["类型"])       if pd.notna(r.get("类型"))    else None,
        ))
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO fund_rating (
                fund_code, name, managers, company, five_star_count,
                rating_shzq, rating_zszq, rating_jajx, rating_morningstar,
                fee, type
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (fund_code) DO UPDATE SET
                name=EXCLUDED.name, managers=EXCLUDED.managers,
                company=EXCLUDED.company, five_star_count=EXCLUDED.five_star_count,
                rating_shzq=EXCLUDED.rating_shzq, rating_zszq=EXCLUDED.rating_zszq,
                rating_jajx=EXCLUDED.rating_jajx, rating_morningstar=EXCLUDED.rating_morningstar,
                fee=EXCLUDED.fee, type=EXCLUDED.type, updated_at=now()
        """, rows)
    print(f"  Fund ratings: {len(rows):,} rows")


# ── 7. Fees via fund_overview_em ──────────────────────────────────────────────

def _fetch_overview(code: str) -> tuple[str, dict | None]:
    try:
        s = ak.fund_overview_em(symbol=code)
        row = s.iloc[0]
        # Inception date is in '成立日期/规模' as 'YYYY年MM月DD日 / ...'
        raw_date = str(row.get("成立日期/规模") or "")
        m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", raw_date)
        inception_iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        return code, {
            "full_name":         str(row.get("基金全称")     or ""),
            "inception_date":    inception_iso,
            "tracking_index":    str(row.get("跟踪标的")     or ""),
            "mgmt_company":      str(row.get("基金管理人")   or ""),
            "custodian":         str(row.get("基金托管人")   or ""),
            "mgmt_rate":         _parse_rate(row.get("管理费率")),
            "custody_rate":      _parse_rate(row.get("托管费率")),
            "sales_svc_rate":    _parse_rate(row.get("销售服务费率")),
            "subscription_rate": _parse_rate(row.get("最高认购费率")),
        }
    except Exception:
        return code, None


async def load_fees(pool: asyncpg.Pool, codes: list[str]):
    """Fetch fund overview and fees for each code, update funds table and insert fund_fees row."""
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    ok = 0
    today = date.today()
    with Progress(
        SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        TextColumn("[cyan]{task.description}"), refresh_per_second=4,
    ) as progress:
        task = progress.add_task("Fund overview/fees...", total=len(codes))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str):
                nonlocal ok
                async with sem:
                    code_out, data = await loop.run_in_executor(executor, _fetch_overview, code)
                    if data:
                        async with pool.acquire() as conn:
                            await conn.execute("""
                                UPDATE funds SET
                                  full_name      = NULLIF($2, ''),
                                  inception_date = CASE WHEN $3 ~ E'^\\d{4}-\\d{2}-\\d{2}$'
                                                        THEN $3::DATE ELSE NULL END,
                                  tracking_index = NULLIF($4, ''),
                                  mgmt_company   = NULLIF($5, ''),
                                  custodian      = NULLIF($6, ''),
                                  updated_at     = now()
                                WHERE code = $1
                            """, code, data["full_name"], data["inception_date"],
                                data["tracking_index"], data["mgmt_company"], data["custodian"])
                            await conn.execute("""
                                INSERT INTO fund_fees
                                  (fund_code, mgmt_rate, custody_rate, sales_svc_rate, subscription_rate, effective_date)
                                VALUES ($1,$2,$3,$4,$5,$6)
                                ON CONFLICT (fund_code, effective_date) DO NOTHING
                            """, code, data["mgmt_rate"], data["custody_rate"],
                                data["sales_svc_rate"], data["subscription_rate"], today)
                        ok += 1
                    progress.update(task, advance=1, description=f"{code_out}")
            await asyncio.gather(*[process_one(c) for c in codes])
    print(f"  Fund overview/fees: {ok}/{len(codes)} succeeded")


# ── 6. Quarterly holdings ─────────────────────────────────────────────────────

def _fetch_holdings(code: str, year: int) -> tuple[str, int, list]:
    try:
        df = ak.fund_portfolio_hold_em(symbol=code, date=str(year))
        if df is None or df.empty:
            return code, year, []
        rows = []
        for _, r in df.iterrows():
            try:
                quarter   = str(r.get("季度")    or "").strip()
                raw_code  = str(r.get("股票代码") or "").strip()
                if not quarter or not raw_code:
                    continue
                if raw_code.isdigit():
                    raw_code = raw_code.zfill(6)
                rows.append((
                    code, quarter, "stock",  # fund_portfolio_hold_em only returns equity holdings
                    raw_code,
                    str(r.get("股票名称") or ""),
                    float(r["占净值比例"]) if pd.notna(r.get("占净值比例")) else None,
                    int(float(r["持股数"])) if pd.notna(r.get("持股数")) else None,
                    float(r["持仓市值"])   if pd.notna(r.get("持仓市值")) else None,
                ))
            except Exception:
                continue
        return code, year, rows
    except Exception:
        return code, year, []


async def load_holdings(pool: asyncpg.Pool, codes: list[str]):
    """Load quarterly stock holdings for each fund for START_YEAR to current year."""
    years = list(range(START_YEAR, date.today().year + 1))
    tasks_list = [(c, y) for c in codes for y in years]
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY)
    total_rows = 0
    empty_count = 0
    with Progress(
        SpinnerColumn(), MofNCompleteColumn(), BarColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        TextColumn("[cyan]{task.description}"), refresh_per_second=4,
    ) as progress:
        ptask = progress.add_task("Holdings...", total=len(tasks_list))
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            async def process_one(code: str, year: int):
                nonlocal total_rows, empty_count
                async with sem:
                    code_out, yr, rows = await loop.run_in_executor(
                        executor, _fetch_holdings, code, year)
                    if rows:
                        async with pool.acquire() as conn:
                            await conn.executemany("""
                                INSERT INTO fund_holdings
                                  (fund_code, quarter, holding_type, security_code, security_name,
                                   pct_of_nav, shares, market_value)
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                                ON CONFLICT DO NOTHING
                            """, rows)
                        total_rows += len(rows)
                    else:
                        empty_count += 1
                    progress.update(ptask, advance=1,
                        description=f"{code_out}/{yr} {len(rows)} rows ({total_rows:,} total)")
            await asyncio.gather(*[process_one(c, y) for c, y in tasks_list])
    print(f"  Holdings: {total_rows:,} rows. {empty_count} fund/year combos returned no data.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    pool = await asyncpg.create_pool(_build_dsn(), min_size=2, max_size=CONCURRENCY + 2)

    # 1. Catalog (returns all fund codes)
    all_codes = await load_catalog(pool)
    if LOCAL_TEST:
        print(f"LOCAL_TEST: capping to 50 funds")
        all_codes = all_codes[:50]

    # 2. Managers + profiles
    await load_managers(pool)
    await load_manager_profiles(pool)

    # 3. NAV for all funds
    print(f"\nLoading fund NAV ({len(all_codes):,} funds, {PRICE_START}–{PRICE_END})...")
    await load_fund_navs(pool, all_codes)

    # 4. Fund rank snapshot
    print("\nLoading fund rank...")
    await load_fund_rank(pool)

    # 5. Fund ratings
    print("\nLoading fund ratings...")
    await load_fund_ratings(pool)

    await pool.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
