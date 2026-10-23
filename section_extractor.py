"""Extract strengths, weaknesses, recommendations, and executive summary."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from score_extractor import Indicator, ScoreTable

@dataclass
class IndicatorDetail:
    indicator: Indicator
    context_text: str = ""
    strengths: str = ""
    weaknesses: str = ""
    recommendations: str = ""

_STRENGTHS_RE = re.compile(r"(?:^|\n)\s*(?:Strengths(?:\s*(?:and|/)\s*best\s*practices)?)\s*\n", re.IGNORECASE)
_WEAKNESSES_RE = re.compile(r"(?:^|\n)\s*(?:Areas\s+(?:that|which)\s+need\s+strengthening(?:\s+and\s+challenges)?|Challenges|Weaknesses)\s*\n", re.IGNORECASE)
_RECOMMENDATIONS_RE = re.compile(r"(?:^|\n)\s*(?:Recommend(?:ed)?\s+priority\s+actions|Recommendations?\s+for\s+priority\s+actions|Priority\s+actions)\s*\n", re.IGNORECASE)
_NEXT_SECTION_RE = re.compile(r"(?:^|\n)(?:(?:P|D|R|CE|RE|PoE|E)\.?\d+\.?\d*\.?\s+.+?[\u2013\u2014\-]+\s*Score\s*[1-5]|Indicators\s+and\s+scores|(?:Prevent|Detect|Respond|Other))", re.IGNORECASE)


def extract_executive_summary(report_text: str) -> str:
    """
    Extract the executive summary section from the JEE report.
    Returns the raw text of the executive summary.
    """
    # Find the start of executive summary
    exec_start = re.search(
        r"(?:^|\n)\s*(?:Executive\s+summary|EXECUTIVE\s+SUMMARY)\s*\n",
        report_text, re.IGNORECASE,
    )
    if not exec_start:
        return ""

    rest = report_text[exec_start.end():]

    # Find where it ends — typically before "Scores and priority actions" or
    # the first technical area section
    end_markers = [
        r"(?:^|\n)\s*(?:Scores?\s+and\s+priority\s+actions|scores\s+and\s+priority)",
        r"(?:^|\n)\s*(?:South\s+\w+\s+scores)",
        r"(?:^|\n)\s*(?:PREVENT|Prevent\s*\n)",
        r"(?:^|\n)\s*(?:National\s+legislation)",
        r"(?:^|\n)\s*(?:P1\.|P\.1\.)",
    ]
    end_pos = len(rest)
    for pattern in end_markers:
        m = re.search(pattern, rest, re.IGNORECASE)
        if m and m.start() < end_pos:
            end_pos = m.start()

    summary_text = rest[:end_pos].strip()

    # Truncate if excessively long (some have boilerplate)
    if len(summary_text) > 5000:
        summary_text = summary_text[:5000]

    return summary_text


def extract_section_details(report_text, score_table, colours=None):
    indicators = score_table.indicators
    if colours:
        indicators = [i for i in indicators if i.colour in colours]
    return [_extract_for_indicator(report_text, ind) for ind in indicators]

def _extract_for_indicator(report_text, ind):
    detail = IndicatorDetail(indicator=ind)
    escaped_code = re.escape(ind.code)
    heading_pattern = re.compile(escaped_code + r"\.?\s+" + re.escape(ind.name[:30]).replace(r"\ ", r"\s+") + r".*?Score\s*" + str(ind.score), re.IGNORECASE | re.DOTALL)
    match = heading_pattern.search(report_text)
    if not match:
        fallback = re.compile(escaped_code + r"\.?\s+.+?Score\s*" + str(ind.score), re.IGNORECASE | re.DOTALL)
        match = fallback.search(report_text)
    if not match: return detail
    start = match.start()
    rest = report_text[start:]
    next_match = _NEXT_SECTION_RE.search(rest[10:])
    block = rest[:next_match.start() + 10] if next_match else rest[:5000]
    detail.context_text = block[:500]
    sub_positions = []
    for label, pattern in [("strengths", _STRENGTHS_RE), ("weaknesses", _WEAKNESSES_RE), ("recommendations", _RECOMMENDATIONS_RE)]:
        m = pattern.search(block)
        if m: sub_positions.append((label, m.end()))
    sub_positions.sort(key=lambda x: x[1])
    for i, (label, pos) in enumerate(sub_positions):
        end = len(block)
        if i + 1 < len(sub_positions):
            next_pos = sub_positions[i + 1][1]
            for p in [_STRENGTHS_RE, _WEAKNESSES_RE, _RECOMMENDATIONS_RE]:
                m2 = p.search(block[max(0, next_pos - 200):next_pos])
                if m2:
                    end = max(0, next_pos - 200) + m2.start()
                    break
        text = re.sub(r"^\s*[\u2022\u25cf\u25aa]\s*", "- ", block[pos:end].strip(), flags=re.MULTILINE)
        setattr(detail, label, text)
    return detail

def group_details_by_section(details):
    grouped = {}
    for d in details:
        grouped.setdefault(d.indicator.section, []).append(d)
    return grouped
