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
MAX_DEBATER_TOOL_RESULT_CHARS = 25000

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
            "4 analysts (2 pro, 2 con) argue with evidence, then a judge synthesizes. "
            "Use when user asks for trade analysis, 'should I buy/sell X', '值得买吗', "
            "'投资分析', stock comparisons, sector analysis, or any investment question. "
            "Takes ~30-60 seconds. Returns structured verdict with confidence score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "6-digit A-share stock code (e.g. '600036'). Optional if question is provided.",
                },
                "question": {
                    "type": "string",
                    "description": "Investment question to debate (e.g. '招商银行 vs 工商银行哪个更好', '银行板块还会涨吗'). If omitted, defaults to '{stock_code} 值得投资吗?'",
                },
                "context": {
                    "type": "string",
                    "description": "Optional: existing data/analysis from conversation to avoid re-fetching",
                },
            },
            "required": [],
        },
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# Shared unit conversion rule — added to every debater/judge/summary prompt.
_UNIT_RULE = """- CRITICAL UNIT CONVERSION: 1 billion = 10亿, NOT 1亿. Data in the pack may use raw numbers (e.g. 170,750,000,000 = 1707.5亿). When the data says "XXX billion", multiply by 10 to get 亿. Examples:
  - 170.75 billion CNY = 1707.5亿元 (NOT 170.75亿)
  - 41.15 billion = 411.5亿 (NOT 41.15亿)
  - 1,322,800,000,000 = 13228亿 (÷ 100,000,000)
  - Unit: 万元 means 10,000 CNY. 13,228,000万元 = 1322.8亿元.
  Always double-check your unit conversions before citing a number."""

_PRO_OPENING = """You are a quantitative analyst. Your task: identify data points that SUPPORT the following hypothesis:
**H₀: {hypothesis}**

{dimensions_text}

You have access to research tools (web search, financial data lookups). Use them only when the provided data lacks a specific number you need.

Rules:
- Every claim must cite a specific number: "营收同比+15.3%至42.1亿元 (Q3 2025)" — never "营收在增长".
- No adjectives like "强劲", "优秀", "令人印象深刻". State the number and let it speak.
- Where data is unfavorable to the hypothesis, state it factually. Do not minimize or explain away.
- End with: KEY EVIDENCE SUMMARY (the 3 strongest data points supporting H₀) and CONVICTION LEVEL (1-10).
- 600-800 words. **You MUST write your entire response in {response_language}**, including all headings, analysis, and conclusions. Maintain a neutral, clinical tone throughout.
""" + _UNIT_RULE + """

=== DATA ===
{data_pack}"""

_CON_OPENING = """You are a quantitative risk analyst. Your task: identify data points that REJECT the following hypothesis:
**H₀: {hypothesis}**

{dimensions_text}

You have access to research tools (web search, financial data lookups). Use them only when the provided data lacks a specific number you need.

Rules:
- Every claim must cite a specific number: "净利率从28.1%降至22.4% (连续4个季度)" — never "利润率在下降".
- No adjectives like "令人担忧", "严重", "危险". State the number and let it speak.
- Where data actually supports the hypothesis, state it factually. Do not dismiss or undermine.
- End with: KEY COUNTER-EVIDENCE (the 3 strongest data points against H₀) and CONVICTION LEVEL (1-10).
- 600-800 words. **You MUST write your entire response in {response_language}**, including all headings, analysis, and conclusions. Maintain a neutral, clinical tone throughout.
""" + _UNIT_RULE + """

=== DATA ===
{data_pack}"""

_DIMENSIONS_SINGLE_STOCK = """逐一分析以下维度，每个维度需给出具体数据，计算相关比率或趋势。

1. 收入结构与驱动力: 主要收入来源（分行业/分产品/分地区）各占比多少？哪些业务在增长、哪些在萎缩？增长驱动力是量还是价？对于银行：利息净收入、手续费收入、投资收益各占比及变化趋势。
2. 宏观敏感性: 该公司收入结构对利率/汇率/行业周期/政策的暴露程度。例如：利率下行对银行净息差的影响，出口依赖型企业对汇率的敏感度。引用历史数据量化。
3. 估值分析: 当前PE/PB与近5年历史区间和行业中位数对比，百分位排名。
4. 盈利趋势: 营收和净利润的环比/同比增速，增长是在加速、稳定还是减速？引用具体数字。
5. 资产负债: 资产负债率趋势、流动比率、现金头寸，标记任何恶化迹象。
6. 现金流: 经营现金流/净利润比率（盈利质量），近4个季度自由现金流趋势。
7. 资金流向: 机构净流入/流出方向及规模，量化描述。
8. 股东变动: 前十大股东持仓变化——增持/减持/新进，净方向判断。
9. 分红: 近12个月股息率、派息率、近3年以上的分红连续性。
10. 前瞻展望: 基于收入结构和宏观环境，哪些业务线可能受益或承压？量化推演。
11. 社区情绪 (仅供参考): 数据包中包含来自东方财富股吧的散户讨论摘要。简要引用其整体情绪（看涨/看跌/中性）和核心主题。你可以接受或质疑该情绪信号——如与基本面相符则说明原因，如相悖则给出数据反驳。散户情绪不得作为主要论据，但必须被提及。"""

