# TradingView China Stock Data Sources

## Overview

TradingView provides a powerful scanner/screener API that returns real-time data for all ~5,265 Chinese A-share stocks (SSE + SZSE). No authentication required. Response time ~1-2 seconds.

---

## Web Pages

### Market Movers (Pre-built Views)

Base URL: `https://cn.tradingview.com/markets/stocks-china/market-movers-{page}/`

| Page | URL Suffix | Description |
|------|-----------|-------------|
| All Stocks | `all-stocks` | All A-shares overview |
| Large Cap | `large-cap` | 大盘股 |
| Top Gainers | `gainers` | 涨幅最大 |
| Top Losers | `losers` | 跌幅最大 |
| Most Active | `active` | 成交最活跃 |
| 52-Week High | `52wk-high` | 52周新高 |
| 52-Week Low | `52wk-low` | 52周新低 |
| Most Volatile | `most-volatile` | 波动最大 |
| Overbought (RSI) | `overbought` | 超买 |
| Oversold (RSI) | `oversold` | 超卖 |
| Penny Stocks | `penny-stocks` | 低价股 |
| High Dividend | `high-dividend` | 高股息 |

### Screener (Custom Filters)

URL: https://cn.tradingview.com/screener/

Allows custom column selection, multi-condition filtering, and sorting by any metric.

---

## Scanner API

**Endpoint:** `POST https://scanner.tradingview.com/china/scan`

**Headers:** `User-Agent: Mozilla/5.0`

**No auth required. Response: JSON. Speed: ~1-2 seconds.**

### Request Format

```json
{
    "columns": ["name", "description", "close", "change", "volume", "market_cap_basic"],
    "filter": [
        {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]}
    ],
    "ignore_unknown_fields": true,
    "options": {"lang": "zh"},
    "range": [0, 20],
    "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
    "symbols": {"query": {"types": ["stock"]}},
    "markets": ["china"]
}
```

### Response Format

```json
{
    "totalCount": 5265,
    "data": [
        {
            "s": "SSE:601398",
            "d": ["601398", "工商银行", 7.11, -0.97, 317392510, 2405571239940]
        }
    ]
}
```

`d` array values correspond to the `columns` array in the request, in the same order.

---

## Available Columns (Fields) — Verified Working

All fields below have been tested and confirmed to return data for Chinese A-share stocks. Some fields may return null for specific industries (e.g., banks often lack gross_margin, ebitda).

### Price & Trading

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `name` | Stock code | "601398" | |
| `description` | Stock name (Chinese) | "工商银行" | |
| `close` | Latest price | 7.11 | |
| `open` | Open price | 7.18 | |
| `high` | High | 7.20 | |
| `low` | Low | 7.08 | |
| `change` | Change % | -0.97 | |
| `change_abs` | Change (absolute) | -0.07 | |
| `volume` | Volume (shares) | 317392510 | |
| `Value.Traded` | Turnover (CNY) | 2263848000 | |
| `average_volume_10d_calc` | 10-day avg volume | 187103001 | |
| `average_volume_30d_calc` | 30-day avg volume | 234801483 | |
| `relative_volume_10d_calc` | Relative volume vs 10d avg | 1.28 | Good for spotting unusual activity |
| `gap` | Gap % (from previous close) | 0.14 | |

### Valuation

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `market_cap_basic` | Total market cap (CNY) | 2405571239940 | |
| `price_earnings_ttm` | PE ratio (TTM) | 6.91 | |
| `price_book_ratio` | PB ratio | 0.70 | |
| `enterprise_value_ebitda_ttm` | EV/EBITDA | 3.21 | Often null for banks |
| `price_free_cash_flow_ttm` | P/FCF ratio | 14.97 | Null if FCF negative |

