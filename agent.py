from __future__ import annotations
import asyncio
import contextvars
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

# ContextVar so tools (e.g. trade_analyzer) can emit status updates
# without changing the execute_tool interface.
status_callback: contextvars.ContextVar[Callable | None] = contextvars.ContextVar(
    "status_callback", default=None,
)

# ContextVar for emitting <think> block content to the frontend.
thinking_callback: contextvars.ContextVar[Callable | None] = contextvars.ContextVar(
    "thinking_callback", default=None,
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
    on_thinking: Callable | None = None,
) -> dict:
    """Run the agent loop. Returns {"text": str, "files": [path, ...]}.

    Loads history from DB, saves all messages to DB, and acquires a per-user
    lock so concurrent messages from the same user are serialized.

    conversation_id: if provided, use this conversation; otherwise use the most recent one.
    on_status: optional async callback(status_text: str) called with progress updates.
    on_thinking: optional async callback(source, label, content) for <think> blocks.
    """
    lock = get_user_lock(user_id)
    async with lock:
        return await _run_agent_inner(user_message, user_id, on_status, conversation_id, on_thinking)


async def _run_agent_inner(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
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

    async def _emit_thinking(source: str, label: str, content: str):
        if on_thinking:
            try:
                await on_thinking(source, label, content)
            except Exception:
                pass

    files = []

    for turn in range(MAX_TURNS):
        logger.info(f"Agent turn {turn + 1}/{MAX_TURNS}")
        await _emit(f"MiniMax · Thinking...")

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
            # Extract and emit <think> blocks before stripping
            for m in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL):
                await _emit_thinking("agent", "MiniMax Agent", m.group(1).strip())
            text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
            return {"text": text, "files": files}

        # Show which tools are running
        tool_names = [tc.function.name for tc in msg.tool_calls]
        await _emit(f"Running: {', '.join(tool_names)}...")

        # Make status/thinking callbacks available to tools via contextvars
        status_token = status_callback.set(_emit)
        thinking_token = thinking_callback.set(_emit_thinking)
        try:
            # Execute all tool calls in parallel
            t0 = time.time()
            results = await asyncio.gather(
                *[_execute_single_tool(tc) for tc in msg.tool_calls]
            )
            elapsed = time.time() - t0
        finally:
            status_callback.reset(status_token)
            thinking_callback.reset(thinking_token)
        logger.info(f"Executed {len(results)} tool(s) in parallel in {elapsed:.2f}s")

        tool_results = []
        for r in results:
            result = r["result"]
            if isinstance(result, dict) and "file" in result:
                files.append(result["file"])
            if isinstance(result, dict) and "files" in result:
                files.extend(result["files"])

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
        for m in re.finditer(r"<think>(.*?)</think>", summary, flags=re.DOTALL):
            await _emit_thinking("agent", "MiniMax Agent", m.group(1).strip())
        summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL).strip()
    except Exception as e:
        logger.error(f"Summary request failed: {e}")
        summary = "I reached the maximum number of steps. Please try a more specific question."

    await save_message(conv_id, "assistant", summary)

    return {"text": summary, "files": files}


async def run_debate(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
) -> dict:
    """Run the debate system directly, bypassing the agent loop.

    1. Use a quick LLM call to extract the stock code from user message + conversation history
    2. Gather recent conversation content as context
    3. Call analyze_trade_opportunity directly
    """
    lock = get_user_lock(user_id)
    async with lock:
        return await _run_debate_inner(user_message, user_id, on_status, conversation_id, on_thinking)


async def _run_debate_inner(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
) -> dict:
    conv_id = conversation_id or await get_active_conversation(user_id)

    # Load recent history
    messages = await load_recent_messages(conv_id)

    # Save the user message
    await save_message(conv_id, "user", user_message)

    async def _emit(text: str):
        if on_status:
            try:
                await on_status(text)
            except Exception:
                pass

    async def _emit_thinking(source: str, label: str, content: str):
        if on_thinking:
            try:
                await on_thinking(source, label, content)
            except Exception:
                pass

    # Step 1: Extract stock code from conversation
    await _emit("Identifying stock code...")

    # Build context from ALL message types (user messages contain stock names!)
    context_parts = []
    for m in messages[-20:]:
        role = m.get("role", "")
        content = m.get("content", "")
        if content and role in ("user", "assistant", "tool"):
            context_parts.append(f"[{role}]: {content[:2000]}")
    conversation_context = "\n".join(context_parts)
    if len(conversation_context) > 8000:
        conversation_context = conversation_context[:8000]

    # First try: regex extraction from user message + conversation (no LLM needed)
    stock_code = ""
    all_text = user_message + "\n" + conversation_context
    code_match = re.search(r"(?<!\d)\d{6}(?!\d)", all_text)
    if code_match:
        stock_code = code_match.group(0)
        logger.info(f"[Debate] Extracted stock code via regex: {stock_code}")

    # Fallback: LLM extraction if regex didn't find one
    if not stock_code:
        try:
            resp = await client.chat.completions.create(
                model=MINIMAX_MODEL,
                messages=[
                    {"role": "system", "content": "Extract the 6-digit Chinese A-share stock code from the conversation. Reply with ONLY the code or NONE."},
                    {"role": "user", "content": f"User message: {user_message}\n\nConversation:\n{conversation_context[:3000]}"},
                ],
                temperature=0,
                max_tokens=20,
            )
            raw = (resp.choices[0].message.content or "").strip()
            code_match = re.search(r"\d{6}", raw)
            stock_code = code_match.group(0) if code_match else ""
        except Exception as e:
            logger.error(f"Stock code extraction failed: {e}")
            stock_code = ""

    if not stock_code:
        text = "Could not identify a stock code from the conversation. Please mention a specific stock (e.g. 600036 招商银行) and try again."
        await save_message(conv_id, "assistant", text)
        return {"text": text, "files": []}

    await _emit(f"Starting debate analysis for {stock_code}...")

    # Step 2: Run trade analyzer directly
    status_token = status_callback.set(_emit)
    thinking_token = thinking_callback.set(_emit_thinking)
    try:
        from tools.trade_analyzer import analyze_trade_opportunity
        result = await analyze_trade_opportunity(stock_code, context=conversation_context)
    finally:
        status_callback.reset(status_token)
        thinking_callback.reset(thinking_token)

    # Build response text
    verdict = result.get("verdict", "")
    summary = result.get("summary", "")
    stock_name = result.get("stock_name", stock_code)
    files = result.get("files", [])

    text = f"## {stock_name} ({stock_code}) Debate Analysis\n\n{summary}\n\n---\n\n{verdict}"

    await save_message(conv_id, "assistant", text)
    return {"text": text, "files": files}


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
