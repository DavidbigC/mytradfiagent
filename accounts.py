from __future__ import annotations
import asyncio
import json
import logging
import time
from uuid import UUID

from db import get_pool

logger = logging.getLogger(__name__)

# Per-user asyncio locks to prevent concurrent agent runs.
# Each entry stores (lock, last_used_timestamp) for TTL-based cleanup.
_user_locks: dict[UUID, tuple[asyncio.Lock, float]] = {}
_LOCK_TTL = 3600  # Clean up locks unused for 1 hour
_LOCK_CLEANUP_INTERVAL = 300  # Run cleanup at most every 5 minutes
_last_lock_cleanup = 0.0


def _cleanup_stale_locks():
    """Remove locks that haven't been used in _LOCK_TTL seconds."""
    global _last_lock_cleanup
    now = time.time()
    if now - _last_lock_cleanup < _LOCK_CLEANUP_INTERVAL:
        return
    _last_lock_cleanup = now
    stale = [uid for uid, (lock, ts) in _user_locks.items()
             if now - ts > _LOCK_TTL and not lock.locked()]
    for uid in stale:
        del _user_locks[uid]
    if stale:
        logger.debug(f"Cleaned up {len(stale)} stale user locks")


def get_user_lock(user_id: UUID) -> asyncio.Lock:
    _cleanup_stale_locks()
    entry = _user_locks.get(user_id)
    if entry:
        _user_locks[user_id] = (entry[0], time.time())
        return entry[0]
    lock = asyncio.Lock()
    _user_locks[user_id] = (lock, time.time())
    return lock



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


def _repair_tool_call_sequence(messages: list[dict]) -> list[dict]:
    """Remove incomplete or orphaned tool-call sequences from a message list.

    Two failure modes that cause MiniMax error 2013:
    1. role:tool message with no preceding role:assistant that has tool_calls
       (e.g. window starts mid-sequence, or the assistant row was trimmed away)
    2. role:assistant with tool_calls but no following role:tool results
       (e.g. agent was stopped after saving the assistant row but before results)

    Both are dropped with a warning. Better to lose context than to crash.
    """
    result: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Collect the expected tool-call IDs from this assistant message.
            tool_calls = msg["tool_calls"]
            expected_ids: set[str] = {
                tc["id"]
                for tc in tool_calls
                if isinstance(tc, dict) and tc.get("id")
            }

            # Look ahead: collect consecutive role:tool messages that follow.
            j = i + 1
            following_tools: list[dict] = []
            while j < len(messages) and messages[j].get("role") == "tool":
                following_tools.append(messages[j])
                j += 1

            found_ids: set[str] = {
                m.get("tool_call_id", "")
                for m in following_tools
                if m.get("tool_call_id")
            }

            if expected_ids and expected_ids != found_ids:
                # Incomplete sequence — drop assistant row + any partial results.
                logger.warning(
                    f"Dropping incomplete tool-call sequence "
                    f"(expected {expected_ids}, found {found_ids})"
                )
                i = j  # skip past the assistant row and any partial tool rows
            else:
                # Complete (or no IDs to match) — keep everything.
                result.append(msg)
                result.extend(following_tools)
                i = j

        elif msg.get("role") == "tool":
            # Orphaned tool result — no preceding assistant-with-tool-calls.
            logger.warning(
                f"Dropping orphaned tool result (tool_call_id={msg.get('tool_call_id')})"
            )
            i += 1

        else:
            result.append(msg)
            i += 1

    return result


async def load_recent_messages(conversation_id: UUID, limit: int = 60) -> list[dict]:
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

    return _repair_tool_call_sequence(messages)


async def get_conversation_summary(conversation_id: UUID) -> str | None:
    """Get the stored conversation summary, if any."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT summary, summary_up_to FROM conversations WHERE id = $1",
            conversation_id,
        )
    if row and row["summary"]:
        return row["summary"]
    return None


async def save_conversation_summary(conversation_id: UUID, summary: str, up_to_message_id: int):
    """Persist a conversation summary, marking which message ID it covers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET summary = $1, summary_up_to = $2 WHERE id = $3",
            summary, up_to_message_id, conversation_id,
        )


async def save_file_record(
    user_id: UUID,
    conversation_id: UUID,
    filepath: str,
    filename: str,
    file_type: str | None = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO files (user_id, conversation_id, filepath, filename, file_type)
               VALUES ($1, $2, $3, $4, $5)""",
            user_id, conversation_id, filepath, filename, file_type,
        )


async def load_user_files(user_id: UUID, file_type: str | None = None) -> list[dict]:
    """Load all files for a user, optionally filtered by type."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if file_type:
            rows = await conn.fetch(
                """SELECT f.filepath, f.filename, f.file_type, f.created_at,
                          c.title AS conversation_title
                   FROM files f
                   JOIN conversations c ON c.id = f.conversation_id
                   WHERE f.user_id = $1 AND f.file_type = $2
                   ORDER BY f.created_at DESC""",
                user_id, file_type,
            )
        else:
            rows = await conn.fetch(
                """SELECT f.filepath, f.filename, f.file_type, f.created_at,
                          c.title AS conversation_title
                   FROM files f
                   JOIN conversations c ON c.id = f.conversation_id
                   WHERE f.user_id = $1
                   ORDER BY f.created_at DESC""",
                user_id,
            )
    return [
        {
            "filepath": r["filepath"],
            "filename": r["filename"],
            "file_type": r["file_type"],
            "created_at": r["created_at"].isoformat(),
            "conversation_title": r["conversation_title"] or "Untitled",
        }
        for r in rows
    ]


async def load_conversation_files(conversation_id: UUID) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT filepath, filename, file_type, created_at
               FROM files
               WHERE conversation_id = $1
               ORDER BY created_at ASC""",
            conversation_id,
        )
    return [
        {
            "filepath": r["filepath"],
            "filename": r["filename"],
            "file_type": r["file_type"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def load_messages_for_summarization(conversation_id: UUID) -> list[dict]:
    """Load ALL messages (user + assistant only) for generating a summary.
    Returns dicts with 'id', 'role', 'content'."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, role, content
               FROM messages
               WHERE conversation_id = $1
                 AND role IN ('user', 'assistant')
                 AND content IS NOT NULL AND content != ''
               ORDER BY id ASC""",
            conversation_id,
        )
    return [{"id": row["id"], "role": row["role"], "content": row["content"]} for row in rows]