_DIMENSIONS_COMPARISON = """逐维度比较两个标的，每个维度需引用双方的具体数据。

1. 收入结构对比: 各自主要收入来源（分行业/分产品）占比，哪些业务驱动增长？收入多元化程度对比。
2. 宏观敏感性对比: 各自收入结构对利率/汇率/政策的暴露程度差异，哪个更具防御性？
3. 估值对比: 各自的PE/PB，哪个折价/溢价？差距多大？
4. 盈利对比: 各自的营收和利润增速，哪个趋势更好？
5. 资产负债对比: 各自的资产负债率和杠杆水平，哪个财务状况更稳健？
6. 现金流对比: 各自的经营现金流/净利润比率，哪个盈利质量更高？
7. 资金流向对比: 机构资金流入对比，哪个获得更多净流入？
8. 股东变动对比: 各自前十大股东持仓变化，净方向对比。
9. 分红对比: 各自股息率和可持续性，哪个股东回报更好？
10. 综合优劣: 基于收入结构和宏观环境，各自的结构性优势和劣势？
11. 社区情绪对比 (仅供参考): 引用数据包中两个标的的股吧散户情绪，对比哪个情绪更积极。简述情绪是否与基本面一致，可接受或质疑该信号，但必须提及。"""

_DIMENSIONS_SECTOR = """分析该板块/市场的以下维度:

1. 估值水平: 板块平均PE/PB与历史区间对比，当前处于周期什么位置？
2. 盈利趋势: 板块整体营收/利润增速，是在加速还是减速？
3. 资金流向: 机构和北向资金的板块流入/流出情况，量化描述。
4. 市场结构: 哪些个股领涨/领跌？涨跌集中度如何？
5. 催化因素: 有数据支撑的板块驱动因素——政策、利率、宏观指标。
6. 风险因素: 数据可量化的逆风因素。

"""

_DIMENSIONS_GENERAL = """从以下维度分析该问题:

1. 估值水平: 相关市场/板块估值与历史区间对比。
2. 宏观指标: 利率、资金流向、相关经济数据。
3. 市场情绪: 机构持仓和资金流向数据，量化描述。
4. 历史规律: 过去类似数据模式及其结果。
5. 风险因素: 数据可量化的风险。
6. 机会信号: 支持该论点的数据点。"""


def _get_dimensions_text(question_type: str) -> str:
    """Return the appropriate dimensions text based on question type."""
    return {
        "single_stock": _DIMENSIONS_SINGLE_STOCK,
        "comparison": _DIMENSIONS_COMPARISON,
        "sector": _DIMENSIONS_SECTOR,
        "general": _DIMENSIONS_GENERAL,
    }.get(question_type, _DIMENSIONS_GENERAL)

_REBUTTAL = """You previously analyzed data {side} the hypothesis:
**H₀: {hypothesis}**

Below are the opposing analysts' findings, followed by your co-analyst's findings.

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
- 300-500 words. **You MUST write your entire response in {response_language}**. Maintain a neutral, clinical tone.
""" + _UNIT_RULE + """

=== ORIGINAL DATA FOR REFERENCE ===
{data_pack}"""

_JUDGE = """You are a quantitative portfolio committee chair. You have received analysis from 4 anonymous analysts — 2 supporting a hypothesis, 2 rejecting it — followed by their cross-examination.

**Hypothesis under review (H₀): {hypothesis}**

Your task: Determine whether the data supports or rejects H₀, based SOLELY on factual accuracy and data completeness.

Evaluation criteria (in order of importance):
1. DATA ACCURACY: Which analysts cited verifiable numbers? Flag any claims that lack specific figures.
2. COMPLETENESS: Which side addressed more analysis dimensions with actual data?
3. CONSISTENCY: Do the cited numbers agree with each other and with the raw data summary?
4. CROSS-EXAMINATION: Did the rebuttals identify real data errors, or were they rhetorical?

Disregard: emotional language, rhetorical flourish, unsubstantiated predictions, appeals to market sentiment.

You MUST produce a response in EXACTLY this structure (**write entirely in {response_language}**):

**判定: {verdict_option_1} / {verdict_option_2} / {verdict_option_3}**
(Choose the third option only if both sides have equal data support — not as a safe default)

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

""" + _UNIT_RULE + """

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
    pattern = os.path.join(_get_output_dir(), f"{stock_name}_*.md")
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
# Phase 0: Hypothesis Formation
# ---------------------------------------------------------------------------

_HYPOTHESIS_PROMPT = """You are a research analyst assistant. Given a user's investment question, form a testable hypothesis and a data collection plan.

Available data-fetching tools (name → parameters):
- web_search(query: str)
- scrape_webpage(url: str)
- fetch_cn_stock_data(symbol: str, info_type: "quote"|"history", period?: "daily"|"weekly"|"monthly", days?: int)
- fetch_multiple_cn_stocks(symbols: list[str], info_type: "quote"|"history")
- fetch_stock_financials(stock_code: str, statement: "balance"|"income"|"cashflow", periods?: int)
- fetch_top_shareholders(stock_code: str, periods?: int)
- fetch_dividend_history(stock_code: str)
- fetch_stock_capital_flow(stock_code: str, days?: int)
- fetch_northbound_flow(days?: int)
- fetch_capital_flow_ranking(direction?: "inflow"|"outflow", limit?: int)
- scan_market_hotspots()
- screen_cn_stocks(sort_by?: str, sort_order?: "desc"|"asc", limit?: int, filters?: list)
- fetch_company_report(stock_code: str, report_type: "yearly"|"q1"|"mid"|"q3")
- fetch_sina_profit_statement(stock_code: str, year?: int)
- fetch_dragon_tiger(stock_code: str, limit?: int)
- fetch_cn_bond_data(bond_type: "treasury_yield"|"corporate")
- fetch_stock_data(symbol: str, info_type: "quote"|"history"|"financials", period?: str) — for US stocks
- fetch_multiple_stocks(symbols: list[str], info_type: "quote"|"history") — for US stocks

EXAMPLES:

Example 1 — Single stock question:
Question: "浦发银行值得投资吗"
{
  "hypothesis": "浦发银行当前估值下值得投资",
  "question_type": "single_stock",
  "entities": [{"type": "stock", "code": "600000", "name": "浦发银行"}],
  "data_plan": [
    {"tool": "fetch_company_report", "args": {"stock_code": "600000", "report_type": "yearly"}},
    {"tool": "fetch_company_report", "args": {"stock_code": "600000", "report_type": "mid"}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600000", "statement": "income", "periods": 8}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600000", "statement": "balance", "periods": 4}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600000", "statement": "cashflow", "periods": 4}},
    {"tool": "fetch_cn_stock_data", "args": {"symbol": "600000", "info_type": "quote"}},
    {"tool": "fetch_stock_capital_flow", "args": {"stock_code": "600000", "days": 20}},
    {"tool": "fetch_top_shareholders", "args": {"stock_code": "600000", "periods": 2}},
    {"tool": "fetch_dividend_history", "args": {"stock_code": "600000"}}
  ],
  "pro_framing": "支持假设：浦发银行当前估值下值得投资",
  "con_framing": "反对假设：浦发银行当前不值得投资",
  "verdict_options": ["支持H₀ (买入)", "反对H₀ (回避)", "证据不足 (观望)"],
  "report_title": "浦发银行 (600000) 投资分析报告"
}

Example 2 — Stock comparison:
Question: "招商银行和工商银行哪个更值得投资"
{
  "hypothesis": "招商银行比工商银行更值得投资",
  "question_type": "comparison",
  "entities": [{"type": "stock", "code": "600036", "name": "招商银行"}, {"type": "stock", "code": "601398", "name": "工商银行"}],
  "data_plan": [
    {"tool": "fetch_company_report", "args": {"stock_code": "600036", "report_type": "yearly"}},
    {"tool": "fetch_company_report", "args": {"stock_code": "601398", "report_type": "yearly"}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600036", "statement": "income", "periods": 8}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600036", "statement": "balance", "periods": 4}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "600036", "statement": "cashflow", "periods": 4}},
    {"tool": "fetch_cn_stock_data", "args": {"symbol": "600036", "info_type": "quote"}},
    {"tool": "fetch_stock_capital_flow", "args": {"stock_code": "600036", "days": 20}},
    {"tool": "fetch_top_shareholders", "args": {"stock_code": "600036", "periods": 2}},
    {"tool": "fetch_dividend_history", "args": {"stock_code": "600036"}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "601398", "statement": "income", "periods": 8}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "601398", "statement": "balance", "periods": 4}},
    {"tool": "fetch_stock_financials", "args": {"stock_code": "601398", "statement": "cashflow", "periods": 4}},
    {"tool": "fetch_cn_stock_data", "args": {"symbol": "601398", "info_type": "quote"}},
    {"tool": "fetch_stock_capital_flow", "args": {"stock_code": "601398", "days": 20}},
    {"tool": "fetch_top_shareholders", "args": {"stock_code": "601398", "periods": 2}},
    {"tool": "fetch_dividend_history", "args": {"stock_code": "601398"}}
  ],
  "pro_framing": "支持假设：招商银行比工商银行更值得投资",
  "con_framing": "反对假设：工商银行比招商银行更值得投资",
  "verdict_options": ["支持H₀ (招商银行更优)", "反对H₀ (工商银行更优)", "证据不足 (两者相当)"],
  "report_title": "招商银行 vs 工商银行 对比分析报告"
}

Example 3 — Sector analysis:
Question: "银行板块还会涨吗"
{
  "hypothesis": "银行板块将继续上涨",
  "question_type": "sector",
  "entities": [{"type": "sector", "name": "银行板块"}],
  "data_plan": [
    {"tool": "screen_cn_stocks", "args": {"filters": [{"field": "sector", "op": "equal", "value": "银行"}], "sort_by": "market_cap_basic", "limit": 10}},
    {"tool": "scan_market_hotspots", "args": {}},
    {"tool": "fetch_northbound_flow", "args": {"days": 30}},
    {"tool": "fetch_capital_flow_ranking", "args": {"direction": "inflow", "limit": 20}},
    {"tool": "web_search", "args": {"query": "银行板块 走势 分析 2025"}}
  ],
  "pro_framing": "支持假设：银行板块将继续上涨",
  "con_framing": "反对假设：银行板块上涨动力不足或将回调",
  "verdict_options": ["支持H₀ (看涨)", "反对H₀ (看跌/回调)", "证据不足 (方向不明)"],
  "report_title": "银行板块走势分析报告"
}

Example 4 — General market question:
Question: "现在适合抄底吗"
{
  "hypothesis": "当前市场处于底部区域，适合买入",
  "question_type": "general",
  "entities": [{"type": "market", "name": "A股市场"}],
  "data_plan": [
    {"tool": "scan_market_hotspots", "args": {}},
    {"tool": "fetch_northbound_flow", "args": {"days": 30}},
    {"tool": "fetch_capital_flow_ranking", "args": {"direction": "inflow", "limit": 20}},
    {"tool": "fetch_cn_bond_data", "args": {"bond_type": "treasury_yield"}},
    {"tool": "screen_cn_stocks", "args": {"sort_by": "change_from_open", "sort_order": "asc", "limit": 20}},
    {"tool": "web_search", "args": {"query": "A股 市场 估值 底部 分析 2025"}}
  ],
  "pro_framing": "支持假设：当前市场处于底部，适合买入",
  "con_framing": "反对假设：市场尚未见底，不适合买入",
  "verdict_options": ["支持H₀ (适合买入)", "反对H₀ (继续观望)", "证据不足 (方向不明)"],
  "report_title": "A股市场抄底时机分析报告"
}

