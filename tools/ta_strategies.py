"""TA strategy knowledge base — lookup, save, update."""
import json
import logging
from db import get_pool

logger = logging.getLogger(__name__)

LOOKUP_TA_STRATEGY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lookup_ta_strategy",
        "description": (
            "Look up a known technical analysis strategy by name. "
            "ALWAYS call this FIRST before using web_search when the user asks for a TA strategy. "
            "Returns the strategy description, indicators to use, and default parameters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Strategy name or alias (e.g. 'MACD crossover', 'volume price trend', 'RSI divergence')",
                },
            },
            "required": ["query"],
        },
    },
}

SAVE_TA_STRATEGY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_ta_strategy",
        "description": (
            "Save a newly learned technical analysis strategy to the knowledge base. "
            "Call this after web_search reveals a strategy definition, so it can be used directly next time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Canonical strategy name, e.g. 'volume price trend'"},
                "description": {"type": "string", "description": "What the strategy is and how it works"},
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pandas-ta indicator names used (e.g. ['VPT', 'EMA'])",
                },
                "aliases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alternative names or abbreviations",
                },
                "parameters": {
                    "type": "object",
                    "description": "Default parameters for the indicators (e.g. {period: 14})",
                },
                "source_url": {"type": "string", "description": "URL where this strategy was learned"},
            },
            "required": ["name", "description", "indicators"],
        },
    },
}

UPDATE_TA_STRATEGY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_ta_strategy",
        "description": (
            "Update an existing TA strategy in the knowledge base. "
            "Use when the user requests changes to a strategy (e.g. 'also include ATR'). "
            "Only the fields provided in updates are changed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact name of the strategy to update"},
                "updates": {
                    "type": "object",
                    "description": "Fields to update: description, indicators, aliases, parameters, source_url",
                },
            },
            "required": ["name", "updates"],
        },
    },
}


def _row_to_dict(row) -> dict:
    return {
        "name": row["name"],
        "aliases": list(row["aliases"] or []),
        "description": row["description"],
        "indicators": list(row["indicators"] or []),
        "parameters": dict(row["parameters"] or {}),
        "source_url": row["source_url"],
    }


async def lookup_ta_strategy(query: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT name, aliases, description, indicators, parameters, source_url
            FROM ta_strategies
            WHERE to_tsvector('simple', name) @@ plainto_tsquery('simple', $1)
               OR $1 = ANY(aliases)
               OR LOWER(name) = LOWER($1)
            ORDER BY ts_rank(to_tsvector('simple', name), plainto_tsquery('simple', $1)) DESC
            LIMIT 1
            """,
            query,
        )
    if row is None:
        return {
            "found": False,
            "suggestion": "Strategy not found. Use web_search to learn about it, then call save_ta_strategy.",
        }
    return {"found": True, **_row_to_dict(row)}


async def save_ta_strategy(
    name: str,
    description: str,
    indicators: list[str],
    aliases: list[str] | None = None,
    parameters: dict | None = None,
    source_url: str | None = None,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ta_strategies (name, aliases, description, indicators, parameters, source_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (name) DO UPDATE SET
                aliases     = EXCLUDED.aliases,
                description = EXCLUDED.description,
                indicators  = EXCLUDED.indicators,
                parameters  = EXCLUDED.parameters,
                source_url  = EXCLUDED.source_url,
                updated_at  = NOW()
            """,
            name,
            aliases or [],
            description,
            indicators,
            json.dumps(parameters or {}),
            source_url,
        )
    logger.info(f"Saved TA strategy: {name}")
    return {"status": "saved", "name": name}


async def update_ta_strategy(name: str, updates: dict) -> dict:
    allowed = {"description", "indicators", "aliases", "parameters", "source_url"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return {"status": "no_valid_fields", "allowed": list(allowed)}

    set_clauses = []
    params: list = []
    for i, (col, val) in enumerate(fields.items(), start=1):
        if col == "parameters":
            val = json.dumps(val)
        set_clauses.append(f"{col} = ${i}")
        params.append(val)
    set_clauses.append("updated_at = NOW()")
    params.append(name)

    sql = f"UPDATE ta_strategies SET {', '.join(set_clauses)} WHERE LOWER(name) = LOWER(${len(params)})"

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(sql, *params)

    updated = int(result.split()[-1]) if result else 0
    if updated == 0:
        return {"status": "not_found", "name": name}
    logger.info(f"Updated TA strategy: {name} — fields: {list(fields)}")
    return {"status": "updated", "name": name, "updated_fields": list(fields)}
