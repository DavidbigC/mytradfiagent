# Chinese Public Fund API Reference (AKShare)

> **For agents:** This file covers ALL publicly available Chinese fund data via AKShare.
> When a user asks about any Chinese fund (ETF, LOF, open-end, money market, graded, REITs),
> use this document to find the correct endpoint. Always `import akshare as ak` before calling.
>
> **DB tables available locally:** `funds`, `fund_nav`, `fund_price`, `fund_managers`,
> `fund_manager_profiles`, `fund_fees`, `fund_holdings` — query these first before calling AKShare
> for historical data that has already been ingested.

---

## Quick Decision Guide — Which Endpoint to Use?

| User Question | Use This Function |
|---|---|
| What ETFs exist? Get list of all ETFs | `fund_etf_spot_em()` or `fund_etf_fund_daily_em()` |
| What is the current price/NAV of an ETF? | `fund_etf_spot_em()` |
| Get ETF price history (OHLCV) | `fund_etf_hist_em(symbol, ...)` |
| Get ETF intraday price data | `fund_etf_hist_min_em(symbol, ...)` |
| Get ETF NAV (net asset value) history | `fund_etf_fund_info_em(fund, ...)` |
| What LOFs exist? LOF real-time prices | `fund_lof_spot_em()` |
| Get LOF price history | `fund_lof_hist_em(symbol, ...)` |
| Get LOF intraday price data | `fund_lof_hist_min_em(symbol, ...)` |
| Get open-end fund NAV today | `fund_open_fund_daily_em()` |
| Get open-end fund NAV history | `fund_open_fund_info_em(symbol, indicator)` |
| Get money market fund returns | `fund_money_fund_daily_em()` or `fund_money_fund_info_em(symbol)` |
| Get graded/tiered fund NAV | `fund_graded_fund_daily_em()` |
| Fund manager info / who manages a fund | `fund_manager_em()` (DB: `fund_managers`, `fund_manager_profiles`) |
| Fund detailed overview (fees, inception, AUM) | `fund_overview_em(symbol)` (DB: `funds`, `fund_fees`) |
| Fund fee schedule | `fund_fee_em(symbol, indicator)` |
| Fund stock holdings / portfolio | `fund_portfolio_hold_em(symbol, date)` (DB: `fund_holdings`) |
| Fund bond holdings | `fund_portfolio_bond_hold_em(symbol, date)` |
| Fund sector/industry allocation | `fund_portfolio_industry_allocation_em(symbol, date)` |
| Fund dividend history | `fund_fh_em(...)` or `fund_etf_dividend_sina(symbol)` |
| Fund splits history | `fund_cf_em(...)` |
| Fund performance ratings | `fund_rating_all()`, `fund_rating_sh()`, `fund_rating_zs()`, `fund_rating_ja()` |
| Fund performance analytics (Sharpe, drawdown) | `fund_individual_analysis_xq(symbol)` |
| Fund ranking by returns | `fund_open_fund_rank_em(symbol)` or `fund_exchange_rank_em()` |
| Fund estimated NAV (intraday) | `fund_value_estimation_em(symbol)` |
| Fund subscription/redemption status | `fund_purchase_em()` |
| What new funds launched recently? | `fund_new_em()` |
| Fund company AUM / scale data | `fund_aum_em(indicator)` or `fund_aum_detail_em()` |
| Fund announcements (dividends, personnel) | `fund_notice_em(symbol)` |
| REITs real-time or historical data | `fund_reits_spot_em()` or `fund_reits_hist_em(symbol, ...)` |
| Hong Kong fund data | `fund_hk_fund_hist_em(code, symbol)` or `fund_hk_rank_em()` |
| Equity fund position aggregate (market-wide) | `fund_position_em(indicator)` |
| All funds basic listing | `fund_name_em()` |
| Index-tracking funds for a given index | `fund_info_index_em(symbol, indicator)` |
| Profit probability analysis (Snowball) | `fund_individual_profit_probability_xq(symbol)` |
| Asset allocation breakdown | `fund_individual_detail_hold_xq(symbol, date)` |

---

## Section 1: Fund Listings & Basic Info

### `fund_name_em()` — All Funds Master List
- **When to use:** Get complete listing of all public funds with type classification
- **Parameters:** None
- **Returns:** `基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称`
- **Example:**
  ```python
  df = ak.fund_name_em()
  # Filter: df[df["基金类型"] == "ETF联接基金"]
  ```

### `fund_purchase_em()` — Subscription/Redemption Status
- **When to use:** Check if a fund is currently open for purchase/redemption
- **Parameters:** None
- **Returns:** `序号, 基金代码, 基金简称, 基金类型, 最新净值/万份收益, 申购状态, 赎回状态, 下一开放日, 购买起点, 日累计限定金额, 手续费`
- **申购状态 values:** `"开放申购"`, `"暂停申购"`, `"封闭期"`

