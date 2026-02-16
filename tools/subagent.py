import asyncio
import json
import logging
from datetime import datetime
from openai import AsyncOpenAI
from config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL
from tools.cache import cached

logger = logging.getLogger(__name__)

DISPATCH_SUBAGENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "dispatch_subagents",
        "description": (
            "Run multiple independent research tasks in parallel using sub-agents. "
            "Each sub-agent gets its own context and can use all available tools. "
            "Use this when you need to gather information about multiple topics simultaneously. "
            "For example: researching multiple stocks, comparing multiple funds, or gathering data from different sources at once. "
            "Each task should be self-contained and independent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of research tasks to run in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Short identifier for this task (e.g. 'fund_a', 'stock_aapl')"},
                            "prompt": {"type": "string", "description": "The research question or task for the sub-agent"},
                        },
                        "required": ["id", "prompt"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
}

SUBAGENT_MAX_TURNS = 8


def _get_subagent_prompt() -> str:
    now = datetime.now()
    return f"""You are a focused financial research sub-agent. Your job is to complete ONE specific research task efficiently.

Current date: {now.strftime("%Y-%m-%d")}. Always calculate relative time from today (e.g. "近两年" = {now.year - 1}-{now.year}).

Rules:
- Use tools to gather data. Be direct and efficient.
- Call multiple tools at once when possible (batch calls).
- When done, provide a concise summary of your findings with key data points.
- Do NOT ask follow-up questions. Just do the research and report results.
- Keep your final answer under 500 words — focus on data, not fluff."""

async def dispatch_subagents(tasks: list[dict]) -> dict:
    """Run multiple sub-agent tasks in parallel and collect results."""
    # Import here to avoid circular imports
    from tools import TOOL_SCHEMAS, execute_tool

    client = AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)

    async def run_subagent(task: dict) -> tuple[str, str]:
        task_id = task["id"]
        prompt = task["prompt"]
        logger.info(f"Sub-agent [{task_id}] starting: {prompt[:100]}")

        messages = [
            {"role": "system", "content": _get_subagent_prompt()},
            {"role": "user", "content": prompt},
        ]

        for turn in range(SUBAGENT_MAX_TURNS):
            try:
                response = await client.chat.completions.create(
                    model=MINIMAX_MODEL,
                    messages=messages,
                    tools=TOOL_SCHEMAS if TOOL_SCHEMAS else None,
                )
            except Exception as e:
                logger.error(f"Sub-agent [{task_id}] LLM error: {e}")
                return task_id, f"Error: {e}"

            msg = response.choices[0].message
            msg_dict = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(msg_dict)

            if not msg.tool_calls:
                logger.info(f"Sub-agent [{task_id}] done in {turn + 1} turns")
                return task_id, msg.content or "No result"

            # Execute tool calls in parallel
            tool_results = []
            async def _exec(tc):
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await execute_tool(name, args)
                except Exception as e:
                    result = {"error": str(e)}
                return {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result),
                }

            tool_results = await asyncio.gather(*[_exec(tc) for tc in msg.tool_calls])
            messages.extend(tool_results)

        # Hit turn limit — ask for summary
        messages.append({"role": "user", "content": "Summarize your findings so far."})
        try:
            response = await client.chat.completions.create(
                model=MINIMAX_MODEL,
                messages=messages,
            )
            return task_id, response.choices[0].message.content or "No result"
        except Exception as e:
            return task_id, f"Error getting summary: {e}"

    # Run all sub-agents in parallel
    results = await asyncio.gather(*[run_subagent(t) for t in tasks])

    return {
        "results": {task_id: result for task_id, result in results},
        "task_count": len(tasks),
    }
