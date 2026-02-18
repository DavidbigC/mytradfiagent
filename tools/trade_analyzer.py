"""Multi-LLM debate system for trade opportunity analysis.

Two models (MiniMax + Qwen) provide 4 debaters (2 bull, 2 bear) with rebuttals,
then a MiniMax judge synthesizes an anonymized verdict.

Architecture:
  Phase 1: Data collection (parallel existing tool calls)
  Phase 2: Opening arguments (4 parallel LLM calls)
  Phase 3: Rebuttals (4 parallel LLM calls)
  Phase 4: Anonymized judge (1 LLM call)
"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime
from openai import AsyncOpenAI
from config import (
    MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL,
    QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL,
)

async def _execute_tool(name: str, args: dict):
    """Late import to avoid circular dependency with tools/__init__.py."""
    from tools import execute_tool
    return await execute_tool(name, args)

# Tools excluded from debater tool-use (output, recursion, meta tools)
_EXCLUDED_TOOLS = {
    "generate_chart", "generate_pdf", "dispatch_subagents",
    "analyze_trade_opportunity", "lookup_data_sources", "save_data_source",
}

MAX_DEBATER_TOOL_ROUNDS = 3
MAX_DEBATER_TOOL_RESULT_CHARS = 3000

PRIOR_REPORT_MAX_AGE_DAYS = 5

logger = logging.getLogger(__name__)

minimax_client = AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)
qwen_client = AsyncOpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

ANALYZE_TRADE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "analyze_trade_opportunity",
        "description": (
            "Deep trade opportunity analysis using multi-LLM debate. "
            "4 analysts (2 bull, 2 bear) argue with evidence, then a judge synthesizes. "
            "Use when user asks for trade analysis, 'should I buy/sell X', '值得买吗', "
            "'投资分析', or trade opportunity assessment. "
            "Takes ~30-60 seconds. Returns structured verdict with confidence score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share stock code (e.g. '600036')",
                },
                "context": {
                    "type": "string",
                    "description": "Optional: existing data/analysis from conversation to avoid re-fetching",
                },
            },
            "required": ["stock_code"],
        },
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_BULL_OPENING = """You are a quantitative equity analyst. Your task: identify data points that support a positive outlook for {stock_name} ({stock_code}).

Analyze each dimension below. For each, state the relevant numbers, compute ratios or trends where applicable, and assess whether the data is favorable. If the data is inconclusive or negative for a given dimension, say so plainly — do not spin it.

1. VALUATION: Current PE/PB vs 5-year historical range and sector median. Percentile rank.
2. EARNINGS TRAJECTORY: Revenue and net profit QoQ/YoY growth rates. Is growth accelerating, stable, or decelerating? Cite exact figures.
3. BALANCE SHEET: Debt-to-asset ratio trend, current ratio, cash position. Flag any deterioration.
4. CASH FLOW: OCF/net income ratio (earnings quality). Free cash flow trend over last 4 quarters.
5. CAPITAL FLOW: Net institutional flow direction and magnitude from the data. Quantify.
6. SHAREHOLDER CHANGES: Top holder position changes — 增持/减持/新进. Net direction.
7. DIVIDEND: Trailing yield, payout ratio, consistency over last 3+ years.
8. FORWARD CATALYSTS: Based strictly on data trends (not speculation), what measurable improvements could continue?

You have access to research tools (web search, financial data lookups). Use them only when the provided data lacks a specific number you need.

Rules:
- Every claim must cite a specific number: "营收同比+15.3%至42.1亿元 (Q3 2025)" — never "营收在增长".
- No adjectives like "强劲", "优秀", "令人印象深刻". State the number and let it speak.
- Where data is unfavorable, state it factually. Do not minimize or explain away.
- End with: PRICE TARGET RATIONALE (based on valuation math, not sentiment) and CONVICTION LEVEL (1-10).
- 600-800 words. Write in the same language as the user query and data provided. Maintain a neutral, clinical tone throughout.

=== DATA ===
{data_pack}"""

_BEAR_OPENING = """You are a quantitative risk analyst. Your task: identify data points that indicate risk or negative outlook for {stock_name} ({stock_code}).

