"""
Test Groq llama-3.1-8b-instant for annual report summarization via PDF.

Flow:
  1. Fetch Sina bulletin page → extract PDF link
  2. Download the PDF → extract full text with pymupdf
  3. Prep text (TOC filter + dedup)
  4. Chunk into ~10k char pieces
  5. Process all chunks in parallel with Groq (semaphore = 4)
  6. Synthesis pass → final structured report

Test stock: 招商银行 (600036), yearly report
"""

import asyncio
import io
import logging
import os
import sys
import tempfile

import fitz  # pymupdf
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL         = "openai/gpt-oss-20b"

STOCK_CODE     = "601229"   # 招商银行
REPORT_TYPE    = "yearly"
FOCUS_KEYWORDS = ["不良率", "净息差", "拨备覆盖率", "资产质量", "净利润", "营业收入", "ROE", "ROA"]

CHUNK_SIZE  = 10_000   # chars per chunk
CHUNK_OVERLAP = 200    # overlap to avoid cutting mid-sentence
MAX_PARALLEL  = 4      # concurrent Groq calls

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Import helpers from sina_reports ─────────────────────────────────────────
sys.path.insert(0, "tools")
from sina_reports import (
    REPORT_URLS, SINA_BASE,
    _fetch_page, _parse_bulletin_list,
    _extract_pdf_link, _prepare_report_text,
)


# ── PDF download + extraction ─────────────────────────────────────────────────

async def download_pdf(url: str) -> bytes:
    log.info(f"Downloading PDF: {url}")
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": SINA_BASE,
        })
        resp.raise_for_status()
    log.info(f"PDF downloaded: {len(resp.content):,} bytes")
    return resp.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pymupdf."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
    doc.close()
    full_text = "\n".join(pages)
    log.info(f"PDF text extracted: {len(full_text):,} chars from {len(pages)} pages")
    return full_text


# ── Chunking ──────────────────────────────────────────────────────────────────

def make_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end + overlap])
        start += chunk_size
    log.info(f"Split into {len(chunks)} chunks of ~{chunk_size} chars")
    return chunks


# ── Groq calls ────────────────────────────────────────────────────────────────

SYSTEM_EXTRACT = """你是一名专业的卖方金融分析师，任务是从财务报告片段中进行无损数据提取。

核心原则：
1. 穷举提取——本片段中出现的每一个数字、比率、金额、百分比、增减变化都必须提取，一个都不能遗漏。
2. 数字必须100%来自原文，严禁编造、推算或四舍五入后不标注。
3. 所有表格必须以完整Markdown表格格式保留，包括每一行每一列，绝对不得省略。
4. 每个数据必须标明报告期（年度、季度、具体日期）。
5. 管理层原话中的关键判断、前瞻性表述、行业分析也必须完整引用，不得压缩。
6. 若本片段确实无财务数据，简短说明后停止，不要填充废话。
7. 输出长度不设上限——有多少数据就输出多少，宁多勿缺。"""

SYSTEM_SYNTHESIS = """你是一名资深卖方金融分析师，将多份片段提取报告整合为一份极度详尽的深度研报。

核心原则：
1. 保留所有数据——每一个出现在片段中的数字、表格、比率都必须出现在最终报告中，严禁丢失。
2. 合并同类数据，消除重复，但保留所有不同报告期的对比数据。
3. 严禁编造，严禁在片段数据之外添加任何数字。
4. 输出不设长度限制，以数据完整性为第一优先级。
5. 排版清晰：大量使用Markdown表格，数据密集段落用表格而非文字呈现。"""


async def process_chunk(
    client: AsyncOpenAI,
    sem: asyncio.Semaphore,
    idx: int,
    total: int,
    chunk: str,
    title: str,
    focus_keywords: list[str],
) -> str:
    focus_note = f"**重点关注**：{', '.join(focus_keywords)}\n\n" if focus_keywords else ""
    prompt = (
        f"**报告**：{title}（年报）\n"
        f"{focus_note}"
        f"这是报告文本的第 {idx+1}/{total} 片段。请对本片段做穷举式数据提取，不遗漏任何数字。\n\n"
        "## 提取结构\n\n"
        "### 一、财务数据全量提取\n"
        "列出本片段中出现的每一个财务数字，包括：收入、利润、资产、负债、比率、增减幅度、每股数据等。\n"
        "遇到表格：完整复现为Markdown表格，一行一列都不能省。\n"
        "遇到散列数字：逐条列出，格式：[指标名] [数值] [报告期]。\n\n"
        "### 二、管理层表述全量提取\n"
        "本片段中管理层对经营情况、战略、行业、风险的所有原话或核心表述，逐条引用，不压缩。\n\n"
        "### 三、风险与异常全量提取\n"
        "本片段中所有风险提示、异常数据、同比大幅变动的指标，逐条列出并附原文数据。\n\n"
        f"--- 片段内容 ---\n\n{chunk}"
    )
    async with sem:
        try:
            resp = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_EXTRACT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=8192,
                temperature=0.1,  # low temp = less hallucination
            )
            content = resp.choices[0].message.content or ""
            log.info(f"Chunk {idx+1}/{total} done: {len(content)} chars")
            return f"## 片段 {idx+1}\n\n{content}"
        except Exception as e:
            log.warning(f"Chunk {idx+1} failed: {e}")
            return f"## 片段 {idx+1}\n\n> 处理失败: {e}"


