from __future__ import annotations
import asyncio
import json
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from db import get_pool
from auth import get_current_user, get_current_user_or_query_token
from accounts import new_conversation, load_conversation_files, load_user_files
from agent import run_agent, run_debate
from tools.output import parse_references

PROJECT_ROOT = os.path.dirname(__file__)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SendBody(BaseModel):
    message: str
    conversation_id: str | None = None
    mode: str | None = None  # "debate" to invoke trade analyzer directly


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, updated_at FROM conversations
               WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 50""",
            user["user_id"],
        )
    return [
        {"id": str(r["id"]), "title": r["title"] or "New Chat", "updated_at": r["updated_at"].isoformat()}
        for r in rows
    ]


@router.post("/conversations")
async def create_conversation(user: dict = Depends(get_current_user)):
    conv_id = await new_conversation(user["user_id"])
    return {"id": str(conv_id)}


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, limit: int = 50, user: dict = Depends(get_current_user)):
    pool = await get_pool()
    cid = UUID(conv_id)
    async with pool.acquire() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner != user["user_id"]:
            raise HTTPException(403, "Not your conversation")

        rows = await conn.fetch(
            """SELECT role, content, tool_calls, tool_call_id, created_at
               FROM messages WHERE conversation_id = $1
               ORDER BY id ASC LIMIT $2""",
            cid, limit,
        )
    messages = [
        {
            "role": r["role"],
            "content": r["content"] or "",
            "tool_calls": json.loads(r["tool_calls"]) if r["tool_calls"] else None,
            "tool_call_id": r["tool_call_id"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    files = await load_conversation_files(cid)
    return {"messages": messages, "files": files}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    pool = await get_pool()
    cid = UUID(conv_id)
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner != user["user_id"]:
            raise HTTPException(403, "Not your conversation")
        await conn.execute("DELETE FROM messages WHERE conversation_id = $1", cid)
        await conn.execute("DELETE FROM conversations WHERE id = $1", cid)
    return {"ok": True}


@router.get("/files")
async def list_user_files(file_type: str | None = None, user: dict = Depends(get_current_user)):
    """List all files for the current user, optionally filtered by type (e.g. 'pdf', 'png')."""
    files = await load_user_files(user["user_id"], file_type=file_type)
    return files


@router.get("/files/{filepath:path}")
async def serve_file(filepath: str, user: dict = Depends(get_current_user_or_query_token)):
    """Serve a user-owned file with authentication."""
    # Verify user owns this file via DB lookup
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM files WHERE filepath = $1",
            filepath,
        )
    if not row:
        raise HTTPException(404, "File not found")
    if row["user_id"] != user["user_id"]:
        raise HTTPException(403, "Access denied")

    # Prevent path traversal attacks
    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, filepath))
    if not full_path.startswith(os.path.abspath(PROJECT_ROOT)):
        raise HTTPException(403, "Invalid file path")

    if not os.path.isfile(full_path):
        raise HTTPException(404, "File not found on disk")

    return FileResponse(full_path)


@router.post("/send")
async def send_message(body: SendBody, user: dict = Depends(get_current_user)):
    user_id: UUID = user["user_id"]
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")

    # Validate conversation ownership if a specific conversation is targeted
    target_conv_id: UUID | None = None
    if body.conversation_id:
        target_conv_id = UUID(body.conversation_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            owner = await conn.fetchval(
                "SELECT user_id FROM conversations WHERE id = $1", target_conv_id
            )
            if owner != user_id:
                raise HTTPException(403, "Not your conversation")

    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def on_status(text: str):
        await queue.put({"event": "status", "data": text})

    async def on_thinking(source: str, label: str, content: str):
        await queue.put({
            "event": "thinking",
            "data": json.dumps({"source": source, "label": label, "content": content}, ensure_ascii=False),
        })

    async def run_in_background():
        try:
            if body.mode == "debate":
                result = await run_debate(message, user_id, on_status=on_status, conversation_id=target_conv_id, on_thinking=on_thinking)
            else:
                result = await run_agent(message, user_id, on_status=on_status, conversation_id=target_conv_id, on_thinking=on_thinking)
            text = result.get("text", "")
            files = result.get("files", [])

            # Parse references from text
            cleaned_text, refs = parse_references(text)

            # Auto-set conversation title from first message
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    # Find the conversation this message was saved to (most recent for user)
                    conv_row = await conn.fetchrow(
                        "SELECT id, title FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
                        user_id,
                    )
                    if conv_row and not conv_row["title"]:
                        title = message[:50] + ("..." if len(message) > 50 else "")
                        await conn.execute(
                            "UPDATE conversations SET title = $1 WHERE id = $2",
                            title, conv_row["id"],
                        )
            except Exception:
                pass

            # Convert file paths to authenticated API URLs
            file_urls = []
            for f in files:
                rel_path = os.path.relpath(f, PROJECT_ROOT)
                file_urls.append(f"/api/chat/files/{rel_path}")

            await queue.put({
                "event": "done",
                "data": json.dumps({
                    "text": cleaned_text,
                    "files": file_urls,
                    "references": refs,
                }, ensure_ascii=False),
            })
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            await queue.put({
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            })

    task = asyncio.create_task(run_in_background())

    async def event_stream():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    yield "event: status\ndata: Still working...\n\n"
                    continue

                yield f"event: {evt['event']}\ndata: {evt['data']}\n\n"

                if evt["event"] in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