Analyze each dimension below. For each, state the relevant numbers, compute ratios or trends where applicable, and assess whether the data signals risk. If the data is actually positive for a given dimension, say so plainly — do not force a negative interpretation.

1. VALUATION: Current PE/PB vs 5-year historical range and sector median. What growth rate is implied? Is that realistic given recent trends?
2. EARNINGS RISK: Revenue/profit growth deceleration, margin compression, non-recurring income inflating results. Cite exact figures.
3. BALANCE SHEET RISK: Debt-to-asset trend, leverage changes, asset quality indicators. Quantify the trajectory.
4. CASH FLOW: OCF/net income divergence (earnings quality concern if ratio < 0.8). Capex intensity vs FCF.
5. CAPITAL FLOW: Net institutional outflow signals. Quantify magnitude and duration.
6. SHAREHOLDER CHANGES: Top holder 减持/退出 patterns. Net direction.
7. DIVIDEND SUSTAINABILITY: Payout ratio vs earnings trend. Can current yield be maintained if earnings decline X%?
8. RISK FACTORS: Based strictly on data trends (not speculation), what measurable deterioration could continue?

You have access to research tools (web search, financial data lookups). Use them only when the provided data lacks a specific number you need.

Rules:
- Every claim must cite a specific number: "净利率从28.1%降至22.4% (连续4个季度)" — never "利润率在下降".
- No adjectives like "令人担忧", "严重", "危险". State the number and let it speak.
- Where data is actually positive, state it factually. Do not dismiss or undermine.
- End with: DOWNSIDE RISK ESTIMATE (based on valuation math, not fear) and CONVICTION LEVEL (1-10).
- 600-800 words. Write in the same language as the user query and data provided. Maintain a neutral, clinical tone throughout.

=== DATA ===
{data_pack}"""

_REBUTTAL = """You previously analyzed the {side} data for {stock_name} ({stock_code}). Below are the opposing analysts' findings, followed by your co-analyst's findings.

=== OPPOSING ANALYSIS ===
{opposing_args}

=== CO-ANALYST'S FINDINGS ===
{ally_arg}

Your task: Examine the opposing analysts' data citations for accuracy and completeness.
- Identify any numbers they cited that are incomplete, out of context, or contradicted by other data points.
- Where their data is accurate, note whether your data provides additional context that changes the interpretation.
- Correct any errors in your original analysis based on what the opposing side surfaced.
- Incorporate any additional data points from your co-analyst that strengthen the factual record.
- You have access to research tools (web search, financial data lookups). Use them only to verify a disputed number or fill a factual gap.

Rules:
- Do not use combative language ("他们忽略了", "这是错误的"). Instead: "该数据点需补充背景: [具体数据]".
- If the opposing side made a valid point with correct data, acknowledge it explicitly.
- Every counter-point must include a specific number.
- 300-500 words. Write in the same language as the debate content. Maintain a neutral, clinical tone.

=== ORIGINAL DATA FOR REFERENCE ===
{data_pack}"""

_JUDGE = """You are a quantitative portfolio committee chair. You have received analysis from 4 anonymous analysts — 2 identifying positive signals, 2 identifying risk signals — followed by their cross-examination.

Your task: Determine which direction the data supports, based SOLELY on factual accuracy and data completeness.

Evaluation criteria (in order of importance):
1. DATA ACCURACY: Which analysts cited verifiable numbers? Flag any claims that lack specific figures.
2. COMPLETENESS: Which side addressed more of the 8 analysis dimensions with actual data?
3. CONSISTENCY: Do the cited numbers agree with each other and with the raw data summary?
4. CROSS-EXAMINATION: Did the rebuttals identify real data errors, or were they rhetorical?

Disregard: emotional language, rhetorical flourish, unsubstantiated predictions, appeals to market sentiment.

You MUST produce a response in EXACTLY this structure (in the same language as the analyst arguments):

**判定: BUY / SELL / HOLD**
(HOLD only if both sides have equal data support — not as a safe default)

**置信度: X/10**

**判定理由:**
200-300 words. For each major data point that influenced your decision, cite the specific number. Explain which analyst's data was more complete or accurate, not which was more persuasive.

