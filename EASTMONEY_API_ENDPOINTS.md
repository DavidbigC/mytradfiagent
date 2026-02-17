# EastMoney API Endpoints Documentation

**Investigation Date:** 2026-02-17
**Test Stock:** 600173 (卧龙新能/卧龙电驱)
**Total Working Endpoints:** 14

## Overview

This document catalogs all verified working API endpoints from EastMoney's data platform for Chinese A-share stocks. The APIs fall into two main categories:

1. **datacenter-web.eastmoney.com** - Structured data API with consistent JSON format
2. **push2.eastmoney.com / push2his.eastmoney.com** - Real-time and historical market data

---

## API Categories

### 1. Market Data (Real-time & Historical)

All push2 APIs use the following base format:
- secid format: `{market}.{stock_code}` where market: 1=Shanghai, 0=Shenzhen
- Fields are numbered (f1, f2, etc.) - meanings need to be mapped

#### 1.1 Real-time Quote (实时行情)

**Endpoint:** `https://push2.eastmoney.com/api/qt/stock/get`

**Parameters:**
- `secid`: Stock ID (e.g., `1.600173`)
- `fields`: Comma-separated field codes

**Example:**
```
https://push2.eastmoney.com/api/qt/stock/get?secid=1.600173&fields=f57,f58,f169,f170,f46,f44,f51,f52,f50,f48,f167,f117,f60,f168,f43,f59,f162,f152,f164,f128,f116,f71
```

**Response Fields:**
- f43, f44, f46, f48, f50, f51, f52, f57, f58, f59, f60, f71, f116, f117, f128, f152, f162, f164, f167, f168, f169, f170

**Value:** HIGH - Essential for real-time monitoring

---

#### 1.2 Intraday Tick Data (分时数据)

**Endpoint:** `https://push2.eastmoney.com/api/qt/stock/trends2/get`

**Parameters:**
- `secid`: Stock ID
- `fields1`: Metadata fields
- `fields2`: Trend data fields

**Example:**
```
https://push2.eastmoney.com/api/qt/stock/trends2/get?secid=1.600173&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57,f58
```

**Response Structure:**
```json
{
  "data": {
    "code": "600173",
    "market": 1,
    "name": "卧龙新能",
    "trends": ["09:30,8.30,139109,...", ...],
    "trendsTotal": 256,
    "preClose": 8.47,
    ...
  }
}
```

**Value:** MEDIUM - Useful for intraday analysis

---

#### 1.3 K-line/OHLC Data (K线数据)

**Endpoint:** `https://push2his.eastmoney.com/api/qt/stock/kline/get`

**Parameters:**
- `secid`: Stock ID
- `klt`: K-line type (101=daily, 102=weekly, 103=monthly)
- `fqt`: Adjustment type (0=none, 1=forward, 2=backward)
- `lmt`: Limit number of records
- `end`: End date (YYYYMMDD)

**Example:**
```
https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600173&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20260217&lmt=120
```

**Response Structure:**
```json
{
  "data": {
    "code": "600173",
    "klines": [
      "2026-02-13,8.47,8.30,8.52,8.28,139109,116365233.00,2.83,-2.01,-0.17,1.99",
      ...
    ],
    "dktotal": 120
  }
}
```

**K-line Format:** `date,open,close,high,low,volume,amount,amplitude,pct_change,change,turnover`

**Value:** HIGH - Essential for technical analysis

---

#### 1.4 Main Force Capital Flow (主力资金流)

**Endpoint:** `https://push2.eastmoney.com/api/qt/stock/fflow/kline/get`

**Parameters:**
- `secid`: Stock ID
- `klt`: Period (101=daily)
- `lmt`: Limit (0=all available)

**Example:**
```
https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?lmt=0&klt=101&secid=1.600173&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65
```

**Response:**
```json
{
  "data": {
    "code": "600173",
    "klines": [
      "2026-02-13,-8186389.0,17106603.0,-8920214.0,-2322323.0,-5864066.0"
    ]
  }
}
```

