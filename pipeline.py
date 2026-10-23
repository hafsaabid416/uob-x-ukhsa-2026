"""
pipeline.py — JEE Summarisation Pipeline.

Usage:
    python pipeline.py report.pdf --country "South Africa" -o outputs/sa.pdf
    python pipeline.py report.pdf --country "South Africa" --dry-run
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from report_loader import load_report
from score_extractor import extract_scores
from section_extractor import extract_section_details, group_details_by_section, extract_executive_summary
from llm_summariser import summarise, build_prompt_only
from pdf_formatter import generate_pdf


def run_pipeline(report_path, country, dry_run=False, output_path=None,
                 api_key=None, colours=None, backend="groq"):
    if colours is None:
        colours = {"red", "green"}
    t0 = time.time()

    # Stage 1: LOAD
    print(f"[1/7] Loading report: {report_path}")
    report_text = load_report(report_path)
    print(f"       → {len(report_text):,} characters loaded")

    # Stage 2: EXTRACT SCORES
    print("[2/7] Extracting score table...")
    score_table = extract_scores(report_text)
    stats = score_table.summary_stats()
    print(f"       → {stats['total_indicators']} indicators parsed")
    print(f"       → Red: {stats['red_count']}  Yellow: {stats['yellow_count']}  "
          f"Green: {stats['green_count']}  Mean: {stats['mean_score']}")

    # Stage 3: EXTRACT EXECUTIVE SUMMARY
    print("[3/7] Extracting executive summary...")
    exec_summary = extract_executive_summary(report_text)
    print(f"       → {len(exec_summary)} characters extracted")

    # Stage 4: FILTER
    print(f"[4/7] Filtering for colours: {colours}")
    filtered = [i for i in score_table.indicators if i.colour in colours]
    print(f"       → {len(filtered)} indicators selected")

    # Stage 5: DETAIL
    print("[5/7] Extracting section details...")
    details = extract_section_details(report_text, score_table, colours=colours)
    details_by_section = group_details_by_section(details)
    print(f"       → {len(details_by_section)} sections with detail text")

    # Stage 6: SUMMARISE
    if dry_run:
        print("[6/7] DRY RUN — building prompt (no API call)...")
        prompt_data = build_prompt_only(country, score_table, details, details_by_section, exec_summary)
        print(f"       → Estimated input tokens: ~{prompt_data['estimated_input_tokens']}")
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            prompt_path = str(Path(output_path).with_suffix(".json"))
            with open(prompt_path, "w") as f:
                json.dump(prompt_data, f, indent=2)
            print(f"[7/7] Prompt saved to: {prompt_path}")
        return {"score_table": score_table, "details": details, "prompt": prompt_data,
                "elapsed_seconds": round(time.time() - t0, 2)}

    print(f"[6/7] Calling LLM for summarisation (backend: {backend})...")
    summary = summarise(
        country=country, score_table=score_table, details=details,
        details_by_section=details_by_section, api_key=api_key,
        backend=backend, executive_summary=exec_summary,
    )
    print(f"       → LLM responded in {summary.latency_seconds}s")
    print(f"       → Tokens: {summary.prompt_tokens} in / {summary.completion_tokens} out")

    # Stage 7: PDF OUTPUT
    if output_path:
        pdf_path = str(Path(output_path).with_suffix(".pdf"))
        print(f"[7/7] Generating PDF report...")
        generate_pdf(
            output_path=pdf_path, country=country, score_table=score_table,
            llm_summary=summary.raw_llm_response,
            executive_brief=summary.executive_brief,
            model=summary.model, prompt_tokens=summary.prompt_tokens,
            completion_tokens=summary.completion_tokens, latency=summary.latency_seconds,
        )
        print(f"       → PDF written to: {pdf_path}")
    else:
        print(f"[7/7] Done (no output path specified, printing summary)")
        print("\n" + summary.raw_llm_response)

    elapsed = round(time.time() - t0, 2)
    print(f"\n✓ Pipeline finished in {elapsed}s")
    return {"score_table": score_table, "details": details,
            "summary": summary, "elapsed_seconds": elapsed}


def main():
    parser = argparse.ArgumentParser(description="JEE Report Summarisation Pipeline")
    parser.add_argument("report", help="Path to the JEE report file")
    parser.add_argument("--country", "-c", required=True)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--backend", "-b", default="groq", choices=["groq", "gemini", "anthropic"])
    parser.add_argument("--include-yellow", action="store_true")
    args = parser.parse_args()
    colours = {"red", "green"}
    if args.include_yellow: colours.add("yellow")
    run_pipeline(report_path=args.report, country=args.country, dry_run=args.dry_run,
                 output_path=args.output, api_key=args.api_key, colours=colours, backend=args.backend)

if __name__ == "__main__":
    main()