**核心风险 (无论判定结果):**
1. [具体数据点]
2. [具体数据点]
3. [具体数据点]

**反方最强数据点:**
The single most compelling data point from the losing side, with the exact number.

**时间维度:** 短期 (1-3月) / 中期 (3-12月) / 长期 (1-3年)

Arguments are labeled Analyst 1-8. You do not know their identity or source model. Judge only the data.

=== MARKET DATA SUMMARY ===
{data_summary}

=== ANALYST ARGUMENTS ===
{all_arguments}"""


# ---------------------------------------------------------------------------
# Phase 1: Data Collection
# ---------------------------------------------------------------------------

def _find_prior_report(stock_name: str) -> str | None:
    """Find the most recent MD report for this stock within PRIOR_REPORT_MAX_AGE_DAYS.

    Returns the report content (truncated) or None.
    """
    import glob
    pattern = os.path.join(_OUTPUT_DIR, f"{stock_name}_*.md")
    matches = glob.glob(pattern)
    if not matches:
        return None

    # Sort by modification time, newest first
    matches.sort(key=os.path.getmtime, reverse=True)
    newest = matches[0]

    # Check age
    age_days = (datetime.now().timestamp() - os.path.getmtime(newest)) / 86400
    if age_days > PRIOR_REPORT_MAX_AGE_DAYS:
        return None

    try:
        with open(newest, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    age_str = f"{age_days:.1f} days ago" if age_days >= 1 else f"{age_days * 24:.0f} hours ago"
    logger.info(f"[TradeAnalyzer] Found prior report: {os.path.basename(newest)} ({age_str})")

    # Cap at 6000 chars to avoid bloating context
    if len(content) > 6000:
        content = content[:6000] + "\n...[prior report truncated]"

    return content


async def _collect_data(stock_code: str, context: str = "") -> tuple[str, str]:
    """Fetch all data in parallel. Returns (data_pack, stock_name)."""
    tasks = {
        "income": _execute_tool("fetch_stock_financials", {
            "stock_code": stock_code, "statement": "income", "periods": 8,
        }),
        "balance": _execute_tool("fetch_stock_financials", {
            "stock_code": stock_code, "statement": "balance", "periods": 4,
        }),
        "cashflow": _execute_tool("fetch_stock_financials", {
            "stock_code": stock_code, "statement": "cashflow", "periods": 4,
        }),
        "quote": _execute_tool("fetch_cn_stock_data", {
            "symbol": stock_code, "info_type": "quote",
        }),
        "capital_flow": _execute_tool("fetch_stock_capital_flow", {
            "stock_code": stock_code, "days": 20,
        }),
        "shareholders": _execute_tool("fetch_top_shareholders", {
            "stock_code": stock_code, "periods": 2,
        }),
        "dividends": _execute_tool("fetch_dividend_history", {
            "stock_code": stock_code,
        }),
    }

    keys = list(tasks.keys())
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results = {}
    for k, v in zip(keys, results_list):
        if isinstance(v, Exception):
            logger.warning(f"Data collection failed for {k}: {v}")
            results[k] = {"error": str(v)}
        else:
            results[k] = v

    # Extract stock name from quote
    quote = results.get("quote", {})
    stock_name = quote.get("股票名称", stock_code)

    # Build data pack string
    sections = []
    section_labels = {
        "quote": "实时行情",
        "income": "利润表 (近8个季度)",
        "balance": "资产负债表 (近4个季度)",
        "cashflow": "现金流量表 (近4个季度)",
        "capital_flow": "资金流向 (近20个交易日)",
        "shareholders": "十大流通股东 (近2期)",
        "dividends": "历史分红",
    }
    for key, label in section_labels.items():
        data = results.get(key, {})
        sections.append(f"### {label}\n{_format_data(data)}")

    if context:
        sections.append(f"### 补充信息 (来自对话上下文)\n{context}")

    # Check for prior report on this stock
    prior = _find_prior_report(stock_name)
    if prior:
        sections.append(
            "### PRIOR ANALYSIS (reference only)\n"
            "A previous report on this stock is shown below. "
            "You may use specific data points or arguments from it if they are still relevant, "
            "but do NOT treat it as authoritative. It may contain outdated numbers, missed factors, "
            "or incorrect conclusions. Always verify against the fresh data above. "
            "If the prior report conflicts with fresh data, trust the fresh data.\n\n"
            f"{prior}"
        )

    data_pack = "\n\n".join(sections)

    # Truncate if too long to fit in LLM context
    if len(data_pack) > 30000:
        data_pack = data_pack[:30000] + "\n...[数据已截断]"

    return data_pack, stock_name


def _format_data(data) -> str:
    """Format tool result dict/list into readable string."""
    if isinstance(data, dict) and "error" in data:
        return f"(数据获取失败: {data['error']})"
    if isinstance(data, str):
        return data
    import json
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(data)


# ---------------------------------------------------------------------------
# Helpers for tool-augmented debaters
# ---------------------------------------------------------------------------

def _get_debater_tool_schemas() -> list[dict]:
    """Return TOOL_SCHEMAS filtered to data-fetching tools only."""
    from tools import TOOL_SCHEMAS
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] not in _EXCLUDED_TOOLS]


def _msg_to_dict(msg) -> dict:
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


def _truncate_tool_result(result) -> str:
    """Serialize and truncate a tool result to keep debater context manageable."""
    text = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
    if len(text) <= MAX_DEBATER_TOOL_RESULT_CHARS:
        return text
    half = MAX_DEBATER_TOOL_RESULT_CHARS // 2
    return text[:half] + f"\n...[truncated {len(text) - MAX_DEBATER_TOOL_RESULT_CHARS} chars]...\n" + text[-half:]


def _extract_and_strip_thinking(text: str) -> tuple[str, list[str]]:
    """Extract <think> block contents and return (stripped_text, [thinking_contents])."""
    thoughts = [m.group(1).strip() for m in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL)]
    stripped = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
    return stripped, thoughts


async def _llm_call_with_tools(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    label: str,
    source: str,
    status_fn=None,
    thinking_fn=None,
) -> str:
    """Mini agent loop for debaters: up to MAX_DEBATER_TOOL_ROUNDS tool rounds, then force text."""
    tool_schemas = _get_debater_tool_schemas()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for round_idx in range(MAX_DEBATER_TOOL_ROUNDS + 1):
        # On the last round, don't offer tools — force a text response
        use_tools = round_idx < MAX_DEBATER_TOOL_ROUNDS

        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2000,
                    tools=tool_schemas if use_tools else None,
                ),
                timeout=90,
            )
        except asyncio.TimeoutError:
            return "(LLM调用超时)"
        except Exception as e:
            logger.error(f"LLM call failed ({model}): {e}")
            return f"(LLM调用失败: {e})"

        msg = resp.choices[0].message

        # Emit thinking blocks
        if msg.content and thinking_fn:
            _, thoughts = _extract_and_strip_thinking(msg.content)
            for thought in thoughts:
                await thinking_fn(source, label, thought)

        if not msg.tool_calls:
            text = msg.content or ""
            text, _ = _extract_and_strip_thinking(text)
            return text

        # Process tool calls
        msg_dict = _msg_to_dict(msg)
        messages.append(msg_dict)

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            if status_fn:
                await status_fn(f"{label} · Searching: {name}...")

            try:
                result = await _execute_tool(name, args)
            except Exception as e:
                logger.error(f"Debater tool {name} failed: {e}")
                result = {"error": str(e)}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(result),
            })

    # Shouldn't reach here, but just in case
    return messages[-1].get("content", "") if isinstance(messages[-1], dict) else ""


# ---------------------------------------------------------------------------
# Phase 2: Opening Arguments
# ---------------------------------------------------------------------------

async def _llm_call(client: AsyncOpenAI, model: str, system: str, user: str, source: str = "", label: str = "", thinking_fn=None, timeout: int = 90, max_tokens: int = 2000) -> str:
    """Make a single LLM call and return the response text."""
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )
        text = resp.choices[0].message.content or ""
        # Extract thinking and emit
        if thinking_fn:
            _, thoughts = _extract_and_strip_thinking(text)
            for thought in thoughts:
                await thinking_fn(source, label, thought)
        text, _ = _extract_and_strip_thinking(text)
        return text
    except asyncio.TimeoutError:
        return "(LLM调用超时)"
    except Exception as e:
        logger.error(f"LLM call failed ({model}): {e}")
        return f"(LLM调用失败: {e})"


async def _run_opening_round(stock_code: str, stock_name: str, data_pack: str, status_fn=None, thinking_fn=None) -> dict:
    """Run 4 parallel opening arguments: 2 bull (MiniMax+Qwen), 2 bear (MiniMax+Qwen)."""
    bull_prompt = _BULL_OPENING.format(
        stock_name=stock_name, stock_code=stock_code, data_pack=data_pack,
    )
    bear_prompt = _BEAR_OPENING.format(
        stock_name=stock_name, stock_code=stock_code, data_pack=data_pack,
    )
    system = "你是一位量化金融分析师。仅基于数据进行分析。禁止使用主观形容词。每个论点必须附带具体数字。"

    bull_a, bull_b, bear_a, bear_b = await asyncio.gather(
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, bull_prompt,
                             label="Bull Analyst A (MiniMax)", source="bull_a",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, bull_prompt,
                             label="Bull Analyst B (Qwen)", source="bull_b",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, bear_prompt,
                             label="Bear Analyst A (MiniMax)", source="bear_a",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, bear_prompt,
                             label="Bear Analyst B (Qwen)", source="bear_b",
                             status_fn=status_fn, thinking_fn=thinking_fn),
    )

    return {
        "bull_a": bull_a,   # MiniMax bull
        "bull_b": bull_b,   # Qwen bull
        "bear_a": bear_a,   # MiniMax bear
        "bear_b": bear_b,   # Qwen bear
    }


# ---------------------------------------------------------------------------
# Phase 3: Rebuttals
# ---------------------------------------------------------------------------

async def _run_rebuttal_round(
    stock_code: str, stock_name: str, data_pack: str, openings: dict,
    status_fn=None, thinking_fn=None,
) -> dict:
    """Each debater rebuts the opposing side, sees ally's argument."""
    system = "你是一位量化金融分析师。请核查对方数据的准确性和完整性。仅用数据回应，禁止情绪化措辞。"

    # Bull-A rebuts bears, sees Bull-B as ally
    bull_a_rebuttal = _REBUTTAL.format(
        side="看多 (bull)", stock_name=stock_name, stock_code=stock_code,
        opposing_args=f"--- 看空分析师1 ---\n{openings['bear_a']}\n\n--- 看空分析师2 ---\n{openings['bear_b']}",
        ally_arg=openings["bull_b"], data_pack=data_pack,
    )
    # Bull-B rebuts bears, sees Bull-A as ally
    bull_b_rebuttal = _REBUTTAL.format(
        side="看多 (bull)", stock_name=stock_name, stock_code=stock_code,
        opposing_args=f"--- 看空分析师1 ---\n{openings['bear_a']}\n\n--- 看空分析师2 ---\n{openings['bear_b']}",
        ally_arg=openings["bull_a"], data_pack=data_pack,
    )
    # Bear-A rebuts bulls, sees Bear-B as ally
    bear_a_rebuttal = _REBUTTAL.format(
        side="看空 (bear)", stock_name=stock_name, stock_code=stock_code,
        opposing_args=f"--- 看多分析师1 ---\n{openings['bull_a']}\n\n--- 看多分析师2 ---\n{openings['bull_b']}",
        ally_arg=openings["bear_b"], data_pack=data_pack,
    )
    # Bear-B rebuts bulls, sees Bear-A as ally
    bear_b_rebuttal = _REBUTTAL.format(
        side="看空 (bear)", stock_name=stock_name, stock_code=stock_code,
        opposing_args=f"--- 看多分析师1 ---\n{openings['bull_a']}\n\n--- 看多分析师2 ---\n{openings['bull_b']}",
        ally_arg=openings["bear_a"], data_pack=data_pack,
    )

    r_bull_a, r_bull_b, r_bear_a, r_bear_b = await asyncio.gather(
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, bull_a_rebuttal,
                             label="Bull Analyst A (MiniMax) Rebuttal", source="bull_a_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, bull_b_rebuttal,
                             label="Bull Analyst B (Qwen) Rebuttal", source="bull_b_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, bear_a_rebuttal,
                             label="Bear Analyst A (MiniMax) Rebuttal", source="bear_a_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, bear_b_rebuttal,
                             label="Bear Analyst B (Qwen) Rebuttal", source="bear_b_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
    )

    return {
        "bull_a": r_bull_a,
        "bull_b": r_bull_b,
        "bear_a": r_bear_a,
        "bear_b": r_bear_b,
    }


