"""Query the local BaoStock `financials` table in the marketdata DB.

The `financials` table holds unified quarterly financial data for all A-share stocks,
covering profitability, operational efficiency, growth, solvency, cash flow, and
DuPont decomposition. Source: BaoStock. One row per stock per quarter.

Column reference: data/financials_columns.md
"""

import logging
from db import get_marketdata_pool

logger = logging.getLogger(__name__)

# ── Column metadata (mirrors data/financials_columns.md) ─────────────────────

_COLUMN_DESCRIPTIONS = {
    # Identity
    "code":                    "Stock code e.g. '600000'",
    "exchange":                "SH / SZ / BJ",
    "pub_date":                "Filing/publication date — use for backtesting (no look-ahead bias)",
    "stat_date":               "Period end date: Mar 31 / Jun 30 / Sep 30 / Dec 31",
    # Profitability
    "roe_avg":                 "Return on equity (average)",
    "np_margin":               "Net profit margin",
    "gp_margin":               "Gross profit margin",
    "net_profit":              "Net profit (yuan)",
    "eps_ttm":                 "EPS trailing twelve months",
    "mb_revenue":              "Main business revenue (yuan)",
    "total_share":             "Total shares outstanding",
    "liqa_share":              "Liquid (tradable) shares",
    # Operational efficiency
    "nr_turn_ratio":           "Accounts receivable turnover ratio",
    "nr_turn_days":            "Accounts receivable turnover days",
    "inv_turn_ratio":          "Inventory turnover ratio",
    "inv_turn_days":           "Inventory turnover days",
    "ca_turn_ratio":           "Current assets turnover ratio",
    "asset_turn_ratio":        "Total asset turnover ratio",
    # Growth (YoY, decimal — 0.15 = +15%)
    "yoy_equity":              "YoY growth: shareholders equity",
    "yoy_asset":               "YoY growth: total assets",
    "yoy_ni":                  "YoY growth: net income",
    "yoy_eps_basic":           "YoY growth: basic EPS",
    "yoy_pni":                 "YoY growth: parent company net income",
    # Solvency / balance sheet
    "current_ratio":           "Current ratio (current assets / current liabilities)",
    "quick_ratio":             "Quick ratio",
    "cash_ratio":              "Cash ratio",
    "yoy_liability":           "YoY growth: total liabilities",
    "liability_to_asset":      "Debt ratio (total liabilities / total assets)",
    "asset_to_equity":         "Financial leverage (total assets / equity)",
    # Cash flow
    "ca_to_asset":             "Current assets / total assets",
    "nca_to_asset":            "Non-current assets / total assets",
    "tangible_asset_to_asset": "Tangible assets / total assets",
    "ebit_to_interest":        "Interest coverage ratio (EBIT / interest expense)",
    "cfo_to_or":               "Operating cash flow / operating revenue",
    "cfo_to_np":               "Operating cash flow / net profit (cash quality indicator)",
    "cfo_to_gr":               "Operating cash flow / gross revenue",
    # DuPont decomposition (ROE = Net Margin × Asset Turnover × Leverage)
    "dupont_roe":              "Return on equity (DuPont)",
    "dupont_asset_sto_equity": "Assets / equity (leverage factor)",
    "dupont_asset_turn":       "Asset turnover",
    "dupont_pnitoni":          "Parent NI / total NI",
    "dupont_nitogr":           "Net income / gross revenue (net margin)",
    "dupont_tax_burden":       "Net income / pre-tax income (tax retention rate)",
    "dupont_int_burden":       "Pre-tax income / EBIT (interest burden)",
    "dupont_ebit_togr":        "EBIT / gross revenue (operating margin)",
}

# Default columns returned when the caller doesn't specify
_DEFAULT_COLUMNS = [
    "stat_date", "pub_date",
    "roe_avg", "np_margin", "gp_margin", "net_profit", "mb_revenue",
    "yoy_ni", "yoy_pni", "yoy_asset",
    "current_ratio", "liability_to_asset", "asset_to_equity",
    "cfo_to_np", "cfo_to_or",
    "eps_ttm",
    "dupont_roe", "dupont_asset_turn", "dupont_ebit_togr",
]