### Per-Share Data

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `earnings_per_share_basic_ttm` | Basic EPS (TTM) | 1.03 | |
| `earnings_per_share_diluted_ttm` | Diluted EPS (TTM) | 1.03 | |
| `revenue_per_share_ttm` | Revenue per share (TTM) | 4.38 | |
| `basic_eps_net_income` | EPS from net income | 0.90 | |
| `dps_common_stock_prim_issue_fy` | Dividends per share (annual) | 0.47 | Full-year DPS |
| `dividends_per_share_fq` | Dividends per share (quarterly) | 0.24 | May be 0 for annual payers |

### Dividends & Returns

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `dividend_yield_recent` | Dividend yield % | 4.30 | |
| `return_on_equity` | ROE % | 10.38 | |
| `return_on_assets` | ROA % | 5.62 | |

### Income Statement

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `total_revenue` | Total revenue (CNY) | 2730893000000 | |
| `net_income` | Net income (CNY) | 164676000000 | |
| `gross_profit` | Gross profit (CNY) | 433137000000 | |
| `ebitda` | EBITDA (CNY) | 406435000000 | Often null for banks |

### Profitability Margins

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `gross_margin` | Gross margin % | 92.40 | Null for banks |
| `operating_margin` | Operating margin % | 68.27 | |
| `net_margin` | Net margin % | 49.49 | |
| `pre_tax_margin` | Pre-tax margin % | 68.71 | Null for some banks |
| `after_tax_margin` | After-tax margin % | 49.49 | Same as net_margin |

### Balance Sheet

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `total_assets` | Total assets (CNY) | 52813421000000 | Works for all stocks |
| `total_debt` | Total debt (CNY) | 373311000000 | Works for all stocks |
| `total_current_assets` | Current assets (CNY) | 701419000000 | Works for all stocks |
| `net_debt` | Net debt (CNY) | 83820000000 | Negative = net cash position |
| `goodwill` | Goodwill (CNY) | 7372000000 | 0 if none |
| `debt_to_equity` | D/E ratio | 0.24 | |
| `current_ratio` | Current ratio | 1.15 | |
| `quick_ratio` | Quick ratio | 0.88 | |

**Fields tested but always null for China stocks:**
- `total_liabilities`, `total_current_liabilities`
- `book_value_per_share`, `cash_and_equivalents`
- `intangible_assets`, `long_term_debt`, `short_term_debt`
- `accounts_receivable`, `inventory`

### Cash Flow

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `free_cash_flow` | Free cash flow (CNY) | 128851000000 | Negative for high-capex companies |

**Fields tested but always null for China stocks:**
- `operating_cash_flow`, `capital_expenditures`
- `cash_f_operating_activities`, `cash_f_investing_activities`, `cash_f_financing_activities`
- `free_cash_flow_per_share`, `cash_flow_per_share`

### Shares

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `total_shares_outstanding` | Total shares | 161922000000 | |
| `float_shares_outstanding` | Float shares | 7724000000 | |

### Other Fundamentals

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `number_of_employees` | Employee count | 370799 | |
| `earnings_release_next_date` | Next earnings date (Unix timestamp) | 1774872000 | |

### Performance

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `Perf.W` | 1-week performance % | -2.74 | |
| `Perf.1M` | 1-month performance % | -8.73 | |
| `Perf.3M` | 3-month performance % | -13.61 | |
| `Perf.6M` | 6-month performance % | -7.66 | |
| `Perf.Y` | 1-year performance % | 3.19 | |
| `Perf.YTD` | Year-to-date performance % | -10.11 | |
| `price_52_week_high` | 52-week high price | 11.15 | |
| `price_52_week_low` | 52-week low price | 7.33 | |
| `High.All` | All-time high price | 42.40 | |
| `Low.All` | All-time low price | 4.04 | |

