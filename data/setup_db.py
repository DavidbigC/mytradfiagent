#!/usr/bin/env python3
"""One-time setup: creates the marketdata database, ohlcv_5m and financials tables."""
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("MARKETDATA_URL") or os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")


def get_conn_params(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    dbname = p.path.lstrip("/") if p.path and p.path != "/" else "postgres"
    if dbname in ("myaiagent", ""):
        dbname = "postgres"
    return dict(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=p.username or os.getenv("USER", "postgres"),
        password=p.password or "",
        dbname=dbname,
    )


params = get_conn_params(DB_URL)
params["dbname"] = "postgres"

# ── Step 1: Create marketdata database ───────────────────────────────────────
conn = psycopg2.connect(**params)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = 'marketdata'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE marketdata")
    print("Created database: marketdata")
else:
    print("Database marketdata already exists")
cur.close()
conn.close()

params["dbname"] = "marketdata"
conn = psycopg2.connect(**params)
cur = conn.cursor()

# ── Step 2: ohlcv_5m (price, yearly partitions 2020–2026) ────────────────────
cur.execute("DROP TABLE IF EXISTS ohlcv_1h CASCADE")

cur.execute("""
CREATE TABLE IF NOT EXISTS ohlcv_5m (
    ts          TIMESTAMPTZ  NOT NULL,
    code        CHAR(6)      NOT NULL,
    exchange    CHAR(2)      NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      BIGINT,
    amount      DOUBLE PRECISION
) PARTITION BY RANGE (ts)
""")
for year in range(2020, 2027):
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS ohlcv_5m_{year}
        PARTITION OF ohlcv_5m
        FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
    """)
cur.execute("CREATE INDEX IF NOT EXISTS ohlcv_5m_code_ts ON ohlcv_5m (code, ts DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS ohlcv_5m_ts_brin ON ohlcv_5m USING BRIN (ts)")
cur.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ohlcv_5m_unique') THEN
            ALTER TABLE ohlcv_5m ADD CONSTRAINT ohlcv_5m_unique UNIQUE (ts, code, exchange);
        END IF;
    END$$
""")
conn.commit()
print("ohlcv_5m: partitioned table + indexes ready")

# ── Step 3: financials (all 6 categories in one table, quarterly) ─────────────
# See data/financials_columns.md for full column documentation.
# pub_date  = filing/publication date — USE THIS for backtesting (no look-ahead bias)
# stat_date = period end date (Mar/Jun/Sep/Dec 31)
# UNIQUE on (code, stat_date) — one row per stock per quarter

