"""
llm_summariser.py - LLM backends (Groq/Gemini/Anthropic) + structured prompts.
Now also summarises the executive summary from the original report.
"""
from __future__ import annotations
import json, os, re, time, requests
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from config.settings import (
    LLM_BACKEND, GROQ_MODEL, GROQ_API_URL,
    GEMINI_MODEL, GEMINI_API_URL, ANTHROPIC_MODEL,
    LLM_MAX_TOKENS, LLM_TEMPERATURE,
)
from score_extractor import ScoreTable
from section_extractor import IndicatorDetail

@dataclass
class SummaryResult:
    country: str
    raw_llm_response: str = ""
    executive_brief: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    backend: str = ""
    latency_seconds: float = 0.0

SYSTEM_PROMPT = """\
You are an expert public health analyst working for UKHSA (UK Health Security Agency).
You will receive extracted data from a WHO JEE report. Produce two outputs separated by
the exact marker ===SECTION_SUMMARIES===

FIRST: A 2-3 sentence executive brief summarising the JEE report's executive summary.
Be direct and specific — mention the country, evaluation date if available, overall
capacity level, and the 1-2 most critical cross-cutting findings. No filler.

THEN the marker line: ===SECTION_SUMMARIES===

THEN: Section-by-section summaries covering ONLY the RED and GREEN indicators.
Rules:
- Be concise. Each bullet 1-2 sentences max.
- Reference indicator codes (e.g. P1.1, D3.4) inline.
- For each section produce:
  (a) Recommendations & Weaknesses — from red indicators
  (b) Strengths — from green indicators
  Omit the sub-heading if a section has only one colour.
- Use ### for section headings and #### for sub-headings.
"""

def _build_user_prompt(country, score_table, details, details_by_section, executive_summary=""):
    stats = score_table.summary_stats()
    parts = [
        f"# JEE Report: {country}",
        f"Total indicators: {stats['total_indicators']} | Mean: {stats['mean_score']}",
        f"Red: {stats['red_count']} | Yellow: {stats['yellow_count']} | Green: {stats['green_count']}",
    ]
    if executive_summary:
        parts += ["", "## Original Executive Summary (summarise into 2-3 sentences)", executive_summary[:2000]]
    parts += ["", "## Indicator Data (Red and Green only)", ""]
    for section, section_details in sorted(details_by_section.items()):
        reds = [d for d in section_details if d.indicator.colour == "red"]
        greens = [d for d in section_details if d.indicator.colour == "green"]
        parts.append(f"### Section: {section}")
        parts.append("")
        if reds:
            parts.append("**RED (score 1):**")
            for d in reds:
                parts.append(f"- {d.indicator.code} {d.indicator.name} — Score {d.indicator.score}")
                if d.weaknesses: parts.append(f"  Weaknesses: {d.weaknesses[:600]}")
                if d.recommendations: parts.append(f"  Recommendations: {d.recommendations[:600]}")
                if d.context_text and not d.weaknesses: parts.append(f"  Context: {d.context_text[:400]}")
            parts.append("")
        if greens:
            parts.append("**GREEN (score 4-5):**")
            for d in greens:
                parts.append(f"- {d.indicator.code} {d.indicator.name} — Score {d.indicator.score}")
                if d.strengths: parts.append(f"  Strengths: {d.strengths[:600]}")
                if d.context_text and not d.strengths: parts.append(f"  Context: {d.context_text[:400]}")
            parts.append("")
    parts.append("## Output instructions")
    parts.append("1. First: 2-3 sentence executive brief from the executive summary above.")
    parts.append("2. Then the marker: ===SECTION_SUMMARIES===")
    parts.append("3. Then: section summaries using ### and #### headings. Be concise.")
    return "\n".join(parts)

# ── Retry helper ──────────────────────────────────────────────────────────
def _retry_on_429(make_request, max_retries=5, backend_name=""):
    for attempt in range(1, max_retries + 1):
        response = make_request()
        if response.status_code != 429: return response
        wait = _parse_retry_delay(response.text, attempt)
        print(f"       ⏳ Rate-limited (429). Waiting {wait}s before retry {attempt}/{max_retries}...")
        time.sleep(wait)
    raise RuntimeError(f"{backend_name} API: still rate-limited after {max_retries} retries.")