### `fund_info_index_em(symbol, indicator)` — Index-Tracking Funds
- **When to use:** Find all funds tracking a specific index (e.g., CSI 300)
- **Parameters:**
  - `symbol` (str) — index code or name, e.g. `"000300"` for CSI 300
  - `indicator` (str) — `"增强指数型"` / `"被动指数型"` / `"ETF"` etc.
- **Returns:** `基金代码, 基金名称, 单位净值, 日期, 日增长率, 近1周, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年, 今年来, 成立来, 手续费, 起购金额, 跟踪标的, 跟踪方式`

### `fund_individual_basic_info_xq(symbol, timeout=None)` — Fund Basic Info (Snowball)
- **When to use:** Get structured fund attributes from Snowball
- **Parameters:** `symbol` (str) — fund code
- **Returns:** `item, value` (key-value pairs with fund details)

### `fund_new_em(page=-1)` — Newly Issued Funds
- **When to use:** User asks what new funds have recently launched
- **Parameters:** `page` (int) — page number; use `-1` to get all pages
- **Returns:** `序号, 基金代码, 基金简称, 基金类型, 发行公司, 发行规模, 成立日期, 手续费`

---

## Section 2: ETF Data

### `fund_etf_spot_em()` — ETF Real-Time Quotes ⭐ Primary ETF Source
- **When to use:** Get all ETFs with current price, IOPV, capital flow, premium/discount
- **Parameters:** None
- **Returns:**
  - `代码, 名称` — fund code and name
  - `最新价, IOPV实时估值, 基金折价率` — price, estimated NAV, premium/discount
  - `涨跌额, 涨跌幅` — price change
  - `成交量, 成交额` — volume and turnover amount
  - `开盘价, 最高价, 最低价, 昨收` — OHLC
  - `换手率, 量比, 委比` — turnover rate, volume ratio, bid-ask ratio
  - `主力净流入-净额, 主力净流入-净占比` — main force net inflow
  - `超大单净流入-净额, 超大单净流入-净占比` — super-large order net inflow
  - `大单净流入-净额, 大单净流入-净占比` — large order net inflow
  - `中单净流入-净额, 中单净流入-净占比` — medium order net inflow
  - `小单净流入-净额, 小单净流入-净占比` — small order net inflow
  - `最新份额, 流通市值, 总市值` — shares, float market cap, total market cap
  - `数据日期, 更新时间`
- **Note:** May fail with SSL error from non-China servers; fallback: `fund_etf_fund_daily_em()`

### `fund_etf_fund_daily_em()` — ETF/Exchange-Traded Fund NAV Summary
- **When to use:** Get all exchange-traded funds' latest NAV and market price (fallback for `fund_etf_spot_em`)
- **Parameters:** None
- **Returns:** `基金代码, 基金简称, 类型, 当前交易日-单位净值, 当前交易日-累计净值, 前一个交易日-单位净值, 前一个交易日-累计净值, 增长值, 增长率, 市价, 折价率`
- **Note:** Column names are date-prefixed (e.g., `"2026-02-13-单位净值"`). Use `_detect_nav_cols()` in `ingest_funds.py` to handle this.

### `fund_etf_fund_info_em(fund, start_date, end_date)` — Single ETF NAV History ⭐
- **When to use:** Get historical NAV time series for one ETF/LOF
- **Parameters:**
  - `fund` (str) — fund code, e.g. `"510050"`
  - `start_date` (str) — `"YYYYMMDD"`
  - `end_date` (str) — `"YYYYMMDD"`
- **Returns:** `净值日期, 单位净值, 累计净值, 日增长率, 申购状态, 赎回状态`
- **Note:** `净值日期` may be `pd.NaT` for some rows — always guard: `if raw_d is pd.NaT: continue`
- **DB equivalent:** `SELECT * FROM fund_nav WHERE fund_code = $1 ORDER BY date DESC`

### `fund_etf_hist_em(symbol, period, start_date, end_date, adjust="")` — ETF Price History ⭐
- **When to use:** Get OHLCV price history for an ETF (for trading/technical analysis)
- **Parameters:**
  - `symbol` (str) — ETF code, e.g. `"510050"`
  - `period` — `"daily"` / `"weekly"` / `"monthly"`
  - `start_date`, `end_date` (str) — `"YYYYMMDD"`
  - `adjust` — `""` (no adj) / `"qfq"` (forward) / `"hfq"` (backward)
- **Returns:** `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率`
- **DB equivalent:** `SELECT * FROM fund_price WHERE fund_code = $1 ORDER BY date DESC`