cur.execute("""
CREATE TABLE IF NOT EXISTS financials (
    code        CHAR(6)  NOT NULL,
    exchange    CHAR(2)  NOT NULL,
    pub_date    DATE,
    stat_date   DATE     NOT NULL,

    -- Profitability (fin_profit)
    roe_avg          DOUBLE PRECISION,  -- Return on equity (avg)
    np_margin        DOUBLE PRECISION,  -- Net profit margin
    gp_margin        DOUBLE PRECISION,  -- Gross profit margin
    net_profit       DOUBLE PRECISION,  -- Net profit (yuan)
    eps_ttm          DOUBLE PRECISION,  -- EPS (trailing twelve months)
    mb_revenue       DOUBLE PRECISION,  -- Main business revenue
    total_share      DOUBLE PRECISION,  -- Total shares outstanding
    liqa_share       DOUBLE PRECISION,  -- Liquid (tradable) shares

    -- Operational efficiency (query_operation_data)
    nr_turn_ratio    DOUBLE PRECISION,  -- Accounts receivable turnover ratio
    nr_turn_days     DOUBLE PRECISION,  -- Accounts receivable turnover days
    inv_turn_ratio   DOUBLE PRECISION,  -- Inventory turnover ratio
    inv_turn_days    DOUBLE PRECISION,  -- Inventory turnover days
    ca_turn_ratio    DOUBLE PRECISION,  -- Current assets turnover ratio
    asset_turn_ratio DOUBLE PRECISION,  -- Total asset turnover ratio

    -- Growth (query_growth_data)
    yoy_equity       DOUBLE PRECISION,  -- YoY growth: shareholders equity
    yoy_asset        DOUBLE PRECISION,  -- YoY growth: total assets
    yoy_ni           DOUBLE PRECISION,  -- YoY growth: net income
    yoy_eps_basic    DOUBLE PRECISION,  -- YoY growth: basic EPS
    yoy_pni          DOUBLE PRECISION,  -- YoY growth: parent net income

    -- Solvency / balance sheet (query_balance_data)
    current_ratio      DOUBLE PRECISION,  -- Current ratio
    quick_ratio        DOUBLE PRECISION,  -- Quick ratio
    cash_ratio         DOUBLE PRECISION,  -- Cash ratio
    yoy_liability      DOUBLE PRECISION,  -- YoY growth: total liabilities
    liability_to_asset DOUBLE PRECISION,  -- Liability-to-asset ratio
    asset_to_equity    DOUBLE PRECISION,  -- Asset-to-equity ratio (leverage)

    -- Cash flow (query_cash_flow_data)
    ca_to_asset              DOUBLE PRECISION,  -- Current assets / total assets
    nca_to_asset             DOUBLE PRECISION,  -- Non-current assets / total assets
    tangible_asset_to_asset  DOUBLE PRECISION,  -- Tangible assets / total assets
    ebit_to_interest         DOUBLE PRECISION,  -- Interest coverage (EBIT / interest)
    cfo_to_or                DOUBLE PRECISION,  -- Operating cash flow / revenue
    cfo_to_np                DOUBLE PRECISION,  -- Operating cash flow / net profit
    cfo_to_gr                DOUBLE PRECISION,  -- Operating cash flow / gross revenue

    -- DuPont decomposition (query_dupont_data)
    dupont_roe               DOUBLE PRECISION,  -- ROE (DuPont)
    dupont_asset_sto_equity  DOUBLE PRECISION,  -- Assets / equity (leverage factor)
    dupont_asset_turn        DOUBLE PRECISION,  -- Asset turnover
    dupont_pnitoni           DOUBLE PRECISION,  -- Parent NI / NI
    dupont_nitogr            DOUBLE PRECISION,  -- Net income / gross revenue (net margin)
    dupont_tax_burden        DOUBLE PRECISION,  -- Net income / pre-tax income (tax retention)
    dupont_int_burden        DOUBLE PRECISION,  -- Pre-tax income / EBIT (interest burden)
    dupont_ebit_togr         DOUBLE PRECISION,  -- EBIT / gross revenue (operating margin)

    UNIQUE (code, stat_date)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS financials_code_stat ON financials (code, stat_date DESC)")
conn.commit()
print("financials: unified table + index ready")

# ── Step 4: Fund tables ───────────────────────────────────────────────────────
cur.execute("""
CREATE TABLE IF NOT EXISTS funds (
    code            TEXT PRIMARY KEY,
    name            TEXT,
    full_name       TEXT,
    type            TEXT,
    exchange        TEXT,
    inception_date  DATE,
    tracking_index  TEXT,
    mgmt_company    TEXT,
    custodian       TEXT,
    updated_at      TIMESTAMPTZ DEFAULT now()
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS fund_managers (
    fund_code     TEXT REFERENCES funds(code),
    manager_name  TEXT,
    start_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date      DATE,
    PRIMARY KEY (fund_code, manager_name, start_date)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS fund_managers_code ON fund_managers (fund_code)")

cur.execute("""
CREATE TABLE IF NOT EXISTS fund_fees (
    id                SERIAL PRIMARY KEY,
    fund_code         TEXT REFERENCES funds(code),
    mgmt_rate         NUMERIC(8,4),
    custody_rate      NUMERIC(8,4),
    sales_svc_rate    NUMERIC(8,4),
    subscription_rate NUMERIC(8,4),
    effective_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date          DATE,
    UNIQUE (fund_code, effective_date)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS fund_nav (
    fund_code        TEXT,
    date             DATE,
    unit_nav         NUMERIC(12,4),
    accum_nav        NUMERIC(12,4),
    daily_return_pct NUMERIC(8,4),
    PRIMARY KEY (fund_code, date)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS fund_nav_code_date ON fund_nav (fund_code, date DESC)")

cur.execute("""
CREATE TABLE IF NOT EXISTS fund_price (
    fund_code            TEXT,
    date                 DATE,
    open                 NUMERIC(12,4),
    high                 NUMERIC(12,4),
    low                  NUMERIC(12,4),
    close                NUMERIC(12,4),
    volume               BIGINT,
    amount               NUMERIC(20,2),
    turnover_rate        NUMERIC(8,4),
    premium_discount_pct NUMERIC(8,4),
    PRIMARY KEY (fund_code, date)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS fund_price_code_date ON fund_price (fund_code, date DESC)")

cur.execute("""
CREATE TABLE IF NOT EXISTS fund_holdings (
    fund_code     TEXT,
    quarter       TEXT,
    holding_type  TEXT,
    security_code TEXT,
    security_name TEXT,
    pct_of_nav    NUMERIC(8,4),
    shares        BIGINT,
    market_value  NUMERIC(20,2),
    PRIMARY KEY (fund_code, quarter, holding_type, security_code)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS fund_holdings_code_q ON fund_holdings (fund_code, quarter)")

conn.commit()
print("fund tables: funds, fund_managers, fund_fees, fund_nav, fund_price, fund_holdings ready")

cur.close()
conn.close()
print("Setup complete.")
