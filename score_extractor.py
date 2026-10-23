"""Parse indicator scores from JEE reports and classify red/yellow/green."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List
from config.settings import SCORE_RED, SCORE_YELLOW, SCORE_GREEN, SCORE_LABELS

@dataclass
class Indicator:
    code: str
    name: str
    score: int
    colour: str
    section: str = ""
    @property
    def score_label(self):
        return SCORE_LABELS.get(self.score, "Unknown")

@dataclass
class ScoreTable:
    indicators: List[Indicator] = field(default_factory=list)

    @property
    def red(self): return [i for i in self.indicators if i.colour == "red"]
    @property
    def yellow(self): return [i for i in self.indicators if i.colour == "yellow"]
    @property
    def green(self): return [i for i in self.indicators if i.colour == "green"]

    def by_section(self):
        sections = {}
        for ind in self.indicators:
            sections.setdefault(ind.section, []).append(ind)
        return sections

    def summary_stats(self):
        total = len(self.indicators)
        return {
            "total_indicators": total,
            "red_count": len(self.red),
            "yellow_count": len(self.yellow),
            "green_count": len(self.green),
            "mean_score": round(sum(i.score for i in self.indicators) / total, 2) if total else 0,
        }

SCORE_PATTERN = re.compile(
    r"(?P<code>(?:P|D|R|CE|RE|PoE|E)\.?\d+\.?\d*\.?)\s+(?P<name>.+?)\s*[\u2013\u2014\-]+\s*Score\s*(?P<score>[1-5])",
    re.IGNORECASE
)
SECTION_RE = re.compile(r"^(P|D|R|CE|RE|PoE|E)\.?(\d+)?")

def _classify(score):
    if score in SCORE_RED: return "red"
    if score in SCORE_GREEN: return "green"
    return "yellow"

def _normalise_section(code):
    m = SECTION_RE.match(code)
    if not m: return code
    return f"{m.group(1)}{m.group(2) or ''}"

def extract_scores(report_text):
    table = ScoreTable()
    seen = set()
    for match in SCORE_PATTERN.finditer(report_text):
        code = match.group("code").strip().rstrip(".")
        name = match.group("name").strip()
        score = int(match.group("score"))
        if code in seen: continue
        seen.add(code)
        table.indicators.append(Indicator(
            code=code, name=name, score=score,
            colour=_classify(score), section=_normalise_section(code),
        ))
    table.indicators.sort(key=lambda i: i.code)
    return table