**Value:** HIGH - Key indicator for institutional activity

---

#### 1.5 Stock Fund Flow Details (个股资金流向)

**Endpoint:** `https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get`

**Example:**
```
https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=0&klt=101&secid=1.600173&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63
```

**Value:** HIGH - Detailed capital flow analysis

---

### 2. Trading Intelligence (龙虎榜数据)

#### 2.1 Dragon Tiger List - Buy Side (龙虎榜买方)

**Endpoint:** `https://datacenter-web.eastmoney.com/api/data/v1/get`

**Parameters:**
- `reportName`: RPT_BILLBOARD_DAILYDETAILSBUY
- `columns`: ALL
- `filter`: (SECURITY_CODE="600173")
- `sortTypes`: -1 (descending)
- `sortColumns`: TRADE_DATE

**Example:**
```
https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BILLBOARD_DAILYDETAILSBUY&columns=ALL&filter=(SECURITY_CODE=%22600173%22)&pageNumber=1&pageSize=50&sortTypes=-1&sortColumns=TRADE_DATE
```

**Response Structure:**
```json
{
  "success": true,
  "result": {
    "count": 412,
    "data": [
      {
        "SECURITY_CODE": "600173",
        "TRADE_DATE": "2025-10-20 00:00:00",
        "OPERATEDEPT_NAME": "粤开证券股份有限公司河南分公司",
        "CLOSE_PRICE": 9.9,
        "ACCUM_AMOUNT": 878449577,
        "BUY": 12345678,
        "SELL": 1234567,
        "NET": 11111111,
        ...
      }
    ]
  }
}
```

**Key Fields:**
- TRADE_DATE: Trading date
- OPERATEDEPT_NAME: Broker/department name
- CLOSE_PRICE: Closing price
- ACCUM_AMOUNT: Total transaction amount
- BUY: Buy amount
- SELL: Sell amount
- NET: Net buy amount
- RISE_PROBABILITY_3DAY: 3-day rise probability after appearing on list

**Value:** HIGH - Tracks major institutional buying

---

#### 2.2 Dragon Tiger List - Sell Side (龙虎榜卖方)

**Report Name:** RPT_BILLBOARD_DAILYDETAILSSELL

**Same format as buy side, 409 records available**

**Value:** HIGH - Tracks major institutional selling

---

### 3. Financial Statements (财务报表)

All financial statements use the same API pattern with different report names.

**Common Parameters:**
- `filter`: (SECUCODE="600173.SH")
- `sortColumns`: REPORT_DATE
- Stock code format: `{code}.{exchange}` (e.g., 600173.SH)

#### 3.1 Balance Sheet (资产负债表)

**Report Name:** RPT_DMSK_FN_BALANCE

**Example:**
```
https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_BALANCE&columns=ALL&filter=(SECUCODE=%22600173.SH%22)&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=REPORT_DATE
```

**Records:** 104 (covers multiple years of quarterly/annual reports)

**Key Fields (57 total):**
- REPORT_DATE: Report period
- TOTAL_ASSETS: Total assets
- TOTAL_LIAB: Total liabilities
- TOTAL_EQUITY: Total equity
- MONETARYFUNDS: Cash and equivalents
- ACCOUNTS_RECE: Accounts receivable
- FIXED_ASSET: Fixed assets
- INTANGIBLE_ASSETS: Intangible assets
- GOODWILL: Goodwill
- And 48 more fields...

**Value:** HIGH - Core financial statement

---

#### 3.2 Income Statement (利润表)

**Report Name:** RPT_DMSK_FN_INCOME

**Records:** 104

