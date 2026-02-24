from __future__ import annotations
import asyncio
import contextvars
import json
import logging
import os
import re
import time
from typing import Callable
from uuid import UUID
from openai import AsyncOpenAI
from config import get_minimax_config, get_system_prompt, get_planning_prompt, GROK_API_KEY, GROK_BASE_URL, GROK_MODEL_REASONING
from tools import TOOL_SCHEMAS, execute_tool
from accounts import (
    get_active_conversation, get_user_lock,
    load_recent_messages, save_message,
    get_conversation_summary, save_conversation_summary,
    load_messages_for_summarization,
    save_file_record,
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

# ContextVar so tools can access the current user's ID for per-user output dirs.
user_id_context: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "user_id_context", default=None,
)

PROJECT_ROOT = os.path.dirname(__file__)

# Max chars per tool result sent to LLM — generous for 200k context window
MAX_TOOL_RESULT_CHARS = 40000

logger = logging.getLogger(__name__)

_mm_api_key, _mm_base_url, _mm_model = get_minimax_config()
client = AsyncOpenAI(api_key=_mm_api_key, base_url=_mm_base_url)

_grok_client = AsyncOpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL) if GROK_API_KEY else None
_grok_model = GROK_MODEL_REASONING

MAX_TURNS = 30

# Summarization settings
SUMMARIZE_THRESHOLD = 60  # Trigger summarization when message count exceeds this
SUMMARIZE_KEEP_RECENT = 20  # Keep this many recent messages unsummarized

_SUMMARIZE_PROMPT = """Summarize the following conversation between a user and a financial research assistant.
Preserve ALL key facts: stock codes, numbers, dates, conclusions, tool results, and decisions made.
Write a dense, factual summary in the same language the conversation used.
Do NOT add commentary — just compress the information.
Max 800 words.

Conversation:
{conversation}"""


async def _maybe_summarize(conv_id: UUID, messages: list[dict]) -> list[dict]:
    """If the conversation is long, summarize older messages and prepend the summary.

    Returns the (potentially shortened) message list to send to the LLM.
    The full history stays in the DB untouched.
    """
    # Only user + assistant messages count toward the threshold
    substantive = [m for m in messages if m["role"] in ("user", "assistant")]
    if len(substantive) < SUMMARIZE_THRESHOLD:
        # Check if there's an existing summary to prepend
        existing = await get_conversation_summary(conv_id)
        if existing:
            summary_msg = {"role": "user", "content": f"[Previous conversation summary]\n{existing}"}
            return [summary_msg] + messages
        return messages

    # Load all user/assistant messages for summarization
    all_msgs = await load_messages_for_summarization(conv_id)
    if len(all_msgs) < SUMMARIZE_THRESHOLD:
        return messages

    # Summarize everything except the most recent SUMMARIZE_KEEP_RECENT messages
    cutoff_idx = len(all_msgs) - SUMMARIZE_KEEP_RECENT
    to_summarize = all_msgs[:cutoff_idx]
    cutoff_message_id = to_summarize[-1]["id"]

    # Build conversation text for summarization
    conv_text_parts = []
    existing_summary = await get_conversation_summary(conv_id)
    if existing_summary:
        conv_text_parts.append(f"[Prior summary]: {existing_summary}\n")

    for m in to_summarize:
        content = m["content"][:2000]  # Cap individual messages
        conv_text_parts.append(f"[{m['role']}]: {content}")
    conv_text = "\n".join(conv_text_parts)
    if len(conv_text) > 15000:
        conv_text = conv_text[:15000] + "\n...[truncated]"

    try:
        response = await client.chat.completions.create(
            model=_mm_model,
            messages=[{"role": "user", "content": _SUMMARIZE_PROMPT.format(conversation=conv_text)}],
            max_tokens=2500,
        )
        summary = response.choices[0].message.content or ""
        # Strip any <think> tags from the summary
        summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL).strip()
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        # Fall back to existing summary or no summary
        existing = await get_conversation_summary(conv_id)
        if existing:
            summary_msg = {"role": "user", "content": f"[Previous conversation summary]\n{existing}"}
            return [summary_msg] + messages
        return messages

    # Persist the summary
    await save_conversation_summary(conv_id, summary, cutoff_message_id)
    logger.info(f"Summarized conversation {conv_id}: {len(to_summarize)} messages → {len(summary)} chars")

    # Return: summary prefix + only the recent messages from our loaded set
    summary_msg = {"role": "user", "content": f"[Previous conversation summary]\n{summary}"}
    return [summary_msg] + messages