# ---------------------------------------------------------------------------
# Phase 4: Anonymized Judge
# ---------------------------------------------------------------------------

async def _run_judge(
    openings: dict, rebuttals: dict, data_pack: str, stock_name: str,
    thinking_fn=None,
) -> str:
    """Shuffle all 8 arguments anonymously and have MiniMax judge."""
    # Build labeled arguments with random order
    arguments = [
        ("看多开场", openings["bull_a"]),
        ("看多开场", openings["bull_b"]),
        ("看空开场", openings["bear_a"]),
        ("看空开场", openings["bear_b"]),
        ("看多反驳", rebuttals["bull_a"]),
        ("看多反驳", rebuttals["bull_b"]),
        ("看空反驳", rebuttals["bear_a"]),
        ("看空反驳", rebuttals["bear_b"]),
    ]
    random.shuffle(arguments)

    formatted = []
    for i, (phase, text) in enumerate(arguments, 1):
        formatted.append(f"=== 分析师 {i} ({phase}) ===\n{text}")

    all_arguments = "\n\n".join(formatted)

    # Build a short data summary for the judge (just quote data)
    data_summary = data_pack[:3000] if len(data_pack) > 3000 else data_pack

    judge_prompt = _JUDGE.format(
        data_summary=data_summary,
        all_arguments=all_arguments,
    )

    system = (
        "你是一位量化投资委员会主席。所有分析均匿名呈现。"
        "仅根据数据准确性、数据完整性和数字一致性进行判断。"
        "忽略任何修辞手法或情绪化表述。不要默认选择HOLD。"
    )

    verdict_text = await _llm_call(minimax_client, MINIMAX_MODEL, system, judge_prompt,
                                    source="judge", label="Judge (MiniMax)", thinking_fn=thinking_fn)
    return verdict_text