### `fund_etf_hist_min_em(symbol, start_date, end_date, period, adjust="")` — ETF Intraday
- **When to use:** Intraday (tick/5-min) price data for an ETF
- **Parameters:** `period` — `"1"` / `"5"` / `"15"` / `"30"` / `"60"` (minutes)
- **Returns (1min):** `时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价`
- **Returns (5/15/30/60min):** `时间, 开盘, 收盘, 最高, 最低, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 换手率`

### `fund_etf_hist_sina(symbol)` — ETF Price History (Sina)
- **When to use:** Alternative source if EastMoney is unavailable
- **Parameters:** `symbol` (str)
- **Returns:** `date, open, high, low, close, volume`

### `fund_etf_dividend_sina(symbol)` — ETF Cumulative Dividends
- **When to use:** Get dividend distribution history for an ETF
- **Parameters:** `symbol` (str)
- **Returns:** `日期, 累计分红`

### `fund_etf_category_ths(symbol, date)` — ETF List by Category (Tonghuashun)
- **When to use:** Filter ETFs by category from THS data
- **Parameters:** `symbol` (category string), `date` (str)
- **Returns:** `序号, 基金代码, 基金名称, 当前-单位净值, 当前-累计净值, 前一日-单位净值, 前一日-累计净值, 增长值, 增长率, 赎回状态, 申购状态, 最新-交易日, 最新-单位净值, 最新-累计净值, 基金类型, 查询日期`

### `fund_etf_spot_ths(date)` — ETF Spot (Tonghuashun)
- **Parameters:** `date` (str)
- **Returns:** Same columns as `fund_etf_category_ths`

### `fund_etf_category_sina(symbol)` — ETF List by Category (Sina)
- **Parameters:** `symbol` (category string)
- **Returns:** `代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额`

### `fund_value_estimation_em(symbol)` — Intraday NAV Estimation
- **When to use:** Get real-time estimated NAV during trading hours
- **Parameters:** `symbol` (str) — fund code
- **Returns:** `序号, 基金代码, 基金名称, 交易日-估算数据-估算值, 交易日-估算数据-估算增长率, 交易日-公布数据-单位净值, 交易日-公布数据-日增长率, 估算偏差, 交易日-单位净值`

---

## Section 3: LOF (Listed Open-end Fund) Data

LOFs trade on exchange like ETFs but also allow OTC subscription/redemption.

### `fund_lof_spot_em()` — LOF Real-Time Quotes
- **When to use:** Get all LOF funds' current market prices
- **Parameters:** None
- **Returns:** `代码, 名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额, 开盘价, 最高价, 最低价, 昨收, 换手率, 流通市值, 总市值`

### `fund_lof_hist_em(symbol, period, start_date, end_date, adjust="")` — LOF Price History ⭐
- **When to use:** OHLCV history for a LOF fund
- **Parameters:** Same as `fund_etf_hist_em`
- **Returns:** `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率`

### `fund_lof_hist_min_em(symbol, start_date, end_date, period, adjust="")` — LOF Intraday
- **Parameters:** Same as `fund_etf_hist_min_em`
- **Returns:** Same structure as ETF intraday

---

## Section 4: Open-End Fund Data (场外, OTC)

Open-end funds are subscribed/redeemed OTC (not exchange-traded).

### `fund_open_fund_daily_em()` — All Open-End Funds Latest NAV
- **When to use:** Get today's NAV for all open-end funds
- **Parameters:** None
- **Returns:** `基金代码, 基金简称, 单位净值, 累计净值, 前交易日-单位净值, 前交易日-累计净值, 日增长值, 日增长率, 申购状态, 赎回状态, 手续费`
- **Note:** Column names are date-prefixed. Use `_detect_nav_cols()` in `ingest_funds.py`.

### `fund_open_fund_info_em(symbol, indicator, period=None)` — Open-End Fund NAV History
- **When to use:** Get historical NAV for a specific open-end fund
- **Parameters:**
  - `symbol` (str) — fund code
  - `indicator` (str) — one of:
    - `"净值走势"` → 净值日期, 单位净值, 日增长率
    - `"累计净值走势"` → 净值日期, 累计净值
    - `"收益率走势"` → 日期, 累计收益率
    - `"同类排名"` → date, rank data
    - `"分红"` → dividend dates and amounts
    - `"拆分"` → split dates and ratios
  - `period` (str, optional) — time period filter

### `fund_open_fund_rank_em(symbol)` — Open-End Fund Rankings
- **When to use:** Rank open-end funds by return across different periods
- **Parameters:** `symbol` (str) — fund category (e.g. `"全部"`, `"股票型"`, `"混合型"`)
- **Returns:** `序号, 基金代码, 基金简称, 日期, 单位净值, 累计净值, 日增长率, 近1周, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年, 今年来, 成立来, 自定义, 手续费`

---

## Section 5: Money Market Fund Data (货币型)

