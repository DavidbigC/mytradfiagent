# Shanghai Stock Exchange (SSE) Data Sources

Official website: https://www.sse.com.cn/market/stockdata/statistic/

## Web Pages

| Page | URL | Description |
|------|-----|-------------|
| Stock Data Home | https://www.sse.com.cn/market/stockdata/statistic/ | Main entry, tabs for Overview / Main Board / STAR Market |
| Market Cap Ranking | https://www.sse.com.cn/market/stockdata/marketvalue/ | 市值排名 — top stocks by total market cap |
| Trading Overview | https://www.sse.com.cn/market/stockdata/overview/ | 成交概况 — daily/monthly/yearly trading summaries |
| Daily Overview | https://www.sse.com.cn/market/stockdata/overview/day/ | 每日成交概况 — per-day stats |
| Bond Data | https://www.sse.com.cn/market/bonddata/overview/day/ | 债券数据 |
| Fund Data | https://www.sse.com.cn/market/funddata/overview/day/ | 基金数据 |
| Margin Trading | https://www.sse.com.cn/market/othersdata/margin/sum/ | 融资融券 |
| Market Trends | https://www.sse.com.cn/market/price/trends/ | 行情信息 |
| SSE Index Series | https://www.sse.com.cn/market/sseindex/overview/ | 上证系列指数 |
| Stock List (Main) | https://www.sse.com.cn/assortment/stock/list/main/ | A-share main board listing |

Note: Most pages load data dynamically via JavaScript. The actual data comes from the APIs below.

---

## API Host 1: `query.sse.com.cn` (Structured Query)

Base URL: `https://query.sse.com.cn/commonQuery.do`
Required headers: `Referer: https://www.sse.com.cn`, `User-Agent: Mozilla/5.0`
Response format: JSONP — `cb({...})`, strip wrapper to get JSON.

### Endpoint: Daily Market Overview

**sqlId:** `COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C`

```
https://query.sse.com.cn/commonQuery.do?jsonCallBack=cb&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C&type=1&isPagination=true&pageHelp.pageSize=20&pageHelp.pageNo=1
```

Optional filter: `&PRODUCT_CODE=01` (A-shares only)

| Field | Description |
|-------|-------------|
| TRADE_DATE | Trading date (YYYYMMDD) |
| PRODUCT_CODE | Product type (see below) |
| LIST_NUM | Number of listed securities |
| TOTAL_VALUE | Total market value (亿元) |
| NEGO_VALUE | Negotiable market value (亿元) |
| TRADE_VOL | Trading volume (亿股) |
| TRADE_AMT | Trading amount (亿元) |
| TRADE_NUM | Number of trades (亿笔) |
| AVG_PE_RATE | Average P/E ratio |
| TOTAL_TO_RATE | Total turnover rate (%) |
| NEGO_TO_RATE | Negotiable turnover rate (%) |

**Product Codes:**

| Code | Type | Example Total Value |
|------|------|-------------------|
| 00 | All securities | 913,478亿 |
| 01 | Main board A-shares | 552,789亿 |
| 02 | B-shares | 930亿 |
| 03 | STAR Market (科创板) | 114,703亿 |
| 05 | Funds | 38,222亿 |
| 06 | Bonds | 35,315亿 |
| 07 | Asset-backed securities | 165,490亿 |
| 17 | All A-shares (main+STAR) | 668,423亿 |

### Endpoint: Stock List (Master Data)

**sqlId:** `COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L`

```
https://query.sse.com.cn/commonQuery.do?jsonCallBack=cb&sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L&isPagination=true&pageHelp.pageSize=20&pageHelp.pageNo=1
```

Optional filters: `&STOCK_TYPE=1` (A-shares), `&STATE_CODE=2` (active only, ~1,837 stocks)

| Field | Description |
|-------|-------------|
| A_STOCK_CODE | Stock code (e.g., "600000") |
| COMPANY_ABBR | Chinese abbreviated name |
| COMPANY_ABBR_EN | English abbreviated name |
| SEC_NAME_CN | Security display name |
| FULL_NAME | Full company name (Chinese) |
| FULL_NAME_IN_ENGLISH | Full company name (English) |
| STOCK_TYPE | "1" = A-share |
| STATE_CODE | "2" = active, "3" = delisted |
| LIST_DATE | Listing date (YYYYMMDD) |
| DELIST_DATE | Delist date ("-" if active) |
| AREA_NAME_DESC | Region (e.g., "上海市") |
| CSRC_CODE_DESC | CSRC industry (e.g., "金融业", "制造业") |
| B_STOCK_CODE | B-share code ("-" if none) |

Total: ~2,497 stocks (1,837 active A-shares)

---

## API Host 2: `yunhq.sse.com.cn:32041` (Real-Time Quotes)

Base URL: `http://yunhq.sse.com.cn:32041/v1/sh1/`
Required headers: `User-Agent: Mozilla/5.0`
Response format: JSONP — `cb({...})`
Note: HTTP only (not HTTPS). Port 32041.

### Endpoint: Equity List (All Stocks with Real-Time Quotes)

```
http://yunhq.sse.com.cn:32041/v1/sh1/list/exchange/equity?callback=cb&select=code,name,open,high,low,last,prev_close,change,chg_rate,volume,amount&order=amount&begin=0&end=20
```

