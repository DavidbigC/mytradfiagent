# AKShare API Reference

AKShare is a free, open-source Python library providing financial and alternative data for Chinese and global markets. Install with `pip install akshare`.

```python
import akshare as ak
```

Data sources include EastMoney, Sina Finance, China Bond, SHFE, DCE, CZCE, CFFEX, AMAC, and many others.

---

## Table of Contents

1. [Stock Data 股票](#1-stock-data-股票)
2. [Fund Data 基金 (Public)](#2-fund-data-基金-public)
3. [Fund Data 基金 (Private)](#3-fund-data-基金-private)
4. [Index Data 指数](#4-index-data-指数)
5. [Futures Data 期货](#5-futures-data-期货)
6. [Options Data 期权](#6-options-data-期权)
7. [Bond Data 债券](#7-bond-data-债券)
8. [Foreign Exchange 外汇](#8-foreign-exchange-外汇)
9. [Interest Rates 利率](#9-interest-rates-利率)
10. [Macro Data 宏观](#10-macro-data-宏观)
11. [Spot & Commodities 现货](#11-spot--commodities-现货)
12. [Energy Data 能源](#12-energy-data-能源)
13. [QDII Data](#13-qdii-data)
14. [Alternative Data 另类数据](#14-alternative-data-另类数据)
15. [High-Frequency Data 高频](#15-high-frequency-data-高频)
16. [NLP Tools](#16-nlp-tools)

---

## 1. Stock Data 股票

### 1.1 Market Overview 市场总貌

**`ak.stock_sse_summary()`**
- Parameters: None
- Returns: 项目, 股票, 科创板, 主板
- Source: Shanghai Stock Exchange

**`ak.stock_szse_summary(date)`**
- Parameters: `date` (str) — e.g., `"20200619"`
- Returns: 证券类别, 数量, 成交金额, 总市值, 流通市值

**`ak.stock_szse_area_summary(symbol, date)`**
- Parameters: `symbol` (`"当月"` or `"当年"`), `date` (str, `"202501"`)
- Returns: 序号, 地区, 总交易额, 占市场, 股票交易额, 基金交易额, 债券交易额, 期权交易额

**`ak.stock_szse_sector_summary(symbol, date)`**
- Parameters: `symbol` (`"当月"` or `"当年"`), `date` (str)
- Returns: 项目名称, 项目名称-英文, 交易天数, 成交金额, 成交股数, 成交笔数 (各含占比)

**`ak.stock_sse_deal_daily(date)`**
- Parameters: `date` (str, format `"20250221"`, after 20211227)
- Returns: 单日情况, 股票, 主板A, 主板B, 科创板, 股票回购

---

### 1.2 Individual Stock Info 个股信息

**`ak.stock_individual_info_em(symbol, timeout=None)`**
- Parameters: `symbol` (str) — 6-digit code e.g. `"603777"`
- Returns: item, value (basic info rows)

**`ak.stock_individual_basic_info_xq(symbol, token=None, timeout=None)`**
- Parameters: `symbol` (str) — e.g. `"SH601127"`
- Returns: item, value

**`ak.stock_bid_ask_em(symbol)`**
- Parameters: `symbol` (str) — e.g. `"000001"`
- Returns: item, value (bid/ask ladder)

---

### 1.3 Real-time Quotes 实时行情

**`ak.stock_zh_a_spot_em()`** — All A-shares (EastMoney)
- Returns: 序号, 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率-动态, 市净率, 总市值, 流通市值, 涨速, 5分钟涨跌, 60日涨跌幅, 年初至今涨跌幅

**`ak.stock_sh_a_spot_em()`** — Shanghai A-shares only (same columns)

**`ak.stock_sz_a_spot_em()`** — Shenzhen A-shares only (same columns)

**`ak.stock_bj_a_spot_em()`** — Beijing Exchange stocks (same columns)

**`ak.stock_kc_a_spot_em()`** — STAR Market (科创板) stocks

**`ak.stock_cy_a_spot_em()`** — ChiNext (创业板) stocks

**`ak.stock_zh_a_st_em()`** — ST/risk-warning board stocks

**`ak.stock_zh_a_spot()`** — Sina Finance all A-shares
- Returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额, 时间戳

**`ak.stock_individual_spot_xq(symbol, token=None, timeout=None)`** — Snowball real-time
- Parameters: `symbol` (str) — e.g. `"SH600000"`

---

### 1.4 Historical OHLCV 历史行情

**`ak.stock_zh_a_hist(symbol, period, start_date, end_date, adjust="", timeout=None)`**
- Parameters:
  - `symbol` (str) — 6-digit code
  - `period` (str) — `"daily"` / `"weekly"` / `"monthly"`
  - `start_date`, `end_date` (str) — `"YYYYMMDD"`
  - `adjust` (str) — `""` (unadjusted), `"qfq"` (前复权), `"hfq"` (后复权)
- Returns: 日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
- Note: **Primary recommended function for daily stock OHLCV**

**`ak.stock_zh_a_daily(symbol, start_date, end_date, adjust="")`**
- Parameters: `symbol` — e.g. `"sh600000"` (with exchange prefix)
- Returns: date, open, high, low, close, volume, amount, outstanding_share, turnover

**`ak.stock_zh_a_hist_tx(symbol, start_date, end_date, adjust="", timeout=None)`** — Tencent source
- Returns: date, open, close, high, low, amount

**`ak.stock_zh_a_minute(symbol, period, adjust="")`**
- Parameters: `symbol` — e.g. `"sh600751"`, `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns: day, open, high, low, close, volume

**`ak.stock_zh_a_hist_min_em(symbol, start_date, end_date, period, adjust="")`** — EastMoney intraday
- Parameters: `start_date` format `"1979-09-01 09:32:00"`, `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns (1min): 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价
- Returns (other): 时间, 开盘, 收盘, 最高, 最低, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 换手率
- Note: **Best source for intraday A-share data**

**`ak.stock_intraday_em(symbol)`** — Tick-level today's trades
- Parameters: `symbol` — e.g. `"000001"`
- Returns: 时间, 成交价, 手数, 买卖盘性质

**`ak.stock_intraday_sina(symbol, date)`** — Sina tick data
- Parameters: `symbol` (str) — `"sz000001"`, `date` — `"20240321"`
- Returns: symbol, name, ticktime, price, volume, prev_price, kind

**`ak.stock_zh_a_hist_pre_min_em(symbol, start_time, end_time)`** — Pre/post market intraday
- Returns: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 最新价

---

### 1.5 Peer Comparison 同行比较

**`ak.stock_zh_growth_comparison_em(symbol)`**
- Parameters: `symbol` — e.g. `"SZ000895"`
- Returns: 代码, 简称, EPS增长率(3年复合/24A/TTM/25E/26E/27E), 营业收入增长率(同维度), 净利润增长率(同维度), 排名

**`ak.stock_zh_valuation_comparison_em(symbol)`**
- Returns: 排名, 代码, 简称, PEG, PE(24A/TTM/25E/26E/27E), PS(同), PB(24A/MRQ), PCF1, PCF2, EV/EBITDA

**`ak.stock_zh_dupont_comparison_em(symbol)`**
- Returns: 代码, 简称, ROE, 净利率, 总资产周转率, 权益乘数 (各3年平均及历年)

**`ak.stock_zh_scale_comparison_em(symbol)`**
- Returns: 代码, 简称, 总市值, 总市值排名, 流通市值, 营业收入, 净利润 (各含排名)

---

### 1.6 B-Shares 港股 港股通

**`ak.stock_zh_b_daily(symbol, start_date, end_date, adjust="")`**
- Parameters: `symbol` — e.g. `"sh900901"`
- Returns: date, open, high, low, close, volume, outstanding_share, turnover

**`ak.stock_zh_b_minute(symbol, period, adjust="")`**
- Parameters: `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns: day, open, high, low, close, volume

---

### 1.7 Market Calendar & IPOs

**`ak.stock_gsrl_gsdt_em(date)`** — Corporate events calendar
- Parameters: `date` — `"20230808"`
- Returns: 序号, 代码, 简称, 事件类型, 具体事项, 交易日

**`ak.stock_zh_a_new_em()`** — Recent IPO stocks real-time
- Returns: 序号, 代码, 名称, 最新价, 涨跌幅, 上市时间, 总市值, 流通市值, ...

---

## 2. Fund Data 基金 (Public)

### 2.1 Basic Info & Listings

**`ak.fund_manager_em()`** — All fund managers (天天基金网-基金经理大全)
- Returns all managers in one call (~4000+ managers, ~32000 rows due to one row per managed fund)
- Returns: 序号, 姓名, 所属公司, 现任基金代码, 现任基金, 累计从业时间(天), 现任基金资产总规模(亿元), 现任基金最佳回报(%)
- Note: **Rows are repeated per managed fund** — deduplicate on 姓名+所属公司 for manager profiles; use as-is to get manager→fund mappings

**`ak.fund_name_em()`**
- Returns: 基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称

**`ak.fund_purchase_em()`**
- Returns: 序号, 基金代码, 基金简称, 基金类型, 最新净值, 申购状态, 赎回状态, 下一开放日, 购买起点, 日累计限额, 手续费

**`ak.fund_info_index_em(symbol, indicator)`** — Index-tracking fund list
- Returns: 基金代码, 基金名称, 单位净值, 日增长率, 近1周/月/季/年/2年/3年, 手续费, 跟踪标的, 跟踪方式

---

### 2.2 ETF Real-time Quotes

**`ak.fund_etf_spot_em()`** — All ETFs real-time (EastMoney)
- Returns: 代码, 名称, 最新价, IOPV实时估值, 基金折价率, 涨跌额, 涨跌幅, 成交量, 成交额, 开盘价, 最高, 最低, 昨收, 换手率, 量比, 委比, 主力净流入, 超大单净流入, 大单净流入, 中单净流入, 小单净流入, 最新份额, 流通市值, 总市值, 数据日期
- Note: **Best source for ETF real-time snapshot**

**`ak.fund_lof_spot_em()`** — LOF funds real-time
- Returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额, 开盘价, 最高, 最低, 昨收, 换手率, 流通市值, 总市值

**`ak.fund_etf_category_sina(symbol)`** — Sina ETF by category
- Parameters: `symbol` (fund category string)
- Returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额

**`ak.fund_etf_category_ths(symbol, date)`** — THS ETF by category
- Returns: 序号, 基金代码, 基金名称, 当前/前一日单位净值, 累计净值, 增长值, 增长率, 赎回/申购状态

---

### 2.3 ETF Historical OHLCV

**`ak.fund_etf_hist_em(symbol, period, start_date, end_date, adjust="")`**
- Parameters:
  - `symbol` (str) — ETF code e.g. `"510050"`
  - `period` — `"daily"` / `"weekly"` / `"monthly"`
  - `adjust` — `""` / `"qfq"` / `"hfq"`
- Returns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
- Note: **Primary recommended function for ETF daily OHLCV**

**`ak.fund_etf_hist_min_em(symbol, start_date, end_date, period, adjust="")`** — ETF intraday
- Parameters: `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns (1min): 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价
- Returns (other): 时间, 开盘, 收盘, 最高, 最低, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 换手率
- Note: **ETF intraday data is available here — unlike BaoStock which has none**

**`ak.fund_lof_hist_em(symbol, period, start_date, end_date, adjust="")`** — LOF daily OHLCV
- Same structure as fund_etf_hist_em

**`ak.fund_lof_hist_min_em(symbol, start_date, end_date, period, adjust="")`** — LOF intraday

**`ak.fund_etf_hist_sina(symbol)`** — Sina ETF historical
- Returns: date, open, high, low, close, volume

---

### 2.4 ETF / Fund NAV Data

**`ak.fund_etf_fund_daily_em()`** — All ETF/fund daily NAV
- Returns: 基金代码, 基金简称, 类型, 当前/前交易日单位/累计净值, 增长值/率, 市价, 折价率

**`ak.fund_etf_fund_info_em(fund, start_date, end_date)`** — Single ETF NAV history
- Returns: 净值日期, 单位净值, 累计净值, 日增长率, 申购/赎回状态

**`ak.fund_open_fund_daily_em()`** — Open-ended fund NAV
- Returns: 基金代码, 基金简称, 单位净值, 累计净值, 前交易日净值, 日增长值/率, 申购/赎回状态, 手续费

**`ak.fund_open_fund_info_em(symbol, indicator, period=None)`** — Open fund NAV history
- Parameters: `indicator` — `"净值走势"/"累计净值"/"收益率"/"同类排名"/"分红"/"拆分"`
- Returns: varies by indicator (净值日期, 单位净值, 日增长率, etc.)

**`ak.fund_money_fund_daily_em()`** — Money market fund NAV
- Returns: 基金代码, 基金简称, 当前/前日万份收益, 7日年化%, 单位净值, 日涨幅

**`ak.fund_graded_fund_daily_em()`** — Graded fund NAV
- Returns: 基金代码, 基金简称, 单位/累计净值, 市价, 折价率, 手续费

---

### 2.5 ETF Holdings / Composition

**`ak.fund_portfolio_hold_em(symbol, date)`** — Stock holdings
- Parameters: `symbol` (fund code), `date` (year, e.g. `"2024"`)
- Returns: 序号, 股票代码, 股票名称, 占净值比例, 持股数, 持仓市值, 季度
- Note: **Key function for ETF/fund composition data**

**`ak.fund_portfolio_bond_hold_em(symbol, date)`** — Bond holdings
- Returns: 序号, 债券代码, 债券名称, 占净值比例, 持仓市值, 季度

**`ak.fund_portfolio_industry_allocation_em(symbol, date)`** — Industry allocation
- Returns: 序号, 行业类别, 占净值比例, 市值, 截止时间

**`ak.fund_portfolio_change_em(symbol, indicator, date)`** — Holding changes
- Parameters: `indicator` — `"累计买入"` or `"累计卖出"`
- Returns: 序号, 股票代码, 股票名称, 本期累计买入/卖出金额, 占期初基金资产净值比例, 季度

---

### 2.6 Fund Rankings

**`ak.fund_open_fund_rank_em(symbol)`** — Open fund performance ranking
- Parameters: `symbol` (fund category)
- Returns: 序号, 基金代码, 基金简称, 日期, 单位/累计净值, 日增长率, 近1周/月/3月/6月/1年/2年/3年, 今年来, 成立来, 手续费

**`ak.fund_exchange_rank_em()`** — Exchange-traded fund ranking
- Returns: 序号, 基金代码, 基金简称, 类型, 日期, 单位/累计净值, 近期收益各周期, 成立日期

**`ak.fund_money_rank_em()`** — Money market fund ranking

**`ak.fund_hk_rank_em()`** — HK fund ranking
- Returns: 序号, 基金代码, 基金简称, 币种, 单位净值, 日增长率, 近期各周期收益, 香港基金代码

---

### 2.7 Fund Analytics (Snowball)

**`ak.fund_individual_achievement_xq(symbol, timeout=None)`**
- Returns: 业绩类型, 周期, 区间收益, 最大回撤, 同类排名

**`ak.fund_individual_analysis_xq(symbol, timeout=None)`**
- Returns: 周期, 较同类风险收益比, 年化波动率, 年化夏普比率, 最大回撤

**`ak.fund_individual_profit_probability_xq(symbol, timeout=None)`**
- Returns: 持有时长, 盈利概率, 平均收益

**`ak.fund_individual_detail_hold_xq(symbol, date, timeout=None)`**
- Returns: 资产类型, 仓位占比

---

### 2.8 Fund Dividends, Fees, Overview

**`ak.fund_etf_dividend_sina(symbol)`**
- Returns: 日期, 累计分红

**`ak.fund_fh_em(year, typ, rank, sort, page)`** — Fund dividend history
- Returns: 序号, 基金代码, 基金简称, 权益登记日, 除息日期, 分红, 分红发放日

**`ak.fund_fh_rank_em(year=None)`** — Top dividend-paying funds
- Returns: 序号, 基金代码, 基金简称, 累计分红, 累计次数, 成立日期

**`ak.fund_overview_em(symbol)`** — Fund summary
- Returns: 基金全称, 基金简称, 基金代码, 基金类型, 发行/成立日期, 资产规模, 份额规模, 基金管理人, 基金托管人, 基金经理人, 管理/托管/销售服务费率, 最高认购费率, 业绩比较基准, 跟踪标的

**`ak.fund_fee_em(symbol, indicator)`** — Fee schedule
- Parameters: `indicator` — `"交易状态"/"申购金额"/"运作费用"/"认购费率"/"申购费率"/"赎回费率"`
- Returns: 费用类型, 条件或名称, 费用

**`ak.fund_value_estimation_em(symbol)`** — Intraday NAV estimation
- Returns: 序号, 基金代码, 基金名称, 交易日估算值, 估算增长率, 交易日单位净值, 日增长率, 估算偏差

---

### 2.9 Fund Ratings

**`ak.fund_rating_all()`**
- Returns: 代码, 简称, 基金经理, 基金公司, 5星评级家数, 上海证券, 招商证券, 济安金信评级, 手续费, 类型

**`ak.fund_rating_sh(date)`** — Shanghai Securities rating
- Returns: 代码, 简称, 基金经理, 3年期/5年期评级, 单位净值, 近期收益, 手续费

---

## 3. Fund Data 基金 (Private)

**`ak.amac_member_info()`** — AMAC member institutions
- Returns: 机构名称, 会员代表, 会员类型, 会员编号, 入会时间, 机构类型

**`ak.amac_manager_info()`** — Private fund managers
- Returns: 私募基金管理人名称, 法定代表人, 机构类型, 注册地, 登记编号, 成立时间, 登记时间

**`ak.amac_manager_classify_info()`** — Manager classification disclosure
- Returns: Above + 办公地, 在管基金数量, 会员类型

**`ak.amac_fund_info(start_page, end_page)`** — Private fund products
- Returns: 基金名称, 管理人名称, 管理人类型, 运行状态, 备案时间, 建立时间, 托管人名称

**`ak.amac_securities_info()`** — Securities company collective AMP products
- Returns: 产品名称, 产品编码, 管理人名称, 成立/到期日期, 投资类型, 托管人名称, 备案日期

**`ak.amac_fund_abs()`** — Asset-backed special plans
- Returns: 编号, 备案编号, 专项计划全称, 管理人, 托管人, 成立日期, 预期到期时间

**`ak.amac_manager_cancelled_info()`** — Cancelled fund managers list
- Returns: 管理人名称, 统一社会信用代码, 登记时间, 注销时间, 注销类型

**`ak.amac_person_fund_org_list(symbol)`** — Fund practitioner registry by org
- Returns: 序号, 机构名称, 员工人数, 基金从业资格, 基金销售业务资格, 基金经理, 投资经理

---

## 4. Index Data 指数

### 4.1 A-Share Indices Real-time

**`ak.stock_zh_index_spot_em(symbol)`**
- Parameters: `symbol` — `"沪深重要指数"` / `"上证系列指数"` / `"深证系列指数"` / `"中证系列指数"` / `"指数成份"`
- Returns: 序号, 代码, 名称, 最新价, 涨跌额, 涨跌幅(%), 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 量比

**`ak.stock_zh_index_spot_sina()`** — Sina A-share indices
- Returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 昨收, 今开, 最高, 最低, 成交量, 成交额

---

### 4.2 A-Share Indices Historical

**`ak.stock_zh_index_daily(symbol)`** — Sina source
- Parameters: `symbol` — e.g. `"sz399552"`
- Returns: date, open, high, low, close, volume

**`ak.stock_zh_index_daily_em(symbol, start_date, end_date)`** — EastMoney source
- Returns: date, open, close, high, low, volume, amount

**`ak.index_zh_a_hist(symbol, period, start_date, end_date)`** — Comprehensive daily/weekly/monthly
- Parameters: `period` — `"daily"` / `"weekly"` / `"monthly"`
- Returns: 日期, 开盘, 收盘, 最高, 最低, 成交量(手), 成交额(元), 振幅(%), 涨跌幅(%), 涨跌额, 换手率

**`ak.index_zh_a_hist_min_em(symbol, period, start_date, end_date)`** — Intraday index data
- Parameters: `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价

---

### 4.3 Global Indices

**`ak.index_global_spot_em()`** — All global indices real-time
- Returns: 序号, 代码, 名称, 最新价, 涨跌额, 涨跌幅, 开盘, 最高, 最低, 昨收, 振幅, 最新行情时间

**`ak.index_global_hist_em(symbol)`** — Global index historical
- Returns: 日期, 代码, 名称, 今开, 最新价, 最高, 最低, 振幅(%)

**`ak.index_us_stock_sina(symbol)`** — US indices
- Parameters: `symbol` — `".IXIC"` / `".DJI"` / `".INX"` / `".NDX"`
- Returns: date, open, high, low, close, volume, amount

**`ak.stock_hk_index_spot_em()`** — HK indices real-time
- Returns: 序号, 内部编号, 代码, 名称, 最新价, 涨跌额, 涨跌幅, 今开, 最高, 最低, 昨收, 成交量, 成交额

---

### 4.4 Index Constituents

**`ak.index_stock_cons(symbol)`** — Index constituent stocks
- Parameters: `symbol` — e.g. `"000300"` (HS300), `"000016"` (SSE50), `"000905"` (ZZ500)
- Returns: 品种代码, 品种名称, 纳入日期

**`ak.index_stock_cons_csindex(symbol)`** — CSIndex constituents (with English names)
- Returns: 日期, 指数代码, 指数名称, 指数英文名称, 成分券代码, 成分券名称, 交易所

**`ak.index_stock_cons_weight_csindex(symbol)`** — Constituent weights
- Returns: 日期, 指数代码, 指数名称, 成分券代码, 成分券名称, 交易所, 权重(%)
- Note: **Critical for ETF replication and factor analysis**

---

### 4.5 Option Volatility Indices (QVIX)

**`ak.index_option_50etf_qvix()`** — 50ETF QVIX daily
- Returns: date, open, high, low, close

**`ak.index_option_50etf_min_qvix()`** — 50ETF QVIX real-time
- Returns: time, qvix

Available for: 50ETF, 300ETF, 500ETF, 创业板(CYB), 科创板(KCB), 深证100ETF, 中证300股指, 中证1000股指, 上证50股指

---

### 4.6 Shenwan Industry Indices

**`ak.sw_index_first_info()`** — Level-1 industries (28 sectors)
- Returns: 行业代码, 行业名称, 成份个数, 静态市盈率, TTM市盈率, 市净率, 静态股息率

**`ak.sw_index_second_info()`** — Level-2 industries
- Returns: 行业代码, 行业名称, 上级行业, 成份个数, 市盈率(静态/TTM), 市净率, 股息率

**`ak.sw_index_third_info()`** — Level-3 industries

**`ak.sw_index_third_cons(symbol)`** — Industry constituent stocks
- Returns: 序号, 股票代码, 股票简称, 纳入时间, 申万1/2/3级, 价格, 市盈率, 市净率, 股息率, 市值, 净利润同比增长, 营收同比增长

---

### 4.7 CNI National Indices

**`ak.index_all_cni()`** — All CNI indices snapshot
- Returns: 指数代码, 指数简称, 样本数, 收盘点位, 涨跌幅, PE滚动, 成交量, 成交额, 总市值, 自由流通市值

**`ak.index_hist_cni(symbol, start_date, end_date)`** — CNI index history
- Returns: 日期, 开盘价, 最高价, 最低价, 收盘价, 涨跌幅, 成交量, 成交额

**`ak.index_detail_cni(symbol)`** — CNI index constituents with weights
- Returns: 日期, 样本代码, 样本简称, 所属行业, 自由流通市值, 总市值, 权重(%)

---

## 5. Futures Data 期货

### 5.1 Contract Info & Fees

**`ak.futures_fees_info()`** — All futures fee schedules
- Returns: 交易所, 合约代码, 合约名称, 品种代码/名称, 合约乘数, 最小变动价位, 开仓/平仓/今平手续费, 多/空保证金率, 结算价, 最新价

**`ak.futures_comm_info(symbol)`**
- Parameters: `symbol` — `"所有"` / `"上海期货交易所"` / `"大连商品交易所"` / `"郑州商品交易所"` / etc.
- Returns: 交易所名称, 合约名称, 代码, 当前价, 涨跌停板, 保证金率, 费率标准, 最小跳动盈亏

**`ak.futures_rule(date)`** — Trading rules
- Returns: 交易所, 品种, 代码, 保证金率, 涨跌停板, 合约乘数, 最小变动价位, 最大下单量

---

### 5.2 Real-time & Historical Futures Quotes

**`ak.futures_zh_spot(symbol, market, adjust)`** — Real-time futures quotes
- Parameters: `market` — `"CF"` (commodity) or `"FF"` (financial)
- Returns: Symbol, Time, Open, High, Low, 当前价, 买/卖价, 持仓量, 成交量

**`ak.futures_zh_realtime(symbol)`** — Futures real-time by variety
- Returns: Symbol, 交易所, 名称, 成交价, 结算价, 开/高/低/收盘, 买卖价/量, 持仓量

**`ak.futures_zh_minute_sina(symbol, period)`** — Futures intraday (Sina)
- Parameters: `period` — `"1"/"5"/"15"/"30"/"60"`
- Returns: Datetime, Open, High, Low, Close, Volume, 持仓量

---

### 5.3 Spot & Basis

**`ak.futures_spot_price(date)`** — Futures-spot spread
- Returns: Symbol, Spot Price, 近月合约/价格, 主力合约/价格, 基差值, 基差率

**`ak.futures_spot_price_daily(start_day, end_day, vars_list)`** — Daily spot-futures spread
- Returns: Symbol, 现货价, 近月合约, 价格, 基差, 基差率, 日期

**`ak.futures_spot_sys(symbol, indicator)`** — Systematic spot data
- Parameters: `indicator` — `"市场价格"` / `"基差率"` / `"主力基差"`

---

### 5.4 Warehouse Receipts & Inventory

**`ak.futures_inventory_em(symbol)`** — Futures inventory trend
- Returns: Date, Inventory, Change

**`ak.futures_warehouse_receipt_czce(date)`** — CZCE warehouse receipts
- Returns: Dict by variety; warehouse details, quantity, change

**`ak.futures_warehouse_receipt_dce(date)`** — DCE warehouse receipts
- Returns: 品种代码, 仓库, 前日库存, 今日库存, 变动

**`ak.futures_shfe_warehouse_receipt(date)`** — SHFE warehouse receipts

---

### 5.5 Position Rankings

**`ak.futures_dce_position_rank(date, vars_list)`** — DCE long/short rankings
- Returns: Dict; Rank, Trader Name, Long/Short Position, Change

**`ak.futures_gfex_position_rank(date, vars_list)`** — GFEX rankings
- Returns: Rank, 多头名称/持仓/变化, 空头名称/持仓/变化

**`ak.futures_hold_pos_sina(symbol, contract, date)`** — Sina position rankings
- Parameters: `symbol` — `"成交量"` / `"多单持仓"` / `"空单持仓"`
- Returns: 排名, 会员名称, 持仓量, 变化量

---

### 5.6 Contract Details

**`ak.futures_contract_info_shfe(date)`** — SHFE contracts
**`ak.futures_contract_info_dce()`** — DCE contracts
**`ak.futures_contract_info_czce(date)`** — CZCE contracts
**`ak.futures_contract_info_cffex(date)`** — CFFEX contracts

All return: Contract Code, Listing Date, Expiration Date, Delivery Date, Min Tick, etc.

---

## 6. Options Data 期权

### 6.1 Financial Options Info

**`ak.option_current_day_sse()`** — Current SSE options contracts
- Returns: 合约编码, 合约交易代码, 合约简称, 标的代码, 类型(认购/认沽), 行权价, 到期日, 开始日期

**`ak.option_current_day_szse()`** — Current SZSE options contracts
- Returns: 合约编码, 合约代码, 标的简称, 合约类型, 行权价, 最后交易日, 到期日, 涨跌停价

**`ak.option_daily_stats_sse(date)`** — SSE daily options stats
- Returns: 合约标的代码/名称, 合约数量, 总成交额/量, 认购/认沽成交量比, 未平仓合约数

**`ak.option_risk_indicator_sse(date)`** — SSE options Greeks
- Returns: TRADE_DATE, CONTRACT_SYMBOL, DELTA, THETA, GAMMA, VEGA, RHO, 隐含波动率

---

### 6.2 Options Real-time & Historical (Sina)

**`ak.option_sse_list_sina(symbol, exchange)`** — SSE ETF option months
- Parameters: `symbol` — `"50ETF"` or `"300ETF"`
- Returns: List of expiry months

**`ak.option_sse_spot_price_sina(symbol)`** — Option real-time price
**`ak.option_sse_greeks_sina(symbol)`** — Option Greeks real-time
**`ak.option_sse_daily_sina(symbol)`** — Option daily OHLCV
- Returns: 日期, 开盘, 最高, 最低, 收盘, 成交

**`ak.option_cffex_sz50_list_sina()`** — CFFEX 上证50 options list
**`ak.option_cffex_sz50_daily_sina(symbol)`** — CFFEX 上证50 option daily

**`ak.option_cffex_hs300_list_sina()`** — CFFEX HS300 options list
**`ak.option_cffex_hs300_daily_sina(symbol)`** — CFFEX HS300 option daily

**`ak.option_cffex_zz1000_list_sina()`** — CFFEX ZZ1000 options list
**`ak.option_cffex_zz1000_daily_sina(symbol)`** — CFFEX ZZ1000 option daily

---

### 6.3 Options Analytics (EastMoney)

**`ak.option_current_em()`** — All options real-time (EastMoney)
- Returns: 代码, 名称, 最新价, 涨跌幅, 成交量, 持仓量, 行权价, 剩余日, 昨结, 市场标识

**`ak.option_value_analysis_em()`** — Options value analysis
- Returns: 期权代码, 期权名称, 最新价, 时间价值, 内在价值, 隐含波动率, 理论价格, 标的最新价, 标的近一年波动率, 到期日

**`ak.option_risk_analysis_em()`** — Options risk metrics
- Returns: 期权代码, 期权名称, 最新价, 涨跌幅, 杠杆比率, 实际杠杆, Delta, Gamma, Vega, Rho, Theta, 到期日

**`ak.option_premium_analysis_em()`** — Options premium/discount
- Returns: 期权代码, 折溢价率, 行权价, 标的最新价, 盈亏平衡价, 到期日

---

### 6.4 Commodity Options

**`ak.option_hist_shfe(symbol, trade_date)`** — SHFE commodity options historical
- Returns: 合约代码, 开/高/低/收/前结算/结算价, 涨跌, Delta, 隐含波动率, 成交量, 持仓量, 行权量

**`ak.option_hist_dce(symbol, trade_date)`** — DCE commodity options historical

**`ak.option_hist_czce(symbol, trade_date)`** — CZCE commodity options historical

**`ak.option_hist_gfex(symbol, trade_date)`** — GFEX options (工业硅/碳酸锂)

**`ak.option_comm_info(symbol)`** — Commodity options fee info
- Returns: 品种, 现价, 权利金, 各类手续费, 保证金, 交易所

---

## 7. Bond Data 债券

### 7.1 Yield Curves & Rates

**`ak.bond_china_yield(start_date, end_date)`** — China bond yield curve
- Returns: 曲线名称, 日期, 3月, 6月, 1年, 3年, 5年, 7年, 10年, 30年
- Note: **Key for interest rate analysis**

**`ak.bond_zh_us_rate(start_date)`** — China vs US treasury yields
- Returns: 日期, 中国国债2/5/10/30年收益率, 利差(10年-2年), 中国GDP年增率, 美国国债各期限收益率, 美国GDP年增率

**`ak.bond_china_close_return(symbol, period, start_date, end_date)`** — Bond close-return
- Returns: 日期, 期限, 到期收益率, 即期收益率, 远期收益率

**`ak.bond_gb_zh_sina(symbol)`** — Chinese gov bond yield history (9 maturities)
**`ak.bond_gb_us_sina(symbol)`** — US Treasury yield history (13 maturities)
- Returns: date, open, high, low, close, volume

---

### 7.2 Convertible Bonds 可转债

**`ak.bond_zh_cov()`** — All convertible bonds snapshot
- Returns: 债券代码, 债券简称, 申购日期, 正股代码, 正股简称, 正股价, 转股价, 转股价值, 债现价, 转股溢价率, 信用评级, 发行规模, 中签率, 上市时间

**`ak.bond_cov_comparison()`** — Convertible bond analysis table
- Returns: 转债代码/名称/最新价/涨跌幅, 正股信息, 转股价/价值/溢价率, 纯债溢价率, 回售/强赎触发价, 纯债价值, 开始转股日

**`ak.bond_zh_cov_value_analysis(symbol)`** — Single convert bond value
- Returns: 日期, 收盘价, 纯债价值, 转股价值, 纯债溢价率, 转股溢价率

**`ak.bond_zh_hs_cov_spot()`** — Convertible bond real-time quotes
**`ak.bond_zh_hs_cov_daily(symbol)`** — Daily OHLCV

**`ak.bond_cb_jsl(cookie)`** — Jisilu convertible bond data (requires cookie)
- Returns: 代码, 现价, 转股溢价率, 债券评级, 剩余年限, 剩余规模, 双低值, 到期税前收益

**`ak.bond_cb_redeem_jsl()`** — Forced redemption data (no cookie needed)

---

### 7.3 Bond Spot Quotes

**`ak.bond_spot_quote()`** — Interbank bond spot bid/ask
- Returns: 报价机构, 债券简称, 买入净价, 卖出净价, 买入收益率, 卖出收益率

**`ak.bond_spot_deal()`** — Bond spot deal prices
- Returns: 债券简称, 成交净价, 最新收益率, 涨跌, 加权收益率, 交易量

**`ak.bond_zh_hs_spot(start_page, end_page)`** — Exchange bond real-time
- Returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额

**`ak.bond_zh_hs_daily(symbol)`** — Exchange bond daily OHLCV
- Returns: date, open, high, low, close, volume

---

### 7.4 Bond Indices

**`ak.bond_new_composite_index_cbond(indicator, period)`** — China bond composite index
**`ak.bond_composite_index_cbond(indicator, period)`** — Legacy bond index
- Parameters: `indicator` (16 options), `period` (12 time period options)
- Returns: date, value

---

## 8. Foreign Exchange 外汇

**`ak.forex_spot_em()`** — All FX pairs real-time (EastMoney)
- Returns: 序号, 代码, 名称, 最新价, 涨跌额, 涨跌幅, 今开, 最高, 最低, 昨收

**`ak.forex_hist_em(symbol)`** — FX historical
- Parameters: `symbol` — e.g. `"USDCNH"`
- Returns: 日期, 代码, 名称, 今开, 最新价, 最高, 最低, 振幅

**`ak.currency_boc_sina(symbol, start_date, end_date)`** — BOC RMB exchange rates history
- Returns: 日期, 中行汇买价, 中行钞买价, 中行钞卖价/汇卖价, 央行中间价

**`ak.currency_boc_safe()`** — SAFE RMB central parity rates (25 currencies)
- Returns: 日期, 美元, 欧元, 日元, 港元, 英镑, 澳元, 加元, 新加坡元, 瑞士法郎, 韩元, 泰铢, ... (25 currencies total)

**`ak.fx_spot_quote()`** — RMB spot FX interbank quotes
- Returns: 货币对, 买报价, 卖报价

**`ak.fx_swap_quote()`** — RMB forward/swap quotes
- Returns: 货币对, 1周, 1月, 3月, 6月, 9月, 1年

**`ak.fx_pair_quote()`** — Cross-currency quotes
- Returns: 货币对, 买报价, 卖报价

**`ak.macro_fx_sentiment(start_date, end_date)`** — COT-style FX sentiment
- Returns: date, AUDJPY, AUDUSD, EURAUD, EURJPY, EURUSD, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY, USDX, XAUUSD

---

## 9. Interest Rates 利率

### 9.1 Central Bank Decisions

All return: 商品, 日期, 今值, 预测值, 前值

- **`ak.macro_bank_china_interest_rate()`** — PBoC (from 1991)
- **`ak.macro_bank_usa_interest_rate()`** — Fed Funds Rate (from 1982)
- **`ak.macro_bank_euro_interest_rate()`** — ECB (from 1999)
- **`ak.macro_bank_japan_interest_rate()`** — BOJ (from 2008)
- **`ak.macro_bank_english_interest_rate()`** — BOE (from 1970)
- **`ak.macro_bank_australia_interest_rate()`** — RBA (from 1980)
- **`ak.macro_bank_newzealand_interest_rate()`** — RBNZ (from 1999)
- **`ak.macro_bank_switzerland_interest_rate()`** — SNB (from 2008)
- **`ak.macro_bank_russia_interest_rate()`** — CBR (from 2003)
- **`ak.macro_bank_india_interest_rate()`** — RBI (from 2000)
- **`ak.macro_bank_brazil_interest_rate()`** — BCB (from 2008)

---

### 9.2 Interbank & Repo Rates

**`ak.rate_interbank(market, symbol, indicator)`** — SHIBOR / LIBOR / etc.
- Parameters:
  - `market` — e.g. `"上海银行同业拆借市场"`
  - `symbol` — e.g. `"Shibor人民币"`
  - `indicator` — e.g. `"隔夜"` / `"1周"` / `"1月"` / `"3月"`
- Returns: 日期, 利率, 涨跌

**`ak.repo_rate_hist(start_date, end_date)`** — Repo fixing rates history
- Returns: date, FR001, FR007, FR014, FDR001, FDR007, FDR014
- Note: Date range must be within 1 year

**`ak.repo_rate_query(symbol)`** — Repo fixing rates latest
- Parameters: `symbol` — `"回购定盘利率"` or `"银银间回购定盘利率"`
- Returns: date, FR001, FR007, FR014

---

## 10. Macro Data 宏观

### 10.1 China Key Indicators

**`ak.macro_china_gdp()`** — GDP quarterly
- Returns: 季度, GDP(绝对值/同比), 第一/二/三产业(绝对值/同比)

**`ak.macro_china_gdp_yearly()`** — GDP annual rate
- Returns: 商品, 日期, 今值, 预测值, 前值

**`ak.macro_china_cpi()`** — CPI monthly detail
- Returns: 月份, 全国/城市/农村(当月/同比/环比/累计)

**`ak.macro_china_cpi_yearly()`** / **`ak.macro_china_cpi_monthly()`** — CPI annual/monthly rate
- Returns: 商品, 日期, 今值, 预测值, 前值

**`ak.macro_china_ppi()`** — PPI monthly
- Returns: 月份, 当月值, 同比, 累计

**`ak.macro_china_ppi_yearly()`** — PPI annual rate

**`ak.macro_china_pmi()`** — PMI manufacturing + non-manufacturing
- Returns: 月份, 制造业(指数/同比), 非制造业(指数/同比)

**`ak.macro_china_pmi_yearly()`** / **`ak.macro_china_cx_pmi_yearly()`** (Caixin) — PMI annual rate

**`ak.macro_china_lpr()`** — LPR rates
- Returns: 交易日期, LPR1Y, LPR5Y, 6月~1年贷款利率, 5年以上贷款利率

**`ak.macro_china_m2_yearly()`** — M2 money supply YoY

**`ak.macro_china_supply_of_money()`** — M0/M1/M2 detail
- Returns: 统计时间, M2/M1/M0(数值/同比), 活期/定期/储蓄存款(数值/同比)

**`ak.macro_china_reserve_requirement_ratio()`** — Reserve requirement ratio changes
- Returns: 公告日期, 执行日期, 大型机构(调前/调后/调整幅度), 中小机构(同), 市场影响, 备注

---

### 10.2 China Trade & Finance

**`ak.macro_china_hgjck()`** — Customs imports/exports
- Returns: 月份, 出口额(当月/同比/环比), 进口额(同), 累计出口/进口(金额/同比)

**`ak.macro_china_fdi()`** — Foreign Direct Investment
- Returns: 月份, 当月值, 同比增长, 环比增长, 累计值, 累计同比

**`ak.macro_china_fx_reserves_yearly()`** — Foreign exchange reserves

**`ak.macro_china_shrzgm()`** — Social financing aggregate
- Returns: 月份, 社融规模增量, 人民币贷款, 外币贷款, 委托贷款, 信托贷款, 未贴现银行承兑汇票, 企业债券, 股票融资

**`ak.macro_china_new_financial_credit()`** — New RMB loans
- Returns: 月份, 当月值, 同比/环比, 累计值

**`ak.macro_china_czsr()`** — Fiscal revenue
- Returns: 月份, 当月/同比/环比/累计/累计同比

---

### 10.3 China Economic Activity

**`ak.macro_china_consumer_goods_retail()`** — Consumer goods retail sales
**`ak.macro_china_gdzctz()`** — Fixed asset investment
**`ak.macro_china_industrial_production_yoy()`** — Industrial production YoY
**`ak.macro_china_exports_yoy()`** / **`ak.macro_china_imports_yoy()`** — Trade YoY
**`ak.macro_china_trade_balance()`** — Trade balance
**`ak.macro_china_urban_unemployment()`** — Urban unemployment rate

All return: 商品, 日期, 今值, 预测值, 前值

---

### 10.4 China Property & Credit

**`ak.macro_china_new_house_price(city_first, city_second)`** — New house prices
- Returns: 日期, 城市, 新建住宅(环比/同比/基期), 二手住宅(同)

**`ak.macro_china_enterprise_boom_index()`** — Business confidence index
- Returns: 季度, 企业家信心(指数/同比/环比), 企业景气(同)

**`ak.macro_china_central_bank_balance()`** — PBoC balance sheet
- Returns: 统计时间, 资产(外汇/国内/其他), 负债(储备/存款/债券/其他)

---

### 10.5 China Commodity Indices

**`ak.macro_china_commodity_price_index()`** — Commodity price index
**`ak.macro_china_energy_index()`** — Energy index
**`ak.macro_china_agricultural_product()`** — Agricultural product price index
**`ak.macro_china_bdti_index()`** — Baltic Dirty Tanker Index
**`ak.macro_china_bsi_index()`** — Supramax Shipping Index
**`ak.macro_shipping_bdi()`** — Baltic Dry Index
**`ak.macro_shipping_bci()`** — Capesize Index
**`ak.macro_shipping_bpi()`** — Panamax Index

All return: 日期, 最新值, 涨跌, 近3月/6月/1年/2年/3年变化

**`ak.macro_china_freight_index()`** — Comprehensive freight index
- Returns: Date, BCI, BHMI, BSI, BDI, HRCI, BCTI, BDTI

---

### 10.6 Global Macro

**`ak.macro_global_sox_index()`** — Philadelphia Semiconductor Index

---

## 11. Spot & Commodities 现货

**`ak.spot_price_qh(symbol)`** — 99期货 spot price trend
- Parameters: `symbol` — e.g. `"螺纹钢"`, `"铜"`, `"铝"`, `"黄金"`
- Returns: 日期, 期货收盘价, 现货价格

**`ak.spot_hist_sge(symbol)`** — Shanghai Gold Exchange historical
- Parameters: `symbol` — e.g. `"Au99.99"`, `"Ag99.99"`
- Returns: date, open, close, low, high

**`ak.spot_quotations_sge(symbol)`** — SGE real-time quotes
- Returns: 品种, 时间, 现价, 更新时间

**`ak.spot_golden_benchmark_sge()`** — SGE gold benchmark price
- Returns: 交易时间, 晚盘价, 早盘价

**`ak.spot_silver_benchmark_sge()`** — SGE silver benchmark

**`ak.spot_hog_soozhu()`** — Live hog spot prices by province
- Returns: 省份, 价格, 涨跌幅

**`ak.spot_hog_year_trend_soozhu()`** — Hog price annual trend
**`ak.spot_corn_price_soozhu()`** — Corn price trend
**`ak.spot_soybean_price_soozhu()`** — Soybean meal price trend

---

## 12. Energy Data 能源

### 12.1 Carbon Markets

**`ak.energy_carbon_domestic(symbol)`** — China carbon market trading
- Parameters: `symbol` — `"湖北"` / `"上海"` / `"北京"` / `"重庆"` / `"广东"` / `"天津"` / `"深圳"` / `"福建"`
- Returns: 日期, 成交价(元), 成交量(吨), 成交额, 地点

**`ak.energy_carbon_bj()`** — Beijing carbon exchange
- Returns: 日期, 成交量(吨), 成交均价(元/吨), 成交额, 成交单位

**`ak.energy_carbon_sz()`** — Shenzhen carbon exchange (domestic)
- Returns: 交易日期, 市场交易指数, 开盘/最高/最低/均价/收盘价, 成交量, 成交额

**`ak.energy_carbon_eu()`** — Shenzhen carbon exchange (international, 2018-2020)

**`ak.energy_carbon_hb()`** — Hubei carbon exchange
**`ak.energy_carbon_gz()`** — Guangzhou carbon exchange (from 2013)
- Returns: 日期, 品种, 开/收/高/低价, 涨跌, 成交数量/金额

---

### 12.2 Oil Prices

**`ak.energy_oil_hist()`** — China gasoline/diesel historical price adjustments
- Returns: 调整日期, 汽油价格(元/吨), 柴油价格(元/吨), 汽油涨幅, 柴油涨幅

**`ak.energy_oil_detail(date)`** — Regional oil prices by grade
- Parameters: `date` — e.g. `"20240118"`
- Returns: 日期, 地区, V_0(0号柴油), V_89(89号汽油), V_92, V_95(价格元/升), 及各自涨跌幅

---

## 13. QDII Data

> All QDII functions from Jisilu require a valid `cookie` parameter (user session).

**`ak.qdii_e_index_jsl(cookie)`** — QDII Europe-America index funds
- Returns: 代码, 名称, 现价, 涨幅, 成交, 场内份额, T-2净值, T-1估值, T-1溢价率, 相关标的, 申购/赎回/托管费, 基金公司

**`ak.qdii_e_comm_jsl(cookie)`** — QDII Europe-America commodity funds
- Returns: Same structure as above

**`ak.qdii_a_index_jsl(cookie)`** — QDII Asia index funds
- Returns: Similar structure

---

## 14. Alternative Data 另类数据

### 14.1 Auto Sales

**`ak.car_market_total_cpca(symbol, indicator)`** — CPCA total auto market
- Returns: Monthly data with current/prior year comparison

**`ak.car_market_man_rank_cpca(symbol, indicator)`** — Manufacturer sales ranking
- Parameters: `indicator` — `"批发"` or `"零售"`
- Returns: 厂商名称, 当月销量, 同比/环比变化, 年累计

**`ak.car_sale_rank_gasgoo(symbol, date)`** — Gasgoo rankings
- Parameters: `symbol` — `"车企榜"` / `"品牌榜"` / `"车型榜"`, `date` — `"YYYYMM"`
- Returns: 排名, 名称, 当月销量, 同比/环比, 年累计

---

### 14.2 News

**`ak.news_cctv(date)`** — CCTV 新闻联播 broadcast text
- Parameters: `date` — `"YYYYMMDD"` (from 2016)
- Returns: date, title, content
- Note: Useful for NLP-based policy sentiment analysis

---

### 14.3 Box Office

**`ak.movie_boxoffice_realtime()`** — Real-time box office (refreshes every 5 min)
- Returns: 排名, 影片名称, 实时票房, 占比, 上映天数, 累计票房

**`ak.movie_boxoffice_daily(date)`** — Daily box office
- Returns: 排名, 影片名称, 当日票房, 环比, 累计票房, 票价, 上座率, 口碑评分, 上映天数

**`ak.movie_boxoffice_weekly(date)`** / **`ak.movie_boxoffice_monthly(date)`** / **`ak.movie_boxoffice_yearly(date)`**

**`ak.movie_boxoffice_cinema_daily(date)`** — Cinema-level daily data
- Returns: 排名, 影院名称, 当日票房, 场次, 场均上座率, 场均票价, 出勤率

---

### 14.4 Air Quality

**`ak.air_quality_rank(date="")`** — National city air quality rankings
- Parameters: `date` — `""` (real-time), `"YYYY-MM-DD"`, `"YYYY-MM"`, or `"YYYY"`
- Returns: 排名, 省份, 城市, AQI, 质量等级, PM2.5, PM10, NO2, SO2, O3, CO

**`ak.air_quality_hist(city, period, start_date, end_date)`** — Historical air quality
- Parameters: `period` — `"hour"` / `"day"` / `"month"`
- Returns: 时间, AQI, 各污染物浓度, 天气, 温度, 湿度

**`ak.air_quality_watch_point(city, start_date, end_date)`** — Station-level data
- Returns: 点位名称, AQI, PM2.5, PM10, NO2, SO2, O3, CO

---

### 14.5 Wealth Rankings

**`ak.hurun_rank(indicator, year)`** — Hurun rankings
- Parameters: `indicator` — 8 types including 胡润百富榜, 胡润全球富豪榜, 胡润独角兽
- Returns: 排名, 财富(亿元), 姓名, 企业, 行业

**`ak.xincaifu_rank(year)`** — 新财富富豪榜 (from 2003)
- Returns: 排名, 财富(亿元), 姓名, 公司, 行业, 总部, 性别, 年龄

**`ak.index_bloomberg_billionaires()`** — Bloomberg Billionaires Index real-time
- Returns: Rank, Name, Total Net Worth, Last Change, YTD Change, Country, Industry

---

### 14.6 Social Media & Sentiment

**`ak.stock_js_weibo_report(time_period)`** — Weibo stock sentiment
- Parameters: `time_period` — 2-hour to 1-month options
- Returns: 股票名称, 人气指数

**`ak.business_value_artist()`** / **`ak.online_value_artist()`** — Artist commercial/traffic value

---

## 15. High-Frequency Data 高频

**`ak.hf_sp_500(year)`** — S&P 500 minute-level data (2012–2018 only)
- Parameters: `year` — `"2012"` through `"2018"`
- Returns: date, open, high, low, close, price
- Note: Large dataset, external server, proxy recommended

---

## 16. NLP Tools

**`ak.nlp_ownthink(word, indicator)`** — Knowledge graph queries
- Parameters:
  - `word` (str) — entity name e.g. `"人工智能"`
  - `indicator` — `"entity"` / `"desc"` / `"avg"` / `"tag"`
- Returns: entity name (str), description (str), attribute DataFrame, or tag list

**`ak.nlp_answer(question)`** — Q&A chatbot
- Parameters: `question` (str) — e.g. `"姚明的身高"`
- Returns: Answer string

---

## Key Notes for Integration

### ETF Data Summary
For loading ETF OHLCV into a database, the best functions are:
- **Daily**: `ak.fund_etf_hist_em(symbol, period="daily", ...)` — supports qfq/hfq adjustment
- **Intraday**: `ak.fund_etf_hist_min_em(symbol, period="5", ...)` — 1/5/15/30/60 min available
- **Real-time snapshot**: `ak.fund_etf_spot_em()` — all ETFs including IOPV and capital flow
- **Holdings/composition**: `ak.fund_portfolio_hold_em(symbol, date)` — quarterly stock holdings
- **Index weights**: `ak.index_stock_cons_weight_csindex(symbol)` — for replication

### BaoStock vs AKShare for ETFs
| Feature | BaoStock | AKShare |
|---------|----------|---------|
| ETF daily OHLCV | ✓ | ✓ `fund_etf_hist_em` |
| ETF intraday (5-min) | ✗ | ✓ `fund_etf_hist_min_em` |
| ETF composition/holdings | ✗ | ✓ `fund_portfolio_hold_em` |
| ETF NAV | ✗ | ✓ `fund_etf_fund_info_em` |
| ETF real-time + IOPV | ✗ | ✓ `fund_etf_spot_em` |
| A-share 5-min (stocks) | ✓ from 2020 | ✓ `stock_zh_a_hist_min_em` |

### Installation
```bash
pip install akshare
```
