# `financials` Table — Column Reference

Unified quarterly financial data for all A-share stocks.
One row per stock per quarter. Source: BaoStock.

## Key Columns

| Column | Type | Description |
|---|---|---|
| `code` | CHAR(6) | Stock code e.g. `600000` |
| `exchange` | CHAR(2) | `SH`, `SZ`, or `BJ` |
| `pub_date` | DATE | **Filing/publication date** — use this for backtesting (avoids look-ahead bias) |
| `stat_date` | DATE | Period end date: Mar 31 / Jun 30 / Sep 30 / Dec 31 |

> **Backtesting note:** Always filter by `pub_date <= your_backtest_date`, not `stat_date`.
> A Q3 report (stat_date = Sep 30) may not be published until late October.

---

## Profitability (`query_profit_data`)

| Column | BaoStock Field | Description |
|---|---|---|
| `roe_avg` | `roeAvg` | Return on equity (average) |
| `np_margin` | `npMargin` | Net profit margin |
| `gp_margin` | `gpMargin` | Gross profit margin |
| `net_profit` | `netProfit` | Net profit (yuan) |
| `eps_ttm` | `epsTTM` | Earnings per share (trailing twelve months) |
| `mb_revenue` | `MBRevenue` | Main business revenue (yuan) |
| `total_share` | `totalShare` | Total shares outstanding |
| `liqa_share` | `liqaShare` | Liquid (tradable) shares |

---

## Operational Efficiency (`query_operation_data`)

| Column | BaoStock Field | Description |
|---|---|---|
| `nr_turn_ratio` | `NRTurnRatio` | Accounts receivable turnover ratio |
| `nr_turn_days` | `NRTurnDays` | Accounts receivable turnover days |
| `inv_turn_ratio` | `INVTurnRatio` | Inventory turnover ratio |
| `inv_turn_days` | `INVTurnDays` | Inventory turnover days |
| `ca_turn_ratio` | `CATurnRatio` | Current assets turnover ratio |
| `asset_turn_ratio` | `AssetTurnRatio` | Total asset turnover ratio |

---

## Growth (`query_growth_data`)

All YoY = year-over-year change (decimal, e.g. 0.15 = +15%).

| Column | BaoStock Field | Description |
|---|---|---|
| `yoy_equity` | `YOYEquity` | YoY growth: shareholders equity |
| `yoy_asset` | `YOYAsset` | YoY growth: total assets |
| `yoy_ni` | `YOYNI` | YoY growth: net income |
| `yoy_eps_basic` | `YOYEPSBasic` | YoY growth: basic EPS |
| `yoy_pni` | `YOYPNI` | YoY growth: parent company net income |

---

## Solvency / Balance Sheet (`query_balance_data`)

| Column | BaoStock Field | Description |
|---|---|---|
| `current_ratio` | `currentRatio` | Current ratio (current assets / current liabilities) |
| `quick_ratio` | `quickRatio` | Quick ratio (liquid assets / current liabilities) |
| `cash_ratio` | `cashRatio` | Cash ratio |
| `yoy_liability` | `YOYLiability` | YoY growth: total liabilities |
| `liability_to_asset` | `liabilityToAsset` | Debt ratio (total liabilities / total assets) |
| `asset_to_equity` | `assetToEquity` | Financial leverage (total assets / equity) |

---

## Cash Flow (`query_cash_flow_data`)

| Column | BaoStock Field | Description |
|---|---|---|
| `ca_to_asset` | `CAToAsset` | Current assets / total assets |
| `nca_to_asset` | `NCAToAsset` | Non-current assets / total assets |
| `tangible_asset_to_asset` | `tangibleAssetToAsset` | Tangible assets / total assets |
| `ebit_to_interest` | `ebitToInterest` | Interest coverage ratio (EBIT / interest expense) |
| `cfo_to_or` | `CFOToOR` | Operating cash flow / operating revenue |
| `cfo_to_np` | `CFOToNP` | Operating cash flow / net profit (cash quality) |
| `cfo_to_gr` | `CFOToGr` | Operating cash flow / gross revenue |

---

## DuPont Decomposition (`query_dupont_data`)

ROE = Net Margin × Asset Turnover × Leverage

| Column | BaoStock Field | Description |
|---|---|---|
| `dupont_roe` | `dupontROE` | Return on equity (DuPont) |
| `dupont_asset_sto_equity` | `dupontAssetStoEquity` | Assets / equity (leverage factor) |
| `dupont_asset_turn` | `dupontAssetTurn` | Asset turnover |
| `dupont_pnitoni` | `dupontPnitoni` | Parent NI / total NI |
| `dupont_nitogr` | `dupontNitogr` | Net income / gross revenue (net margin) |
| `dupont_tax_burden` | `dupontTaxBurden` | Net income / pre-tax income (tax retention rate) |
| `dupont_int_burden` | `dupontIntburden` | Pre-tax income / EBIT (interest burden) |
| `dupont_ebit_togr` | `dupontEbittogr` | EBIT / gross revenue (operating margin) |

---

## Example Queries

```sql
-- Latest quarter for one stock
SELECT * FROM financials WHERE code = '600036' ORDER BY stat_date DESC LIMIT 4;

-- Backtest-safe: only use data available before a given date
SELECT * FROM financials WHERE code = '600036' AND pub_date <= '2023-06-01' ORDER BY stat_date DESC LIMIT 1;

-- Most profitable stocks last quarter
SELECT code, exchange, roe_avg, np_margin, net_profit
FROM financials
WHERE stat_date = '2024-09-30'
ORDER BY roe_avg DESC NULLS LAST
LIMIT 20;

-- High growth, low leverage screen
SELECT code, exchange, yoy_ni, liability_to_asset, eps_ttm
FROM financials
WHERE stat_date = '2024-09-30'
  AND yoy_ni > 0.2
  AND liability_to_asset < 0.5
ORDER BY yoy_ni DESC;
```
