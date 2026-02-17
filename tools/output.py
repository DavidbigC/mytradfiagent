import os
import re
import uuid
import textwrap
import urllib.request
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from datetime import datetime
from fpdf import FPDF

# Configure Chinese font for matplotlib (macOS + Linux)
_CN_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "WenQuanYi Micro Hei",
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


# --- PDF font resolution (macOS + Linux) ---

_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
os.makedirs(_FONTS_DIR, exist_ok=True)

_BUNDLED_FONT = os.path.join(_FONTS_DIR, "NotoSansSC-Regular.ttf")

_PDF_FONT_PATHS = [
    # Bundled / downloaded font (highest priority)
    _BUNDLED_FONT,
    # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    # Linux — common packages
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]

_NOTO_SANS_SC_URL = (
    "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
)


def _ensure_cjk_font() -> str | None:
    """Return path to a CJK-capable font, downloading Noto Sans SC if needed."""
    for path in _PDF_FONT_PATHS:
        if os.path.exists(path):
            return path
    # Download Noto Sans SC as fallback
    try:
        urllib.request.urlretrieve(_NOTO_SANS_SC_URL, _BUNDLED_FONT)
        return _BUNDLED_FONT
    except Exception:
        return None


def _setup_pdf_fonts(pdf: FPDF) -> tuple[str, str]:
    """Register CJK font with fpdf2. Returns (regular_family, bold_family).

    Bold is simulated by re-registering the same file under style "B".
    """
    font_path = _ensure_cjk_font()
    if font_path:
        try:
            pdf.add_font("CJK", "", font_path)
            pdf.add_font("CJK", "B", font_path)  # fpdf2 simulates bold
            return "CJK", "CJK"
        except Exception:
            pass
    return "Helvetica", "Helvetica"


# --- Colors ---
_CLR_PRIMARY = (22, 42, 72)       # dark navy — titles
_CLR_ACCENT = (45, 100, 160)      # steel blue — headings
_CLR_TEXT = (40, 40, 40)           # near-black body text
_CLR_MUTED = (110, 110, 110)      # grey — footer, captions
_CLR_TABLE_HEAD = (235, 240, 248) # light blue-grey header bg
_CLR_TABLE_ALT = (245, 247, 250)  # very light alternating row
_CLR_RULE = (180, 195, 215)       # subtle separator lines


def _mc(pdf: FPDF, h: float, text: str):
    """multi_cell wrapper that always resets cursor to left margin."""
    pdf.multi_cell(w=0, h=h, text=text, new_x="LMARGIN", new_y="NEXT")


def _render_table(pdf: FPDF, lines: list[str], font_family: str):
    """Render a markdown table with borders, header shading, and alternating rows."""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return

    # Skip separator rows (|---|---|)
    data_rows = [r for r in rows if not all(set(c) <= {"-", ":", " "} for c in r)]
    if not data_rows:
        return

    num_cols = max(len(r) for r in data_rows)
    # Normalize row lengths
    for r in data_rows:
        while len(r) < num_cols:
            r.append("")

    # Calculate column widths proportionally within page width
    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    # Estimate widths from content
    col_max = [0.0] * num_cols
    pdf.set_font(font_family, "", 9)
    for r in data_rows:
        for ci, cell in enumerate(r):
            w = pdf.get_string_width(cell) + 4
            if w > col_max[ci]:
                col_max[ci] = w
    total = sum(col_max) or 1
    col_widths = [max(page_w * (cw / total), 18) for cw in col_max]
    # Re-scale to fit page
    scale = page_w / sum(col_widths)
    col_widths = [w * scale for w in col_widths]

    y_start = pdf.get_y()

    def _fit_cell(text: str, width: float, font_family: str, style: str, size: int) -> str:
        """Truncate text to fit within cell width."""
        pdf.set_font(font_family, style, size)
        if pdf.get_string_width(text) <= width - 2:
            return text
        while len(text) > 1 and pdf.get_string_width(text + "...") > width - 2:
            text = text[:-1]
        return text + "..." if text else ""

    # Header row
    if len(data_rows) >= 1:
        pdf.set_fill_color(*_CLR_TABLE_HEAD)
        pdf.set_draw_color(*_CLR_RULE)
        pdf.set_font(font_family, "B", 9)
        pdf.set_text_color(*_CLR_PRIMARY)
        row_h = 7
        for ci, cell in enumerate(data_rows[0]):
            fitted = _fit_cell(cell, col_widths[ci], font_family, "B", 9)
            pdf.cell(col_widths[ci], row_h, fitted, border=1, fill=True)
        pdf.ln(row_h)

    # Data rows
    pdf.set_font(font_family, "", 9)
    pdf.set_text_color(*_CLR_TEXT)
    for ri, row in enumerate(data_rows[1:]):
        if ri % 2 == 1:
            pdf.set_fill_color(*_CLR_TABLE_ALT)
            fill = True
        else:
            fill = False
        row_h = 6
        for ci, cell in enumerate(row):
            fitted = _fit_cell(cell, col_widths[ci], font_family, "", 9)
            pdf.cell(col_widths[ci], row_h, fitted, border="LR", fill=fill)
        pdf.ln(row_h)

    # Bottom border
    pdf.set_draw_color(*_CLR_RULE)
    x = pdf.l_margin
    for w in col_widths:
        pdf.line(x, pdf.get_y(), x + w, pdf.get_y())
        x += w
    pdf.ln(4)