### `fund_money_fund_daily_em()` — Money Market Funds Today
- **When to use:** Get all money market funds' yield and NAV
- **Parameters:** None
- **Returns:** `基金代码, 基金简称, 当前交易日-万份收益, 当前交易日-7日年化%, 当前交易日-单位净值, 前一交易日-万份收益, 前一交易日-7日年化%, 前一交易日-单位净值, 日涨幅, 成立日期, 基金经理, 手续费, 可购全部`

### `fund_money_fund_info_em(symbol)` — Money Market Fund History
- **When to use:** Historical yield data for a specific money market fund
- **Parameters:** `symbol` (str) — fund code
- **Returns:** `净值日期, 每万份收益, 7日年化收益率, 申购状态, 赎回状态`

### `fund_money_rank_em()` — Money Market Fund Rankings
- **Returns:** `序号, 基金代码, 基金简称, 日期, 万份收益, 年化收益率7日, 年化收益率14日, 年化收益率28日, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年, 近5年, 今年来, 成立来, 手续费`

---

## Section 6: Graded / Tiered Fund Data (分级基金)

### `fund_graded_fund_daily_em()` — Graded Funds Today
- **When to use:** Get current NAV and market price for all graded/tiered funds
- **Parameters:** None
- **Returns:** `基金代码, 基金简称, 单位净值, 累计净值, 前交易日-单位净值, 前交易日-累计净值, 日增长值, 日增长率, 市价, 折价率, 手续费`

### `fund_graded_fund_info_em(symbol)` — Graded Fund History
- **Parameters:** `symbol` (str) — fund code
- **Returns:** `净值日期, 单位净值, 累计净值, 日增长率, 申购状态, 赎回状态`

---

## Section 7: Wealth Management Funds (理财型)

### `fund_financial_fund_daily_em()` — Wealth Management Funds Today
- **Parameters:** None
- **Returns:** `序号, 基金代码, 基金简称, 上一期年化收益率, 当前交易日-万份收益, 当前交易日-7日年化, 前一个交易日-万份收益, 前一个交易日-7日年化, 封闭期, 申购状态`

### `fund_financial_fund_info_em(symbol)` — Wealth Management Fund History
- **Parameters:** `symbol` (str)
- **Returns:** `净值日期, 单位净值, 累计净值, 日增长率, 申购状态, 赎回状态, 分红送配`

### `fund_lcx_rank_em()` — Wealth Management Fund Rankings
- **Returns:** `序号, 基金代码, 基金简称, 日期, 万份收益, 年化收益率7日/14日/28日, 近1周/月/3月/6月, 今年来, 成立来, 可购买, 手续费`

---

## Section 8: Fund Manager Data

### `fund_manager_em()` — All Fund Managers ⭐ Primary Manager Source
- **When to use:** Get all fund managers with their current funds and performance metrics
- **Parameters:** None (returns all managers)
- **Returns:**
  - `序号, 姓名` — manager ID and name
  - `所属公司` — fund company name
  - `现任基金代码` — fund code(s) currently managed
  - `现任基金` — fund name(s) currently managed
  - `累计从业时间(天)` — total tenure in days
  - `现任基金资产总规模(亿元)` — total AUM of current funds (100M CNY)
  - `现任基金最佳回报(%)` — best return among current funds
- **⚠️ Important:** One row per fund managed. A manager managing 3 funds = 3 rows. Deduplicate on `姓名` + `所属公司` for manager profiles.
- **DB equivalent:** `SELECT * FROM fund_managers WHERE end_date IS NULL` (current assignments), `SELECT * FROM fund_manager_profiles` (aggregated stats)

### `fund_manager_info_em(symbol)` — Individual Manager Detail
- **When to use:** Get detailed management history and performance for one manager
- **Parameters:** `symbol` (str) — manager name or ID
- **Returns:** Manager biography, fund management history, returns analysis

---

## Section 9: Fund Overview & Fees

### `fund_overview_em(symbol)` — Fund Complete Profile ⭐
- **When to use:** Get all key attributes of a specific fund (slow — do not call in bulk)
- **Parameters:** `symbol` (str) — fund code
- **Returns:**
  - `基金全称, 基金简称, 基金代码`
  - `基金类型` — fund category
  - `发行日期, 成立日期/规模` — IPO and inception date/scale
  - `资产规模, 份额规模` — AUM and share count
  - `基金管理人, 基金托管人` — management company and custodian
  - `基金经理人` — current manager(s)
  - `成立来分红` — dividends since inception
  - `管理费率, 托管费率, 销售服务费率` — annual rates
  - `最高认购费率` — max subscription fee
  - `业绩比较基准` — benchmark index
  - `跟踪标的` — tracking index (for index funds)
- **DB equivalent:** `SELECT * FROM funds WHERE code = $1`; fees in `fund_fees`
- **⚠️ Slow:** ~1-2s per fund. Never call in bulk for 10,000+ funds. Use DB instead.