# ---------------------------------------------------------------------------
# Phase 5: Executive Summary
# ---------------------------------------------------------------------------

_SUMMARY = """You are a senior research editor. Below is the complete output of a multi-analyst debate on {stock_name} ({stock_code}), including the committee verdict.

Your task: produce an institutional-quality executive summary that a portfolio manager can read in 2 minutes.

Structure EXACTLY as follows (in Chinese):

## 执行摘要

一句话结论 (BUY/SELL/HOLD + 置信度 + 核心理由)。

## 关键财务指标

| 指标 | 数值 | 同比/趋势 |
|------|------|-----------|
(Fill 8-12 rows from the data: PE, PB, 股息率, 营收, 净利润, ROE, 资产负债率, OCF/净利润, 主力资金净流入, 净资产, etc. Use exact numbers.)

## 多方核心论据 (数据支撑)

3-5 bullet points. Each bullet: one sentence with specific number.

## 空方核心论据 (数据支撑)

3-5 bullet points. Each bullet: one sentence with specific number.

## 争议焦点与数据分歧

List 2-3 specific data points where bull and bear analysts disagreed, noting both interpretations.

## 风险因素

3-4 bullet points of measurable risks with specific thresholds.

## 结论与建议

2-3 sentences. Restate verdict with the key numbers that drive it. Include time horizon.

Rules:
- Every bullet point must contain at least one specific number.
- No adjectives like "强劲", "令人担忧", "优秀". Numbers only.
- Do not repeat the judge verdict verbatim — synthesize and restructure.
- 800-1200 words total.
- Write in the same language as the debate content and data provided.

=== JUDGE VERDICT ===
{verdict}

=== BULL OPENING (Analyst A) ===
{bull_a}

=== BULL OPENING (Analyst B) ===
{bull_b}

=== BEAR OPENING (Analyst A) ===
{bear_a}

=== BEAR OPENING (Analyst B) ===
{bear_b}

=== BULL REBUTTAL (Analyst A) ===
{rebuttal_bull_a}

=== BULL REBUTTAL (Analyst B) ===
{rebuttal_bull_b}

=== BEAR REBUTTAL (Analyst A) ===
{rebuttal_bear_a}

=== BEAR REBUTTAL (Analyst B) ===
{rebuttal_bear_b}

=== KEY MARKET DATA ===
{data_summary}"""


