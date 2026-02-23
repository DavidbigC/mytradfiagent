from __future__ import annotations
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Literal, Optional
from uuid import UUID

import io
from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from db import get_pool
from auth import get_current_user, get_current_user_or_query_token
from accounts import new_conversation, load_conversation_files, load_user_files
from agent import run_agent, run_debate
from tools.output import parse_references

PROJECT_ROOT = os.path.dirname(__file__)
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Per-user background run state ─────────────────────────────────────────────

@dataclass
class AgentRun:
    """Survives SSE disconnects. Buffers all events so late subscribers get them."""
    task: asyncio.Task
    conv_id: Optional[UUID] = None
    _events: list = field(default_factory=list)
    _queues: list = field(default_factory=list)

    def put(self, evt: dict):
        self._events.append(evt)
        for q in list(self._queues):
            q.put_nowait(evt)

    def subscribe(self) -> asyncio.Queue:
        """Returns a queue pre-loaded with buffered events plus new ones."""
        q: asyncio.Queue = asyncio.Queue()
        for evt in self._events:
            q.put_nowait(evt)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    @property
    def done(self) -> bool:
        return self.task.done()


# Keyed by user_id UUID
_active_runs: dict[UUID, AgentRun] = {}


async def _event_stream(run: AgentRun) -> asyncio.AsyncGenerator:
    q = run.subscribe()
    try:
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=120)
            except asyncio.TimeoutError:
                yield "event: status\ndata: Still working...\n\n"
                continue

            yield f"event: {evt['event']}\ndata: {evt['data']}\n\n"

            if evt["event"] in ("done", "error"):
                break

            # If task already finished but we haven't seen done/error yet,
            # the buffer had all events — drain remaining then stop
            if run.done and q.empty():
                break
    finally:
        run.unsubscribe(q)


# ── Route handlers ─────────────────────────────────────────────────────────────

class SendBody(BaseModel):
    message: str
    conversation_id: str | None = None
    mode: Literal["normal", "debate"] | None = None


