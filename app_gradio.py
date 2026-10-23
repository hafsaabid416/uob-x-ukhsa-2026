
import os, re, sys, time, tempfile
from pathlib import Path
import gradio as gr

sys.path.insert(0, str(Path(__file__).parent))

from report_loader import load_report
from score_extractor import extract_scores
from section_extractor import extract_section_details, group_details_by_section, extract_executive_summary
from llm_summariser import summarise
from pdf_formatter import generate_pdf
from spar_processor import fetch_spar, generate_spar_pdf


def _extract_year(text):
    m = re.search(r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(20[12]\d)', text[:3000])
    if m: return m.group(1)
    years = re.findall(r'20[12]\d', text[:3000])
    return years[-1] if years else "Unknown"




def _run_jee_pipeline(report_path, country, api_key, backend, jee_url=None, jee_year=None, progress=None):
    if progress: progress(0.2, desc="Loading report...")
    report_text = load_report(report_path)

    if progress: progress(0.3, desc="Extracting scores...")
    score_table = extract_scores(report_text)
    stats = score_table.summary_stats()
    if stats["total_indicators"] == 0:
        raise gr.Error("No JEE indicators found. Check this is a valid JEE report.")

    if progress: progress(0.35, desc="Extracting executive summary...")
    exec_summary = extract_executive_summary(report_text)

    if not jee_year: jee_year = _extract_year(report_text)
    if not country:
        m = re.search(r'(?:core capacities of|evaluation of)\s+(.+?)(?:\n|$)', report_text[:2000], re.IGNORECASE)
        country = m.group(1).strip().rstrip(".") if m else "Unknown"

    if progress: progress(0.4, desc="Extracting section details...")
    details = extract_section_details(report_text, score_table, colours={"red","green"})
    details_by_section = group_details_by_section(details)

    env_map = {"groq":"GROQ_API_KEY","gemini":"GEMINI_API_KEY","anthropic":"ANTHROPIC_API_KEY"}
    os.environ[env_map.get(backend,"GROQ_API_KEY")] = api_key.strip()

    if progress: progress(0.5, desc=f"Calling {backend.title()} LLM...")
    summary = summarise(country=country, score_table=score_table, details=details,
                        details_by_section=details_by_section, backend=backend, executive_summary=exec_summary)

    if progress: progress(0.85, desc="Generating PDF...")
    safe = re.sub(r'[^a-zA-Z0-9]','_', country.lower())
    yr = f"_{jee_year}" if jee_year and jee_year != "Unknown" else ""
    pdf_path = os.path.join(tempfile.gettempdir(), f"JEE_Summary_{safe}{yr}.pdf")
    generate_pdf(output_path=pdf_path, country=country, score_table=score_table,
                 llm_summary=summary.raw_llm_response, executive_brief=summary.executive_brief,
                 model=summary.model, prompt_tokens=summary.prompt_tokens,
                 completion_tokens=summary.completion_tokens, latency=summary.latency_seconds,
                 jee_year=jee_year, jee_url=jee_url)

    status = (
        f"## \u2705 JEE Summary: {country} ({jee_year})\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Indicators | {stats['total_indicators']} |\n"
        f"| \U0001f7e2 Green | {stats['green_count']} |\n"
        f"| \U0001f7e1 Yellow | {stats['yellow_count']} |\n"
        f"| \U0001f534 Red | {stats['red_count']} |\n"
        f"| Mean | {stats['mean_score']} / 5 |\n"
        f"| LLM | {summary.model} ({summary.latency_seconds}s) |\n"
    )
    if jee_url: status += f"\n\U0001f517 [Source]({jee_url})"
    return pdf_path, status



def jee_upload_fn(file, country, year, api_key, backend, progress=gr.Progress()):
    if not file: raise gr.Error("Please upload a JEE report.")
    if not country: raise gr.Error("Please enter the country name.")
    if not api_key: raise gr.Error("Please enter your API key.")
    progress(0.1, desc="Starting...")
    return _run_jee_pipeline(file, country.strip(), api_key, backend,
                             jee_year=year.strip() if year else None, progress=progress)




def jee_lookup_fn(country, api_key, backend, progress=gr.Progress()):
    if not country: raise gr.Error("Please enter a country name.")
    if not api_key: raise gr.Error("Please enter your API key.")
    progress(0.05, desc=f"Searching WHO for {country.strip()}...")
    from jee_fetcher import fetch_jee_report
    try:
        local_path, meta = fetch_jee_report(country.strip())
    except Exception as e:
        raise gr.Error(str(e))
    progress(0.15, desc=f"Found: {meta.get('title','')[:60]}")
    return _run_jee_pipeline(local_path, country.strip(), api_key, backend,
                             jee_url=meta.get("url"), jee_year=meta.get("year"), progress=progress)




def spar_lookup_fn(country, year, progress=gr.Progress()):
    if not country: raise gr.Error("Please enter a country name.")
    year = (year or "").strip() or "2024"
    progress(0.2, desc=f"Fetching SPAR for {country.strip()} ({year})...")
    try:
        report = fetch_spar(country.strip(), year)
    except Exception as e:
        raise gr.Error(str(e))
    progress(0.6, desc="Generating PDF...")
    safe = re.sub(r'[^a-zA-Z0-9]','_', country.strip().lower())
    pdf_path = os.path.join(tempfile.gettempdir(), f"SPAR_Summary_{safe}_{year}.pdf")
    generate_spar_pdf(pdf_path, report)
    progress(1.0, desc="Done!")

    strong = [c for c in report.capacities if c.colour == "green"]
    weak = [c for c in report.capacities if c.colour == "red"]
    status = (
        f"## \u2705 SPAR Summary: {report.country} ({report.year})\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Overall score | {report.overall_score}% |\n"
        f"| Capacities | {len(report.capacities)} |\n"
        f"| \U0001f7e2 Strong (>60%) | {len(strong)} |\n"
        f"| \U0001f534 Weak (\u226430%) | {len(weak)} |\n"
        f"| Global avg | {report.global_score}% |\n"
        f"| Regional avg | {report.regional_score}% |\n"
        f"\n\U0001f517 [Source]({report.url})"
    )
    return pdf_path, status


# ═══════════════════════════════════════════════════════════════════════════
# Gradio UI
# ═══════════════════════════════════════════════════════════════════════════

with gr.Blocks(title="JEE/SPAR Summariser", theme=gr.themes.Soft(primary_hue="blue")) as demo:

    gr.HTML("""
    <div style="text-align:center; background:linear-gradient(135deg,#1E3A5F,#2D5F8A);
                padding:1.2rem; border-radius:10px; margin-bottom:1rem;">
      <h1 style="color:white; margin:0; font-size:1.6rem;">\U0001f3e5 JEE / SPAR Report Summariser</h1>
      <p style="color:#CBD5E1; margin:0.2rem 0 0; font-size:0.9rem;">
        WHO Joint External Evaluation & SPAR \u2192 UKHSA-ready PDF summaries
      </p>
    </div>
    """)

    with gr.Tabs():

        # ── Tab 1: JEE Upload ─────────────────────────────────────────
        with gr.Tab("\U0001f4c4 JEE Upload"):
            gr.Markdown("Upload a JEE report file and generate a summary PDF.")
            with gr.Row():
                with gr.Column(scale=2):
                    up_file = gr.File(label="JEE Report (PDF/TXT)", file_types=[".pdf",".txt"])
                    up_country = gr.Textbox(label="Country", placeholder="e.g. South Africa")
                    up_year = gr.Textbox(label="JEE Year (optional)", placeholder="e.g. 2024")
                with gr.Column(scale=1):
                    up_key = gr.Textbox(label="API Key", type="password", placeholder="gsk_...")
                    up_backend = gr.Dropdown(label="LLM", choices=["groq","gemini","anthropic"], value="groq")
            up_btn = gr.Button("\U0001f680 Generate JEE Summary", variant="primary")
            with gr.Row():
                up_pdf = gr.File(label="Download PDF")
                up_status = gr.Markdown()
            up_btn.click(jee_upload_fn, [up_file,up_country,up_year,up_key,up_backend], [up_pdf,up_status])

        # ── Tab 2: JEE Lookup ─────────────────────────────────────────
        with gr.Tab("\U0001f310 JEE Lookup"):
            gr.Markdown("Enter a country name \u2014 the tool will search WHO for the JEE report, download it, and generate a summary.")
            with gr.Row():
                with gr.Column(scale=2):
                    lk_country = gr.Textbox(label="Country", placeholder="e.g. Brazil, Kenya, Japan...")
                with gr.Column(scale=1):
                    lk_key = gr.Textbox(label="API Key", type="password", placeholder="gsk_...")
                    lk_backend = gr.Dropdown(label="LLM", choices=["groq","gemini","anthropic"], value="groq")
            lk_btn = gr.Button("\U0001f50d Fetch & Summarise", variant="primary")
            with gr.Row():
                lk_pdf = gr.File(label="Download PDF")
                lk_status = gr.Markdown()
            lk_btn.click(jee_lookup_fn, [lk_country,lk_key,lk_backend], [lk_pdf,lk_status])

        # ── Tab 3: SPAR Lookup ────────────────────────────────────────
        with gr.Tab("\U0001f4ca SPAR Lookup"):
            gr.Markdown("Enter a country name to fetch the latest SPAR data from WHO and generate a summary PDF. **No API key needed** \u2014 SPAR summaries are built from structured data, no LLM required.")
            with gr.Row():
                sp_country = gr.Textbox(label="Country", placeholder="e.g. South Africa, New Zealand...")
                sp_year = gr.Textbox(label="Year", value="2024", placeholder="2024")
            sp_btn = gr.Button("\U0001f4ca Generate SPAR Summary", variant="primary")
            with gr.Row():
                sp_pdf = gr.File(label="Download PDF")
                sp_status = gr.Markdown()
            sp_btn.click(spar_lookup_fn, [sp_country,sp_year], [sp_pdf,sp_status])

    gr.Markdown("---\n*Built for UKHSA analysts \u00b7 MSc AI/ML dissertation*")

if __name__ == "__main__":
    demo.launch(share=True)