async def _run_summary(
    stock_code: str, stock_name: str, data_pack: str,
    openings: dict, rebuttals: dict, verdict: str,
    thinking_fn=None,
) -> str:
    """Produce an executive summary synthesizing the entire debate."""
    data_summary = data_pack[:4000] if len(data_pack) > 4000 else data_pack

    prompt = _SUMMARY.format(
        stock_name=stock_name, stock_code=stock_code,
        verdict=verdict,
        bull_a=openings["bull_a"], bull_b=openings["bull_b"],
        bear_a=openings["bear_a"], bear_b=openings["bear_b"],
        rebuttal_bull_a=rebuttals["bull_a"], rebuttal_bull_b=rebuttals["bull_b"],
        rebuttal_bear_a=rebuttals["bear_a"], rebuttal_bear_b=rebuttals["bear_b"],
        data_summary=data_summary,
    )

    system = (
        "你是一位机构研究部主编。将辩论结果提炼为结构化的执行摘要。"
        "仅陈述事实和数据。禁止使用主观形容词。"
    )

    return await _llm_call(
        minimax_client, MINIMAX_MODEL, system, prompt,
        source="summary", label="Summary Editor (MiniMax)",
        thinking_fn=thinking_fn,
        timeout=120, max_tokens=3000,
    )


