"""Structured financial data for Chinese A-shares via EastMoney datacenter APIs.

Provides:
- Financial statements (balance sheet, income, cash flow) — quarterly, 10+ years
- Top 10 shareholders with holding changes
- Dragon Tiger List (龙虎榜) — broker buy/sell on exceptional trading days
- Dividend history
"""

import logging
import httpx

logger = logging.getLogger(__name__)

_DC_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}
_TIMEOUT = 15


def _secucode(code: str) -> str:
    """Convert 6-digit code to SECUCODE format (e.g. 600173.SH)."""
    if code.startswith("6") or code.startswith("5"):
        return f"{code}.SH"
    return f"{code}.SZ"


def _fmt_yuan(v) -> str | None:
    """Format yuan value to readable string."""
    if v is None:
        return None
    try:
        v = float(v)
    except (ValueError, TypeError):
        return None
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


async def _query_dc(report_name: str, filter_str: str, sort_col: str = "REPORT_DATE",
                    page_size: int = 20, columns: str = "ALL") -> list[dict]:
    """Query EastMoney datacenter API."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": 1,
        "pageSize": page_size,
        "sortTypes": "-1",
        "sortColumns": sort_col,
        "source": "WEB",
        "client": "WEB",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(_DC_BASE, params=params, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("success") or not data.get("result"):
        return []
    return data["result"].get("data", [])


# ── Tool schemas ─────────────────────────────────────────────────────

FETCH_STOCK_FINANCIALS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_stock_financials",
        "description": (
            "Fetch structured quarterly/annual financial statements for a Chinese A-share company "
            "from EastMoney. Choose statement type: balance sheet (资产负债表), income statement (利润表), "
            "or cash flow statement (现金流量表). Returns 10+ years of quarterly data with exact numbers. "
            "Use this for trend analysis, financial health assessment, and detailed comparisons."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600519', '000001'",
                },
                "statement": {
                    "type": "string",
                    "enum": ["balance", "income", "cashflow"],
                    "description": "Financial statement type: balance=资产负债表, income=利润表, cashflow=现金流量表",
                },
                "periods": {
                    "type": "integer",
                    "description": "Number of recent reporting periods to return (default 8 = ~2 years quarterly)",
                    "default": 8,
                },
            },
            "required": ["stock_code", "statement"],
        },
    },
}

FETCH_TOP_SHAREHOLDERS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_top_shareholders",
        "description": (
            "Fetch top 10 circulating shareholders (十大流通股东) for a Chinese A-share company. "
            "Shows shareholder names, share counts, percentage held, and changes (新进/增持/减持/不变) "
            "across reporting periods. Use this to track institutional ownership changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600519', '000001'",
                },
                "periods": {
                    "type": "integer",
                    "description": "Number of recent reporting periods (default 2, each has 10 shareholders)",
                    "default": 2,
                },
            },
            "required": ["stock_code"],
        },
    },
}

FETCH_DRAGON_TIGER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_dragon_tiger",
        "description": (
            "Fetch Dragon Tiger List (龙虎榜) data for a Chinese A-share stock. "
            "Shows which brokerages were the top buyers and sellers on days when the stock "
            "had exceptional price moves (涨跌停, 振幅超7%, etc.). Includes buy/sell amounts "
            "by individual broker branches. Use this to see institutional/hot-money trading patterns."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600519', '000001'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent entries to return (default 20)",
                    "default": 20,
                },
            },
            "required": ["stock_code"],
        },
    },
}

FETCH_DIVIDEND_HISTORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_dividend_history",
        "description": (
            "Fetch complete dividend and share bonus history (分红送配) for a Chinese A-share company. "
            "Shows cash dividends per 10 shares, bonus shares, ex-dividend dates, and distribution progress. "
            "Use this for dividend yield analysis and payout consistency."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit stock code, e.g. '600519', '000001'",
                },
            },
            "required": ["stock_code"],
        },
    },
}


# ── Tool implementations ─────────────────────────────────────────────

_REPORT_MAP = {
    "balance": "RPT_DMSK_FN_BALANCE",
    "income": "RPT_DMSK_FN_INCOME",
    "cashflow": "RPT_DMSK_FN_CASHFLOW",
}

_BALANCE_FIELDS = [
    ("REPORT_DATE", "报告期"),
    ("TOTAL_ASSETS", "总资产"),
    ("TOTAL_LIABILITIES", "总负债"),
    ("TOTAL_EQUITY", "净资产(股东权益)"),
    ("DEBT_ASSET_RATIO", "资产负债率(%)"),
    ("CURRENT_RATIO", "流动比率"),
    ("MONETARYFUNDS", "货币资金"),
    ("ACCOUNTS_RECE", "应收账款"),
    ("INVENTORY", "存货"),
    ("FIXED_ASSET", "固定资产"),
    ("ACCOUNTS_PAYABLE", "应付账款"),
]

_INCOME_FIELDS = [
    ("REPORT_DATE", "报告期"),
    ("TOTAL_OPERATE_INCOME", "营业总收入"),
    ("TOI_RATIO", "营收同比(%)"),
    ("TOTAL_OPERATE_COST", "营业总成本"),
    ("OPERATE_COST", "营业成本"),
    ("SALE_EXPENSE", "销售费用"),
    ("MANAGE_EXPENSE", "管理费用"),
    ("FINANCE_EXPENSE", "财务费用"),
    ("OPERATE_PROFIT", "营业利润"),
    ("TOTAL_PROFIT", "利润总额"),
    ("PARENT_NETPROFIT", "归母净利润"),
    ("PARENT_NETPROFIT_RATIO", "净利润同比(%)"),
    ("DEDUCT_PARENT_NETPROFIT", "扣非归母净利润"),
    ("INCOME_TAX", "所得税"),
]

_CASHFLOW_FIELDS = [
    ("REPORT_DATE", "报告期"),
    ("SALES_SERVICES", "销售收到现金"),
    ("NETCASH_OPERATE", "经营活动净现金流"),
    ("NETCASH_INVEST", "投资活动净现金流"),
    ("NETCASH_FINANCE", "筹资活动净现金流"),
    ("CCE_ADD", "现金净增加额"),
    ("PAY_STAFF_CASH", "支付员工现金"),
    ("CONSTRUCT_LONG_ASSET", "购建固定资产等"),
]

_FIELD_MAP = {
    "balance": _BALANCE_FIELDS,
    "income": _INCOME_FIELDS,
    "cashflow": _CASHFLOW_FIELDS,
}


async def fetch_stock_financials(stock_code: str, statement: str, periods: int = 8) -> dict:
    """Fetch structured financial statements."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}
    if statement not in _REPORT_MAP:
        return {"error": f"Invalid statement: {statement}. Must be: balance, income, cashflow"}

    periods = min(max(periods, 1), 40)
    sc = _secucode(code)
    report_name = _REPORT_MAP[statement]
    fields = _FIELD_MAP[statement]

    try:
        rows = await _query_dc(report_name, f'(SECUCODE="{sc}")', page_size=periods)
    except Exception as e:
        return {"error": f"Failed to fetch financials: {e}"}

    if not rows:
        return {"error": f"No {statement} data for {code}", "stock_code": code}

    statement_cn = {"balance": "资产负债表", "income": "利润表", "cashflow": "现金流量表"}
    # Fields that are ratios/percentages, not yuan amounts
    ratio_fields = {"DEBT_ASSET_RATIO", "CURRENT_RATIO", "TOI_RATIO",
                    "PARENT_NETPROFIT_RATIO", "DPN_RATIO"}

    records = []
    for row in rows:
        record = {}
        for api_key, cn_name in fields:
            val = row.get(api_key)
            if api_key == "REPORT_DATE" and val:
                record[cn_name] = val[:10]
            elif api_key in ratio_fields and val is not None:
                record[cn_name] = f"{val:.2f}" if isinstance(val, float) else val
            elif isinstance(val, (int, float)):
                record[cn_name] = _fmt_yuan(val)
            else:
                record[cn_name] = val
        records.append(record)

    return {
        "stock_code": code,
        "statement_type": statement_cn[statement],
        "periods": len(records),
        "data": records,
    }