class CreateConversationBody(BaseModel):
    mode: Literal["normal", "debate"] = "normal"


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, updated_at, mode, share_token, is_public
               FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 50""",
            user["user_id"],
        )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"] or "New Chat",
            "updated_at": r["updated_at"].isoformat(),
            "mode": r["mode"] or "normal",
            "share_token": r["share_token"] if r["share_token"] else None,
            "is_public": r["is_public"],
        }
        for r in rows
    ]


@router.post("/conversations")
async def create_conversation(body: CreateConversationBody = Body(default_factory=CreateConversationBody), user: dict = Depends(get_current_user)):
    conv_id = await new_conversation(user["user_id"], body.mode)
    return {"id": str(conv_id)}


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, limit: int = 100, user: dict = Depends(get_current_user)):
    pool = await get_pool()
    cid = UUID(conv_id)
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner != user["user_id"]:
            raise HTTPException(403, "Not your conversation")

        rows = await conn.fetch(
            """SELECT role, content, tool_calls, tool_call_id, created_at
               FROM messages WHERE conversation_id = $1
               ORDER BY id DESC LIMIT $2""",
            cid, limit,
        )
        rows = list(reversed(rows))
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


class ShareBody(BaseModel):
    enabled: bool


@router.post("/conversations/{conv_id}/share")
async def toggle_share(conv_id: str, body: ShareBody, user: dict = Depends(get_current_user)):
    import secrets
    pool = await get_pool()
    cid = UUID(conv_id)
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner != user["user_id"]:
            raise HTTPException(403, "Not your conversation")

        if body.enabled:
            token = secrets.token_urlsafe(24)
            await conn.execute(
                """UPDATE conversations
                   SET is_public = TRUE,
                       share_token = COALESCE(share_token, $1)
                   WHERE id = $2""",
                token, cid,
            )
        else:
            await conn.execute(
                "UPDATE conversations SET is_public = FALSE WHERE id = $1",
                cid,
            )

        row = await conn.fetchrow(
            "SELECT share_token, is_public FROM conversations WHERE id = $1", cid
        )
    return {
        "share_token": row["share_token"],
        "is_public": row["is_public"],
    }


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


@router.get("/share/{share_token}")
async def get_shared_conversation(share_token: str, limit: int = 100):
    pool = await get_pool()
    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT id, title FROM conversations WHERE share_token = $1 AND is_public = TRUE",
            share_token,
        )
        if not conv:
            raise HTTPException(404, "Conversation not found or sharing has been disabled")

        rows = await conn.fetch(
            """SELECT role, content, created_at
               FROM messages WHERE conversation_id = $1
                 AND role IN ('user', 'assistant')
               ORDER BY id ASC LIMIT $2""",
            conv["id"], limit,
        )
    messages = [
        {
            "role": r["role"],
            "content": r["content"] or "",
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return {"title": conv["title"] or "Shared Conversation", "messages": messages}


@router.get("/files")
async def list_user_files(file_type: str | None = None, user: dict = Depends(get_current_user)):
    files = await load_user_files(user["user_id"], file_type=file_type)
    return files


@router.get("/files/{filepath:path}")
async def serve_file(filepath: str, user: dict = Depends(get_current_user_or_query_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM files WHERE filepath = $1", filepath,
        )
    if not row:
        raise HTTPException(404, "File not found")
    if row["user_id"] != user["user_id"]:
        raise HTTPException(403, "Access denied")

    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, filepath))
    if not full_path.startswith(os.path.abspath(PROJECT_ROOT)):
        raise HTTPException(403, "Invalid file path")
    if not os.path.isfile(full_path):
        raise HTTPException(404, "File not found on disk")

    return FileResponse(full_path)


@router.get("/active")
async def get_active_run(user: dict = Depends(get_current_user)):
    """Return whether an agent run is currently in progress for this user."""
    user_id: UUID = user["user_id"]
    run = _active_runs.get(user_id)
    if run and not run.done:
        return {
            "running": True,
            "conversation_id": str(run.conv_id) if run.conv_id else None,
        }
    return {"running": False, "conversation_id": None}


@router.post("/stop")
async def stop_agent_run(user: dict = Depends(get_current_user)):
    """Cancel the running agent task for this user."""
    user_id: UUID = user["user_id"]
    run = _active_runs.pop(user_id, None)
    if not run or run.done:
        return {"ok": True, "stopped": False}
    run.task.cancel()
    run.put({"event": "error", "data": json.dumps({"error": "Stopped by user"})})
    logger.info(f"Agent run cancelled for user {user_id}")
    return {"ok": True, "stopped": True}


@router.post("/stt")
async def speech_to_text(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Transcribe audio with Whisper, then extract + fuzzy-match stock names.

    Returns {text, matched_stocks: [{stock_code, stock_name, exchange, distance}]}.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    audio_bytes = await file.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Audio too short or empty")

    from openai import OpenAI
    from tools.stt_stocks import extract_and_find_stocks

    client = OpenAI(api_key=api_key)
    filename = file.filename or "audio.webm"
    try:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, io.BytesIO(audio_bytes), file.content_type or "audio/webm"),
            language="zh",
            response_format="text",
            temperature=0,
            prompt="用户正在使用中国A股金融研究助手进行语音输入。",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    text = response.strip() if isinstance(response, str) else str(response).strip()
    logger.info(f"STT user={user['user_id']}: '{text}'")

    # Skip stock extraction for non-finance audio — return raw transcription immediately
    _FINANCE_RE = re.compile(
        r"股票|股|基金|债券|A股|港股|美股|牛市|熊市|涨停|跌停|板块|行情|"
        r"ETF|PE|PB|ROE|净利润|营收|分红|增发|回购|北向|外资|机构|主力|"
        r"买入|卖出|持仓|仓位|止损|止盈|支撑|压力|均线|MACD|KDJ|"
        r"\d{6}\.(?:SH|SZ|BJ)|[沪深]市"
    )
    if not _FINANCE_RE.search(text):
        logger.info("STT: no finance keywords detected, returning raw transcription")
        return JSONResponse({"text": text, "matched_stocks": [], "replacements": {}})

    pool = await get_pool()
    stock_result = await extract_and_find_stocks(text, client, pool)
    logger.info(f"STT stocks: extracted={stock_result['extracted_names']} matched={[(s['stock_name'], s['distance']) for s in stock_result['matched_stocks']]}")

    return JSONResponse({
        "text": text,
        "matched_stocks": stock_result["matched_stocks"],
        "replacements": stock_result["replacements"],
    })


@router.get("/stream")
async def reconnect_stream(user: dict = Depends(get_current_user)):
    """Reconnect to an in-progress agent run. Replays all buffered events."""
    user_id: UUID = user["user_id"]
    run = _active_runs.get(user_id)
    if not run or run.done:
        raise HTTPException(404, "No active agent run")
    return StreamingResponse(
        _event_stream(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/send")
async def send_message(body: SendBody, user: dict = Depends(get_current_user)):
    user_id: UUID = user["user_id"]
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")

    # If agent already running for this user, just reattach — don't start a new one
    existing = _active_runs.get(user_id)
    if existing and not existing.done:
        logger.info(f"User {user_id} reconnected to existing agent run")
        return StreamingResponse(
            _event_stream(existing),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    if body.conversation_id:
        target_conv_id = UUID(body.conversation_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            owner = await conn.fetchval(
                "SELECT user_id FROM conversations WHERE id = $1", target_conv_id
            )
            if owner != user_id:
                raise HTTPException(403, "Not your conversation")
    else:
        target_conv_id = await new_conversation(user_id)

    run = AgentRun(task=None, conv_id=target_conv_id)

    async def on_status(text: str):
        run.put({"event": "status", "data": text})

    async def on_thinking(source: str, label: str, content: str):
        run.put({
            "event": "thinking",
            "data": json.dumps({"source": source, "label": label, "content": content}, ensure_ascii=False),
        })

    async def on_token(tok: str):
        run.put({"event": "token", "data": json.dumps(tok)})

    async def run_in_background():
        import time as _time
        t0 = _time.time()
        try:
            if body.mode == "debate":
                result = await run_debate(message, user_id, on_status=on_status, conversation_id=target_conv_id, on_thinking=on_thinking)
            else:
                result = await run_agent(message, user_id, on_status=on_status, conversation_id=target_conv_id, on_thinking=on_thinking, on_token=on_token)

            elapsed = round(_time.time() - t0)
            logger.info(f"Agent completed in {elapsed}s for user {user_id}")

            text = result.get("text", "")
            files = result.get("files", [])
            cleaned_text, refs = parse_references(text)

            # Auto-set conversation title from first message
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    title_row = await conn.fetchrow(
                        "SELECT title FROM conversations WHERE id = $1",
                        run.conv_id,
                    )
                    if title_row and not title_row["title"]:
                        title = message[:50] + ("..." if len(message) > 50 else "")
                        await conn.execute(
                            "UPDATE conversations SET title = $1 WHERE id = $2",
                            title, run.conv_id,
                        )
            except Exception:
                pass

            file_urls = [f"/api/chat/files/{os.path.relpath(f, PROJECT_ROOT)}" for f in files]
            run.put({
                "event": "done",
                "data": json.dumps({"text": cleaned_text, "files": file_urls, "references": refs, "elapsed_seconds": elapsed}, ensure_ascii=False),
            })
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            run.put({"event": "error", "data": json.dumps({"error": str(e)})})

    task = asyncio.create_task(run_in_background())
    run.task = task
    _active_runs[user_id] = run

    def _cleanup(_):
        _active_runs.pop(user_id, None)

    task.add_done_callback(_cleanup)

    return StreamingResponse(
        _event_stream(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
