
import os
import sys
import time
import tempfile
from pathlib import Path

import streamlit as st

# Ensure pipeline modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from report_loader import load_report
from score_extractor import extract_scores
from section_extractor import (
    extract_section_details,
    group_details_by_section,
    extract_executive_summary,
)
from llm_summariser import summarise
from pdf_formatter import generate_pdf
from jee_fetcher import fetch_jee_report



st.set_page_config(
    page_title="JEE Report Summariser",
    page_icon="🏥",
    layout="centered",
)



with st.sidebar:
    st.markdown("### ⚙️ Settings")

    api_key = st.text_input(
        "Groq API Key",
        type="password",
        placeholder="gsk_...",
        help="Get a free key at [console.groq.com/keys](https://console.groq.com/keys)",
    )
    if api_key:
        os.environ["GROQ_API_KEY"] = api_key

    backend = st.selectbox(
        "LLM Backend",
        ["groq", "gemini", "anthropic"],
        index=0,
        help="Groq is free and recommended",
    )

    if backend == "gemini":
        gemini_key = st.text_input("Gemini API Key", type="password", placeholder="AI...")
        if gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
    elif backend == "anthropic":
        anth_key = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
        if anth_key:
            os.environ["ANTHROPIC_API_KEY"] = anth_key

    st.markdown("---")
    st.markdown(
        "**JEE Summarisation Pipeline**\n\n"
        "Automated WHO JEE report summarisation for UKHSA analysts.\n\n"
        "Built for MSc AI/ML dissertation research."
    )