**Key Fields (46 total):**
- REPORT_DATE: Report period
- PARENT_NETPROFIT: Net profit attributable to parent
- TOTAL_OPERATE_INCOME: Total operating income
- TOTAL_OPERATE_COST: Total operating cost
- OPERATE_COST: Operating cost
- OPERATE_EXPENSE: Operating expenses
- SALES_FEE: Sales expenses
- MANAGE_FEE: Management expenses
- FINANCE_FEE: Finance expenses
- RESEARCH_FEE: R&D expenses
- And 36 more fields...

**Value:** HIGH - Core financial statement

---

#### 3.3 Cash Flow Statement (现金流量表)

**Report Name:** RPT_DMSK_FN_CASHFLOW

**Records:** 99

**Key Fields (48 total):**
- REPORT_DATE: Report period
- NETCASH_OPERATE: Net cash from operating activities
- NETCASH_INVEST: Net cash from investing activities
- NETCASH_FINANCE: Net cash from financing activities
- SALES_SERVICES: Cash from sales/services
- PAY_STAFF_CASH: Cash paid to employees
- And 43 more fields...

**Value:** HIGH - Core financial statement

---

### 4. Shareholding Data (股东数据)

#### 4.1 Top 10 Circulating Shareholders (十大流通股东)

**Report Name:** RPT_F10_EH_FREEHOLDERS

**Example:**
```
https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_FREEHOLDERS&columns=ALL&filter=(SECUCODE=%22600173.SH%22)&pageNumber=1&pageSize=50&sortTypes=-1&sortColumns=END_DATE
```

**Records:** 920 (top 10 per reporting period across multiple years)

**Key Fields (40 total):**
- END_DATE: Report date
- HOLDER_NAME: Shareholder name
- HOLD_NUM: Number of shares held
- FREE_HOLDNUM_RATIO: % of circulating shares
- HOLD_NUM_CHANGE: Change description (新进/增持/减持/不变)
- CHANGE_RATIO: Change ratio
- HOLDER_RANK: Rank (1-10)
- IS_HOLDORG: Is institutional holder
- HOLDER_TYPE: Holder type code

**Value:** HIGH - Track institutional ownership changes

---

#### 4.2 Top 10 Total Shareholders (十大股东)

**Report Name:** RPT_F10_EH_HOLDERS

**Records:** 909

**Key Fields (26 total):**
- END_DATE: Report date
- HOLDER_NAME: Shareholder name
- HOLD_NUM: Number of shares
- HOLD_NUM_RATIO: % of total shares
- HOLD_NUM_CHANGE: Change description
- HOLDER_RANK: Rank
- IS_HOLDORG: Is institutional

**Difference from 4.1:** Includes restricted/non-circulating shares

**Value:** MEDIUM - Total ownership including restricted shares

---

### 5. Corporate Actions (公司行为)

#### 5.1 Dividends & Share Bonus (分红送配)

**Report Name:** RPT_SHAREBONUS_DET

**Example:**
```
https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHAREBONUS_DET&columns=ALL&filter=(SECURITY_CODE=%22600173%22)&pageNumber=1&pageSize=50&sortTypes=-1&sortColumns=REPORT_DATE
```

**Records:** 18 (historical dividend distributions)

**Key Fields (30 total):**
- REPORT_DATE: Report period
- PRETAX_BONUS_RMB: Cash dividend per 10 shares (pre-tax)
- BONUS_RATIO: Bonus shares per 10 shares
- IT_RATIO: Conversion shares per 10 shares
- EX_DIVIDEND_DATE: Ex-dividend date
- EQUITY_RECORD_DATE: Record date
- PLAN_NOTICE_DATE: Announcement date
- ASSIGN_PROGRESS: Distribution progress
- BASIC_EPS: Basic EPS for the period

**Value:** MEDIUM - Dividend history for valuation

---

### 6. Company Information (公司信息)

#### 6.1 Core Themes/Concepts (核心题材)

**Report Name:** RPT_F10_CORETHEME_CONTENT

**Example:**
```
https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_CORETHEME_CONTENT&columns=ALL&filter=(SECUCODE=%22600173.SH%22)
```

**Records:** 7

