import httpx
import xml.etree.ElementTree as ET
from tools.cache import cached

TOOL_TIMEOUT = 30

FETCH_FUND_HOLDINGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_fund_holdings",
        "description": "Fetch fund/institutional holdings from SEC 13F filings. Shows what stocks a hedge fund or institution holds with share counts and market values.",
        "parameters": {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "SEC CIK number of the institution (e.g. '0001067983' for Berkshire Hathaway)",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top holdings to return (default 20)",
                    "default": 20,
                },
            },
            "required": ["cik"],
        },
    },
}

SEC_HEADERS = {"User-Agent": "FinResearchBot research@example.com"}


@cached(ttl=3600)
async def fetch_fund_holdings(cik: str, top_n: int = 20) -> dict:
    cik_padded = cik.lstrip("0").zfill(10)

    async with httpx.AsyncClient(timeout=20, headers=SEC_HEADERS, follow_redirects=True) as client:
        # Step 1: Get filing index to find latest 13F
        sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        resp = await client.get(sub_url)
        resp.raise_for_status()
        data = resp.json()

        company_name = data.get("name", "Unknown")
        filings = data.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])

        # Find latest 13F-HR
        filing_acc = None
        filing_date = None
        for i, form in enumerate(forms):
            if form in ("13F-HR", "13F-HR/A"):
                filing_acc = accessions[i]
                filing_date = dates[i]
                break

        if not filing_acc:
            return {"error": f"No 13F filing found for CIK {cik}"}

        # Step 2: Get the filing's document index to find the infotable XML
        acc_no_dash = filing_acc.replace("-", "")
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_no_dash}/index.json"
        resp = await client.get(idx_url)
        resp.raise_for_status()
        idx_data = resp.json()

        # Find the infotable XML file — try multiple naming patterns
        infotable_url = None
        xml_files = []
        for item in idx_data.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.lower().endswith(".xml") and name.lower() != "primary_doc.xml":
                xml_files.append(name)
                if "infotable" in name.lower():
                    infotable_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_no_dash}/{name}"
                    break

        # If no file explicitly named "infotable", take the first non-primary XML
        if not infotable_url and xml_files:
            infotable_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_no_dash}/{xml_files[0]}"

        if not infotable_url:
            return {
                "company": company_name,
                "filing_date": filing_date,
                "error": "Could not find infotable XML in filing. Try scrape_webpage on the EDGAR filing page.",
                "edgar_url": f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_no_dash}/",
            }

        # Step 3: Parse the infotable XML to extract actual holdings
        resp = await client.get(infotable_url)
        resp.raise_for_status()

        holdings = _parse_13f_xml(resp.text)

        # Sort by market value descending, take top N
        holdings.sort(key=lambda h: h.get("value_usd", 0), reverse=True)
        top_holdings = holdings[:top_n]

        total_value = sum(h.get("value_usd", 0) for h in holdings)

        return {
            "company": company_name,
            "cik": cik,
            "filing_date": filing_date,
            "total_positions": len(holdings),
            "total_value_usd": total_value,
            "top_holdings": top_holdings,
        }


def _parse_13f_xml(xml_text: str) -> list[dict]:
    """Parse SEC 13F infotable XML into a list of holdings.
    Aggregates multiple entries for the same issuer (different managers)."""
    # Strip namespace for simpler parsing
    xml_text = xml_text.replace('xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"', '')
    xml_text = xml_text.replace('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"', '')

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Parse individual entries
    raw_holdings = []
    for entry in root.findall(".//infoTable"):
        name = _xml_text(entry, "nameOfIssuer")
        if not name:
            continue
        raw_holdings.append({
            "name": name,
            "title": _xml_text(entry, "titleOfClass"),
            "cusip": _xml_text(entry, "cusip"),
            "value_usd": _xml_int(entry, "value"),
            "shares": _xml_int(entry, ".//sshPrnamt"),
            "share_type": _xml_text(entry, ".//sshPrnamtType"),
        })

    # Aggregate by cusip (same stock may appear under different managers)
    aggregated: dict[str, dict] = {}
    for h in raw_holdings:
        key = h.get("cusip", h["name"])
        if key in aggregated:
            aggregated[key]["value_usd"] += h["value_usd"]
            aggregated[key]["shares"] += h["shares"]
        else:
            aggregated[key] = h.copy()

    return list(aggregated.values())


def _xml_text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _xml_int(elem, tag: str) -> int:
    text = _xml_text(elem, tag)
    try:
        return int(text)
    except (ValueError, TypeError):
        return 0
