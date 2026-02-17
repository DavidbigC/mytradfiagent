from __future__ import annotations
import asyncio
import json
import logging
import re
import time
from typing import Callable
from uuid import UUID
from openai import AsyncOpenAI
from config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL, get_system_prompt
from tools import TOOL_SCHEMAS, execute_tool
from accounts import (
    get_active_conversation, get_user_lock,
    load_recent_messages, save_message,
)

# Max chars per tool result sent to LLM — prevents token explosion from large data dumps
MAX_TOOL_RESULT_CHARS = 4000

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)

MAX_TURNS = 30


def _truncate_result(result: dict | list | str) -> str:
    """Serialize and truncate tool results to save tokens."""
    text = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    # For data-heavy results, keep start and end for context
    half = MAX_TOOL_RESULT_CHARS // 2
    return text[:half] + f"\n...[truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]...\n" + text[-half:]


async def _execute_single_tool(tc) -> dict:
    """Execute a single tool call with error handling."""
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError:
        args = {}

    logger.info(f"Tool call: {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    try:
        result = await execute_tool(name, args)
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        result = {"error": str(e)}

    return {
        "tool_call_id": tc.id,
        "result": result,
    }


async def run_agent(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
) -> dict:
    """Run the agent loop. Returns {"text": str, "files": [path, ...]}.

    Loads history from DB, saves all messages to DB, and acquires a per-user
    lock so concurrent messages from the same user are serialized.

    conversation_id: if provided, use this conversation; otherwise use the most recent one.
    on_status: optional async callback(status_text: str) called with progress updates.
    """
    lock = get_user_lock(user_id)
    async with lock:
        return await _run_agent_inner(user_message, user_id, on_status, conversation_id)


async def _run_agent_inner(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
) -> dict:
    conv_id = conversation_id or await get_active_conversation(user_id)

    # Load recent history from DB
    messages = await load_recent_messages(conv_id)

    # Always prepend fresh system prompt (not stored in DB)
    messages.insert(0, {"role": "system", "content": get_system_prompt()})

    # Add user message and persist it
    messages.append({"role": "user", "content": user_message})
    await save_message(conv_id, "user", user_message)

    async def _emit(text: str):
        if on_status:
            try:
                await on_status(text)
            except Exception:
                pass

    files = []

    for turn in range(MAX_TURNS):
        logger.info(f"Agent turn {turn + 1}/{MAX_TURNS}")
        await _emit(f"Thinking... (step {turn + 1})")

        response = await client.chat.completions.create(
            model=MINIMAX_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS if TOOL_SCHEMAS else None,
        )

        msg = response.choices[0].message
        msg_dict = _message_to_dict(msg)
        messages.append(msg_dict)

        # Persist assistant message
        await save_message(
            conv_id, "assistant", msg.content,
            tool_calls=msg_dict.get("tool_calls"),
        )

        if not msg.tool_calls:
            text = msg.content or "I couldn't generate a response."
            # Strip model thinking tags (e.g. MiniMax <think>...</think>)
            text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
            return {"text": text, "files": files}

        # Show which tools are running
        tool_names = [tc.function.name for tc in msg.tool_calls]
        await _emit(f"Running: {', '.join(tool_names)}...")

        # Execute all tool calls in parallel
        t0 = time.time()
        results = await asyncio.gather(
            *[_execute_single_tool(tc) for tc in msg.tool_calls]
        )
        elapsed = time.time() - t0
        logger.info(f"Executed {len(results)} tool(s) in parallel in {elapsed:.2f}s")

        tool_results = []
        for r in results:
            result = r["result"]
            if isinstance(result, dict) and "file" in result:
                files.append(result["file"])

            content = _truncate_result(result)
            tool_results.append({
                "role": "tool",
                "tool_call_id": r["tool_call_id"],
                "content": content,
            })

            # Persist tool result
            await save_message(
                conv_id, "tool", content,
                tool_call_id=r["tool_call_id"],
            )

        messages.extend(tool_results)

    # Hit the turn limit — ask the model to summarize what it has so far
    logger.info("Hit max turns, requesting summary from model")
    summary_request = "You have reached the maximum number of steps. Please summarize all the data and findings you have gathered so far into a final response. Do not make any more tool calls."
    messages.append({"role": "user", "content": summary_request})
    await save_message(conv_id, "user", summary_request)

    try:
        response = await client.chat.completions.create(
            model=MINIMAX_MODEL,
            messages=messages,
        )
        summary = response.choices[0].message.content or "I reached the maximum number of steps but couldn't generate a summary."
        summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL).strip()
    except Exception as e:
        logger.error(f"Summary request failed: {e}")
        summary = "I reached the maximum number of steps. Please try a more specific question."

    await save_message(conv_id, "assistant", summary)

    return {"text": summary, "files": files}


def _message_to_dict(msg) -> dict:
    """Convert an OpenAI message object to a serializable dict."""
    d = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d
