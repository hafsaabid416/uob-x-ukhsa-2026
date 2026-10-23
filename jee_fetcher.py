"""
jee_fetcher.py — Fetch JEE reports from the WHO SPH Document Library.

JEE PDFs live at predictable URLs on the SPH portal:
  Download: https://extranet.who.int/sph/sites/default/files/document-library/document/JEE%20Report%20{Country}%20{Year}.pdf
  Page:     https://extranet.who.int/sph/jee-report-{slug}-{year}

Strategy: try direct download URLs for each year from 2024 down to 2016.
"""
from __future__ import annotations
import re, tempfile
from pathlib import Path
from typing import Tuple
from urllib.parse import quote
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (JEE Pipeline Research Tool)"}
BASE = "https://extranet.who.int/sph/sites/default/files/document-library/document"


def fetch_jee_report(country: str) -> Tuple[str, dict]:
    """Fetch the latest JEE report PDF for a country from the WHO SPH portal."""
    country = country.strip()
    errors = []

    # Try direct PDF download for each year (newest first)
    for year in range(2025, 2015, -1):
        for name_variant in _name_variants(country, year):
            url = f"{BASE}/{quote(name_variant)}"
            try:
                print(f"  Trying: {name_variant}")
                resp = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    print(f"  ✅ Found!")
                    path = _download(url, country)
                    page_url = _page_url(country, year)
                    return path, {"url": page_url, "year": str(year), "title": name_variant}
            except Exception as e:
                continue

    # Try the SPH "Read More" page pattern
    for year in range(2025, 2015, -1):
        page = _page_url(country, year)
        try:
            print(f"  Trying page: {page}")
            resp = requests.get(page, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and "Download" in resp.text:
                # Find the download link
                m = re.search(r'href="([^"]*document-library/document/[^"]*\.pdf[^"]*)"', resp.text)
                if m:
                    pdf_url = m.group(1)
                    if not pdf_url.startswith("http"):
                        pdf_url = "https://extranet.who.int" + pdf_url
                    path = _download(pdf_url, country)
                    return path, {"url": page, "year": str(year), "title": f"JEE Report {country} {year}"}
        except Exception:
            continue

    raise FileNotFoundError(
        f"Could not find a JEE report for '{country}' on the WHO SPH portal.\n"
        f"Upload the report manually instead."
    )


def _name_variants(country: str, year: int) -> list:
    """Generate filename variants to try."""
    c = country.strip()
    return [
        f"JEE Report {c} {year}.pdf",
        f"JEE%20Report%20{c.replace(' ','%20')}%20{year}.pdf",
        f"JEE Report {c.replace(' ', '_')} {year}.pdf",
        f"JEE_{c.replace(' ', '_')}_{year}.pdf",
        f"jee-report-{c.lower().replace(' ','-')}-{year}.pdf",
    ]


def _page_url(country: str, year: int) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', country.lower()).strip('-')
    return f"https://extranet.who.int/sph/jee-report-{slug}-{year}"


def _download(url: str, country: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    safe = re.sub(r'[^a-zA-Z0-9]', '_', country.lower())
    content = resp.content
    suffix = ".pdf" if content[:5] == b"%PDF-" else ".txt"
    tmp = tempfile.NamedTemporaryFile(delete=False, prefix=f"jee_{safe}_", suffix=suffix)
    tmp.write(content)
    tmp.close()
    return tmp.name