### `fund_fee_em(symbol, indicator)` — Fund Fee Schedule
- **When to use:** Get detailed fee breakdown for a fund
- **Parameters:**
  - `symbol` (str) — fund code
  - `indicator` (str) — one of:
    - `"交易状态"` — subscription/redemption status
    - `"申购金额"` — minimum purchase amounts
    - `"运作费用"` — ongoing operating costs
    - `"认购费率"` — subscription fee rates
    - `"申购费率"` — purchase fee rates
    - `"赎回费率"` — redemption fee rates
- **Returns:** `费用类型, 条件或名称, 费用`

### `fund_individual_detail_info_xq(symbol, timeout=None)` — Trading Rules (Snowball)
- **When to use:** Get trading rules and fee schedule from Snowball
- **Parameters:** `symbol` (str)
- **Returns:** `费用类型, 条件或名称, 费用`

---

## Section 10: Fund Holdings / Portfolio Composition

> **DB note:** `fund_holdings` table stores quarterly holdings ingested via `ingest_funds.py`.
> Query DB first; use AKShare only for funds not yet in DB or for the latest quarter.

### `fund_portfolio_hold_em(symbol, date)` — Stock Holdings ⭐
- **When to use:** See what stocks a fund holds (top 10 typically)
- **Parameters:**
  - `symbol` (str) — fund code
  - `date` (str) — year string, e.g. `"2024"` (returns all quarters for that year)
- **Returns:** `序号, 股票代码, 股票名称, 占净值比例, 持股数, 持仓市值, 季度`

### `fund_portfolio_bond_hold_em(symbol, date)` — Bond Holdings
- **When to use:** See what bonds a fund holds
- **Parameters:** Same as above
- **Returns:** `序号, 债券代码, 债券名称, 占净值比例, 持仓市值, 季度`

### `fund_portfolio_industry_allocation_em(symbol, date)` — Industry/Sector Allocation
- **When to use:** See how a fund allocates across industries
- **Parameters:** Same as above
- **Returns:** `序号, 行业类别, 占净值比例, 市值, 截止时间`

### `fund_portfolio_change_em(symbol, indicator, date)` — Portfolio Turnover
- **When to use:** See which stocks a fund bought/sold in a quarter
- **Parameters:**
  - `symbol` (str)
  - `indicator` (str) — `"累计买入"` or `"累计卖出"`
  - `date` (str) — year
- **Returns:** `序号, 股票代码, 股票名称, 本期累计买入/卖出金额, 占期初基金资产净值比例, 季度`

### `fund_individual_detail_hold_xq(symbol, date, timeout=None)` — Asset Allocation (Snowball)
- **When to use:** Get high-level asset class breakdown (stocks vs bonds vs cash)
- **Parameters:** `symbol` (str), `date` (str)
- **Returns:** `资产类型, 仓位占比`

### `fund_position_em(indicator)` — Market-Wide Fund Equity Positions
- **When to use:** See the overall equity position of all funds of a given type
- **Parameters:** `indicator` (str) — one of:
  - `"股票型基金仓位"` — equity funds
  - `"平衡混合型基金仓位"` — balanced hybrid funds
  - `"灵活配置型基金仓位"` — flexible allocation funds
- **Returns:** `日期, 仓位占比, 基金数`

### `fund_position_detail_em(symbol, date)` — Position Detail by Fund
- **When to use:** Get position details for a specific fund
- **Parameters:** `symbol` (str), `date` (str) — year `"YYYY"`
- **Returns:** `序号, 股票代码, 股票名称, 占净值比例, 持股数, 持仓市值, 季度`

### `fund_position_industry_em(symbol, date)` — Position Industry Detail
- **Parameters:** `symbol` (str), `date` (str) — year `"YYYY"`
- **Returns:** `序号, 行业类别, 占净值比例, 市值, 截止时间`

---

## Section 11: Fund Ratings

### `fund_rating_all()` — Combined Ratings Summary ⭐
- **When to use:** Quick view of which funds have high ratings from multiple agencies
- **Parameters:** None
- **Returns:** `代码, 简称, 基金经理, 基金公司, 5星评级家数, 上海证券, 招商证券, 济安金信, 手续费, 类型`
- **Note:** `5星评级家数` shows how many agencies rate it 5-star (max 3)

### `fund_rating_sh(date)` — Shanghai Securities Rating (上海证券)
- **Parameters:** `date` (str) — `"YYYYMMDD"` format
- **Returns:** `代码, 简称, 基金经理, 基金公司, 3年期评级-3年评级, 3年期评级-较上期, 5年期评级-5年评级, 5年期评级-较上期, 单位净值, 日期, 日增长率, 近1年涨幅, 近3年涨幅, 近5年涨幅, 手续费, 类型`

### `fund_rating_zs(date)` — Zhaoshan Securities Rating (招商证券)
- **Parameters:** `date` (str) — `"YYYYMMDD"` format
- **Returns:** Same columns as `fund_rating_sh`