FETCH_BAOSTOCK_FINANCIALS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_baostock_financials",
        "description": (
            "Query the local BaoStock `financials` table (marketdata DB) for a Chinese A-share stock. "
            "Returns quarterly financial metrics sourced from BaoStock — covering profitability, "
            "operational efficiency, growth, solvency/balance-sheet, cash flow, and DuPont decomposition. "
            "This is different from fetch_stock_financials (EastMoney API): use this for deeper ratio analysis "
            "(DuPont breakdown, cash quality CFO/NP, operational efficiency ratios) or when you need "
            "backtesting-safe data (filter by pub_date). "
            "pub_date = filing date (no look-ahead bias); stat_date = period end date. "
            "Available columns — Profitability: roe_avg, np_margin, gp_margin, net_profit, eps_ttm, mb_revenue. "
            "Growth (YoY decimal): yoy_ni, yoy_pni, yoy_asset, yoy_equity, yoy_eps_basic. "
            "Solvency: current_ratio, quick_ratio, liability_to_asset, asset_to_equity. "
            "Cash flow quality: cfo_to_np (CFO/net profit), cfo_to_or (CFO/revenue), ebit_to_interest. "
            "DuPont: dupont_roe, dupont_asset_turn, dupont_ebit_togr, dupont_nitogr, dupont_tax_burden, dupont_int_burden. "
            "Efficiency: nr_turn_days, inv_turn_days, asset_turn_ratio."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share stock code, e.g. '600036', '000001'",
                },
                "periods": {
                    "type": "integer",
                    "description": "Number of most-recent quarters to return (default 8, max 20)",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific columns to return. Omit to get the default set covering key ratios. "
                        "See tool description for available column names."
                    ),
                },
            },
            "required": ["stock_code"],
        },
    },
}


async def fetch_baostock_financials(
    stock_code: str,
    periods: int = 8,
    columns: list[str] | None = None,
) -> dict:
    """Query the local financials table for a stock and return structured quarterly data."""
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"error": f"Invalid stock code '{code}'. Must be 6 digits e.g. '600036'."}

    periods = min(max(int(periods), 1), 20)

    # Resolve which columns to fetch
    requested = columns if columns else _DEFAULT_COLUMNS
    # Always include stat_date for orientation
    select_cols = list(dict.fromkeys(["stat_date", "pub_date"] + requested))
    # Validate column names against known set
    valid = set(_COLUMN_DESCRIPTIONS.keys())
    unknown = [c for c in select_cols if c not in valid]
    if unknown:
        return {"error": f"Unknown column(s): {unknown}. See tool description for valid names."}

    col_sql = ", ".join(select_cols)

    try:
        pool = await get_marketdata_pool()
        rows = await pool.fetch(
            f"SELECT {col_sql} FROM financials WHERE code = $1 "
            f"ORDER BY stat_date DESC LIMIT $2",
            code, periods,
        )
    except Exception as e:
        logger.error(f"fetch_baostock_financials failed for {code}: {e}")
        return {"error": f"DB query failed: {e}"}

    if not rows:
        return {
            "stock_code": code,
            "message": "No financial data found in local DB. "
                       "Run data/ingest_financials.py to populate.",
            "rows": [],
        }

    def _fmt(v):
        if v is None:
            return None
        if isinstance(v, float):
            return round(v, 6)
        return v

    data = [
        {col: _fmt(row[col]) for col in select_cols}
        for row in rows
    ]

    # Include column descriptions for the returned columns
    col_docs = {c: _COLUMN_DESCRIPTIONS[c] for c in select_cols if c in _COLUMN_DESCRIPTIONS}

    return {
        "stock_code": code,
        "periods_returned": len(data),
        "columns_doc": col_docs,
        "data": data,
        "note": (
            "pub_date = filing date (backtesting-safe). "
            "Ratio values are decimals: 0.15 = 15%. "
            "YoY columns (yoy_*) are year-over-year change: 0.20 = +20%."
        ),
    }
