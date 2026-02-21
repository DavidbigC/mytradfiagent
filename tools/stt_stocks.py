"""
Shared STT stock-resolution logic.

Pipeline:
  1. GPT extracts stock short-names from Whisper transcription
  2. Each name is converted to tone-free pinyin
  3. Fuzzy (Levenshtein) match against the stocknames table
  4. Returns matched stocks with edit-distance scores

Used by both the production STT endpoint (api_chat.py) and the test tool
(tests/test_whisper_web.py).
"""

import json
import logging
from pypinyin import lazy_pinyin

log = logging.getLogger(__name__)


def to_pinyin(text: str) -> str:
    """Convert Chinese text to tone-free pinyin, e.g. 继峰股份 → jifenggufen."""
    return "".join(lazy_pinyin(text.strip()))


def levenshtein(s1: str, s2: str) -> int:
    """Character-level Levenshtein edit distance."""
    if abs(len(s1) - len(s2)) > 4:
        return abs(len(s1) - len(s2))
    m, n = len(s1), len(s2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            prev, dp[j] = dp[j], (prev if s1[i - 1] == s2[j - 1] else 1 + min(prev, dp[j], dp[j - 1]))
    return dp[n]


async def extract_and_find_stocks(text: str, openai_client, db_pool) -> dict:
    """
    Full pipeline: GPT name extraction → pinyin → fuzzy DB lookup.

    Returns:
        {
          extracted_names: list[str],
          extracted_pinyins: list[str],
          matched_stocks: list[dict],   # each has distance field
          extraction_ms: int,
          lookup_ms: int,
        }
    """
    import time

    # ── Step 1: GPT extracts stock names ───────────────────────────────────────
    t0 = time.monotonic()
    extracted_names: list[str] = []
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是A股语音输入识别助手。"
                        "从用户语句中提取所有可能是A股股票简称的词语（通常2-5个汉字的公司名称）。"
                        "注意：输入来自语音识别，可能有误字，请提取听起来像公司名称的词组，即使与真实股票名称有出入。"
                        '只返回JSON：{"stocks": ["词1", "词2"]}，找不到则返回{"stocks": []}。'
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        extracted_names = json.loads(resp.choices[0].message.content).get("stocks", [])
    except Exception as e:
        log.warning(f"STT GPT extraction failed: {e}")
    extraction_ms = int((time.monotonic() - t0) * 1000)
    log.info(f"STT GPT extract in {extraction_ms}ms: {extracted_names}")

    # ── Step 2: Pinyin conversion + fuzzy DB lookup ────────────────────────────
    t1 = time.monotonic()
    extracted_pinyins = [to_pinyin(n) for n in extracted_names]
    matched_stocks: list[dict] = []

    replacements: dict = {}   # extracted_name -> best confident match

    if db_pool and extracted_pinyins:
        all_rows = await db_pool.fetch(
            "SELECT stock_code, stock_name, exchange, pinyin FROM stocknames WHERE pinyin IS NOT NULL"
        )
        seen: set = set()
        for name, py in zip(extracted_names, extracted_pinyins):
            threshold = max(1, len(py) // 5)   # ~20% edit distance, min 1
            candidates = []
            for row in all_rows:
                dist = levenshtein(py, row["pinyin"])
                if dist <= threshold:
                    key = (row["stock_code"], row["exchange"])
                    if key not in seen:
                        seen.add(key)
                        r = dict(row)
                        r["distance"] = dist
                        candidates.append(r)
            candidates.sort(key=lambda x: x["distance"])
            matched_stocks.extend(candidates[:10])  # top 10 per name (for test tool)
            if candidates:
                replacements[name] = candidates[0]  # best match for this name

    lookup_ms = int((time.monotonic() - t1) * 1000)

    return {
        "extracted_names": extracted_names,
        "extracted_pinyins": extracted_pinyins,
        "matched_stocks": matched_stocks,
        "replacements": replacements,
        "extraction_ms": extraction_ms,
        "lookup_ms": lookup_ms,
    }