### `fund_rating_ja(date)` — Jian-An Jin-Xin Rating (济安金信)
- **Parameters:** `date` (str) — `"YYYYMMDD"` format
- **Returns:** Same columns as `fund_rating_sh`

---

## Section 12: Fund Performance Analytics (Snowball)

These endpoints query Snowball (雪球) and may be slower. Require a valid Snowball fund code.

### `fund_individual_achievement_xq(symbol, timeout=None)` — Performance Record
- **When to use:** Compare fund performance across periods vs peers
- **Returns:** `业绩类型, 周期, 本产品区间收益, 本产品最大回撒, 周期收益同类排名`

### `fund_individual_analysis_xq(symbol, timeout=None)` — Risk-Return Analysis
- **When to use:** Get Sharpe ratio, volatility, max drawdown
- **Returns:** `周期, 较同类风险收益比, 较同类抗风险波动, 年化波动率, 年化夏普比率, 最大回撤`

### `fund_individual_profit_probability_xq(symbol, timeout=None)` — Profit Probability
- **When to use:** Answer "What is the probability of profit if I hold for X months?"
- **Returns:** `持有时长, 盈利概率, 平均收益`

---

## Section 13: Fund Rankings (Comprehensive)

### `fund_exchange_rank_em()` — Exchange-Traded Fund Rankings
- **When to use:** Rank all ETFs and LOFs by historical returns
- **Parameters:** None
- **Returns:** `序号, 基金代码, 基金简称, 类型, 日期, 单位净值, 累计净值, 近1周, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年, 今年来, 成立来, 成立日期`

### `fund_hk_rank_em()` — HK Fund Rankings
- **Returns:** `序号, 基金代码, 基金简称, 币种, 日期, 单位净值, 日增长率, 近1周, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年, 今年来, 成立来, 可购买, 香港基金代码`

---

## Section 14: Dividends and Splits

### `fund_fh_em(year, typ, rank, sort, page)` — Fund Dividend Records
- **When to use:** Get detailed dividend history across all funds
- **Parameters:**
  - `year` (str) — year, e.g. `"2024"`
  - `typ` (str) — fund type filter
  - `rank`, `sort`, `page` — sorting and pagination
- **Returns:** `序号, 基金代码, 基金简称, 权益登记日, 除息日期, 分红, 分红发放日`

### `fund_fh_rank_em()` — Top Dividend-Paying Funds
- **When to use:** Find which funds have paid the most dividends historically
- **Returns:** `序号, 基金代码, 基金简称, 累计分红, 累计次数, 成立日期`

### `fund_cf_em(year, typ, rank, sort, page)` — Fund Split Records
- **When to use:** Get fund split/折算 history
- **Returns:** `序号, 基金代码, 基金简称, 拆分折算日, 拆分类型, 拆分折算`

---

## Section 15: Fund AUM / Scale Data

### `fund_aum_em(indicator)` — Fund Scale by Category ⭐
- **When to use:** Find largest funds by AUM in a specific category
- **Parameters:** `indicator` (str) — one of:
  - `"开放式基金"` — open-end funds
  - `"封闭式基金"` — closed-end funds
  - `"分级子基金"` — tiered sub-funds
  - `"ETF基金份额-上交所"` — ETFs on Shanghai Stock Exchange
  - `"ETF基金份额-深交所"` — ETFs on Shenzhen Stock Exchange
- **Returns:** `序号, 基金代码, 基金简称, 基金类型, 基金公司, 规模, 份额, 日期`

### `fund_aum_detail_em()` — Fund Company AUM Summary
- **When to use:** Compare fund management companies by total AUM
- **Parameters:** None
- **Returns:** `序号, 基金公司, 非货币基金规模, 货币基金规模, 合计规模, 基金数, 日期`

### `fund_aum_hist_em(symbol)` — Fund Company Historical AUM
- **When to use:** See how a fund company's AUM has grown over years
- **Parameters:** `symbol` (str) — fund company name (Chinese)
- **Returns:** `年份, 非货币基金规模, 货币基金规模, 合计规模, 基金数`

---

## Section 16: Fund Announcements

### `fund_notice_em(symbol, page=-1)` — Fund Announcements
- **When to use:** Get fund announcements (dividends, personnel changes, regulatory filings)
- **Parameters:**
  - `symbol` (str) — announcement type:
    - `"分红配送"` — dividend distributions
    - `"定期报告"` — periodic reports (annual/semi-annual)
    - `"人事公告"` — personnel announcements (manager changes)
  - `page` (int) — page number; `-1` for all
- **Returns:** `序号, 基金代码, 基金简称, 公告日期, 公告标题`

