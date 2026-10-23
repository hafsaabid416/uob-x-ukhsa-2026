"""
pdf_formatter.py — Compact, professionally formatted PDF output.

Changes from previous version:
  1. Score table: one row per technical area, avg score, indicator codes
     as colour-coded dots (no full names, no capacity level column)
  2. Scoring key at top of table, not bottom
  3. Executive brief at start of document
  4. Tighter spacing throughout to reduce page count
"""
from __future__ import annotations
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)

from score_extractor import ScoreTable
from config.settings import SECTION_MAP, SCORE_LABELS

# ── Colours ───────────────────────────────────────────────────────────────

RED_BG      = HexColor("#FECACA"); RED_TEXT   = HexColor("#991B1B"); RED_DOT   = HexColor("#DC2626")
YELLOW_BG   = HexColor("#FEF3C7"); YELLOW_TEXT= HexColor("#92400E"); YELLOW_DOT= HexColor("#F59E0B")
GREEN_BG    = HexColor("#D1FAE5"); GREEN_TEXT = HexColor("#065F46"); GREEN_DOT = HexColor("#10B981")
HEADER_BG   = HexColor("#1E3A5F"); UKHSA_BLUE = HexColor("#1E3A5F")
LIGHT_GREY  = HexColor("#F3F4F6"); BORDER_GREY= HexColor("#D1D5DB")

COLOUR_MAP = {
    "red":    {"bg": RED_BG,    "text": RED_TEXT,    "dot": RED_DOT},
    "yellow": {"bg": YELLOW_BG, "text": YELLOW_TEXT, "dot": YELLOW_DOT},
    "green":  {"bg": GREEN_BG,  "text": GREEN_TEXT,  "dot": GREEN_DOT},
}

def _section_label(prefix):
    return SECTION_MAP.get(prefix, prefix)

def _pct(n, total):
    return f"{n / total * 100:.0f}%" if total else "0%"


# ── Styles ────────────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=base["Title"], fontSize=22, leading=26, textColor=UKHSA_BLUE, spaceAfter=2*mm, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("ST", parent=base["Normal"], fontSize=10, leading=13, textColor=HexColor("#6B7280"), spaceAfter=4*mm),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontSize=14, leading=17, textColor=UKHSA_BLUE, spaceBefore=5*mm, spaceAfter=2*mm),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontSize=12, leading=15, textColor=UKHSA_BLUE, spaceBefore=4*mm, spaceAfter=1.5*mm),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontSize=10, leading=13, textColor=HexColor("#374151"), spaceBefore=3*mm, spaceAfter=1*mm),
        "body": ParagraphStyle("B", parent=base["Normal"], fontSize=9, leading=12, textColor=HexColor("#1F2937"), spaceAfter=1.5*mm, alignment=TA_JUSTIFY),
        "body_small": ParagraphStyle("BS", parent=base["Normal"], fontSize=8, leading=11, textColor=HexColor("#1F2937"), spaceAfter=1*mm, alignment=TA_JUSTIFY),
        "bullet": ParagraphStyle("BL", parent=base["Normal"], fontSize=9, leading=12, textColor=HexColor("#1F2937"), leftIndent=10*mm, bulletIndent=5*mm, spaceAfter=1*mm),
        "exec_brief": ParagraphStyle("EB", parent=base["Normal"], fontSize=9, leading=13, textColor=HexColor("#1F2937"), spaceAfter=1.5*mm, alignment=TA_JUSTIFY, backColor=LIGHT_GREY, borderPadding=6, leftIndent=3*mm, rightIndent=3*mm),
        "metric_big": ParagraphStyle("MB", parent=base["Normal"], fontSize=18, leading=22, textColor=UKHSA_BLUE, alignment=TA_CENTER, spaceAfter=0),
        "metric_label": ParagraphStyle("ML", parent=base["Normal"], fontSize=8, leading=10, textColor=HexColor("#6B7280"), alignment=TA_CENTER),
        "table_header": ParagraphStyle("TH", parent=base["Normal"], fontSize=8, leading=10, textColor=white, alignment=TA_LEFT),
        "table_cell": ParagraphStyle("TC", parent=base["Normal"], fontSize=8, leading=10, textColor=HexColor("#1F2937")),
        "table_cell_center": ParagraphStyle("TCC", parent=base["Normal"], fontSize=8, leading=10, textColor=HexColor("#1F2937"), alignment=TA_CENTER),
        "footer": ParagraphStyle("F", parent=base["Normal"], fontSize=7, leading=9, textColor=HexColor("#9CA3AF"), alignment=TA_CENTER),
        "strong_item": ParagraphStyle("SI", parent=base["Normal"], fontSize=9, leading=12, textColor=GREEN_TEXT, leftIndent=5*mm, spaceAfter=0.5*mm),
        "weak_item": ParagraphStyle("WI", parent=base["Normal"], fontSize=9, leading=12, textColor=RED_TEXT, leftIndent=5*mm, spaceAfter=0.5*mm),
        "legend": ParagraphStyle("LG", parent=base["Normal"], fontSize=7, leading=9, textColor=HexColor("#6B7280"), spaceAfter=2*mm, alignment=TA_CENTER),
    }


