import os
import re
import uuid
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from datetime import datetime
from fpdf import FPDF

# Configure Chinese font for matplotlib
_CN_FONT_CANDIDATES = [
    "Hiragino Sans GB",
    "PingFang SC",
    "STHeiti",
    "Arial Unicode MS",
]

_cn_font = None
for _fname in _CN_FONT_CANDIDATES:
    if any(_fname in f.name for f in fm.fontManager.ttflist):
        _cn_font = _fname
        break

if _cn_font:
    plt.rcParams["font.sans-serif"] = [_cn_font, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

GENERATE_CHART_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_chart",
        "description": "Generate a chart image (PNG). Supports line charts, bar charts, and comparison charts.",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "comparison"],
                    "description": "Type of chart to generate",
                },
                "title": {"type": "string", "description": "Chart title"},
                "x_label": {"type": "string", "description": "X-axis label", "default": ""},
                "y_label": {"type": "string", "description": "Y-axis label", "default": ""},
                "series": {
                    "type": "array",
                    "description": "Data series. Each item has 'name', 'x' (list), and 'y' (list).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "x": {"type": "array", "items": {"type": "string"}},
                            "y": {"type": "array", "items": {"type": "number"}},
                        },
                        "required": ["name", "x", "y"],
                    },
                },
            },
            "required": ["chart_type", "title", "series"],
        },
    },
}

GENERATE_PDF_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_pdf",
        "description": "Generate a PDF report from markdown text.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title"},
                "content": {"type": "string", "description": "Report content in Markdown format"},
            },
            "required": ["title", "content"],
        },
    },
}


async def generate_chart(chart_type: str, title: str, series: list, x_label: str = "", y_label: str = "") -> dict:
    fig, ax = plt.subplots(figsize=(10, 6))

    for s in series:
        x = s["x"]
        y = s["y"]

        # Try to parse dates
        try:
            x_parsed = [datetime.fromisoformat(d) for d in x]
            is_date = True
        except (ValueError, TypeError):
            x_parsed = x
            is_date = False

        if chart_type == "bar":
            ax.bar(x_parsed, y, label=s["name"], alpha=0.7)
        else:
            ax.plot(x_parsed, y, label=s["name"], linewidth=2)

        if is_date:
            # Smart date locator based on date range
            if len(x_parsed) >= 2:
                span = (max(x_parsed) - min(x_parsed)).days
                if span > 365 * 2:
                    ax.xaxis.set_major_locator(mdates.YearLocator())
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
                elif span > 180:
                    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
                elif span > 30:
                    ax.xaxis.set_major_locator(mdates.MonthLocator())
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
                else:
                    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
            else:
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)

    # For non-date x-axis with many labels, also rotate
    if not is_date and len(series) > 0 and len(series[0]["x"]) > 8:
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if len(series) > 1:
        ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    filename = f"chart_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(filepath, dpi=150)
    plt.close(fig)

    return {"file": filepath, "message": f"Chart saved: {filename}"}


# Chinese-capable .ttf fonts (avoid .ttc which fpdf2 handles poorly)
_PDF_FONT_PATHS = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/NISC18030.ttf",
]


def _setup_pdf_font(pdf: FPDF) -> str:
    """Register a Chinese-capable .ttf font with fpdf2. Returns font family name."""
    for path in _PDF_FONT_PATHS:
        if os.path.exists(path):
            try:
                pdf.add_font("CJK", "", path)
                return "CJK"
            except Exception:
                continue
    return "Helvetica"


def _mc(pdf: FPDF, h: float, text: str):
    """multi_cell wrapper that always resets cursor to left margin."""
    pdf.multi_cell(w=0, h=h, text=text, new_x="LMARGIN", new_y="NEXT")


def _render_table(pdf: FPDF, lines: list[str], font_family: str):
    """Render a markdown table as formatted text rows."""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return

    # Skip separator rows (e.g. |---|---|)
    data_rows = [r for r in rows if not all(set(c) <= {"-", ":", " "} for c in r)]

    if not data_rows:
        return

    # Render header
    if len(data_rows) >= 1:
        pdf.set_font(font_family, "", 10)
        _mc(pdf, 6, "  |  ".join(data_rows[0]))
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(1)

    # Render data rows
    pdf.set_font(font_family, "", 10)
    for row in data_rows[1:]:
        _mc(pdf, 5.5, "  |  ".join(row))
    pdf.ln(2)


