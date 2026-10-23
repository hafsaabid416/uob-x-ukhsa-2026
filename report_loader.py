"""Load JEE reports from disk (plain text, zip archive, or PDF)."""
from __future__ import annotations
import io, os, zipfile
from pathlib import Path

def load_report(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")
    raw = path.read_bytes()
    if zipfile.is_zipfile(io.BytesIO(raw)):
        return _load_from_zip(io.BytesIO(raw))
    if raw[:5] == b"%PDF-":
        return _load_from_pdf(path)
    return raw.decode("utf-8", errors="replace")

def _load_from_zip(buf):
    with zipfile.ZipFile(buf) as zf:
        txt_names = sorted(
            [n for n in zf.namelist() if n.endswith(".txt")],
            key=lambda n: int(Path(n).stem)
        )
        pages = [zf.read(n).decode("utf-8", errors="replace").strip() for n in txt_names]
        return "\n\n".join(p for p in pages if p)

def _load_from_pdf(path):
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
