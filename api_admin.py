"""Admin API — database inspection for admin user only."""

from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from db import get_pool
from auth import get_current_user
from config import ADMIN_USERNAME

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(user: dict):
    if user["username"] != ADMIN_USERNAME:
        raise HTTPException(403, "Admin only")


@router.get("/tables")
async def list_tables(user: dict = Depends(get_current_user)):
    _require_admin(user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'public' ORDER BY table_name"""
        )
    return [r["table_name"] for r in rows]


@router.get("/tables/{table_name}")
async def table_info(table_name: str, user: dict = Depends(get_current_user)):
    """Get column info and row count for a table."""
    _require_admin(user)
    # Validate table name to prevent injection
    if not table_name.isidentifier():
        raise HTTPException(400, "Invalid table name")
    pool = await get_pool()
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = $1
               ORDER BY ordinal_position""",
            table_name,
        )
        if not cols:
            raise HTTPException(404, "Table not found")
        count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
    return {
        "table": table_name,
        "row_count": count,
        "columns": [
            {"name": c["column_name"], "type": c["data_type"], "nullable": c["is_nullable"] == "YES"}
            for c in cols
        ],
    }


@router.get("/tables/{table_name}/rows")
async def table_rows(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Browse rows of a table with pagination."""
    _require_admin(user)
    if not table_name.isidentifier():
        raise HTTPException(400, "Invalid table name")
    if limit > 200:
        limit = 200
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Verify table exists
        exists = await conn.fetchval(
            """SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = $1""",
            table_name,
        )
        if not exists:
            raise HTTPException(404, "Table not found")
        rows = await conn.fetch(
            f'SELECT * FROM "{table_name}" ORDER BY 1 DESC LIMIT $1 OFFSET $2',
            limit, offset,
        )
    return [dict(r) for r in rows]


class QueryBody(BaseModel):
    sql: str


@router.post("/query")
async def run_query(body: QueryBody, user: dict = Depends(get_current_user)):
    """Run a read-only SQL query. Only SELECT/WITH/EXPLAIN allowed."""
    _require_admin(user)
    sql = body.sql.strip().rstrip(";")
    if not sql:
        raise HTTPException(400, "Empty query")

    # Only allow read-only statements
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        raise HTTPException(400, "Only SELECT, WITH, and EXPLAIN queries are allowed")

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            # Use a read-only transaction for safety
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(sql)
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": [dict(r) for r in rows],
            "count": len(rows),
        }
    except Exception as e:
        raise HTTPException(400, str(e))