def _parse_retry_delay(response_text, attempt):
    m = re.search(r'"retryDelay":\s*"(\d+)s?"', response_text)
    if m: return float(m.group(1)) + 2
    m = re.search(r'retry in ([\d.]+)s', response_text)
    if m: return float(m.group(1)) + 2
    return min(15 * (2 ** (attempt - 1)), 120)

# ── Backends ──────────────────────────────────────────────────────────────
def _call_groq(system_prompt, user_prompt, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": LLM_TEMPERATURE, "max_tokens": LLM_MAX_TOKENS}
    t0 = time.time()
    response = _retry_on_429(lambda: requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120), backend_name="Groq")
    latency = round(time.time() - t0, 2)
    if response.status_code != 200: raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")
    data = response.json()
    usage = data.get("usage", {})
    return {"text": data["choices"][0]["message"]["content"], "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0), "latency": latency, "model": GROQ_MODEL}

def _call_gemini(system_prompt, user_prompt, api_key):
    url = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": [{"role": "user", "parts": [{"text": user_prompt}]}], "generationConfig": {"temperature": LLM_TEMPERATURE, "maxOutputTokens": LLM_MAX_TOKENS}}
    t0 = time.time()
    response = _retry_on_429(lambda: requests.post(url, json=payload, timeout=120), backend_name="Gemini")
    latency = round(time.time() - t0, 2)
    if response.status_code != 200: raise RuntimeError(f"Gemini API error {response.status_code}: {response.text}")
    data = response.json()
    text = ""
    candidates = data.get("candidates", [])
    if candidates: text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
    usage = data.get("usageMetadata", {})
    return {"text": text, "prompt_tokens": usage.get("promptTokenCount", 0), "completion_tokens": usage.get("candidatesTokenCount", 0), "latency": latency, "model": GEMINI_MODEL}

def _call_anthropic(system_prompt, user_prompt, api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    t0 = time.time()
    response = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=LLM_MAX_TOKENS, temperature=LLM_TEMPERATURE, system=system_prompt, messages=[{"role": "user", "content": user_prompt}])
    latency = round(time.time() - t0, 2)
    return {"text": response.content[0].text, "prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens, "latency": latency, "model": ANTHROPIC_MODEL}

_BACKENDS = {
    "groq": (_call_groq, "GROQ_API_KEY", "https://console.groq.com/keys"),
    "gemini": (_call_gemini, "GEMINI_API_KEY", "https://aistudio.google.com/apikey"),
    "anthropic": (_call_anthropic, "ANTHROPIC_API_KEY", "https://console.anthropic.com/"),
}

def summarise(country, score_table, details, details_by_section, api_key=None, backend=None, executive_summary=""):
    backend = backend or LLM_BACKEND
    if backend not in _BACKENDS: raise ValueError(f"Unknown backend '{backend}'.")
    call_fn, env_var, signup_url = _BACKENDS[backend]
    key = api_key or os.environ.get(env_var)
    if not key: raise ValueError(f"Set {env_var} env var or pass --api-key. Get a free key at: {signup_url}")
    user_prompt = _build_user_prompt(country, score_table, details, details_by_section, executive_summary)
    llm_result = call_fn(SYSTEM_PROMPT, user_prompt, key)
    full_text = llm_result["text"]
    # Split executive brief from section summaries
    exec_brief, section_text = "", full_text
    if "===SECTION_SUMMARIES===" in full_text:
        parts = full_text.split("===SECTION_SUMMARIES===", 1)
        exec_brief = parts[0].strip()
        section_text = parts[1].strip()
    return SummaryResult(country=country, raw_llm_response=section_text, executive_brief=exec_brief,
        prompt_tokens=llm_result["prompt_tokens"], completion_tokens=llm_result["completion_tokens"],
        model=llm_result["model"], backend=backend, latency_seconds=llm_result["latency"])

def build_prompt_only(country, score_table, details, details_by_section, executive_summary=""):
    user_prompt = _build_user_prompt(country, score_table, details, details_by_section, executive_summary)
    return {"system": SYSTEM_PROMPT, "user": user_prompt, "estimated_input_tokens": len(user_prompt) // 4}