# ── Metrics bar ───────────────────────────────────────────────────────────

def _build_metrics_bar(score_table, styles):
    stats = score_table.summary_stats()
    total = stats["total_indicators"]
    def _cell(count, cname, label):
        cm = COLOUR_MAP[cname]
        return [Paragraph(f'<font color="{cm["dot"].hexval()}"><b>{count}</b></font>', styles["metric_big"]),
                Paragraph(f'{label} ({_pct(count, total)})', styles["metric_label"])]
    data = [[
        _cell(stats["green_count"], "green", "Green"),
        _cell(stats["yellow_count"], "yellow", "Yellow"),
        _cell(stats["red_count"], "red", "Red"),
        [Paragraph(f'<b>{stats["mean_score"]}</b>', styles["metric_big"]),
         Paragraph("Mean / 5", styles["metric_label"])],
    ]]
    t = Table(data, colWidths=[40*mm]*4)
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"), ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("BOX",(0,0),(-1,-1),0.75,BORDER_GREY), ("INNERGRID",(0,0),(-1,-1),0.5,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),3*mm), ("BOTTOMPADDING",(0,0),(-1,-1),3*mm),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT_GREY),
    ]))
    return t


# ── Compact score table (one row per technical area) ──────────────────────

def _build_score_table(score_table, styles):
    """
    One row per technical area:
    | Technical Area | Avg Score | Indicators (colour-coded codes) |
    """
    header = [
        Paragraph("<b>Technical Area</b>", styles["table_header"]),
        Paragraph("<b>Avg</b>", styles["table_header"]),
        Paragraph("<b>Indicators</b>", styles["table_header"]),
    ]
    data = [header]
    row_bg_colours = []

    sections = score_table.by_section()
    for section_key in sorted(sections.keys()):
        indicators = sorted(sections[section_key], key=lambda i: i.code)
        section_name = _section_label(section_key)
        n = len(indicators)
        avg = sum(i.score for i in indicators) / n

        # Determine row background by dominant colour
        reds = sum(1 for i in indicators if i.colour == "red")
        greens = sum(1 for i in indicators if i.colour == "green")
        if reds > 0 and reds >= greens:
            row_bg = RED_BG
        elif greens > n / 2:
            row_bg = GREEN_BG
        else:
            row_bg = YELLOW_BG
        row_bg_colours.append(row_bg)

        # Build indicator codes with colour dots
        ind_parts = []
        for ind in indicators:
            cm = COLOUR_MAP[ind.colour]
            # Short code: D.1.1 -> D1.1, CE.2 -> CE.2
            short_code = ind.code.replace(".", "")
            # Re-insert dots properly: P11 -> P1.1, D13 -> D1.3
            if len(short_code) > 2 and short_code[0] in "PDR" and short_code[1:].isdigit():
                short_code = f"{short_code[0]}{short_code[1]}.{short_code[2:]}"
            elif short_code.startswith(("CE","RE","PoE")) and not "." in ind.code:
                # Already fine
                pass
            else:
                short_code = ind.code  # keep original

            ind_parts.append(
                f'<font color="{cm["dot"].hexval()}">\u25cf</font>'
                f'<font size="7"> {short_code}</font>'
            )

        indicators_text = "   ".join(ind_parts)

        row = [
            Paragraph(f"<b>{section_name}</b>", styles["table_cell"]),
            Paragraph(f"<b>{avg:.1f}</b>", styles["table_cell_center"]),
            Paragraph(indicators_text, styles["table_cell"]),
        ]
        data.append(row)

    col_widths = [52*mm, 14*mm, 105*mm]
    t = Table(data, colWidths=col_widths, repeatRows=1)

    cmds = [
        ("BACKGROUND",(0,0),(-1,0),HEADER_BG),
        ("TEXTCOLOR",(0,0),(-1,0),white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,0),8),
        ("GRID",(0,0),(-1,-1),0.5,BORDER_GREY),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),3),
        ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),2),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("ALIGN",(1,0),(1,-1),"CENTER"),
    ]
    for i, bg in enumerate(row_bg_colours):
        cmds.append(("BACKGROUND", (0, i+1), (-1, i+1), bg))
    t.setStyle(TableStyle(cmds))
    return t


