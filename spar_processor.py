"""
spar_processor.py — Fetch, parse, and generate PDF for WHO SPAR reports.

Key fix: strips all HTML tags before parsing so it works with both
raw HTML (from requests in Colab) and markdown-converted text.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import requests

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# ── Colours ───────────────────────────────────────────────────────────────
RED_BG=HexColor("#FECACA"); RED_DOT=HexColor("#DC2626"); RED_TEXT=HexColor("#991B1B")
YELLOW_BG=HexColor("#FEF3C7"); YELLOW_DOT=HexColor("#F59E0B"); YELLOW_TEXT=HexColor("#92400E")
GREEN_BG=HexColor("#D1FAE5"); GREEN_DOT=HexColor("#10B981"); GREEN_TEXT=HexColor("#065F46")
HEADER_BG=HexColor("#1E3A5F"); UKHSA_BLUE=HexColor("#1E3A5F")
LIGHT_GREY=HexColor("#F3F4F6"); BORDER_GREY=HexColor("#D1D5DB")

def _cls(score): return "red" if score <= 30 else ("yellow" if score <= 60 else "green")
_DOT = {"red": RED_DOT, "yellow": YELLOW_DOT, "green": GREEN_DOT}
_BG  = {"red": RED_BG,  "yellow": YELLOW_BG,  "green": GREEN_BG}

@dataclass
class SparIndicator:
    code: str; name: str; score: int; colour: str

@dataclass
class SparCapacity:
    code: str; name: str; avg_score: int; colour: str
    indicators: List[SparIndicator] = field(default_factory=list)

@dataclass
class SparReport:
    country: str; year: str; url: str
    overall_score: int = 0; global_score: int = 0; regional_score: int = 0
    capacities: List[SparCapacity] = field(default_factory=list)
    poe: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# FETCH + PARSE
# ═══════════════════════════════════════════════════════════════════════════

def _country_slug(c):
    return re.sub(r'[^a-z0-9]+', '-', re.sub(r"[''()]", "", c.lower().strip())).strip('-')


def _strip_html(html: str) -> str:
    """
    Convert raw HTML to plain text lines.
    This is the critical fix — requests.get() returns raw HTML in Colab,
    not the markdown that web_fetch produces.
    """
    # Remove script/style blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Replace <br>, </p>, </div>, </li>, </tr> with newlines
    text = re.sub(r'<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>', '\n', text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#039;', "'").replace('&quot;', '"')
    # Collapse whitespace within lines but keep newlines
    lines = []
    for line in text.split('\n'):
        cleaned = re.sub(r'\s+', ' ', line).strip()
        if cleaned:
            lines.append(cleaned)
    return '\n'.join(lines)


def fetch_spar(country: str, year: str = "2024") -> SparReport:
    slug = _country_slug(country)
    url = f"https://extranet.who.int/sph/spar-{slug}-submitted{year}"
    print(f"  Fetching: {url}")
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (SPAR Research)"})
    if resp.status_code == 404:
        raise FileNotFoundError(f"SPAR not found for '{country}' ({year}). Try a different year.")
    resp.raise_for_status()
    # Strip HTML tags to get clean text — works for both raw HTML and markdown
    clean_text = _strip_html(resp.text)
    return _parse(clean_text, country, year, url)


def _parse(text: str, country: str, year: str, url: str) -> SparReport:
    """Parse the plain-text version of the SPAR page."""
    report = SparReport(country=country, year=year, url=url)

    # Also strip ** markdown bold markers (from web_fetch markdown conversion)
    text = text.replace('**', '')

    # Overall scores
    m = re.search(r'(?:Spar\s*)?CountryCapacityScore\s*\n?\s*(\d+)', text, re.IGNORECASE)
    if m: report.overall_score = int(m.group(1))
    m = re.search(r'Global Capacity Score\s*\n?\s*(\d+)', text, re.IGNORECASE)
    if m: report.global_score = int(m.group(1))
    m = re.search(r'Regional Capacity Score\s*\n?\s*(\d+)', text, re.IGNORECASE)
    if m: report.regional_score = int(m.group(1))

    # PoE
    for t in ["Ground crossings", "Port", "Airport"]:
        m = re.search(rf'{t}\s*\n?\s*(\d+)', text, re.IGNORECASE)
        if m: report.poe[t] = int(m.group(1))

    # ── Parse line by line ─────────────────────────────────────────────
    lines = text.split('\n')
    current_cap = None
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # ── Capacity header: "C1: Name" or "C1. Name" ─────────────────
        # Match: C1: Legislation and financing
        # Match: C13. Radiation emergencies
        # Match: C7:Human resources (no space)
        cap_m = re.match(r'^(C\d+)[:.]\s*(.+)', line)
        if cap_m:
            code = cap_m.group(1).upper()
            name = cap_m.group(2).strip()

            # Skip if this is "C1: Average Capacities Score" (not a header)
            if 'average' in name.lower() or 'score' in name.lower():
                # This IS the average score line — look for the number
                score_val = 0
                for j in range(i, min(i+3, len(lines))):
                    sm = re.match(r'^\s*(\d+)\s*$', lines[j].strip())
                    if sm:
                        score_val = int(sm.group(1))
                        break
                # Assign to current capacity if exists
                if current_cap and current_cap.avg_score == 0:
                    current_cap.avg_score = score_val
                    current_cap.colour = _cls(score_val)
                i += 1
                continue

            # It's a real capacity header
            current_cap = SparCapacity(code=code, name=name, avg_score=0, colour="yellow")
            report.capacities.append(current_cap)
            i += 1
            continue

        # ── Average score line that starts differently ─────────────────
        avg_m = re.match(r'^C\d+:\s*Average\s+Capacit', line, re.IGNORECASE)
        if avg_m:
            # Score is on this line or next
            score_on_line = re.search(r'(\d+)\s*$', line)
            if score_on_line:
                score_val = int(score_on_line.group(1))
            else:
                score_val = 0
                for j in range(i+1, min(i+3, len(lines))):
                    sm = re.match(r'^\s*(\d+)\s*$', lines[j].strip())
                    if sm:
                        score_val = int(sm.group(1))
                        break
            if current_cap and current_cap.avg_score == 0:
                current_cap.avg_score = score_val
                current_cap.colour = _cls(score_val)
            i += 1
            continue

        # ── Indicator line: C.X.Y name ─────────────────────────────────
        ind_m = re.match(r'^(C\.\d+\.\d+)\s+(.+)', line)
        if ind_m and current_cap is not None:
            ind_code = ind_m.group(1)
            ind_name = ind_m.group(2).strip().rstrip('(').strip()
            # Score is on the NEXT line that's just a number
            score = 0
            for j in range(i+1, min(i+4, len(lines))):
                sm = re.match(r'^\s*(\d+)\s*$', lines[j].strip())
                if sm:
                    score = int(sm.group(1))
                    break
            current_cap.indicators.append(
                SparIndicator(code=ind_code, name=ind_name, score=score, colour=_cls(score))
            )
            i += 1
            continue

        i += 1

    return report


# ═══════════════════════════════════════════════════════════════════════════
# PDF GENERATION — concise analyst brief
# ═══════════════════════════════════════════════════════════════════════════

def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=base["Title"], fontSize=22, leading=26, textColor=UKHSA_BLUE, spaceAfter=2*mm, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("ST", parent=base["Normal"], fontSize=10, leading=13, textColor=HexColor("#6B7280"), spaceAfter=2*mm),
        "link": ParagraphStyle("LK", parent=base["Normal"], fontSize=8, textColor=HexColor("#2563EB"), spaceAfter=3*mm),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontSize=13, leading=16, textColor=UKHSA_BLUE, spaceBefore=4*mm, spaceAfter=2*mm),
        "body": ParagraphStyle("B", parent=base["Normal"], fontSize=9, leading=12, textColor=HexColor("#1F2937"), spaceAfter=1.5*mm),
        "bullet_green": ParagraphStyle("BG", parent=base["Normal"], fontSize=9, leading=12, textColor=GREEN_TEXT, leftIndent=5*mm, spaceAfter=0.5*mm),
        "bullet_red": ParagraphStyle("BR", parent=base["Normal"], fontSize=9, leading=12, textColor=RED_TEXT, leftIndent=5*mm, spaceAfter=0.5*mm),
        "bullet_yellow": ParagraphStyle("BY", parent=base["Normal"], fontSize=9, leading=12, textColor=YELLOW_TEXT, leftIndent=5*mm, spaceAfter=0.5*mm),
        "metric_big": ParagraphStyle("MB", parent=base["Normal"], fontSize=18, leading=22, textColor=UKHSA_BLUE, alignment=TA_CENTER),
        "metric_label": ParagraphStyle("ML", parent=base["Normal"], fontSize=8, leading=10, textColor=HexColor("#6B7280"), alignment=TA_CENTER),
        "th": ParagraphStyle("TH", parent=base["Normal"], fontSize=8, leading=10, textColor=white),
        "tc": ParagraphStyle("TC", parent=base["Normal"], fontSize=8, leading=10, textColor=HexColor("#1F2937")),
        "tcc": ParagraphStyle("TCC", parent=base["Normal"], fontSize=9, leading=12, textColor=HexColor("#1F2937"), alignment=TA_CENTER),
        "legend": ParagraphStyle("LG", parent=base["Normal"], fontSize=7, leading=9, textColor=HexColor("#6B7280"), spaceAfter=1.5*mm, alignment=TA_CENTER),
        "footer": ParagraphStyle("F", parent=base["Normal"], fontSize=7, leading=9, textColor=HexColor("#9CA3AF"), alignment=TA_CENTER),
    }


def generate_spar_pdf(output_path: str, report: SparReport) -> str:
    s = _styles()
    el = []

    # Title
    el.append(Spacer(1, 4*mm))
    el.append(Paragraph(f"SPAR Summary: {report.country} ({report.year})", s["title"]))
    el.append(Paragraph("IHR State Party Self-Assessment Annual Report", s["subtitle"]))
    el.append(Paragraph(
        f'<a href="{report.url}" color="#2563EB">\u2197 View original SPAR on WHO SPH Portal</a>', s["link"]))

    # Metrics bar
    strong = [c for c in report.capacities if c.colour == "green"]
    weak = [c for c in report.capacities if c.colour == "red"]
    med = [c for c in report.capacities if c.colour == "yellow"]

    def _cell(n, cn, label):
        return [Paragraph(f'<font color="{_DOT[cn].hexval()}"><b>{n}</b></font>', s["metric_big"]),
                Paragraph(label, s["metric_label"])]
    bar = [[
        _cell(len(strong), "green", "Strong >60%"),
        _cell(len(med), "yellow", "Moderate 31-60%"),
        _cell(len(weak), "red", "Weak \u226430%"),
        [Paragraph(f'<b>{report.overall_score}%</b>', s["metric_big"]),
         Paragraph("Country score", s["metric_label"])],
        [Paragraph(f'<b>{report.regional_score}%</b>', s["metric_big"]),
         Paragraph("Regional avg", s["metric_label"])],
    ]]
    t = Table(bar, colWidths=[33*mm]*5)
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("BOX",(0,0),(-1,-1),0.75,BORDER_GREY),("INNERGRID",(0,0),(-1,-1),0.5,BORDER_GREY),
        ("TOPPADDING",(0,0),(-1,-1),2.5*mm),("BOTTOMPADDING",(0,0),(-1,-1),2.5*mm),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT_GREY),
    ]))
    el.append(t)
    el.append(Spacer(1, 3*mm))

    # Key findings
    el.append(Paragraph("Key Findings", s["h1"]))
    el.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_GREY))
    el.append(Spacer(1, 1*mm))

    diff = report.overall_score - report.global_score
    direction = "above" if diff >= 0 else "below"
    reg_diff = report.overall_score - report.regional_score
    reg_dir = "above" if reg_diff >= 0 else "below"
    el.append(Paragraph(
        f"Country score <b>{report.overall_score}%</b> is <b>{abs(diff)} points {direction}</b> "
        f"the global average ({report.global_score}%) and <b>{abs(reg_diff)} points {reg_dir}</b> "
        f"the regional average ({report.regional_score}%).", s["body"]))

    if weak:
        el.append(Paragraph('<font color="#991B1B"><b>Priority areas requiring investment:</b></font>', s["body"]))
        for c in sorted(weak, key=lambda x: x.avg_score):
            worst = [i for i in c.indicators if i.score <= 30]
            detail = ""
            if worst: detail = " \u2014 weakest: " + ", ".join(f"{i.code} ({i.score}%)" for i in worst)
            el.append(Paragraph(f"\u2022  <b>{c.code}: {c.name}</b> ({c.avg_score}%){detail}", s["bullet_red"]))

    if med:
        el.append(Spacer(1, 1*mm))
        el.append(Paragraph('<font color="#92400E"><b>Areas with development gaps:</b></font>', s["body"]))
        for c in sorted(med, key=lambda x: x.avg_score):
            low = [i for i in c.indicators if i.score <= 40]
            detail = ""
            if low: detail = " \u2014 weakest: " + ", ".join(f"{i.code} ({i.score}%)" for i in low)
            el.append(Paragraph(f"\u2022  <b>{c.code}: {c.name}</b> ({c.avg_score}%){detail}", s["bullet_yellow"]))

    if strong:
        el.append(Spacer(1, 1*mm))
        el.append(Paragraph('<font color="#065F46"><b>Demonstrated capacity:</b></font>', s["body"]))
        for c in sorted(strong, key=lambda x: -x.avg_score):
            el.append(Paragraph(f"\u2022  <b>{c.code}: {c.name}</b> ({c.avg_score}%)", s["bullet_green"]))

    el.append(Spacer(1, 3*mm))

    # Capacity table
    el.append(Paragraph("Capacity Scores", s["h1"]))
    el.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_GREY))
    el.append(Paragraph(
        '<font color="#DC2626">\u25cf</font> \u226430% (Weak)   '
        '<font color="#F59E0B">\u25cf</font> 31\u201360% (Moderate)   '
        '<font color="#10B981">\u25cf</font> >60% (Strong)', s["legend"]))

    hdr = [Paragraph("<b></b>",s["th"]), Paragraph("<b>Capacity</b>",s["th"]),
           Paragraph("<b>Score</b>",s["th"]), Paragraph("<b>Indicators</b>",s["th"])]
    tdata = [hdr]; row_bgs = []
    for c in report.capacities:
        dot_s = ParagraphStyle("d",fontSize=12,alignment=TA_CENTER)
        inds = "   ".join(
            f'<font color="{_DOT[i.colour].hexval()}">\u25cf</font>'
            f'<font size="7"> {i.code} ({i.score}%)</font>'
            for i in c.indicators
        ) if c.indicators else "\u2014"
        tdata.append([
            Paragraph(f'<font color="{_DOT[c.colour].hexval()}">\u25cf</font>', dot_s),
            Paragraph(f"<b>{c.code}:</b> {c.name}", s["tc"]),
            Paragraph(f"<b>{c.avg_score}%</b>", s["tcc"]),
            Paragraph(inds, s["tc"]),
        ])
        row_bgs.append(_BG[c.colour])

    t = Table(tdata, colWidths=[10*mm, 48*mm, 14*mm, 99*mm], repeatRows=1)
    cmds = [
        ("BACKGROUND",(0,0),(-1,0),HEADER_BG),("GRID",(0,0),(-1,-1),0.5,BORDER_GREY),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("ALIGN",(0,0),(0,-1),"CENTER"),("ALIGN",(2,0),(2,-1),"CENTER"),
    ]
    for i, bg in enumerate(row_bgs): cmds.append(("BACKGROUND",(0,i+1),(-1,i+1),bg))
    t.setStyle(TableStyle(cmds))
    el.append(t)

    if report.poe:
        el.append(Spacer(1, 2*mm))
        poe_text = " \u00b7 ".join(f"{k}: <b>{v}</b>" for k,v in report.poe.items())
        el.append(Paragraph(f"IHR Designated Points of Entry: {poe_text}", s["body"]))

    el.append(Spacer(1, 4*mm))
    el.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GREY))
    el.append(Paragraph("Generated by JEE/SPAR Summarisation Pipeline \u00b7 Source: WHO SPH Portal", s["footer"]))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm, topMargin=16*mm, bottomMargin=14*mm)
    def hf(canvas, d):
        canvas.saveState(); w,h = A4
        canvas.setStrokeColor(UKHSA_BLUE); canvas.setLineWidth(1.5)
        canvas.line(15*mm,h-12*mm,w-15*mm,h-12*mm)
        canvas.setFont("Helvetica",7); canvas.setFillColor(HexColor("#6B7280"))
        canvas.drawString(15*mm,h-10.5*mm,f"SPAR: {report.country} ({report.year})")
        canvas.drawRightString(w-15*mm,h-10.5*mm,"UKHSA \u00b7 State Party Self-Assessment")
        canvas.setFont("Helvetica",7); canvas.setFillColor(HexColor("#9CA3AF"))
        canvas.drawCentredString(w/2,8*mm,f"Page {d.page}")
        canvas.restoreState()
    doc.build(el, onFirstPage=hf, onLaterPages=hf)
    return str(output_path)
