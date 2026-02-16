from __future__ import annotations
import asyncio
import json
import logging
from uuid import UUID

from db import get_pool

logger = logging.getLogger(__name__)

# Per-user asyncio locks to prevent concurrent agent runs
_user_locks: dict[UUID, asyncio.Lock] = {}


def get_user_lock(user_id: UUID) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


async def get_or_create_user(platform: str, platform_uid: str) -> UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Try to find existing platform account
        row = await conn.fetchrow(
            "SELECT user_id FROM platform_accounts WHERE platform = $1 AND platform_uid = $2",
            platform, platform_uid,
        )
        if row:
            await conn.execute(
                "UPDATE users SET last_active_at = now() WHERE id = $1",
                row["user_id"],
            )
            return row["user_id"]

        # Create new user + platform account
        user_id = await conn.fetchval(
            "INSERT INTO users (display_name) VALUES ($1) RETURNING id",
            platform_uid,
        )
        await conn.execute(
            "INSERT INTO platform_accounts (user_id, platform, platform_uid) VALUES ($1, $2, $3)",
            user_id, platform, platform_uid,
        )
        logger.info(f"Created user {user_id} for {platform}:{platform_uid}")
        return user_id


async def get_active_conversation(user_id: UUID) -> UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Get most recent conversation
        conv_id = await conn.fetchval(
            "SELECT id FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
            user_id,
        )
        if conv_id:
            return conv_id
        return await _create_conversation(conn, user_id)


async def new_conversation(user_id: UUID) -> UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _create_conversation(conn, user_id)


async def _create_conversation(conn, user_id: UUID) -> UUID:
    conv_id = await conn.fetchval(
        "INSERT INTO conversations (user_id) VALUES ($1) RETURNING id",
        user_id,
    )
    logger.info(f"Created conversation {conv_id} for user {user_id}")
    return conv_id


async def save_message(
    conversation_id: UUID,
    role: str,
    content: str | None,
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        tc_json = json.dumps(tool_calls) if tool_calls else None
        await conn.execute(
            """INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id)
               VALUES ($1, $2, $3, $4::jsonb, $5)""",
            conversation_id, role, content or "", tc_json, tool_call_id,
        )
        await conn.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = $1",
            conversation_id,
        )


async def load_recent_messages(conversation_id: UUID, limit: int = 20) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT role, content, tool_calls, tool_call_id
               FROM messages
               WHERE conversation_id = $1
               ORDER BY id DESC
               LIMIT $2""",
            conversation_id, limit,
        )

    # Reverse to chronological order
    messages = []
    for row in reversed(rows):
        msg: dict = {"role": row["role"], "content": row["content"] or ""}
        if row["tool_calls"]:
            msg["tool_calls"] = json.loads(row["tool_calls"])
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        messages.append(msg)

    # Trim orphaned tool results from the front.
    # If our window starts mid-sequence (e.g. tool results without the
    # preceding assistant tool_call message), the API will reject it.
    # Skip until we hit a 'user' or plain 'assistant' (no tool_call_id) message.
    while messages and (
        messages[0].get("role") == "tool"
        or (messages[0].get("role") == "assistant" and messages[0].get("tool_calls"))
    ):
        messages.pop(0)

    return messages