RULES:
- Output valid JSON only, no other text.
- The hypothesis must be a concrete, testable statement (not a question).
- data_plan: max 20 tool calls. Choose tools relevant to the question type.
- For single_stock: ALWAYS include fetch_company_report(yearly) + fetch_company_report(mid or q3) for the full annual report (contains revenue breakdown, segment analysis, management discussion). Then add income/balance/cashflow/quote/capital_flow/shareholders/dividends.
- For comparison: include fetch_company_report(yearly) for each stock, plus the standard tools for each.
- For sector/general: use screener, hotspots, flows, and web search.
- pro_framing and con_framing should be concise instructions for the analysts.
- verdict_options must have exactly 3 options.
- report_title should be descriptive and in the same language as the question.
- Match the language of the user's question for hypothesis, framings, and title.
- Include a "response_language" field: the language the user wrote in (e.g. "中文", "English", "日本語").

USER QUESTION: __QUESTION__
"""


async def _form_hypothesis(user_question: str, context: str = "", thinking_fn=None) -> dict:
    """Phase 0: Parse user question into a testable hypothesis and data plan."""
    prompt = _HYPOTHESIS_PROMPT.replace("__QUESTION__", user_question)
    if context:
        prompt += f"\n\nADDITIONAL CONTEXT FROM CONVERSATION:\n{context[:2000]}"

    system = "You are a structured data extraction assistant. Output valid JSON only."

    raw = await _llm_call(
        minimax_client, MINIMAX_MODEL, system, prompt,
        source="hypothesis", label="Hypothesis Formation",
        thinking_fn=thinking_fn, timeout=60, max_tokens=2000,
    )

    # Parse JSON from response (handle markdown code fences)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        hypothesis = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"[TradeAnalyzer] Failed to parse hypothesis JSON: {raw[:500]}")
        # Fallback: treat the whole question as a single stock if we can extract a code
        code_match = re.search(r"(?<!\d)\d{6}(?!\d)", user_question)
        stock_code = code_match.group(0) if code_match else "000001"
        hypothesis = {
            "hypothesis": f"{user_question}",
            "question_type": "single_stock",
            "entities": [{"type": "stock", "code": stock_code, "name": stock_code}],
            "data_plan": [
                {"tool": "fetch_stock_financials", "args": {"stock_code": stock_code, "statement": "income", "periods": 8}},
                {"tool": "fetch_stock_financials", "args": {"stock_code": stock_code, "statement": "balance", "periods": 4}},
                {"tool": "fetch_stock_financials", "args": {"stock_code": stock_code, "statement": "cashflow", "periods": 4}},
                {"tool": "fetch_cn_stock_data", "args": {"symbol": stock_code, "info_type": "quote"}},
                {"tool": "fetch_stock_capital_flow", "args": {"stock_code": stock_code, "days": 20}},
                {"tool": "fetch_top_shareholders", "args": {"stock_code": stock_code, "periods": 2}},
                {"tool": "fetch_dividend_history", "args": {"stock_code": stock_code}},
            ],
            "pro_framing": f"支持: {user_question}",
            "con_framing": f"反对: {user_question}",
            "verdict_options": ["支持H₀ (买入)", "反对H₀ (回避)", "证据不足 (观望)"],
            "report_title": f"{user_question} 分析报告",
        }

    # Validate and cap data_plan
    if "data_plan" in hypothesis:
        hypothesis["data_plan"] = hypothesis["data_plan"][:20]

    logger.info(f"[TradeAnalyzer] Hypothesis formed: {hypothesis.get('hypothesis', '')}")
    logger.info(f"[TradeAnalyzer] Question type: {hypothesis.get('question_type', 'unknown')}, "
                f"Data plan: {len(hypothesis.get('data_plan', []))} tool calls")

    return hypothesis


async def _collect_data_from_plan(
    data_plan: list[dict], context: str = "", entities: list[dict] | None = None,
) -> str:
    """Execute a data collection plan in parallel. Returns formatted data pack string."""
    if not data_plan:
        return "(No data plan provided)"

    # Execute all tools from data_plan in parallel
    async def _run_one(item: dict):
        tool_name = item.get("tool", "")
        args = item.get("args", {})
        label = f"{tool_name}({', '.join(f'{k}={v}' for k, v in args.items())})"
        try:
            result = await _execute_tool(tool_name, args)
            return label, result
        except Exception as e:
            logger.warning(f"Data plan tool {tool_name} failed: {e}")
            return label, {"error": str(e)}

    results = await asyncio.gather(*[_run_one(item) for item in data_plan], return_exceptions=True)

    # Format results into sections
    sections = []
    for r in results:
        if isinstance(r, Exception):
            sections.append(f"### (tool failed)\n{r}")
        else:
            label, data = r
            sections.append(f"### {label}\n{_format_data(data)}")

    if context:
        sections.append(f"### 补充信息 (来自对话上下文)\n{context}")

    # Check for prior reports matching any entity
    if entities:
        for entity in entities:
            name = entity.get("name", "")
            if name:
                prior = _find_prior_report(name)
                if prior:
                    sections.append(
                        f"### PRIOR ANALYSIS for {name} (reference only)\n"
                        "A previous report is shown below. "
                        "You may use specific data points if still relevant, "
                        "but do NOT treat it as authoritative. Always verify against fresh data.\n\n"
                        f"{prior}"
                    )
                    break  # Only include one prior report

    data_pack = "\n\n".join(sections)

    # Truncate if too long — generous limit for 200k context window
    if len(data_pack) > 100000:
        data_pack = data_pack[:100000] + "\n...[数据已截断]"

    return data_pack


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
                    max_tokens=4000,
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

async def _llm_call(client: AsyncOpenAI, model: str, system: str, user: str, source: str = "", label: str = "", thinking_fn=None, timeout: int = 90, max_tokens: int = 3000) -> str:
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


async def _run_opening_round(hypothesis: dict, data_pack: str, status_fn=None, thinking_fn=None) -> dict:
    """Run 4 parallel opening arguments: 2 pro-H₀ (MiniMax+Qwen), 2 con-H₀ (MiniMax+Qwen)."""
    h = hypothesis.get("hypothesis", "")
    question_type = hypothesis.get("question_type", "general")
    lang = hypothesis.get("response_language", "中文")
    dimensions_text = _get_dimensions_text(question_type)

    pro_prompt = _PRO_OPENING.format(
        hypothesis=h, dimensions_text=dimensions_text, data_pack=data_pack, response_language=lang,
    )
    con_prompt = _CON_OPENING.format(
        hypothesis=h, dimensions_text=dimensions_text, data_pack=data_pack, response_language=lang,
    )
    system = "你是一位量化金融分析师。仅基于数据进行分析。禁止使用主观形容词。每个论点必须附带具体数字。注意单位换算：1 billion = 10亿，数据中的万元需÷10000得到亿元。"

    pro_a, pro_b, con_a, con_b = await asyncio.gather(
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, pro_prompt,
                             label="Pro-H₀ Analyst A (MiniMax)", source="pro_a",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, pro_prompt,
                             label="Pro-H₀ Analyst B (Qwen)", source="pro_b",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, con_prompt,
                             label="Con-H₀ Analyst A (MiniMax)", source="con_a",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, con_prompt,
                             label="Con-H₀ Analyst B (Qwen)", source="con_b",
                             status_fn=status_fn, thinking_fn=thinking_fn),
    )

    return {
        "pro_a": pro_a,   # MiniMax pro
        "pro_b": pro_b,   # Qwen pro
        "con_a": con_a,   # MiniMax con
        "con_b": con_b,   # Qwen con
    }


# ---------------------------------------------------------------------------
# Phase 3: Rebuttals
# ---------------------------------------------------------------------------

async def _run_rebuttal_round(
    hypothesis: dict, data_pack: str, openings: dict,
    status_fn=None, thinking_fn=None,
) -> dict:
    """Each debater rebuts the opposing side, sees ally's argument."""
    h = hypothesis.get("hypothesis", "")
    lang = hypothesis.get("response_language", "中文")
    system = "你是一位量化金融分析师。请核查对方数据的准确性和完整性。仅用数据回应，禁止情绪化措辞。注意单位换算：1 billion = 10亿。"

    # Pro-A rebuts cons, sees Pro-B as ally
    pro_a_rebuttal = _REBUTTAL.format(
        side="supporting (支持H₀)", hypothesis=h,
        opposing_args=f"--- 反方分析师1 ---\n{openings['con_a']}\n\n--- 反方分析师2 ---\n{openings['con_b']}",
        ally_arg=openings["pro_b"], data_pack=data_pack, response_language=lang,
    )
    # Pro-B rebuts cons, sees Pro-A as ally
    pro_b_rebuttal = _REBUTTAL.format(
        side="supporting (支持H₀)", hypothesis=h,
        opposing_args=f"--- 反方分析师1 ---\n{openings['con_a']}\n\n--- 反方分析师2 ---\n{openings['con_b']}",
        ally_arg=openings["pro_a"], data_pack=data_pack, response_language=lang,
    )
    # Con-A rebuts pros, sees Con-B as ally
    con_a_rebuttal = _REBUTTAL.format(
        side="rejecting (反对H₀)", hypothesis=h,
        opposing_args=f"--- 正方分析师1 ---\n{openings['pro_a']}\n\n--- 正方分析师2 ---\n{openings['pro_b']}",
        ally_arg=openings["con_b"], data_pack=data_pack, response_language=lang,
    )
    # Con-B rebuts pros, sees Con-A as ally
    con_b_rebuttal = _REBUTTAL.format(
        side="rejecting (反对H₀)", hypothesis=h,
        opposing_args=f"--- 正方分析师1 ---\n{openings['pro_a']}\n\n--- 正方分析师2 ---\n{openings['pro_b']}",
        ally_arg=openings["con_a"], data_pack=data_pack, response_language=lang,
    )

    r_pro_a, r_pro_b, r_con_a, r_con_b = await asyncio.gather(
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, pro_a_rebuttal,
                             label="Pro-H₀ Analyst A (MiniMax) Rebuttal", source="pro_a_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, pro_b_rebuttal,
                             label="Pro-H₀ Analyst B (Qwen) Rebuttal", source="pro_b_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(minimax_client, MINIMAX_MODEL, system, con_a_rebuttal,
                             label="Con-H₀ Analyst A (MiniMax) Rebuttal", source="con_a_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
        _llm_call_with_tools(qwen_client, QWEN_MODEL, system, con_b_rebuttal,
                             label="Con-H₀ Analyst B (Qwen) Rebuttal", source="con_b_rebuttal",
                             status_fn=status_fn, thinking_fn=thinking_fn),
    )

    return {
        "pro_a": r_pro_a,
        "pro_b": r_pro_b,
        "con_a": r_con_a,
        "con_b": r_con_b,
    }