async def synthesis_pass(
    client: AsyncOpenAI,
    chunks_text: str,
    title: str,
) -> str:
    prompt = (
        f"**任务**：生成《{title}》的最终深度研报汇总。\n\n"
        "以下是从原始PDF各片段并行提取的子报告集合。请整合、去重、润色，输出统一结构化报告。\n\n"
        "## 输出结构（Markdown）\n\n"
        "### 一、核心财务指标汇总\n"
        "合并所有财务数据，以Markdown表格呈现，注明报告期。\n\n"
        "### 二、经营情况与管理层分析\n"
        "按逻辑提炼整体经营情况、业务结构、核心战略（至少400字）。\n\n"
        "### 三、关键财务明细表\n"
        "整合营收结构、贷款/存款明细、分部数据等关键表格。\n\n"
        "### 四、银行特定指标\n"
        "净息差、不良率、拨备覆盖率、资本充足率等专项指标及同比变化。\n\n"
        "### 五、风险因素\n"
        "管理层披露的关键风险，去重整理。\n\n"
        "### 六、亮点与异常发现\n"
        "全篇最核心的超预期/低于预期指标及趋势判断，附具体数据。\n\n"
        "**重要提示：以上六个部分必须全部输出，每个部分尽可能详尽，不设长度限制。**\n\n"
        f"--- 片段提取集合 ---\n\n{chunks_text}"
    )
    log.info("Running synthesis pass...")
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_SYNTHESIS},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=8192,
        temperature=0.15,
    )
    return resp.choices[0].message.content or ""


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set in .env")
        return

    client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)

    # Step 1: Get bulletin listing → latest report metadata
    listing_url = SINA_BASE + REPORT_URLS[REPORT_TYPE].format(code=STOCK_CODE)
    log.info(f"Fetching bulletin list: {listing_url}")
    listing_html = await _fetch_page(listing_url)
    reports = _parse_bulletin_list(listing_html)
    if not reports:
        print("No reports found.")
        return

    latest = reports[0]
    log.info(f"Latest: {latest['title']} ({latest['date']})")

    # Step 2: Get detail page → extract PDF link
    detail_html = await _fetch_page(latest["url"])
    pdf_url = _extract_pdf_link(detail_html)
    if not pdf_url:
        print("ERROR: No PDF link found on detail page.")
        return
    log.info(f"PDF URL: {pdf_url}")

    # Step 3: Download PDF → extract text
    pdf_bytes = await download_pdf(pdf_url)
    full_text = extract_pdf_text(pdf_bytes)

    # Step 4: Prep (TOC filter + dedup)
    prepared = _prepare_report_text(full_text, focus_keywords=FOCUS_KEYWORDS, max_chars=999_999)
    log.info(f"Text: raw={len(full_text):,}  prepared={len(prepared):,} chars")

    # Step 5: Chunk + parallel extraction
    chunks = make_chunks(prepared)
    sem = asyncio.Semaphore(MAX_PARALLEL)
    tasks = [
        process_chunk(client, sem, i, len(chunks), c, latest["title"], FOCUS_KEYWORDS)
        for i, c in enumerate(chunks)
    ]
    results = await asyncio.gather(*tasks)
    combined = "\n\n---\n\n".join(results)

    # Step 6: Synthesis
    final = await synthesis_pass(client, combined, latest["title"])

    # Output
    print("\n" + "=" * 70)
    print(f"  {latest['title']}  ({latest['date']})")
    print(f"  PDF: {pdf_url}")
    print("=" * 70 + "\n")
    print(final)
    print("\n" + "─" * 70)
    print(f"Raw PDF text:  {len(full_text):,} chars")
    print(f"Prepared text: {len(prepared):,} chars")
    print(f"Chunks:        {len(chunks)}")
    print(f"Model:         {MODEL}")


if __name__ == "__main__":
    asyncio.run(main())