async def generate_pdf(title: str, content: str) -> dict:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    font_family = _setup_pdf_font(pdf)

    # Title
    pdf.set_font(font_family, "", 18)
    _mc(pdf, 12, title)
    pdf.ln(2)
    pdf.set_draw_color(22, 33, 62)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # Body — collect lines, detect tables
    all_lines = content.split("\n")
    i = 0
    while i < len(all_lines):
        stripped = all_lines[i].strip()

        # Detect markdown table block
        if "|" in stripped and stripped.startswith("|"):
            table_lines = []
            while i < len(all_lines) and "|" in all_lines[i].strip():
                table_lines.append(all_lines[i])
                i += 1
            _render_table(pdf, table_lines, font_family)
            continue

        if stripped.startswith("### "):
            pdf.ln(3)
            pdf.set_font(font_family, "", 12)
            _mc(pdf, 7, stripped[4:])
            pdf.set_font(font_family, "", 11)
        elif stripped.startswith("## "):
            pdf.ln(4)
            pdf.set_font(font_family, "", 14)
            _mc(pdf, 8, stripped[3:])
            pdf.set_font(font_family, "", 11)
        elif stripped.startswith("# "):
            pdf.ln(4)
            pdf.set_font(font_family, "", 16)
            _mc(pdf, 10, stripped[2:])
            pdf.set_font(font_family, "", 11)
        elif stripped.startswith(("- ", "* ")):
            pdf.set_font(font_family, "", 11)
            _mc(pdf, 6, f"  {stripped}")
        elif stripped:
            pdf.set_font(font_family, "", 11)
            _mc(pdf, 6, stripped)
        else:
            pdf.ln(3)
        i += 1

    filename = f"report_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)
    pdf.output(filepath)

    return {"file": filepath, "message": f"PDF report saved: {filename}"}


# --- Reference image generation ---

_REF_PATTERN = re.compile(
    r"\[references\]\s*\n(.*?)\n\s*\[/references\]",
    re.DOTALL | re.IGNORECASE,
)
_REF_LINE = re.compile(r"\[(\d+)\]\s*(.+?)\s*\|\s*(\S+)")
_REF_LINE_NO_URL = re.compile(r"\[(\d+)\]\s*(.+)")


def parse_references(text: str) -> tuple[str, list[dict]]:
    """Extract [references]...[/references] block from text.

    Returns (cleaned_text, references_list) where references_list is
    [{"num": "1", "name": "Source", "url": "https://..."}, ...]
    """
    match = _REF_PATTERN.search(text)
    if not match:
        return text, []

    refs = []
    for line in match.group(1).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _REF_LINE.match(line)
        if m:
            refs.append({"num": m.group(1), "name": m.group(2).strip(), "url": m.group(3).strip()})
        else:
            # Fallback: line without URL (e.g. "[1] TradingView Scanner API")
            m2 = _REF_LINE_NO_URL.match(line)
            if m2:
                refs.append({"num": m2.group(1), "name": m2.group(2).strip(), "url": "(tool data)"})

    cleaned = text[:match.start()].rstrip() + text[match.end():]
    cleaned = cleaned.rstrip()
    return cleaned, refs


def generate_references_image(refs: list[dict]) -> str | None:
    """Render a list of references into a clean PNG image. Returns filepath or None."""
    if not refs:
        return None

    # Build text lines with wrapping
    lines = []
    max_chars = 90  # wrap URLs/names at this width
    for r in refs:
        label = f"[{r['num']}] {r['name']}"
        url = r["url"]
        # Wrap long URLs
        wrapped_url = textwrap.fill(url, width=max_chars, subsequent_indent="     ")
        lines.append((label, wrapped_url))

    # Calculate figure height: each ref = label line + url line(s) + spacing
    line_count = sum(2 + wrapped.count("\n") for _, wrapped in lines)
    fig_height = max(1.5, 0.32 * line_count + 1.0)
    fig_width = 10

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Background
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Title
    y = 0.95
    ax.text(0.03, y, "References", color="#e0e0e0", fontsize=13,
            fontweight="bold", va="top", fontfamily="sans-serif")
    y -= 0.08
    ax.axhline(y=y, xmin=0.02, xmax=0.98, color="#3a3a5c", linewidth=0.8)
    y -= 0.04

    step = 1.0 / (line_count + 4)  # dynamic spacing

    for label, wrapped_url in lines:
        if y < 0.02:
            break
        ax.text(0.03, y, label, color="#82b1ff", fontsize=9.5,
                va="top", fontfamily="sans-serif", fontweight="bold")
        y -= step
        for url_line in wrapped_url.split("\n"):
            ax.text(0.05, y, url_line, color="#8a8a9a", fontsize=8,
                    va="top", fontfamily="sans-serif")
            y -= step

    plt.tight_layout(pad=0.3)
    filename = f"refs_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(filepath, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return filepath