# ---------------------------------------------------------------------------
# Phase 4: Anonymized Judge
# ---------------------------------------------------------------------------

async def _run_judge(
    hypothesis: dict, openings: dict, rebuttals: dict, data_pack: str,
    thinking_fn=None,
) -> str:
    """Shuffle all 8 arguments anonymously and have MiniMax judge."""
    h = hypothesis.get("hypothesis", "")
    lang = hypothesis.get("response_language", "中文")
    verdict_options = hypothesis.get("verdict_options", ["支持H₀", "反对H₀", "证据不足"])

    # Build labeled arguments with random order
    arguments = [
        ("正方开场 (支持H₀)", openings["pro_a"]),
        ("正方开场 (支持H₀)", openings["pro_b"]),
        ("反方开场 (反对H₀)", openings["con_a"]),
        ("反方开场 (反对H₀)", openings["con_b"]),
        ("正方反驳", rebuttals["pro_a"]),
        ("正方反驳", rebuttals["pro_b"]),
        ("反方反驳", rebuttals["con_a"]),
        ("反方反驳", rebuttals["con_b"]),
    ]
    random.shuffle(arguments)

    formatted = []
    for i, (phase, text) in enumerate(arguments, 1):
        formatted.append(f"=== 分析师 {i} ({phase}) ===\n{text}")

    all_arguments = "\n\n".join(formatted)

    # Build a short data summary for the judge (just quote data)
    data_summary = data_pack[:3000] if len(data_pack) > 3000 else data_pack

    judge_prompt = _JUDGE.format(
        hypothesis=h,
        verdict_option_1=verdict_options[0] if len(verdict_options) > 0 else "支持H₀",
        verdict_option_2=verdict_options[1] if len(verdict_options) > 1 else "反对H₀",
        verdict_option_3=verdict_options[2] if len(verdict_options) > 2 else "证据不足",
        data_summary=data_summary,
        all_arguments=all_arguments,
        response_language=lang,
    )

    system = (
        "你是一位量化投资委员会主席。所有分析均匿名呈现。"
        "仅根据数据准确性、数据完整性和数字一致性进行判断。"
        "忽略任何修辞手法或情绪化表述。不要默认选择第三个选项。"
    )

    verdict_text = await _llm_call(minimax_client, MINIMAX_MODEL, system, judge_prompt,
                                    source="judge", label="Judge (MiniMax)", thinking_fn=thinking_fn)
    return verdict_text


