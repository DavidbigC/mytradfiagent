"""
Fetch all A-share stock names/codes from SSE, SZSE, and BSE official APIs
and upsert into the stocknames table.

As a library:
    from tools.populate_stocknames import populate_stocknames
    await populate_stocknames(pool)

As a standalone script:
    python tools/populate_stocknames.py
"""

import asyncio
import json
import logging
import re
import warnings
from datetime import date, datetime
from io import BytesIO

import requests
import pandas as pd

log = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO stocknames (stock_code, exchange, stock_name, full_name, sector, industry, list_date)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (stock_code, exchange) DO UPDATE SET
    stock_name = EXCLUDED.stock_name,
    full_name  = EXCLUDED.full_name,
    sector     = EXCLUDED.sector,
    industry   = EXCLUDED.industry,
    list_date  = EXCLUDED.list_date,
    updated_at = now()
"""


def _parse_date(raw) -> date | None:
    if not raw or str(raw).strip() in ("-", "nan", "None", ""):
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _clean_industry(raw) -> str | None:
    if not raw:
        return None
    return re.sub(r"^[A-Z]\s+", "", str(raw).strip()) or None


# ─────────────────────────────────────────
# Sync fetch functions (run in thread pool)
# ─────────────────────────────────────────

def _fetch_sse() -> list[tuple]:
    url = "https://query.sse.com.cn/sseQuery/commonQuery.do"
    headers = {
        "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    rows = []
    for stock_type, sector in [("1", "主板"), ("8", "科创板")]:
        params = {
            "STOCK_TYPE": stock_type,
            "CSRC_CODE": "", "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
            "COMPANY_STATUS": "2,4,5,7,8",
            "type": "inParams",
            "isPagination": "true",
            "pageHelp.pageSize": "10000",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.endPage": "1",
            "pageHelp.cacheSize": "1",
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json().get("result", [])
        for rec in data:
            rows.append((
                rec.get("A_STOCK_CODE", "").strip(),
                "SH",
                rec.get("SEC_NAME_CN", "").strip(),
                rec.get("FULL_NAME", "").strip() or None,
                sector,
                _clean_industry(rec.get("CSRC_CODE_DESC")),
                _parse_date(rec.get("LIST_DATE")),
            ))
        log.info(f"SSE {sector}: {len(data)} stocks fetched")
    return rows


def _fetch_szse() -> list[tuple]:
    url = "https://www.szse.cn/api/report/ShowReport"
    params = {"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1", "random": "0.12345"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        df = pd.read_excel(BytesIO(r.content))
    rows = []
    for _, rec in df.iterrows():
        code = str(rec.get("A股代码", "")).split(".")[0].strip().zfill(6)
        if not code or code == "000nan":
            continue
        rows.append((
            code,
            "SZ",
            str(rec.get("A股简称", "")).strip(),
            str(rec.get("公司全称", "")).strip() or None,
            str(rec.get("板块", "")).strip() or None,
            _clean_industry(rec.get("所属行业")),
            _parse_date(rec.get("A股上市日期")),
        ))
    log.info(f"SZSE: {len(rows)} stocks fetched")
    return rows


def _bse_post(session, url, payload, headers, retries=3) -> dict:
    """POST to BSE with retries on connection errors."""
    import time
    for attempt in range(retries):
        try:
            r = session.post(url, data=payload, headers=headers, timeout=20)
            r.raise_for_status()
            text = r.text
            return json.loads(text[text.find("["):-1])
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                log.warning(f"BSE page {payload.get('page')} failed (attempt {attempt+1}), retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


def _fetch_bse(delay: float = 0) -> list[tuple]:
    import time
    if delay:
        time.sleep(delay)
    url = "https://www.bseinfo.net/nqxxController/nqxxCnzq.do"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bseinfo.net/nq/listedcompany.html",
    }
    payload = {"page": "0", "typejb": "T", "xxfcbj[]": "2", "xxzqdm": "", "sortfield": "xxzqdm", "sorttype": "asc"}

    session = requests.Session()
    data = _bse_post(session, url, payload, headers)
    total_pages = data[0]["totalPages"]
    all_records = list(data[0]["content"])

    for page in range(1, total_pages):
        payload["page"] = str(page)
        data = _bse_post(session, url, payload, headers)
        all_records.extend(data[0]["content"])

    rows = []
    for rec in all_records:
        code = str(rec.get("xxzqdm", "")).strip().zfill(6)
        if not code:
            continue
        rows.append((
            code,
            "BJ",
            str(rec.get("xxzqjc", "")).strip(),
            None,
            "北交所",
            str(rec.get("xxhyzl", "")).strip() or None,
            _parse_date(rec.get("fxssrq")),
        ))
    log.info(f"BSE: {len(rows)} stocks fetched")
    return rows


# ─────────────────────────────────────────
# Main async entry point
# ─────────────────────────────────────────

async def populate_stocknames(pool) -> int:
    """Fetch all stocks from SSE/SZSE/BSE and upsert into stocknames. Returns row count.
    Partial success is accepted — if one exchange fails, the others are still saved."""
    log.info("populate_stocknames: starting fetch from all exchanges...")

    results = await asyncio.gather(
        asyncio.to_thread(_fetch_sse),
        asyncio.to_thread(_fetch_szse),
        asyncio.to_thread(_fetch_bse, 3.0),   # 5s delay so BSE starts after SSE/SZSE settle
        return_exceptions=True,
    )

    labels = ["SSE", "SZSE", "BSE"]
    all_rows = []
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            log.error(f"populate_stocknames: {label} fetch failed — {result}")
        else:
            all_rows.extend(result)

    if not all_rows:
        raise RuntimeError("All exchange fetches failed — nothing to upsert")

    log.info(f"populate_stocknames: upserting {len(all_rows)} stocks...")
    async with pool.acquire() as conn:
        await conn.executemany(UPSERT_SQL, all_rows)

    count = await pool.fetchval("SELECT COUNT(*) FROM stocknames")
    log.info(f"populate_stocknames: done. stocknames table now has {count} rows.")
    return count


# ─────────────────────────────────────────
# Standalone script
# ─────────────────────────────────────────

async def _standalone():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from dotenv import load_dotenv
    load_dotenv()
    import asyncpg
    from config import DATABASE_URL

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Ensure table exists
        from db import SCHEMA_SQL
        await conn.execute(SCHEMA_SQL)
        pool_mock = conn  # single connection works with executemany + fetchval
        await populate_stocknames(pool_mock)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_standalone())