| Select Field | Description |
|-------------|-------------|
| code | Stock code |
| name | Stock name |
| open | Open price |
| high | High price |
| low | Low price |
| last | Latest price |
| prev_close | Previous close |
| change | Price change |
| chg_rate | Change rate (%) |
| volume | Volume (shares) |
| amount | Turnover (CNY) |

**Sorting** (via `&order=` param):
- `amount` — by turnover (成交额), descending
- `volume` — by volume (成交量), descending
- `chg_rate` — by change rate (涨跌幅), top gainers first
- `last` — by price, highest first

**Pagination:** `&begin=0&end=20` (0-indexed)
**Total stocks:** ~2,348

Note: `pe`, `market_cap`, `float_market_cap`, `turnover` fields exist but return `null`.

### Endpoint: Fund List

```
http://yunhq.sse.com.cn:32041/v1/sh1/list/exchange/fund?callback=cb&select=code,name,last,change,chg_rate,volume,amount&begin=0&end=20
```

Total: ~945 funds. Same fields as equity list.

### Endpoint: Bond List

```
http://yunhq.sse.com.cn:32041/v1/sh1/list/exchange/bond?callback=cb&select=code,name,last,change,chg_rate,volume,amount&begin=0&end=20
```

Total: ~460 bonds.

### Endpoint: Single Stock Snapshot (Real-Time + Order Book)

```
http://yunhq.sse.com.cn:32041/v1/sh1/snap/{code}?callback=cb
```

With select: `&select=name,last,open,high,low,prev_close,change,chg_rate,volume,amount`

Full response (no select param) returns 15 fields:

| Index | Field | Example (600519 Moutai) |
|-------|-------|------------------------|
| 0 | name | 贵州茅台 |
| 1 | prev_close | 1486.60 |
| 2 | open | 1486.60 |
| 3 | high | 1507.80 |
| 4 | low | 1470.58 |
| 5 | last | 1485.30 |
| 6 | change | -1.30 |
| 7 | chg_rate | -0.09 |
| 8 | volume | 4,167,901 |
| 9 | amount | 6,216,379,203 |
| 10 | active_buy_vol | 39,251 |
| 11 | active_sell_vol | 2,442,899 |
| 12 | num_trades | 1,725,002 |
| 13 | bid (5 levels) | [price1, vol1, price2, vol2, ...] |
| 14 | ask (5 levels) | [price1, vol1, price2, vol2, ...] |

### Endpoint: Index Snapshot

```
http://yunhq.sse.com.cn:32041/v1/sh1/snap/000001?callback=cb&select=name,last,open,high,low,prev_close,change,chg_rate,volume,amount
```

Common indices: `000001` (上证指数), `000016` (上证50), `000300` (沪深300)

### Endpoint: Intraday Line (Minute-by-Minute)

```
http://yunhq.sse.com.cn:32041/v1/sh1/line/{code}?callback=cb&begin=0&end=241
```

Returns 241 data points per day (one per minute, 9:30-15:00).
Each point: `[price, avg_price, cumulative_volume]`

Also works for indices: `/v1/sh1/line/000001`

### Endpoint: Daily K-Line (OHLCV History)

```
http://yunhq.sse.com.cn:32041/v1/sh1/dayk/{code}?callback=cb&begin=-30&end=-1&select=date,open,high,low,close,volume
```

**Negative indexing:** `begin=-30&end=-1` = last 30 trading days.
Full history available (e.g., 5,864 daily bars for 600519 Moutai back to IPO).

Each record: `[date(YYYYMMDD), open, high, low, close, volume]`

Also works for indices: `/v1/sh1/dayk/000001` (8,585 bars for SSE Composite).

### Endpoint: 5-Minute K-Line

```
http://yunhq.sse.com.cn:32041/v1/sh1/mink/{code}?callback=cb&begin=-10&end=-1&select=date,open,high,low,close,volume
```

Date format: `YYYYMMDDHHmmSS`
Total data: ~12,000 bars (many days of 5-minute history).

### Not Working

- `/v1/sh1/weekk/{code}` — 503 error
- `/v1/sh1/monthk/{code}` — 503 error

---

## Summary: Best API for Each Use Case

| Use Case | Best API | Speed |
|----------|----------|-------|
| Market-wide daily stats (总市值, PE, turnover) | query.sse.com.cn `MRGK_C` | ~1s |
| Stock master list (codes, names, industry) | query.sse.com.cn `GP_L` | ~1s |
| Real-time stock screening (top by volume/amount/gainers) | yunhq equity list | ~1s |
| Single stock real-time quote + order book | yunhq snap | ~1s |
| Historical daily OHLCV (back to IPO) | yunhq dayk | ~1s |
| Intraday minute data | yunhq line | ~1s |
| 5-minute candles | yunhq mink | ~1s |
| Index real-time | yunhq snap (000001) | ~1s |
| Fund/Bond lists | yunhq fund/bond list | ~1s |
| Market cap ranking | **Not available on SSE API** — use EastMoney API instead |

Note: SSE's `yunhq` API does not return market cap or PE for individual stocks. For market cap rankings, use the EastMoney API (already implemented in `rank_cn_stocks` tool).