async def fetch_top_shareholders(stock_code: str, periods: int = 2) -> dict:
    """Fetch top 10 circulating shareholders."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    periods = min(max(periods, 1), 10)
    sc = _secucode(code)

    try:
        rows = await _query_dc(
            "RPT_F10_EH_FREEHOLDERS", f'(SECUCODE="{sc}")',
            sort_col="END_DATE", page_size=periods * 10,
        )
    except Exception as e:
        return {"error": f"Failed to fetch shareholders: {e}"}

    if not rows:
        return {"error": f"No shareholder data for {code}", "stock_code": code}

    # Group by reporting period
    by_period: dict[str, list] = {}
    for row in rows:
        date = row.get("END_DATE", "")[:10]
        if date not in by_period:
            by_period[date] = []
        by_period[date].append({
            "rank": row.get("HOLDER_RANK"),
            "name": row.get("HOLDER_NAME"),
            "shares": _fmt_yuan(row.get("HOLD_NUM")),
            "pct": f"{row.get('FREE_HOLDNUM_RATIO', 0):.2f}%" if row.get("FREE_HOLDNUM_RATIO") else None,
            "change": row.get("HOLD_NUM_CHANGE", ""),
            "is_institution": row.get("IS_HOLDORG") == "1",
        })

    result_periods = []
    for date in sorted(by_period.keys(), reverse=True)[:periods]:
        holders = sorted(by_period[date], key=lambda x: x.get("rank") or 99)
        result_periods.append({
            "report_date": date,
            "holders": holders,
        })

    return {
        "stock_code": code,
        "periods": result_periods,
    }


async def fetch_dragon_tiger(stock_code: str, limit: int = 20) -> dict:
    """Fetch Dragon Tiger List (龙虎榜) data."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    limit = min(max(limit, 1), 50)

    try:
        buy_rows = await _query_dc(
            "RPT_BILLBOARD_DAILYDETAILSBUY", f'(SECURITY_CODE="{code}")',
            sort_col="TRADE_DATE", page_size=limit,
        )
        sell_rows = await _query_dc(
            "RPT_BILLBOARD_DAILYDETAILSSELL", f'(SECURITY_CODE="{code}")',
            sort_col="TRADE_DATE", page_size=limit,
        )
    except Exception as e:
        return {"error": f"Failed to fetch dragon tiger data: {e}"}

    if not buy_rows and not sell_rows:
        return {"error": f"No dragon tiger data for {code}", "stock_code": code}

    def parse_entries(rows: list, side: str) -> list[dict]:
        entries = []
        for row in rows:
            entries.append({
                "date": row.get("TRADE_DATE", "")[:10],
                "side": side,
                "broker": row.get("OPERATEDEPT_NAME"),
                "buy_amount": _fmt_yuan(row.get("BUY")),
                "sell_amount": _fmt_yuan(row.get("SELL")),
                "net": _fmt_yuan(row.get("NET")),
                "close_price": row.get("CLOSE_PRICE"),
                "change_pct": f"{row.get('CHANGE_RATE', '')}%" if row.get("CHANGE_RATE") is not None else None,
                "turnover_rate": f"{row.get('TURNOVERRATE', '')}%" if row.get("TURNOVERRATE") is not None else None,
            })
        return entries

    buys = parse_entries(buy_rows, "buy")
    sells = parse_entries(sell_rows, "sell")

    # Merge and sort by date
    all_entries = sorted(buys + sells, key=lambda x: x["date"], reverse=True)

    # Get unique dates for summary
    dates = sorted(set(e["date"] for e in all_entries), reverse=True)

    return {
        "stock_code": code,
        "total_appearances": len(dates),
        "note": "Dragon Tiger List only contains days with exceptional moves (涨跌停, 振幅>7%, etc.)",
        "entries": all_entries,
    }