# ---------------------------------------------------------------------------
# Phase 6: Report Generation (MD + PDF)
# ---------------------------------------------------------------------------

_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)


def _build_report_markdown(
    stock_code: str, stock_name: str,
    openings: dict, rebuttals: dict, verdict: str,
    summary: str,
) -> str:
    """Build an institutional-quality markdown report."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {stock_name} ({stock_code}) 投资分析报告",
        f"",
        f"**日期:** {ts}  ",
        f"**分析方法:** 多模型对抗辩论 (MiniMax + Qwen, 4位分析师 + 独立评审)  ",
        f"**免责声明:** 本报告由AI生成，仅供参考，不构成投资建议。",
        f"",
        f"---",
        f"",
        # Part 1: Executive Summary (the new Phase 5 output)
        summary,
        f"",
        f"---",
        f"",
        # Part 2: Committee Verdict
        f"## 投资委员会评审意见",
        f"",
        verdict,
        f"",
        f"---",
        f"",
        # Part 3: Full Analyst Arguments
        f"# 附录: 完整分析师论述",
        f"",
        f"## A.1 看多分析 — 分析师A",
        f"",
        openings["bull_a"],
        f"",
        f"## A.2 看多分析 — 分析师B",
        f"",
        openings["bull_b"],
        f"",
        f"## A.3 看空分析 — 分析师A",
        f"",
        openings["bear_a"],
        f"",
        f"## A.4 看空分析 — 分析师B",
        f"",
        openings["bear_b"],
        f"",
        f"## A.5 交叉质证 — 看多分析师A",
        f"",
        rebuttals["bull_a"],
        f"",
        f"## A.6 交叉质证 — 看多分析师B",
        f"",
        rebuttals["bull_b"],
        f"",
        f"## A.7 交叉质证 — 看空分析师A",
        f"",
        rebuttals["bear_a"],
        f"",
        f"## A.8 交叉质证 — 看空分析师B",
        f"",
        rebuttals["bear_b"],
    ]
    return "\n".join(lines)


async def _generate_report(
    stock_code: str, stock_name: str,
    openings: dict, rebuttals: dict, verdict: str,
    summary: str,
) -> list[str]:
    """Generate MD + PDF report files. Returns list of file paths."""
    from tools.output import generate_pdf

    md_content = _build_report_markdown(
        stock_code, stock_name, openings, rebuttals, verdict, summary,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{stock_name}_{ts}"

    # Save markdown
    md_path = os.path.join(_OUTPUT_DIR, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Generate PDF using existing generate_pdf tool
    title = f"{stock_name} ({stock_code}) 投资分析报告"
    try:
        pdf_result = await generate_pdf(title=title, content=md_content)
        pdf_orig = pdf_result.get("file", "")
        # Rename to match our naming convention
        pdf_path = os.path.join(_OUTPUT_DIR, f"{base_name}.pdf")
        if pdf_orig and os.path.exists(pdf_orig):
            os.rename(pdf_orig, pdf_path)
        else:
            pdf_path = ""
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        pdf_path = ""

    files = [md_path]
    if pdf_path:
        files.append(pdf_path)

    return files


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

async def analyze_trade_opportunity(stock_code: str, context: str = "") -> dict:
    """Run multi-LLM debate analysis for a stock. Returns structured report."""
    # Get callbacks from contextvars (set by agent.py)
    from agent import status_callback, thinking_callback
    _emit = status_callback.get(None)
    _think = thinking_callback.get(None)

    async def _status(text: str):
        if _emit:
            try:
                await _emit(text)
            except Exception:
                pass

    async def _thinking(source: str, label: str, content: str):
        if _think:
            try:
                await _think(source, label, content)
            except Exception:
                pass

    logger.info(f"[TradeAnalyzer] Starting debate analysis for {stock_code}")

    # Phase 1: Data collection
    await _status("Collecting market data...")
    logger.info(f"[TradeAnalyzer] Phase 1: Collecting data for {stock_code}")
    data_pack, stock_name = await _collect_data(stock_code, context)
    logger.info(f"[TradeAnalyzer] Data collected: {stock_name} ({len(data_pack)} chars)")

    # Phase 2: Opening arguments
    await _status("MiniMax + Qwen · Opening arguments (4 analysts)...")
    logger.info(f"[TradeAnalyzer] Phase 2: Opening arguments (4 parallel LLM calls)")
    openings = await _run_opening_round(stock_code, stock_name, data_pack,
                                         status_fn=_status, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Opening arguments complete")

    # Phase 3: Rebuttals
    await _status("MiniMax + Qwen · Rebuttals (4 analysts)...")
    logger.info(f"[TradeAnalyzer] Phase 3: Rebuttals (4 parallel LLM calls)")
    rebuttals = await _run_rebuttal_round(stock_code, stock_name, data_pack, openings,
                                           status_fn=_status, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Rebuttals complete")

    # Phase 4: Judge
    await _status("MiniMax · Judge rendering verdict...")
    logger.info(f"[TradeAnalyzer] Phase 4: Judge (1 LLM call)")
    verdict = await _run_judge(openings, rebuttals, data_pack, stock_name, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Judge verdict rendered")

    # Phase 5: Executive Summary
    await _status("MiniMax · Synthesizing executive summary...")
    logger.info("[TradeAnalyzer] Phase 5: Executive summary (1 LLM call)")
    summary = await _run_summary(stock_code, stock_name, data_pack, openings, rebuttals, verdict, thinking_fn=_thinking)
    # Graceful fallback if summary generation failed
    if summary.startswith("(LLM") or summary.startswith("("):
        logger.warning(f"[TradeAnalyzer] Summary failed: {summary}, using verdict as fallback")
        summary = verdict
    logger.info("[TradeAnalyzer] Executive summary complete")

    # Phase 6: Generate MD + PDF report
    await _status("Generating report...")
    files = await _generate_report(stock_code, stock_name, openings, rebuttals, verdict, summary)
    logger.info(f"[TradeAnalyzer] Report generated: {files}")

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "verdict": verdict,
        "summary": summary,
        "files": files,
        "debate_log": {
            "opening_bull_a": openings["bull_a"],
            "opening_bull_b": openings["bull_b"],
            "opening_bear_a": openings["bear_a"],
            "opening_bear_b": openings["bear_b"],
            "rebuttal_bull_a": rebuttals["bull_a"],
            "rebuttal_bull_b": rebuttals["bull_b"],
            "rebuttal_bear_a": rebuttals["bear_a"],
            "rebuttal_bear_b": rebuttals["bear_b"],
        },
    }