### Technical Indicators

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `SMA50` | 50-day SMA | 7.62 | |
| `SMA200` | 200-day SMA | 7.58 | |
| `EMA50` | 50-day EMA | 7.53 | |
| `EMA200` | 200-day EMA | 7.46 | |
| `RSI` | RSI (14) | 31.16 | |
| `MACD.macd` | MACD line | -0.12 | |
| `BB.upper` | Bollinger Band upper | 7.48 | |
| `BB.lower` | Bollinger Band lower | 7.07 | |
| `ATR` | Average True Range | 0.12 | |
| `Stoch.K` | Stochastic %K | 23.61 | |
| `Stoch.D` | Stochastic %D | 39.63 | |
| `CCI20` | CCI (20) | -146.98 | |
| `ADX` | ADX | 24.73 | |
| `Aroon.Up` | Aroon Up | 28.57 | |
| `Aroon.Down` | Aroon Down | 100 | |
| `Pivot.M.Classic.S1` | Monthly Pivot S1 | 6.95 | |
| `Pivot.M.Classic.R1` | Monthly Pivot R1 | 7.74 | |
| `Recommend.All` | Overall technical rating (-1 to 1) | -0.56 | -1=strong sell, 1=strong buy |
| `Recommend.MA` | Moving average rating | -0.93 | |
| `Recommend.Other` | Oscillator rating | -0.18 | |
| `beta_1_year` | 1-year beta | 0.07 | |

**Fields tested but always null for China stocks:**
- `volatility_w`, `volatility_m`

### Classification

| Column | Description | Example | Notes |
|--------|-------------|---------|-------|
| `sector` | Sector | "Finance" | |
| `industry` | Industry | "Major Banks" | |
| `exchange` | Exchange | "SSE" or "SZSE" | |

### Growth Metrics

**All tested growth fields return null for China stocks:**
- `revenue_growth`, `earnings_growth`
- `revenue_growth_quarterly`, `earnings_growth_quarterly`
- `revenue_one_year_growth`, `earnings_one_year_growth`, `revenue_three_year_growth`
- `dividend_payout_ratio`

**Workaround:** Use `Perf.YTD`, `Perf.Y`, `Perf.3M` for price performance trends, or calculate growth from `total_revenue`/`net_income` across time periods.

### Other Fields Tested but Always Null

- `gross_margin` (null for banks, works for industrial/tech)
- `price_to_sales_ratio`, `debt_to_assets`, `interest_coverage`
- `asset_turnover`, `inventory_turnover`, `receivables_turnover`
- `operating_cash_flow`, `operating_income`

---

## Sort Options

Use `sort.sortBy` with any column name, and `sort.sortOrder` as `"desc"` or `"asc"`.

| Sort By | Use Case |
|---------|----------|
| `market_cap_basic` desc | Largest companies (市值最高) |
| `change` desc | Top gainers (涨幅最大) |
| `change` asc | Top losers (跌幅最大) |
| `volume` desc | Most traded by volume (成交量最大) |
| `Value.Traded` desc | Most traded by turnover (成交额最大) |
| `dividend_yield_recent` desc | Highest dividend yield (股息最高) |
| `relative_volume_10d_calc` desc | Unusual volume (异常放量) |
| `Perf.YTD` desc | Best YTD performance |
| `RSI` asc | Most oversold |
| `RSI` desc | Most overbought |
| `price_earnings_ttm` asc | Lowest PE (cheapest by earnings) |
| `price_book_ratio` asc | Lowest PB (cheapest by book value) |
| `return_on_equity` desc | Highest ROE |
| `gross_margin` desc | Highest gross margin |
| `net_margin` desc | Most profitable (by margin) |
| `total_assets` desc | Largest by total assets |
| `free_cash_flow` desc | Most free cash flow |
| `number_of_employees` desc | Largest employers |
| `beta_1_year` desc | Highest beta (most volatile) |
| `Recommend.All` desc | Best technical rating |

---

## Filter Options

Filters go in the `filter` array. Each filter is an object:

```json
{"left": "<field>", "operation": "<op>", "right": <value>}
```

### Operations

