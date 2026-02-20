import logging
import asyncpg
from config import DATABASE_URL

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_accounts (
    id              SERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    platform        TEXT NOT NULL,
    platform_uid    TEXT NOT NULL,
    linked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform, platform_uid)
);

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,
    content         TEXT,
    tool_calls      JSONB,
    tool_call_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_platform_accounts_lookup ON platform_accounts(platform, platform_uid);

-- Column for storing summarized conversation history (added 2026-02-18)
ALTER TABLE IF EXISTS conversations ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE IF EXISTS conversations ADD COLUMN IF NOT EXISTS summary_up_to INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS web_accounts (
    id              SERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS files (
    id              SERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    filepath        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_type       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_conversation ON files(conversation_id);
CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);
CREATE INDEX IF NOT EXISTS idx_files_filepath ON files(filepath);
-- Report distillation cache (added 2026-02-20)
CREATE TABLE IF NOT EXISTS report_cache (
    id          SERIAL PRIMARY KEY,
    stock_code  CHAR(6)      NOT NULL,
    report_type VARCHAR(10)  NOT NULL,
    report_year SMALLINT     NOT NULL,
    report_date VARCHAR(12),
    title       TEXT,
    filepath    TEXT         NOT NULL,
    source_url  TEXT,
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (stock_code, report_type, report_year)
);
CREATE INDEX IF NOT EXISTS idx_report_cache_lookup
    ON report_cache(stock_code, report_type, report_year);

"""


async def init_db():
    global pool
    if pool is not None:
        return  # already initialized
    logger.info("Connecting to database...")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database initialized.")


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return pool