async def generate_pdf(title: str, content: str) -> dict:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    font_family, bold_family = _setup_pdf_fonts(pdf)

    # --- Header band ---
    pdf.set_fill_color(*_CLR_PRIMARY)
    # Measure title height to size the band
    pdf.set_font(font_family, "B", 18)
    title_w = pdf.get_string_width(title)
    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    title_lines = max(1, int(title_w / page_w) + 1)
    band_h = 16 + title_lines * 12
    pdf.rect(0, 0, pdf.w, band_h, "F")
    pdf.set_y(6)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_family, "B", 18)
    pdf.multi_cell(0, 12, title, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(band_h + 2)

    # Subtitle line (date)
    pdf.set_text_color(*_CLR_MUTED)
    pdf.set_font(font_family, "", 9)
    pdf.cell(0, 5, datetime.now().strftime("%Y-%m-%d"), align="C")
    pdf.ln(10)

    # Thin accent rule
    pdf.set_draw_color(*_CLR_ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    # --- Body ---
    pdf.set_text_color(*_CLR_TEXT)
    all_lines = content.split("\n")
    i = 0
    while i < len(all_lines):
        stripped = all_lines[i].strip()

        # Markdown table block
        if "|" in stripped and stripped.startswith("|"):
            table_lines = []
            while i < len(all_lines) and "|" in all_lines[i].strip():
                table_lines.append(all_lines[i])
                i += 1
            _render_table(pdf, table_lines, font_family)
            continue

        # Bold markers (simple **text** → strip for display)
        display = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)

        if stripped.startswith("### "):
            pdf.ln(3)
            pdf.set_text_color(*_CLR_ACCENT)
            pdf.set_font(font_family, "B", 11)
            _mc(pdf, 6, display[4:])
            pdf.set_text_color(*_CLR_TEXT)
            pdf.set_font(font_family, "", 10)
        elif stripped.startswith("## "):
            pdf.ln(5)
            pdf.set_text_color(*_CLR_PRIMARY)
            pdf.set_font(font_family, "B", 13)
            _mc(pdf, 7, display[3:])
            # Thin rule under section heading
            pdf.set_draw_color(*_CLR_RULE)
            pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
            pdf.ln(3)
            pdf.set_text_color(*_CLR_TEXT)
            pdf.set_font(font_family, "", 10)
        elif stripped.startswith("# "):
            pdf.ln(6)
            pdf.set_text_color(*_CLR_PRIMARY)
            pdf.set_font(font_family, "B", 15)
            _mc(pdf, 9, display[2:])
            pdf.set_draw_color(*_CLR_ACCENT)
            pdf.set_line_width(0.5)
            pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
            pdf.set_line_width(0.2)
            pdf.ln(4)
            pdf.set_text_color(*_CLR_TEXT)
            pdf.set_font(font_family, "", 10)
        elif stripped.startswith(("- ", "* ")):
            bullet = display[2:]
            pdf.set_font(font_family, "", 10)
            x = pdf.get_x()
            pdf.cell(6, 5.5, chr(8226))  # bullet char
            pdf.multi_cell(w=0, h=5.5, text=bullet, new_x="LMARGIN", new_y="NEXT")
        elif stripped:
            pdf.set_font(font_family, "", 10)
            _mc(pdf, 5.5, display)
        else:
            pdf.ln(3)
        i += 1

    # --- Footer on each page ---
    total = pdf.page
    for pg in range(1, total + 1):
        pdf.page = pg
        pdf.set_y(-15)
        pdf.set_draw_color(*_CLR_RULE)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.set_font(font_family, "", 8)
        pdf.set_text_color(*_CLR_MUTED)
        pdf.cell(0, 8, f"Page {pg} / {total}", align="C")

    filename = f"report_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)
    pdf.output(filepath)

    return {"file": filepath, "message": f"PDF report saved: {filename}"}


# --- Reference image generation ---

_REF_PATTERN = re.compile(
    r"\[references\]\s*\n(.*?)\n\s*\[/references\]",
    re.DOTALL | re.IGNORECASE,
)
_REF_LINE_URL_ONLY = re.compile(r"\[(\d+)\]\s*(https?://\S+)")
_REF_LINE_WITH_NAME = re.compile(r"\[(\d+)\]\s*(.+?)\s*\|\s*(https?://\S+)")
_REF_LINE_FALLBACK = re.compile(r"\[(\d+)\]\s*(.+)")


def parse_references(text: str) -> tuple[str, list[dict]]:
    """Extract [references]...[/references] block from text.

    Returns (cleaned_text, references_list) where references_list is
    [{"num": "1", "url": "https://..."}, ...]
    """
    match = _REF_PATTERN.search(text)
    if not match:
        return text, []

    refs = []
    for line in match.group(1).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Try: [1] https://url.com
        m = _REF_LINE_URL_ONLY.match(line)
        if m:
            refs.append({"num": m.group(1), "url": m.group(2).strip()})
            continue
        # Try: [1] Name | https://url.com
        m = _REF_LINE_WITH_NAME.match(line)
        if m:
            refs.append({"num": m.group(1), "url": m.group(3).strip()})
            continue
        # Fallback: [1] anything — check if it contains a URL somewhere
        m = _REF_LINE_FALLBACK.match(line)
        if m:
            content = m.group(2).strip()
            url_match = re.search(r"https?://\S+", content)
            if url_match:
                refs.append({"num": m.group(1), "url": url_match.group(0).strip()})
            # Skip lines with no URL at all

    cleaned = text[:match.start()].rstrip() + text[match.end():]
    cleaned = cleaned.rstrip()
    return cleaned, refs


def generate_references_image(refs: list[dict]) -> str | None:
    """Render a list of references into a clean PNG image. Returns filepath or None."""
    if not refs:
        return None

    # Build text lines with wrapping
    lines = []
    max_chars = 90  # wrap URLs at this width
    for r in refs:
        label = f"[{r['num']}]"
        url = r["url"]
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
