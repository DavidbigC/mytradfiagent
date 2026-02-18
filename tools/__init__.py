from tools.web import web_search, scrape_webpage, WEB_SEARCH_SCHEMA, SCRAPE_WEBPAGE_SCHEMA
from tools.stocks import (
    fetch_stock_data, fetch_multiple_stocks,
    FETCH_STOCK_DATA_SCHEMA, FETCH_MULTIPLE_STOCKS_SCHEMA,
)
from tools.cn_market import (
    fetch_cn_stock_data, fetch_multiple_cn_stocks, fetch_cn_bond_data,
    FETCH_CN_STOCK_DATA_SCHEMA, FETCH_MULTIPLE_CN_STOCKS_SCHEMA, FETCH_CN_BOND_DATA_SCHEMA,
)
from tools.funds import fetch_fund_holdings, FETCH_FUND_HOLDINGS_SCHEMA
from tools.cn_funds import fetch_cn_fund_holdings, FETCH_CN_FUND_HOLDINGS_SCHEMA
from tools.output import generate_chart, generate_pdf, GENERATE_CHART_SCHEMA, GENERATE_PDF_SCHEMA
from tools.subagent import dispatch_subagents, DISPATCH_SUBAGENTS_SCHEMA
from tools.sources import (
    lookup_data_sources, save_data_source,
    LOOKUP_DATA_SOURCES_SCHEMA, SAVE_DATA_SOURCE_SCHEMA,
)
from tools.market_scan import scan_market_hotspots, SCAN_MARKET_HOTSPOTS_SCHEMA
from tools.cn_screener import screen_cn_stocks, SCREEN_CN_STOCKS_SCHEMA
from tools.sina_reports import fetch_company_report, FETCH_COMPANY_REPORT_SCHEMA
from tools.cn_capital_flow import (
    fetch_stock_capital_flow, fetch_northbound_flow, fetch_capital_flow_ranking,
    FETCH_STOCK_CAPITAL_FLOW_SCHEMA, FETCH_NORTHBOUND_FLOW_SCHEMA, FETCH_CAPITAL_FLOW_RANKING_SCHEMA,
)
from tools.cn_eastmoney import (
    fetch_stock_financials, fetch_top_shareholders, fetch_dragon_tiger, fetch_dividend_history,
    FETCH_STOCK_FINANCIALS_SCHEMA, FETCH_TOP_SHAREHOLDERS_SCHEMA,
    FETCH_DRAGON_TIGER_SCHEMA, FETCH_DIVIDEND_HISTORY_SCHEMA,
)
from tools.trade_analyzer import analyze_trade_opportunity, ANALYZE_TRADE_SCHEMA

TOOL_SCHEMAS = [
    LOOKUP_DATA_SOURCES_SCHEMA,
    SAVE_DATA_SOURCE_SCHEMA,
    WEB_SEARCH_SCHEMA,
    SCRAPE_WEBPAGE_SCHEMA,
    FETCH_STOCK_DATA_SCHEMA,
    FETCH_MULTIPLE_STOCKS_SCHEMA,
    FETCH_CN_STOCK_DATA_SCHEMA,
    FETCH_MULTIPLE_CN_STOCKS_SCHEMA,
    FETCH_CN_BOND_DATA_SCHEMA,
    FETCH_FUND_HOLDINGS_SCHEMA,
    FETCH_CN_FUND_HOLDINGS_SCHEMA,
    GENERATE_CHART_SCHEMA,
    GENERATE_PDF_SCHEMA,
    DISPATCH_SUBAGENTS_SCHEMA,
    SCAN_MARKET_HOTSPOTS_SCHEMA,
    SCREEN_CN_STOCKS_SCHEMA,
    FETCH_COMPANY_REPORT_SCHEMA,
    FETCH_STOCK_CAPITAL_FLOW_SCHEMA,
    FETCH_NORTHBOUND_FLOW_SCHEMA,
    FETCH_CAPITAL_FLOW_RANKING_SCHEMA,
    FETCH_STOCK_FINANCIALS_SCHEMA,
    FETCH_TOP_SHAREHOLDERS_SCHEMA,
    FETCH_DRAGON_TIGER_SCHEMA,
    FETCH_DIVIDEND_HISTORY_SCHEMA,
    ANALYZE_TRADE_SCHEMA,
]

TOOL_MAP = {
    "lookup_data_sources": lookup_data_sources,
    "save_data_source": save_data_source,
    "web_search": web_search,
    "scrape_webpage": scrape_webpage,
    "fetch_stock_data": fetch_stock_data,
    "fetch_multiple_stocks": fetch_multiple_stocks,
    "fetch_cn_stock_data": fetch_cn_stock_data,
    "fetch_multiple_cn_stocks": fetch_multiple_cn_stocks,
    "fetch_cn_bond_data": fetch_cn_bond_data,
    "fetch_fund_holdings": fetch_fund_holdings,
    "fetch_cn_fund_holdings": fetch_cn_fund_holdings,
    "generate_chart": generate_chart,
    "generate_pdf": generate_pdf,
    "dispatch_subagents": dispatch_subagents,
    "scan_market_hotspots": scan_market_hotspots,
    "screen_cn_stocks": screen_cn_stocks,
    "fetch_company_report": fetch_company_report,
    "fetch_stock_capital_flow": fetch_stock_capital_flow,
    "fetch_northbound_flow": fetch_northbound_flow,
    "fetch_capital_flow_ranking": fetch_capital_flow_ranking,
    "fetch_stock_financials": fetch_stock_financials,
    "fetch_top_shareholders": fetch_top_shareholders,
    "fetch_dragon_tiger": fetch_dragon_tiger,
    "fetch_dividend_history": fetch_dividend_history,
    "analyze_trade_opportunity": analyze_trade_opportunity,
}


async def execute_tool(name: str, args: dict):
    func = TOOL_MAP.get(name)
    if not func:
        return {"error": f"Unknown tool: {name}"}
    return await func(**args)