**Key Fields (13 total):**
- KEYWORD: Theme keyword
- MAINPOINT: Main point title
- MAINPOINT_CONTENT: Detailed content
- KEY_CLASSIF: Classification name
- KEY_CLASSIF_CODE: Classification code

**Value:** MEDIUM - Thematic/sector classification

---

## API Usage Guidelines

### Standard Headers

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://data.eastmoney.com/'
}
```

### Python Example

```python
import urllib.request
import json

# Example: Get balance sheet data
stock_code = "600173"
secucode = "600173.SH"

url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_BALANCE&columns=ALL&filter=(SECUCODE=%22{secucode}%22)&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=REPORT_DATE"

headers = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://data.eastmoney.com/'
}

req = urllib.request.Request(url, headers=headers)
response = urllib.request.urlopen(req)
data = json.loads(response.read().decode('utf-8'))

if data.get('success'):
    records = data['result']['data']
    print(f"Retrieved {len(records)} records")
```

### Stock Code Format

- **datacenter-web API:** Use SECUCODE format: `{code}.{exchange}`
  - Shanghai: `600173.SH`
  - Shenzhen: `000001.SZ`
  - ChiNext: `300001.SZ`

- **push2 API:** Use secid format: `{market}.{code}`
  - Shanghai: `1.600173`
  - Shenzhen: `0.000001`
  - ChiNext: `0.300001`

---

## Missing/Unavailable Endpoints

The following data types were investigated but no working API endpoints were found:

1. **公告 (Announcements)** - Corporate announcements/filings
2. **个股日历 (Stock Calendar)** - Upcoming events calendar
3. **千股千评 (Stock Ratings/Comments)** - Daily stock commentary
4. **股东户数 (Shareholder Count)** - Number of shareholders over time
5. **融资融券 (Margin Trading)** - Margin financing and securities lending data
6. **大宗交易 (Block Trades)** - Large block transaction records
7. **限售解禁 (Lock-up Expiry)** - Restricted share unlock schedule
8. **股东增减持 (Shareholder Changes)** - Major shareholder buying/selling
9. **高管持股 (Executive Holdings)** - Executive shareholding
10. **股东大会 (Shareholder Meetings)** - General meeting records
11. **机构调研 (Institutional Research)** - Institutional research visits
12. **研报 (Research Reports)** - Analyst research reports
13. **机构评级 (Institutional Ratings)** - Analyst ratings/recommendations
14. **股本结构 (Share Structure)** - Detailed share capital structure

These may require:
- Different API endpoints not yet discovered
- Authentication/login
- Different URL patterns
- May only be available through web scraping

---

## Recommended Priority for Agent Tools

### Tier 1 (HIGH Value - Implement First)

1. **Real-time Quote** - Essential market data
2. **K-line Data** - Historical OHLC for analysis
3. **Balance Sheet** - Core financials
4. **Income Statement** - Core financials
5. **Cash Flow Statement** - Core financials
6. **Top 10 Circulating Shareholders** - Track ownership
7. **Main Force Capital Flow** - Institutional activity
8. **Dragon Tiger List (Buy/Sell)** - Major transactions

### Tier 2 (MEDIUM Value - Implement Later)

9. **Intraday Tick Data** - For detailed analysis
10. **Stock Fund Flow Details** - Detailed capital flows
11. **Top 10 Total Shareholders** - Complete ownership picture
12. **Dividends** - For valuation
13. **Core Themes** - Sector classification

---

## Notes

- All datacenter-web APIs return paginated results (pageNumber, pageSize)
- Historical data typically goes back 10+ years for financial statements
- Dragon Tiger List only contains records for days when stock appeared on the list
- Shareholder data is updated quarterly
- Financial statements have both quarterly and annual versions (check DATE_TYPE_CODE field)
- Some fields may be null/None for certain periods or stock types

---

**Last Updated:** 2026-02-17
**Status:** Production Ready
**Test Coverage:** All endpoints verified with stock 600173