class _DateEncoder(json.JSONEncoder):
    def default(self, obj):
        import datetime
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return super().default(obj)


def _truncate_result(result: dict | list | str) -> str:
    """Serialize and truncate tool results to save tokens."""
    text = json.dumps(result, ensure_ascii=False, cls=_DateEncoder) if isinstance(result, (dict, list)) else str(result)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    # For data-heavy results, keep start and end for context
    half = MAX_TOOL_RESULT_CHARS // 2
    return text[:half] + f"\n...[truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]...\n" + text[-half:]


async def _execute_single_tool(tc) -> dict:
    """Execute a single tool call with error handling. Accepts dict or OpenAI object."""
    if isinstance(tc, dict):
        name = tc["function"]["name"]
        tc_id = tc["id"]
        raw_args = tc["function"]["arguments"]
    else:
        name = tc.function.name
        tc_id = tc.id
        raw_args = tc.function.arguments

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = {}

    logger.info(f"Tool call: {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    try:
        result = await execute_tool(name, args)
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        result = {"error": str(e)}

    return {
        "tool_call_id": tc_id,
        "result": result,
    }


async def _stream_llm_response(
    messages: list[dict],
    tools: list | None,
    on_token: Callable | None,
    on_thinking_chunk: Callable | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    client_override: AsyncOpenAI | None = None,
    model_override: str | None = None,
) -> tuple[str, list[str], list[dict]]:
    """Streaming LLM call.

    - Emits <think> content incrementally via on_thinking_chunk as it arrives.
    - Emits clean content tokens via on_token (after the think block).
    - Returns (clean_content, thoughts, tool_calls_dicts).

    State machine:
      "pre"   — buffering until we know whether the stream starts with <think>
      "think" — inside <think>…</think>, streaming to on_thinking_chunk
      "post"  — past </think>, streaming to on_token
    """
    full_content: list[str] = []
    tool_calls_acc: dict[int, dict] = {}
    has_tool_calls = False

    state = "pre"
    pre_buf = ""
    think_buf = ""
    think_emitted = 0  # chars of think_buf already sent via on_thinking_chunk

    _client = client_override or client
    _model = model_override or _mm_model
    create_kwargs: dict = {
        "model": _model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        create_kwargs["tools"] = tools
    if max_tokens:
        create_kwargs["max_tokens"] = max_tokens
    stream = await _client.chat.completions.create(
        **create_kwargs,
        **({"timeout": timeout} if timeout else {}),
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        if delta.tool_calls:
            has_tool_calls = True
            for tc in delta.tool_calls:
                acc = tool_calls_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        acc["name"] += tc.function.name
                    if tc.function.arguments:
                        acc["arguments"] += tc.function.arguments

        tok = delta.content or ""
        if not tok:
            continue
        full_content.append(tok)

        if has_tool_calls:
            continue

        if state == "post":
            if on_token:
                await on_token(tok)

        elif state == "think":
            think_buf += tok
            if "</think>" in think_buf:
                # Emit any unemitted think content before the closing tag
                think_part = think_buf.split("</think>", 1)[0]
                unemitted = think_part[think_emitted:]
                if unemitted and on_thinking_chunk:
                    await on_thinking_chunk(unemitted)
                # Switch to post-think and emit content that follows </think>
                rest = think_buf.split("</think>", 1)[1].lstrip("\n ")
                state = "post"
                think_buf = ""
                think_emitted = 0
                if rest and on_token:
                    await on_token(rest)
            else:
                # Stream incremental think content
                new_content = think_buf[think_emitted:]
                if new_content and on_thinking_chunk:
                    await on_thinking_chunk(new_content)
                    think_emitted = len(think_buf)

        else:  # state == "pre"
            pre_buf += tok
            if "<think>" in pre_buf:
                before, after_tag = pre_buf.split("<think>", 1)
                if before and on_token:
                    await on_token(before)
                state = "think"
                pre_buf = ""
                if after_tag:
                    think_buf = after_tag
                    if "</think>" in think_buf:
                        # Opening and closing tag arrived in the same batch
                        think_part = think_buf.split("</think>", 1)[0]
                        if think_part and on_thinking_chunk:
                            await on_thinking_chunk(think_part)
                        rest = think_buf.split("</think>", 1)[1].lstrip("\n ")
                        state = "post"
                        think_buf = ""
                        think_emitted = 0
                        if rest and on_token:
                            await on_token(rest)
                    else:
                        if on_thinking_chunk:
                            await on_thinking_chunk(after_tag)
                        think_emitted = len(think_buf)
            elif len(pre_buf) >= 7 and not pre_buf.startswith("<"):
                # Not a think block — start streaming immediately
                state = "post"
                if on_token:
                    await on_token(pre_buf)
                pre_buf = ""
            # else: keep accumulating

    # Flush any remaining pre_buf (response had no think block, buffer never hit 7 chars)
    if state == "pre" and pre_buf and on_token:
        await on_token(pre_buf)

    raw = "".join(full_content)
    thoughts = [m.strip() for m in re.findall(r"<think>(.*?)</think>", raw, re.DOTALL)]
    clean = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()
    tool_calls = []
    for _, v in sorted(tool_calls_acc.items()):
        args = v["arguments"]
        try:
            json.loads(args)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Tool call '{v['name']}' has invalid JSON args, replacing with {{}}")
            args = "{}"
        tool_calls.append({"id": v["id"], "type": "function", "function": {"name": v["name"], "arguments": args}})
    return clean, thoughts, tool_calls


async def run_agent(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
    on_token: Callable | None = None,
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
        return await _run_agent_inner(user_message, user_id, on_status, conversation_id, on_thinking, on_token)


async def _run_agent_inner(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
    on_token: Callable | None = None,
) -> dict:
    conv_id = conversation_id or await get_active_conversation(user_id)

    # Load recent history from DB
    messages = await load_recent_messages(conv_id)

    # Add user message and persist it
    messages.append({"role": "user", "content": user_message})
    await save_message(conv_id, "user", user_message)

    # Summarize older messages if conversation is long
    messages = await _maybe_summarize(conv_id, messages)

    # Always prepend fresh system prompt (not stored in DB)
    messages.insert(0, {"role": "system", "content": get_system_prompt()})

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

    async def _emit_token(tok: str):
        if on_token:
            try:
                await on_token(tok)
            except Exception:
                pass

    files = []
    prev_tool_names: list[str] = []

    # ── Planning turn ─────────────────────────────────────────────────
    # One tool-free LLM call that first classifies intent (chitchat vs finance),
    # then either answers directly (chitchat) or produces a research plan (finance).
    await _emit("Planning...")
    planning_messages = messages + [{"role": "user", "content": get_planning_prompt()}]
    try:
        async def _on_plan_think_chunk(chunk: str):
            # Stream planning think tokens in real-time to a separate source
            await _emit_thinking("agent_plan_think", "Planning · Thinking", chunk)

        # Stream the planning call so think content is visible in real-time
        # on_token=None because the plan text itself is not the final answer
        plan, _, _ = await _stream_llm_response(
            planning_messages,
            None,
            on_token=None,
            on_thinking_chunk=_on_plan_think_chunk,
        )

        # Parse intent from first line
        first_line = plan.split("\n", 1)[0].strip().upper()
        rest = plan.split("\n", 1)[1].strip() if "\n" in plan else ""

        if "INTENT: CHITCHAT" in first_line:
            # Direct answer — no tools, no agentic loop
            answer = rest or plan
            logger.info(f"Chitchat detected, returning direct answer ({len(answer)} chars)")
            await save_message(conv_id, "assistant", answer)
            return {"text": answer, "files": []}

        # Finance intent (or no intent line) — strip the intent line and plan as usual
        if "INTENT: FINANCE" in first_line:
            plan = rest

        if plan:
            await _emit_thinking("agent_plan", "Research Plan", plan)
            messages.append({"role": "assistant", "content": plan})
            messages.append({"role": "user", "content": "按照以上计划，现在开始调用工具获取数据。"})
    except Exception as e:
        logger.warning(f"Planning turn failed (continuing anyway): {e}")

    for turn in range(MAX_TURNS):
        logger.info(f"Agent turn {turn + 1}/{MAX_TURNS}")
        await _emit(f"MiniMax · Thinking...")

        # Pre-compute the think label for real-time streaming (before we know tool_calls)
        if turn == 0:
            think_label = "Turn 1 · Analysis"
        elif prev_tool_names:
            think_label = f"Turn {turn + 1} · After {', '.join(prev_tool_names)}"
        else:
            think_label = f"Turn {turn + 1} · Thinking"

        think_source = f"agent_t{turn + 1}"

        async def _on_think_chunk(chunk: str, _src=think_source, _lbl=think_label):
            await _emit_thinking(_src, _lbl, chunk)

        clean, _, tool_calls = await _stream_llm_response(
            messages,
            TOOL_SCHEMAS if TOOL_SCHEMAS else None,
            on_token=_emit_token,
            on_thinking_chunk=_on_think_chunk,
        )

        msg_dict: dict = {"role": "assistant", "content": clean}
        if tool_calls:
            msg_dict["tool_calls"] = tool_calls
        messages.append(msg_dict)

        await save_message(
            conv_id, "assistant", clean,
            tool_calls=tool_calls or None,
        )

        if not tool_calls:
            return {"text": clean or "I couldn't generate a response.", "files": files}

        # Show which tools are running
        tool_names = [tc["function"]["name"] for tc in tool_calls]
        prev_tool_names = tool_names
        await _emit(f"Running: {', '.join(tool_names)}...")

        # Make status/thinking/user_id callbacks available to tools via contextvars
        status_token = status_callback.set(_emit)
        thinking_token = thinking_callback.set(_emit_thinking)
        uid_token = user_id_context.set(user_id)
        try:
            # Execute all tool calls in parallel
            t0 = time.time()
            results = await asyncio.gather(
                *[_execute_single_tool(tc) for tc in tool_calls]
            )
            elapsed = time.time() - t0
        finally:
            status_callback.reset(status_token)
            thinking_callback.reset(thinking_token)
            user_id_context.reset(uid_token)
        logger.info(f"Executed {len(results)} tool(s) in parallel in {elapsed:.2f}s")

        tool_results = []
        files_before = len(files)
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

        # Save file records for any new files from this turn
        for file_path in files[files_before:]:
            try:
                rel_path = os.path.relpath(file_path, PROJECT_ROOT)
                ext = os.path.splitext(file_path)[1].lstrip(".")
                await save_file_record(user_id, conv_id, rel_path, os.path.basename(file_path), ext)
            except Exception as e:
                logger.warning(f"Failed to save file record for {file_path}: {e}")

    # Hit the turn limit — ask the model to summarize what it has so far
    logger.info("Hit max turns, requesting summary from model")
    summary_request = "You have reached the maximum number of steps. Please summarize all the data and findings you have gathered so far into a final response. Do not make any more tool calls."
    messages.append({"role": "user", "content": summary_request})
    await save_message(conv_id, "user", summary_request)

    try:
        async def _on_summary_think(chunk: str):
            await _emit_thinking("agent_summary_think", "Summary · Thinking", chunk)

        summary, _, _ = await _stream_llm_response(
            messages,
            None,
            on_token=_emit_token,
            on_thinking_chunk=_on_summary_think,
        )
        if not summary:
            summary = "I reached the maximum number of steps but couldn't generate a summary."
    except Exception as e:
        logger.error(f"Summary request failed: {e}")
        summary = "I reached the maximum number of steps. Please try a more specific question."

    await save_message(conv_id, "assistant", summary)

    return {"text": summary, "files": files}


async def run_agent_fast(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
    on_token: Callable | None = None,
) -> dict:
    lock = get_user_lock(user_id)
    async with lock:
        return await _run_agent_fast_inner(
            user_message, user_id, on_status, conversation_id, on_thinking, on_token
        )


async def _run_agent_fast_inner(
    user_message: str,
    user_id: UUID,
    on_status: Callable | None = None,
    conversation_id: UUID | None = None,
    on_thinking: Callable | None = None,
    on_token: Callable | None = None,
) -> dict:
    from config import get_fast_system_prompt
    from tools.web import _grok_web_search

    user_id_context.set(user_id)

    async def _emit(text: str):
        if on_status:
            try:
                await on_status(text)
            except Exception:
                pass

    async def _emit_token(tok: str):
        if on_token:
            try:
                await on_token(tok)
            except Exception:
                pass

    conv_id = conversation_id or await get_active_conversation(user_id)
    messages = await load_recent_messages(conv_id)
    await save_message(conv_id, "user", user_message)

    # Step 1: live web search via Grok Responses API
    await _emit("⚡ Fast Mode · Searching live data...")
    search = await _grok_web_search(user_message)

    # Build search context block to inject into the user turn
    search_context = ""
    if search.get("answer"):
        search_context = f"\n\n[实时搜索结果]\n{search['answer']}"
        if search.get("sources"):
            urls = "\n".join(s["url"] for s in search["sources"][:10] if s.get("url"))
            search_context += f"\n\n可用来源:\n{urls}"

    augmented_message = user_message + search_context if search_context else user_message

    # Step 2: stream a clean summary via Grok chat completions
    await _emit("⚡ Fast Mode · Summarizing...")
    system_msg = {"role": "system", "content": get_fast_system_prompt()}
    full_messages = [system_msg] + messages + [{"role": "user", "content": augmented_message}]

    response_text, _, _ = await _stream_llm_response(
        full_messages, None,
        on_token=_emit_token, on_thinking_chunk=None,
        max_tokens=1500,
        client_override=_grok_client,
        model_override=_grok_model,
    )

    logger.info(f"Fast mode response: {len(response_text or '')} chars")
    await save_message(conv_id, "assistant", response_text or "")
    return {"text": response_text or "", "files": []}


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

    # Build conversation context for the hypothesis engine
    context_parts = []
    for m in messages[-20:]:
        role = m.get("role", "")
        content = m.get("content", "")
        if content and role in ("user", "assistant", "tool"):
            context_parts.append(f"[{role}]: {content[:2000]}")
    conversation_context = "\n".join(context_parts)
    if len(conversation_context) > 8000:
        conversation_context = conversation_context[:8000]

    await _emit("Starting hypothesis-driven debate...")

    # Pass user question directly — hypothesis engine handles everything
    status_token = status_callback.set(_emit)
    thinking_token = thinking_callback.set(_emit_thinking)
    uid_token = user_id_context.set(user_id)
    try:
        from tools.trade_analyzer import run_hypothesis_debate
        result = await run_hypothesis_debate(user_message, context=conversation_context)
    finally:
        status_callback.reset(status_token)
        thinking_callback.reset(thinking_token)
        user_id_context.reset(uid_token)

    # Build response text
    verdict = result.get("verdict", "")
    summary = result.get("summary", "")
    hypothesis = result.get("hypothesis", user_message)
    report_title = result.get("report_title", hypothesis)
    files = result.get("files", [])

    # Save file records for debate-generated files
    for file_path in files:
        try:
            rel_path = os.path.relpath(file_path, PROJECT_ROOT)
            ext = os.path.splitext(file_path)[1].lstrip(".")
            await save_file_record(user_id, conv_id, rel_path, os.path.basename(file_path), ext)
        except Exception as e:
            logger.warning(f"Failed to save file record for {file_path}: {e}")

    text = f"## {report_title}\n\n**H₀: {hypothesis}**\n\n{summary}\n\n---\n\n{verdict}"

    await save_message(conv_id, "assistant", text)
    return {"text": text, "files": files}