# ---------------------------------------------------------------------------
# Phase 5: Executive Summary
# ---------------------------------------------------------------------------

_SUMMARY = """You are a senior research editor. Below is the complete output of a multi-analyst debate on the following hypothesis, including the committee verdict.

**H₀: {hypothesis}**
**Report: {report_title}**

Your task: produce an institutional-quality executive summary that a portfolio manager can read in 2 minutes.

Structure EXACTLY as follows (**write entirely in {response_language}**):

## 执行摘要

一句话结论 (判定结果 + 置信度 + 核心理由)。

## 关键数据指标

| 指标 | 数值 | 同比/趋势 |
|------|------|-----------|
(Fill 8-12 rows from the data with the most relevant metrics. Use exact numbers.)

## 正方核心论据 (支持H₀)

3-5 bullet points. Each bullet: one sentence with specific number.

## 反方核心论据 (反对H₀)

3-5 bullet points. Each bullet: one sentence with specific number.

## 社区情绪 (股吧散户观点)

1-2 sentences. State the overall retail sentiment tone (看涨/看跌/中性) and the dominant retail narrative. Note whether it aligns with or contradicts the fundamental verdict.

## 争议焦点与数据分歧

List 2-3 specific data points where the two sides disagreed, noting both interpretations.

## 风险因素

3-4 bullet points of measurable risks with specific thresholds.

## 结论与建议

2-3 sentences. Restate verdict with the key numbers that drive it. Include time horizon.

Rules:
- Every bullet point must contain at least one specific number.
- No adjectives like "强劲", "令人担忧", "优秀". Numbers only.
- Do not repeat the judge verdict verbatim — synthesize and restructure.
- 800-1200 words total.
- **You MUST write your entire response in {response_language}**, including all headings and analysis.
""" + _UNIT_RULE + """

=== JUDGE VERDICT ===
{verdict}

=== PRO-H₀ OPENING (Analyst A) ===
{pro_a}

=== PRO-H₀ OPENING (Analyst B) ===
{pro_b}

=== CON-H₀ OPENING (Analyst A) ===
{con_a}

=== CON-H₀ OPENING (Analyst B) ===
{con_b}

=== PRO-H₀ REBUTTAL (Analyst A) ===
{rebuttal_pro_a}

=== PRO-H₀ REBUTTAL (Analyst B) ===
{rebuttal_pro_b}

=== CON-H₀ REBUTTAL (Analyst A) ===
{rebuttal_con_a}

=== CON-H₀ REBUTTAL (Analyst B) ===
{rebuttal_con_b}

=== KEY MARKET DATA ===
{data_summary}"""