| Operation | Description | Example |
|-----------|-------------|---------|
| `greater` | > | `{"left": "market_cap_basic", "operation": "greater", "right": 100000000000}` |
| `less` | < | `{"left": "price_earnings_ttm", "operation": "less", "right": 15}` |
| `in_range` | in list | `{"left": "exchange", "operation": "in_range", "right": ["SSE"]}` |
| `equal` | = | `{"left": "sector", "operation": "equal", "right": "Finance"}` |
| `not_equal` | != | `{"left": "sector", "operation": "not_equal", "right": "Finance"}` |

### Verified Filter Fields

Any column that returns data can be used as a filter. Tested and confirmed:

| Filter Field | Description | Example Use |
|--------------|-------------|-------------|
| `exchange` | SSE or SZSE | `in_range: ["SSE"]` |
| `name` | Stock code | `in_range: ["600519", "601398"]` for specific stocks |
| `sector` | Sector name | `equal: "Finance"` or `in_range: ["Finance", "Technology"]` |
| `market_cap_basic` | Market cap (CNY) | `greater: 100000000000` (>1000亿) |
| `price_earnings_ttm` | PE ratio | `less: 10` |
| `price_book_ratio` | PB ratio | `less: 1` |
| `dividend_yield_recent` | Dividend yield % | `greater: 3` |
| `return_on_equity` | ROE % | `greater: 15` |
| `change` | Daily change % | `greater: 5` (涨幅>5%) |
| `RSI` | RSI (14) | `less: 30` (oversold) |
| `total_assets` | Total assets | `greater: 1000000000000` |
| `current_ratio` | Current ratio | `greater: 1.5` |
| `debt_to_equity` | D/E ratio | `less: 0.5` |

### Common Filter Recipes

**Value stocks — large cap, low PE, high dividend:**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "market_cap_basic", "operation": "greater", "right": 100000000000},
    {"left": "price_earnings_ttm", "operation": "less", "right": 15},
    {"left": "dividend_yield_recent", "operation": "greater", "right": 3}
]
```
Result: ~27 stocks (工商银行, 农业银行, 中国石油, 中国移动, 中国平安, etc.)

**Low PE large caps (PE < 10):**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "price_earnings_ttm", "operation": "less", "right": 10}
]
```
Result: banks, insurance, energy stocks — 工商银行 PE=6.9, 农业银行 PE=7.9, 中国人寿 PE=7.9

**Finance sector, highest dividend yield:**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "sector", "operation": "in_range", "right": ["Finance"]}
]
```
Sort by `dividend_yield_recent` desc → 华夏银行 6.0%, 北京银行 5.9%, 光大银行 5.8%

**High ROE, profitable companies:**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "return_on_equity", "operation": "greater", "right": 20},
    {"left": "market_cap_basic", "operation": "greater", "right": 50000000000}
]
```

**Oversold stocks (RSI < 30):**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "RSI", "operation": "less", "right": 30}
]
```

**Specific stock lookup by code:**
```json
[
    {"left": "exchange", "operation": "in_range", "right": ["SSE", "SZSE"]},
    {"left": "name", "operation": "in_range", "right": ["600519"]}
]
```

**SSE only / SZSE only:**
```json
{"left": "exchange", "operation": "in_range", "right": ["SSE"]}
{"left": "exchange", "operation": "in_range", "right": ["SZSE"]}
```

---

## Pagination

Use `range: [start, end]` (0-indexed).

- `[0, 20]` — first 20 results
- `[20, 40]` — next 20 results
- `[0, 50]` — first 50 results

Total count is returned in `totalCount`.

---

## Field Availability by Industry

Some fields are industry-specific:

| Field | Banks | Industrial | Tech | Energy |
|-------|-------|-----------|------|--------|
| `gross_margin` | null | yes | yes | yes |
| `ebitda` | null | often null | often null | yes |
| `enterprise_value_ebitda_ttm` | null | often null | often null | yes |
| `pre_tax_margin` | some | yes | yes | yes |
| `quick_ratio` | yes (low) | yes | yes | yes |
| `free_cash_flow` | yes | yes | yes (can be negative) | yes |

Banks typically have: very low current_ratio/quick_ratio, high debt_to_equity, no gross_margin, high total_assets.
