#!/usr/bin/env python3
"""One-time setup: creates the marketdata database and ohlcv_1h table."""
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost/myaiagent")


def get_conn_params(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    return dict(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=p.username or "postgres",
        password=p.password or "",
        dbname="postgres",
    )


params = get_conn_params(DB_URL)

# Step 1: Create marketdata database
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

# Step 2: Connect to marketdata and create schema
params["dbname"] = "marketdata"
conn = psycopg2.connect(**params)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS ohlcv_1h (
    ts          TIMESTAMPTZ     NOT NULL,
    code        CHAR(6)         NOT NULL,
    exchange    CHAR(2)         NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      BIGINT,
    amount      DOUBLE PRECISION,
    UNIQUE (ts, code, exchange)
)
""")
conn.commit()
print("Table ohlcv_1h ready")

# BRIN index on ts — compact, ideal for append-only time-ordered data
cur.execute("CREATE INDEX IF NOT EXISTS ohlcv_1h_ts_brin ON ohlcv_1h USING BRIN (ts)")
# Btree index for per-stock range queries
cur.execute("CREATE INDEX IF NOT EXISTS ohlcv_1h_code_ts ON ohlcv_1h (code, ts DESC)")
conn.commit()
print("Indexes created")

cur.close()
conn.close()
print("Setup complete.")