st.markdown(
    """
    <div style="background: linear-gradient(135deg, #1E3A5F 0%, #2D5F8A 100%);
                padding: 1.5rem 2rem; border-radius: 10px; margin-bottom: 1.5rem;">
        <h1 style="color: white; margin: 0; font-size: 1.8rem;">
            🏥 JEE Report Summariser
        </h1>
        <p style="color: #CBD5E1; margin: 0.3rem 0 0 0; font-size: 0.95rem;">
            WHO Joint External Evaluation → UKHSA-ready PDF summary
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)



tab_auto, tab_upload = st.tabs(["🌐 Fetch by Country", "📄 Upload Report"])

report_path = None
country = None
jee_year = None
jee_url = None

with tab_auto:
    col1, col2 = st.columns([3, 1])
    with col1:
        country_input = st.text_input(
            "Country name",
            placeholder="e.g. South Africa, New Zealand, Brazil...",
            label_visibility="collapsed",
        )
    with col2:
        fetch_btn = st.button("🔍 Fetch & Summarise", type="primary", use_container_width=True)

    if fetch_btn and country_input:
        country = country_input.strip()

        if not api_key and backend == "groq":
            st.error("Enter your Groq API key in the sidebar first.")
            st.stop()

        with st.status(f"Fetching JEE report for {country}...", expanded=True) as status:
            try:
                st.write("🔍 Searching WHO website...")
                local_path, metadata = fetch_jee_report(country)
                report_path = local_path
                jee_year = metadata.get("year", "Unknown")
                jee_url = metadata.get("url", "")
                st.write(f"✅ Found: {metadata.get('title', 'JEE Report')[:80]}")
                st.write(f"📅 Year: {jee_year}")
                if jee_url:
                    st.write(f"🔗 [Source link]({jee_url})")
                status.update(label="Report fetched!", state="complete")
            except Exception as e:
                status.update(label="Fetch failed", state="error")
                st.error(f"Could not fetch report: {e}")
                st.info("Try uploading the report manually using the Upload tab.")
                st.stop()

with tab_upload:
    uploaded_file = st.file_uploader(
        "Upload a JEE report (PDF or text)",
        type=["pdf", "txt"],
        help="Upload a WHO JEE report file",
    )
    upload_country = st.text_input(
        "Country name (for uploaded file)",
        placeholder="e.g. South Africa",
        key="upload_country",
    )
    upload_year = st.text_input(
        "JEE year (optional)",
        placeholder="e.g. 2024",
        key="upload_year",
    )
    upload_btn = st.button("📊 Summarise Upload", type="primary")

    if upload_btn and uploaded_file and upload_country:
        country = upload_country.strip()
        jee_year = upload_year.strip() if upload_year else None

        if not api_key and backend == "groq":
            st.error("Enter your Groq API key in the sidebar first.")
            st.stop()

        # Save uploaded file to temp
        suffix = Path(uploaded_file.name).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_file.getbuffer())
        tmp.close()
        report_path = tmp.name

    elif upload_btn:
        if not uploaded_file:
            st.warning("Please upload a file.")
        if not upload_country:
            st.warning("Please enter the country name.")



if report_path and country:
    st.markdown("---")

    with st.status("Running summarisation pipeline...", expanded=True) as status:
        try:
            # Stage 1: Load
            st.write("📄 Loading report...")
            report_text = load_report(report_path)
            st.write(f"  → {len(report_text):,} characters loaded")

            # Stage 2: Extract scores
            st.write("📊 Extracting score table...")
            score_table = extract_scores(report_text)
            stats = score_table.summary_stats()
            st.write(
                f"  → {stats['total_indicators']} indicators: "
                f"🔴 {stats['red_count']} red · "
                f"🟡 {stats['yellow_count']} yellow · "
                f"🟢 {stats['green_count']} green · "
                f"Mean: {stats['mean_score']}"
            )

            # Stage 3: Executive summary
            st.write("📋 Extracting executive summary...")
            exec_summary = extract_executive_summary(report_text)

            # Stage 4: Extract details
            st.write("🔬 Extracting section details...")
            colours = {"red", "green"}
            details = extract_section_details(report_text, score_table, colours=colours)
            details_by_section = group_details_by_section(details)

            # Stage 5: Extract year if not known
            if not jee_year:
                import re
                match = re.search(
                    r'(?:January|February|March|April|May|June|July|August|'
                    r'September|October|November|December)\s+(20[12]\d)',
                    report_text[:3000],
                )
                if match:
                    jee_year = match.group(1)
                else:
                    years = re.findall(r'20[12]\d', report_text[:3000])
                    jee_year = years[-1] if years else "Unknown"

            # Stage 6: LLM summarisation
            st.write(f"🤖 Calling {backend.title()} LLM...")
            summary = summarise(
                country=country,
                score_table=score_table,
                details=details,
                details_by_section=details_by_section,
                backend=backend,
                executive_summary=exec_summary,
            )
            st.write(
                f"  → {summary.latency_seconds}s · "
                f"{summary.prompt_tokens} in / {summary.completion_tokens} out"
            )

            # Stage 7: Generate PDF
            st.write("📝 Generating PDF report...")
            safe_name = country.lower().replace(" ", "_")
            pdf_path = os.path.join(tempfile.gettempdir(), f"jee_{safe_name}.pdf")

            # Build subtitle with year and link
            subtitle_extra = ""
            if jee_year and jee_year != "Unknown":
                subtitle_extra = f" \u00b7 JEE {jee_year}"

            generate_pdf(
                output_path=pdf_path,
                country=country,
                score_table=score_table,
                llm_summary=summary.raw_llm_response,
                executive_brief=summary.executive_brief,
                model=summary.model,
                prompt_tokens=summary.prompt_tokens,
                completion_tokens=summary.completion_tokens,
                latency=summary.latency_seconds,
                jee_year=jee_year,
                jee_url=jee_url,
            )
            st.write("✅ PDF generated!")

            status.update(label="Pipeline complete!", state="complete")

        except Exception as e:
            status.update(label="Pipeline failed", state="error")
            st.error(f"Error: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

 

    st.markdown("---")
    st.markdown("### 📄 Generated Summary")

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🟢 Green", stats["green_count"])
    with col2:
        st.metric("🟡 Yellow", stats["yellow_count"])
    with col3:
        st.metric("🔴 Red", stats["red_count"])
    with col4:
        st.metric("Mean", stats["mean_score"])

    # Download button
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    year_tag = f"_{jee_year}" if jee_year and jee_year != "Unknown" else ""
    filename = f"JEE_Summary_{country.replace(' ', '_')}{year_tag}.pdf"

    st.download_button(
        label=f"⬇️ Download {filename}",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )

    # Source link
    if jee_url:
        st.caption(f"Source: [{jee_url[:60]}...]({jee_url})")

    # Show LLM output as expandable
    with st.expander("View LLM section summaries (raw text)"):
        if summary.executive_brief:
            st.markdown("**Executive Brief:**")
            st.markdown(summary.executive_brief)
            st.markdown("---")
        st.markdown(summary.raw_llm_response)

    # Cleanup temp files
    try:
        os.unlink(report_path)
    except Exception:
        pass
