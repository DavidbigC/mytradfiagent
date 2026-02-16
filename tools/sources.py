import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SOURCES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sources.json")

LOOKUP_DATA_SOURCES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lookup_data_sources",
        "description": (
            "Look up known data source URLs for a specific type of financial data. "
            "ALWAYS call this FIRST before using web_search when you need financial data. "
            "Returns URL patterns you can use directly with scrape_webpage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What data you need (e.g. 'dividend', 'fund holdings', 'balance sheet', 'company profile')",
                },
                "market": {
                    "type": "string",
                    "enum": ["cn_stock", "cn_fund", "us_stock", "us_fund", "global", "all"],
                    "description": "Which market the data is for (default 'all')",
                    "default": "all",
                },
            },
            "required": ["query"],
        },
    },
}

SAVE_DATA_SOURCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_data_source",
        "description": (
            "Save a newly discovered useful data source URL to the knowledge base. "
            "Call this whenever you find a webpage that provides reliable, structured financial data. "
            "This helps you go directly to the source next time instead of searching."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name for the source (e.g. '新浪财经 - 现金流量表')"},
                "category": {
                    "type": "string",
                    "enum": ["cn_stock", "cn_fund", "us_stock", "us_fund", "cn_bond", "global", "other"],
                    "description": "Category of the data source",
                },
                "data_type": {
                    "type": "string",
                    "description": "Type of data (e.g. 'dividend', 'financials', 'holdings', 'news')",
                },
                "url_pattern": {
                    "type": "string",
                    "description": "URL pattern with {placeholders} for variable parts (e.g. 'https://example.com/stock/{code}/info')",
                },
                "params": {
                    "type": "object",
                    "description": "Description of each placeholder parameter",
                },
                "example": {
                    "type": "string",
                    "description": "A concrete example URL that works",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes about what data is available, quality, any gotchas",
                },
            },
            "required": ["name", "category", "data_type", "url_pattern", "example"],
        },
    },
}


def _load_sources() -> dict:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sources": []}


def _save_sources(data: dict):
    os.makedirs(os.path.dirname(SOURCES_FILE), exist_ok=True)
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Map common Chinese/English synonyms to canonical data types
KEYWORD_ALIASES = {
    "分红": "dividend", "派息": "dividend", "红利": "dividend", "股息": "dividend", "dividend": "dividend",
    "财务": "financials", "财报": "financials", "报表": "financials", "financials": "financials",
    "利润": "income_statement", "收入": "income_statement",
    "资产负债": "balance_sheet", "负债": "balance_sheet",
    "现金流": "cash_flow",
    "股东": "shareholders", "持股": "shareholders",
    "公司": "company_profile", "简介": "company_profile",
    "持仓": "fund_holdings", "基金持仓": "fund_holdings", "holdings": "fund_holdings",
    "基金": "fund_overview", "净值": "fund_overview", "etf": "fund_overview",
    "债券": "bond", "国债": "treasury_yield",
    "market": "market_overview", "行情": "market_overview",
    "pe": "valuation", "估值": "valuation", "市盈率": "valuation", "市净率": "valuation",
    "quote": "quote", "价格": "quote", "股价": "quote", "行情": "quote",
    "代码": "reference", "code": "reference",
}


async def lookup_data_sources(query: str, market: str = "all") -> dict:
    data = _load_sources()
    query_lower = query.lower()

    # Expand query with aliases
    expanded_terms = set(query_lower.split())
    for keyword, alias in KEYWORD_ALIASES.items():
        if keyword in query_lower:
            expanded_terms.add(alias)

    matches = []
    for src in data["sources"]:
        # Filter by market
        if market != "all" and src.get("category") != market:
            continue

        # Match by data_type, name, or notes
        searchable = f"{src.get('data_type', '')} {src.get('name', '')} {src.get('notes', '')}".lower()
        if any(term in searchable for term in expanded_terms):
            matches.append({
                "name": src["name"],
                "data_type": src.get("data_type"),
                "url_pattern": src["url_pattern"],
                "params": src.get("params", {}),
                "example": src.get("example"),
                "notes": src.get("notes", ""),
            })

    if not matches:
        return {"matches": [], "suggestion": "No known sources found. Try web_search, and if you find a good source, save it with save_data_source."}

    return {
        "matches": matches,
        "instruction": "Use scrape_webpage with the url_pattern above (replace placeholders with actual values). Do NOT use web_search — go directly to the URL.",
    }


async def save_data_source(
    name: str,
    category: str,
    data_type: str,
    url_pattern: str,
    example: str,
    params: dict | None = None,
    notes: str = "",
) -> dict:
    data = _load_sources()

    # Check for duplicate URL patterns
    for src in data["sources"]:
        if src["url_pattern"] == url_pattern:
            return {"status": "exists", "message": f"Source already exists: {src['name']}"}

    # Generate ID
    source_id = f"{category}_{data_type}_{len(data['sources']) + 1}"

    new_source = {
        "id": source_id,
        "name": name,
        "category": category,
        "data_type": data_type,
        "url_pattern": url_pattern,
        "params": params or {},
        "example": example,
        "notes": notes,
        "added_by": "agent",
        "added_at": datetime.now().isoformat(),
    }

    data["sources"].append(new_source)
    _save_sources(data)

    logger.info(f"Saved new data source: {name} ({url_pattern})")
    return {"status": "saved", "source": new_source}