### `fund_notice_detail_em(url)` — Announcement Full Text
- **When to use:** Read the full content of a specific announcement
- **Parameters:** `url` (str) — URL from `fund_notice_em` results
- **Returns:** `公告标题, 公告日期, 公告内容`

---

## Section 17: REITs Data

### `fund_reits_spot_em()` — REITs Real-Time Quotes
- **When to use:** Get current prices for all REITs products
- **Parameters:** None
- **Returns:** `代码, 名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额, 开盘价, 最高价, 最低价, 昨收, 换手率, 流通市值, 总市值`

### `fund_reits_hist_em(symbol, period, start_date, end_date, adjust="")` — REITs History
- **When to use:** OHLCV history for a REITs product
- **Parameters:**
  - `symbol` (str) — REITs code
  - `period` (str) — `"daily"` / `"weekly"` / `"monthly"`
  - `adjust` (str) — `""` / `"qfq"` / `"hfq"`
- **Returns:** `日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率`

---

## Section 18: Hong Kong Fund Data

### `fund_hk_fund_hist_em(code, symbol)` — HK Fund Historical NAV
- **Parameters:**
  - `code` (str) — HK fund identifier
  - `symbol` (str) — specific data type
- **Returns (NAV):** `净值日期, 单位净值, 日增长值, 日增长率, 单位`
- **Returns (dividends):** `年份, 权益登记日, 除息日, 分红发放日, 分红金额, 单位`

---

## Section 19: Common Patterns and Gotchas

### Getting ETF Codes (Robust Pattern)
```python
def get_etf_codes() -> list[str]:
    try:
        df = ak.fund_etf_spot_em()
        return [str(r).strip().zfill(6) for r in df["代码"].tolist()]
    except Exception:
        # Fallback when CDN node SSL fails (common from non-China IPs)
        df = ak.fund_etf_fund_daily_em()
        return [str(r).strip().zfill(6) for r in df["基金代码"].tolist()]
```

### Date-Prefixed Column Detection
`fund_open_fund_daily_em()` and `fund_etf_fund_daily_em()` return columns like `"2026-02-13-单位净值"`.
Use this pattern:
```python
nav_col   = next((c for c in df.columns if c.endswith("-单位净值")), None)
accum_col = next((c for c in df.columns if c.endswith("-累计净值")), None)
nav_date  = date.fromisoformat(nav_col.replace("-单位净值", "")) if nav_col else date.today()
```

### Safe Date Extraction (避免 NaT)
`fund_etf_fund_info_em` and similar can return `pd.NaT` for `净值日期`:
```python
raw_d = r["净值日期"]
if raw_d is None or raw_d is pd.NaT or not pd.notna(raw_d):
    continue
d = raw_d.date() if hasattr(raw_d, "date") and callable(raw_d.date) else date.fromisoformat(str(raw_d))
if not isinstance(d, date):
    continue
```

### SSL Errors from Non-China Servers
`fund_etf_spot_em()` calls `88.push2.eastmoney.com` — this CDN node frequently fails SSL handshake
from non-mainland servers. Always wrap in try/except with a fallback.

### Rate Parsing (费率 fields)
Fee fields like `管理费率` may contain `"%"` or be `"-"` or `None`:
```python
import re
def _parse_rate(val) -> float | None:
    if val is None or str(val).strip() in ("", "-", "--", "---"):
        return None
    m = re.search(r"[-+]?\d+\.?\d*", str(val))
    return float(m.group()) if m else None
```

### Using Local DB vs AKShare
- **Historical price/NAV data:** Query `fund_price` / `fund_nav` tables first (already ingested)
- **Manager info:** Query `fund_managers` + `fund_manager_profiles` tables
- **Fund metadata:** Query `funds` + `fund_fees` tables
- **Live/today's data:** Call AKShare (DB may be 1 day behind)
- **Holdings (quarterly):** Query `fund_holdings` table; update via `fund_portfolio_hold_em()`

### Fund Type Classification
| Type | Chinese | Exchange Traded? | AKShare Functions |
|---|---|---|---|
| ETF | ETF联接基金/ETF | Yes (SSE/SZSE) | `fund_etf_*` |
| LOF | 上市开放式基金 | Yes (SSE/SZSE) | `fund_lof_*` |
| Open-end | 开放式基金 | No (OTC only) | `fund_open_fund_*` |
| Money market | 货币型 | No | `fund_money_fund_*` |
| Graded/Tiered | 分级基金 | Yes | `fund_graded_fund_*` |
| Wealth mgmt | 理财型 | No | `fund_financial_fund_*` |
| REITs | 公募REITs | Yes | `fund_reits_*` |
| HK fund | 香港基金 | Yes (HK) | `fund_hk_*` |

### Fund Code Format
All AKShare fund codes are 6-digit strings, zero-padded:
- Shanghai ETFs: `510xxx`, `512xxx`, `513xxx`, `515xxx`, `516xxx`, `517xxx`, `518xxx`
- Shenzhen ETFs: `159xxx`
- LOFs: `160xxx`–`169xxx`, `501xxx`
- Open-end: Codes not traded on exchange