# ── LLM markdown → flowables ─────────────────────────────────────────────

def _parse_llm_markdown(llm_text, styles):
    elements = []
    lines = llm_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line: i += 1; continue
        if line.startswith("### "):
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line[4:].strip())
            elements.append(Paragraph(text, styles["h2"])); i += 1; continue
        if line.startswith("#### "):
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line[5:].strip())
            elements.append(Paragraph(text, styles["h3"])); i += 1; continue
        if line.startswith(("- ", "* ")):
            text = line[2:].strip()
            while i+1 < len(lines) and lines[i+1].strip() and not lines[i+1].strip().startswith(("-","*","#")):
                i += 1; text += " " + lines[i].strip()
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            elements.append(Paragraph(f"\u2022  {text}", styles["bullet"])); i += 1; continue
        text = line
        while i+1 < len(lines) and lines[i+1].strip() and not lines[i+1].strip().startswith(("-","*","#")):
            i += 1; text += " " + lines[i].strip()
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        elements.append(Paragraph(text, styles["body"])); i += 1
    return elements


# ── Header / footer ──────────────────────────────────────────────────────

def _header_footer(canvas, doc, country, jee_year=None):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(UKHSA_BLUE); canvas.setLineWidth(1.5)
    canvas.line(15*mm, h - 12*mm, w - 15*mm, h - 12*mm)
    canvas.setFont("Helvetica", 7); canvas.setFillColor(HexColor("#6B7280"))
    year_tag = f" ({jee_year})" if jee_year and jee_year != "Unknown" else ""
    canvas.drawString(15*mm, h - 10.5*mm, f"JEE Summary: {country}{year_tag}")
    canvas.drawRightString(w - 15*mm, h - 10.5*mm, "UKHSA \u00b7 Joint External Evaluation")
    canvas.setFont("Helvetica", 7); canvas.setFillColor(HexColor("#9CA3AF"))
    canvas.drawCentredString(w / 2, 8*mm, f"Page {doc.page}")
    canvas.restoreState()


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def generate_pdf(
    output_path, country, score_table, llm_summary,
    executive_brief="", model="", prompt_tokens=0,
    completion_tokens=0, latency=0.0,
    jee_year=None, jee_url=None,
):
    styles = _build_styles()
    elements = []
    stats = score_table.summary_stats()
    sections = score_table.by_section()

    # ── Title ──────────────────────────────────────────────────────────
    elements.append(Spacer(1, 4*mm))
    year_tag = f" ({jee_year})" if jee_year and jee_year != "Unknown" else ""
    elements.append(Paragraph(f"JEE Summary: {country}{year_tag}", styles["title"]))

    subtitle_parts = [
        f"Joint External Evaluation of IHR Core Capacities",
        f"{stats['total_indicators']} indicators assessed",
    ]
    subtitle = " \u00b7 ".join(subtitle_parts)
    elements.append(Paragraph(subtitle, styles["subtitle"]))

    # Source link
    if jee_url:
        link_style = ParagraphStyle(
            "Link", parent=styles["body_small"],
            textColor=HexColor("#2563EB"), fontSize=8, spaceAfter=3*mm,
        )
        elements.append(Paragraph(
            f'<a href="{jee_url}" color="#2563EB">'
            f'\u2197 View original JEE report on WHO website</a>',
            link_style,
        ))

    # ── Executive brief ────────────────────────────────────────────────
    if executive_brief:
        elements.append(Paragraph("Executive Brief", styles["h1"]))
        brief_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', executive_brief)
        elements.append(Paragraph(brief_text, styles["exec_brief"]))
        elements.append(Spacer(1, 2*mm))

    # ── Metrics bar ────────────────────────────────────────────────────
    elements.append(_build_metrics_bar(score_table, styles))
    elements.append(Spacer(1, 3*mm))

    # ── Overall assessment ─────────────────────────────────────────────
    elements.append(Paragraph("Overall Assessment", styles["h1"]))
    elements.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_GREY))
    elements.append(Spacer(1, 1*mm))

    strong_sections, weak_sections = [], []
    for skey, inds in sorted(sections.items()):
        sname = _section_label(skey)
        reds = [i for i in inds if i.colour == "red"]
        greens = [i for i in inds if i.colour == "green"]
        n = len(inds); avg = sum(i.score for i in inds) / n if n else 0
        if reds:
            codes = ", ".join(i.code for i in reds)
            weak_sections.append(f"<b>{sname}</b> \u2014 {len(reds)}/{n} at score 1 ({codes})")
        if len(greens) == n:
            strong_sections.append(f"<b>{sname}</b> \u2014 all {n} at score 4\u20135 (avg {avg:.1f})")
        elif len(greens) > n / 2:
            strong_sections.append(f"<b>{sname}</b> \u2014 {len(greens)}/{n} at score 4\u20135 (avg {avg:.1f})")

    if strong_sections:
        elements.append(Paragraph('<font color="#065F46"><b>Strong capacity:</b></font>', styles["body"]))
        for s in strong_sections:
            elements.append(Paragraph(f"\u2022  {s}", styles["strong_item"]))
    if weak_sections:
        elements.append(Spacer(1, 1*mm))
        elements.append(Paragraph('<font color="#991B1B"><b>Critical gaps:</b></font>', styles["body"]))
        for w in weak_sections:
            elements.append(Paragraph(f"\u2022  {w}", styles["weak_item"]))
    elements.append(Spacer(1, 3*mm))

    # ── Score table ────────────────────────────────────────────────────
    elements.append(Paragraph("Score Overview", styles["h1"]))
    elements.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_GREY))
    elements.append(Spacer(1, 1*mm))
    # Legend ABOVE the table
    elements.append(Paragraph(
        '<font color="#DC2626">\u25cf</font> Score 1 (No capacity)   '
        '<font color="#F59E0B">\u25cf</font> Score 2\u20133 (Limited / Developed)   '
        '<font color="#10B981">\u25cf</font> Score 4\u20135 (Demonstrated / Sustainable)',
        styles["legend"],
    ))
    elements.append(_build_score_table(score_table, styles))
    elements.append(Spacer(1, 3*mm))

    # ── Section summaries ──────────────────────────────────────────────
    elements.append(Paragraph("Section Summaries", styles["h1"]))
    elements.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_GREY))
    elements.append(Spacer(1, 1*mm))
    elements.extend(_parse_llm_markdown(llm_summary, styles))

    # ── Footer ─────────────────────────────────────────────────────────
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GREY))
    elements.append(Paragraph(
        f"Generated by JEE Summarisation Pipeline \u00b7 Model: {model} \u00b7 "
        f"Tokens: {prompt_tokens} in / {completion_tokens} out \u00b7 Latency: {latency}s",
        styles["footer"],
    ))

    # ── Build ──────────────────────────────────────────────────────────
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=16*mm, bottomMargin=14*mm,
    )
    doc.build(
        elements,
        onFirstPage=lambda c, d: _header_footer(c, d, country, jee_year),
        onLaterPages=lambda c, d: _header_footer(c, d, country, jee_year),
    )
    return str(output_path)