async def fetch_dividend_history(stock_code: str) -> dict:
    """Fetch dividend and share bonus history."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code: {code}. Must be 6 digits."}

    try:
        rows = await _query_dc(
            "RPT_SHAREBONUS_DET", f'(SECURITY_CODE="{code}")',
            sort_col="REPORT_DATE", page_size=50,
        )
    except Exception as e:
        return {"error": f"Failed to fetch dividend history: {e}"}

    if not rows:
        return {"error": f"No dividend data for {code}", "stock_code": code}

    records = []
    for row in rows:
        cash = row.get("PRETAX_BONUS_RMB")
        bonus = row.get("BONUS_RATIO")
        convert = row.get("IT_RATIO")

        # Build description
        parts = []
        if cash and float(cash) > 0:
            parts.append(f"每10股派{cash}元")
        if bonus and float(bonus) > 0:
            parts.append(f"每10股送{bonus}股")
        if convert and float(convert) > 0:
            parts.append(f"每10股转{convert}股")

        records.append({
            "report_date": row.get("REPORT_DATE", "")[:10],
            "plan": "，".join(parts) if parts else "无分配",
            "cash_per_10": cash,
            "bonus_shares_per_10": bonus,
            "convert_per_10": convert,
            "ex_dividend_date": (row.get("EX_DIVIDEND_DATE") or "")[:10] or None,
            "record_date": (row.get("EQUITY_RECORD_DATE") or "")[:10] or None,
            "progress": row.get("ASSIGN_PROGRESS"),
            "eps": row.get("BASIC_EPS"),
        })

    # Summary
    cash_years = [float(r["cash_per_10"]) for r in records if r["cash_per_10"] and float(r["cash_per_10"]) > 0]

    return {
        "stock_code": code,
        "total_distributions": len(records),
        "years_with_cash_dividend": len(cash_years),
        "avg_cash_per_10": f"{sum(cash_years) / len(cash_years):.2f}" if cash_years else None,
        "history": records,
    }