async def _run_summary(
    hypothesis: dict, data_pack: str,
    openings: dict, rebuttals: dict, verdict: str,
    thinking_fn=None,
) -> str:
    """Produce an executive summary synthesizing the entire debate."""
    data_summary = data_pack[:4000] if len(data_pack) > 4000 else data_pack

    prompt = _SUMMARY.format(
        hypothesis=hypothesis.get("hypothesis", ""),
        report_title=hypothesis.get("report_title", ""),
        verdict=verdict,
        pro_a=openings["pro_a"], pro_b=openings["pro_b"],
        con_a=openings["con_a"], con_b=openings["con_b"],
        rebuttal_pro_a=rebuttals["pro_a"], rebuttal_pro_b=rebuttals["pro_b"],
        rebuttal_con_a=rebuttals["con_a"], rebuttal_con_b=rebuttals["con_b"],
        data_summary=data_summary,
        response_language=hypothesis.get("response_language", "中文"),
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

_BASE_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
os.makedirs(_BASE_OUTPUT, exist_ok=True)


def _get_output_dir() -> str:
    """Return per-user output dir if user context is set, else base output dir."""
    try:
        from agent import user_id_context
        uid = user_id_context.get(None)
        if uid:
            d = os.path.join(_BASE_OUTPUT, str(uid))
            os.makedirs(d, exist_ok=True)
            return d
    except (ImportError, LookupError):
        pass
    os.makedirs(_BASE_OUTPUT, exist_ok=True)
    return _BASE_OUTPUT


def _build_report_markdown(
    hypothesis: dict,
    openings: dict, rebuttals: dict, verdict: str,
    summary: str,
) -> str:
    """Build an institutional-quality markdown report."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = hypothesis.get("report_title", "投资分析报告")
    h = hypothesis.get("hypothesis", "")

    lines = [
        f"# {title}",
        f"",
        f"**日期:** {ts}  ",
        f"**假设 (H₀):** {h}  ",
        f"**分析方法:** 多模型对抗辩论 (MiniMax + Qwen, 4位分析师 + 独立评审)  ",
        f"**免责声明:** 本报告由AI生成，仅供参考，不构成投资建议。",
        f"",
        f"---",
        f"",
        # Part 1: Executive Summary
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
        f"## A.1 正方分析 (支持H₀) — 分析师A",
        f"",
        openings["pro_a"],
        f"",
        f"## A.2 正方分析 (支持H₀) — 分析师B",
        f"",
        openings["pro_b"],
        f"",
        f"## A.3 反方分析 (反对H₀) — 分析师A",
        f"",
        openings["con_a"],
        f"",
        f"## A.4 反方分析 (反对H₀) — 分析师B",
        f"",
        openings["con_b"],
        f"",
        f"## A.5 交叉质证 — 正方分析师A",
        f"",
        rebuttals["pro_a"],
        f"",
        f"## A.6 交叉质证 — 正方分析师B",
        f"",
        rebuttals["pro_b"],
        f"",
        f"## A.7 交叉质证 — 反方分析师A",
        f"",
        rebuttals["con_a"],
        f"",
        f"## A.8 交叉质证 — 反方分析师B",
        f"",
        rebuttals["con_b"],
    ]
    return "\n".join(lines)


async def _generate_report(
    hypothesis: dict,
    openings: dict, rebuttals: dict, verdict: str,
    summary: str,
) -> list[str]:
    """Generate MD + PDF report files. Returns list of file paths."""
    from tools.output import generate_pdf

    md_content = _build_report_markdown(
        hypothesis, openings, rebuttals, verdict, summary,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Build filename from entity names or hypothesis
    entities = hypothesis.get("entities", [])
    if entities:
        name_parts = [e.get("name", "") for e in entities if e.get("name")]
        base_name = "_vs_".join(name_parts) + f"_{ts}" if name_parts else f"report_{ts}"
    else:
        # Sanitize hypothesis text for filename
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", hypothesis.get("hypothesis", "report"))[:30]
        base_name = f"{safe}_{ts}"

    # Save markdown
    out_dir = _get_output_dir()
    md_path = os.path.join(out_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Generate PDF using existing generate_pdf tool
    title = hypothesis.get("report_title", "投资分析报告")
    try:
        pdf_result = await generate_pdf(title=title, content=md_content)
        pdf_orig = pdf_result.get("file", "")
        # Rename to match our naming convention
        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
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
# Community Sentiment Subagent
# ---------------------------------------------------------------------------

def _guba_url(code: str) -> str:
    return f"https://guba.eastmoney.com/list,{code}.html"


async def _fetch_community_sentiment(
    entities: list[dict],
    status_fn=None,
    thinking_fn=None,
) -> str:
    """Scrape 股吧 for each stock entity and summarize retail investor sentiment.

    Runs scrape_webpage in parallel for all entities, then does a single LLM
    call to summarize. Returns a formatted section ready to append to data_pack.
    """
    stock_entities = [e for e in entities if e.get("type") == "stock" and e.get("code")]
    if not stock_entities:
        return ""

    if status_fn:
        await status_fn("Community sentiment subagent · Scraping 股吧...")

    # Scrape all stock guba pages in parallel
    async def _scrape_one(code: str) -> tuple[str, str]:
        url = _guba_url(code)
        try:
            result = await _execute_tool("scrape_webpage", {"url": url})
            if isinstance(result, dict):
                text = result.get("content", result.get("text", ""))
                if not text and "error" in result:
                    return url, f"(抓取失败: {result['error']})"
                return url, str(text)[:5000]
            return url, str(result)[:5000]
        except Exception as e:
            return url, f"(抓取失败: {e})"

    scrape_results = await asyncio.gather(
        *[_scrape_one(e["code"]) for e in stock_entities],
        return_exceptions=True,
    )

    # Build combined text for the LLM
    sections = []
    source_urls = []
    for i, entity in enumerate(stock_entities):
        name = entity.get("name", entity["code"])
        r = scrape_results[i]
        if isinstance(r, Exception):
            text = f"(错误: {r})"
            url = _guba_url(entity["code"])
        else:
            url, text = r
        source_urls.append(url)
        sections.append(f"=== {name} 股吧 ({url}) ===\n{text}")

    combined = "\n\n".join(sections)

    if not combined.strip() or all("抓取失败" in s or "错误" in s for s in sections):
        return "### 社区情绪 (Community Sentiment — 股吧)\n(论坛数据获取失败)"

    system = (
        "You are a financial analyst. Summarize retail investor sentiment from the following 股吧 forum posts. "
        "Be factual and concise. Cover: (1) overall tone — bullish/bearish/mixed with rough ratio, "
        "(2) key themes or catalysts being discussed, (3) main concerns or risks retail investors mention, "
        "(4) any notable events or news driving discussion. "
        "Under 350 words. Write in the same language as the posts (usually Chinese)."
    )

    if status_fn:
        await status_fn("Community sentiment subagent · Summarizing 股吧 posts...")

    summary = await _llm_call(
        minimax_client, MINIMAX_MODEL,
        system, combined,
        source="sentiment", label="Community Sentiment Subagent",
        thinking_fn=thinking_fn,
        timeout=60, max_tokens=700,
    )

    url_list = "\n".join(f"- {u}" for u in source_urls)
    return f"### 社区情绪 (Community Sentiment — 股吧)\n**数据来源:**\n{url_list}\n\n{summary}"


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

async def run_hypothesis_debate(user_question: str, context: str = "") -> dict:
    """Run hypothesis-driven multi-LLM debate for any investment question.

    This is the main entry point. Forms a hypothesis from the question,
    collects data per the plan, and runs the full debate pipeline.
    """
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

    logger.info(f"[TradeAnalyzer] Starting hypothesis debate for: {user_question}")

    # Phase 0: Form hypothesis
    await _status("Forming hypothesis from question...")
    logger.info("[TradeAnalyzer] Phase 0: Forming hypothesis")
    hypothesis = await _form_hypothesis(user_question, context, thinking_fn=_thinking)
    logger.info(f"[TradeAnalyzer] Hypothesis: {hypothesis.get('hypothesis', '')}")

    # Phase 1: Data collection + community sentiment subagent (in parallel)
    entities = hypothesis.get("entities", [])
    question_type = hypothesis.get("question_type", "general")
    has_stocks = question_type in ("single_stock", "comparison") and any(
        e.get("type") == "stock" for e in entities
    )

    await _status("Collecting data + community sentiment in parallel...")
    logger.info(f"[TradeAnalyzer] Phase 1: Data collection ({len(hypothesis.get('data_plan', []))} tools)"
                + (" + 股吧 sentiment subagent" if has_stocks else ""))

    if has_stocks:
        data_pack, sentiment = await asyncio.gather(
            _collect_data_from_plan(hypothesis.get("data_plan", []), context, entities),
            _fetch_community_sentiment(entities, status_fn=_status, thinking_fn=_thinking),
        )
        if sentiment:
            data_pack += f"\n\n{sentiment}"
    else:
        data_pack = await _collect_data_from_plan(
            hypothesis.get("data_plan", []), context, entities,
        )

    logger.info(f"[TradeAnalyzer] Phase 1 complete: {len(data_pack)} chars")

    # Phase 2: Opening arguments
    await _status("MiniMax + Qwen · Opening arguments (4 analysts)...")
    logger.info("[TradeAnalyzer] Phase 2: Opening arguments (4 parallel LLM calls)")
    openings = await _run_opening_round(hypothesis, data_pack,
                                         status_fn=_status, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Opening arguments complete")

    # Phase 3: Rebuttals
    await _status("MiniMax + Qwen · Rebuttals (4 analysts)...")
    logger.info("[TradeAnalyzer] Phase 3: Rebuttals (4 parallel LLM calls)")
    rebuttals = await _run_rebuttal_round(hypothesis, data_pack, openings,
                                           status_fn=_status, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Rebuttals complete")

    # Phase 4: Judge
    await _status("MiniMax · Judge rendering verdict...")
    logger.info("[TradeAnalyzer] Phase 4: Judge (1 LLM call)")
    verdict = await _run_judge(hypothesis, openings, rebuttals, data_pack, thinking_fn=_thinking)
    logger.info("[TradeAnalyzer] Judge verdict rendered")

    # Phase 5: Executive Summary
    await _status("MiniMax · Synthesizing executive summary...")
    logger.info("[TradeAnalyzer] Phase 5: Executive summary (1 LLM call)")
    summary = await _run_summary(hypothesis, data_pack, openings, rebuttals, verdict, thinking_fn=_thinking)
    if summary.startswith("(LLM") or summary.startswith("("):
        logger.warning(f"[TradeAnalyzer] Summary failed: {summary}, using verdict as fallback")
        summary = verdict
    logger.info("[TradeAnalyzer] Executive summary complete")

    # Phase 6: Generate MD + PDF report
    await _status("Generating report...")
    files = await _generate_report(hypothesis, openings, rebuttals, verdict, summary)
    logger.info(f"[TradeAnalyzer] Report generated: {files}")

    return {
        "hypothesis": hypothesis.get("hypothesis", ""),
        "question_type": hypothesis.get("question_type", ""),
        "verdict": verdict,
        "summary": summary,
        "files": files,
        "report_title": hypothesis.get("report_title", ""),
        "debate_log": {
            "opening_pro_a": openings["pro_a"],
            "opening_pro_b": openings["pro_b"],
            "opening_con_a": openings["con_a"],
            "opening_con_b": openings["con_b"],
            "rebuttal_pro_a": rebuttals["pro_a"],
            "rebuttal_pro_b": rebuttals["pro_b"],
            "rebuttal_con_a": rebuttals["con_a"],
            "rebuttal_con_b": rebuttals["con_b"],
        },
    }


async def analyze_trade_opportunity(
    stock_code: str = "", question: str = "", context: str = "",
) -> dict:
    """Backward-compatible wrapper. Accepts stock_code or question."""
    if question:
        return await run_hypothesis_debate(question, context)
    if stock_code:
        return await run_hypothesis_debate(f"{stock_code} 值得投资吗?", context)
    return {"error": "Either stock_code or question must be provided"}