Always normalize: `code = str(code).strip().zfill(6)`

---

## Section 20: Full Function Index

| Function | Category | Parameters |
|---|---|---|
| `fund_aum_detail_em` | AUM/Scale | none |
| `fund_aum_em` | AUM/Scale | `indicator` |
| `fund_aum_hist_em` | AUM/Scale | `symbol` (company name) |
| `fund_cf_em` | Splits | `year, typ, rank, sort, page` |
| `fund_etf_category_sina` | ETF Quotes | `symbol` |
| `fund_etf_category_ths` | ETF Quotes | `symbol, date` |
| `fund_etf_dividend_sina` | ETF Dividends | `symbol` |
| `fund_etf_fund_daily_em` | ETF NAV | none |
| `fund_etf_fund_info_em` | ETF NAV | `fund, start_date, end_date` |
| `fund_etf_hist_em` | ETF OHLCV | `symbol, period, start_date, end_date, adjust` |
| `fund_etf_hist_min_em` | ETF Intraday | `symbol, start_date, end_date, period, adjust` |
| `fund_etf_hist_sina` | ETF OHLCV | `symbol` |
| `fund_etf_spot_em` | ETF Real-time | none |
| `fund_etf_spot_ths` | ETF Quotes | `date` |
| `fund_exchange_rank_em` | Rankings | none |
| `fund_fee_em` | Fees | `symbol, indicator` |
| `fund_fh_em` | Dividends | `year, typ, rank, sort, page` |
| `fund_fh_rank_em` | Dividends | none |
| `fund_financial_fund_daily_em` | Wealth Mgmt | none |
| `fund_financial_fund_info_em` | Wealth Mgmt | `symbol` |
| `fund_graded_fund_daily_em` | Graded | none |
| `fund_graded_fund_info_em` | Graded | `symbol` |
| `fund_hk_fund_hist_em` | HK Fund | `code, symbol` |
| `fund_hk_rank_em` | Rankings | none |
| `fund_individual_achievement_xq` | Analytics | `symbol, timeout` |
| `fund_individual_analysis_xq` | Analytics | `symbol, timeout` |
| `fund_individual_basic_info_xq` | Basic Info | `symbol, timeout` |
| `fund_individual_detail_hold_xq` | Holdings | `symbol, date, timeout` |
| `fund_individual_detail_info_xq` | Fees | `symbol, timeout` |
| `fund_individual_profit_probability_xq` | Analytics | `symbol, timeout` |
| `fund_info_index_em` | Index Funds | `symbol, indicator` |
| `fund_lcx_rank_em` | Rankings | none |
| `fund_lof_hist_em` | LOF OHLCV | `symbol, period, start_date, end_date, adjust` |
| `fund_lof_hist_min_em` | LOF Intraday | `symbol, start_date, end_date, period, adjust` |
| `fund_lof_spot_em` | LOF Real-time | none |
| `fund_manager_em` | Managers | none |
| `fund_manager_info_em` | Managers | `symbol` |
| `fund_money_fund_daily_em` | Money Market | none |
| `fund_money_fund_info_em` | Money Market | `symbol` |
| `fund_money_rank_em` | Rankings | none |
| `fund_name_em` | Basic Info | none |
| `fund_new_em` | Basic Info | `page` |
| `fund_notice_detail_em` | Announcements | `url` |
| `fund_notice_em` | Announcements | `symbol, page` |
| `fund_open_fund_daily_em` | Open-End NAV | none |
| `fund_open_fund_info_em` | Open-End NAV | `symbol, indicator, period` |
| `fund_open_fund_rank_em` | Rankings | `symbol` |
| `fund_overview_em` | Overview | `symbol` |
| `fund_portfolio_bond_hold_em` | Holdings | `symbol, date` |
| `fund_portfolio_change_em` | Holdings | `symbol, indicator, date` |
| `fund_portfolio_hold_em` | Holdings | `symbol, date` |
| `fund_portfolio_industry_allocation_em` | Holdings | `symbol, date` |
| `fund_position_detail_em` | Positions | `symbol, date` |
| `fund_position_em` | Positions | `indicator` |
| `fund_position_industry_em` | Positions | `symbol, date` |
| `fund_purchase_em` | Status | none |
| `fund_rating_all` | Ratings | none |
| `fund_rating_ja` | Ratings | `date` |
| `fund_rating_sh` | Ratings | `date` |
| `fund_rating_zs` | Ratings | `date` |
| `fund_reits_hist_em` | REITs | `symbol, period, start_date, end_date, adjust` |
| `fund_reits_spot_em` | REITs | none |
| `fund_value_estimation_em` | NAV Estimation | `symbol` |
