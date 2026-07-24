#!/usr/bin/env python3
"""Extract PDF pages to individual JPG files under assets/<book name>/.

Examples:
    # Extract every page; book name taken from the PDF filename
    .venv/bin/python scripts/extract_pdf.py "path/to/book.pdf"

    # Name the book explicitly -> app/assets/<name>/page1.jpg ...
    .venv/bin/python scripts/extract_pdf.py --name 海底100层 "path/to/book.pdf"

    # Extract pages 1-10 at 300 DPI with higher quality
    .venv/bin/python scripts/extract_pdf.py --name 海底100层 --start 1 --end 10 --dpi 300 --quality 95 "path/to/book.pdf"

    # Re-extract over existing pages
    .venv/bin/python scripts/extract_pdf.py --name 海底100层 --force "path/to/book.pdf"

Options:
    pdf            Path to the PDF file (positional)
    --name         Book name (defaults to the PDF filename without extension)
    --out_dir      Base output directory; pages go into <out_dir>/<name>/ (default: app/assets)
    --dpi          Render resolution in DPI (default: 150)
    --quality      JPG quality 1-100 (default: 85)
    --start        First page to extract, 1-indexed (default: 1)
    --end          Last page to extract, 1-indexed; 0 means the last page (default: 0)
    --force        Overwrite existing page images in the output directory

Run with --help to see the auto-generated usage from fastcore.
"""
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from fastcore.script import call_parse, store_true


@call_parse
def extract_pdf(
    pdf: str,  # Path to the PDF file
    name: str = None,  # Book name (defaults to the PDF filename without extension)
    out_dir: str = "app/assets",  # Base output directory; pages go into <out_dir>/<name>/
    dpi: int = 150,  # Render resolution in DPI
    quality: int = 85,  # JPG quality (1-100)
    start: int = 1,  # First page to extract (1-indexed)
    end: int = 0,  # Last page to extract (1-indexed; 0 means the last page)
    force: store_true = False,  # Overwrite existing page images in the output directory
):
    """Render each page of a PDF to a JPG in `assets/<book name>/page1.jpg`, `page2.jpg`, ..."""

    pdf_path = Path(pdf).expanduser()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    book = name or pdf_path.stem
    dest = Path(out_dir) / book
    dest.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        existing = sorted(dest.glob("page*.jpg"))
        if existing and not force:
            raise SystemExit(
                f"{len(existing)} page image(s) already in {dest} "
                f"(use --force to overwrite)"
            )
        if force:
            for f in existing:
                f.unlink()

    doc = fitz.open(pdf_path)
    total = doc.page_count
    first = max(1, start)
    last = total if end <= 0 else min(end, total)
    if first > last:
        raise SystemExit(f"No pages in range {first}-{last} (PDF has {total} page(s))")

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    count = 0
    for page_no in range(first - 1, last):
        page = doc[page_no]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out = dest / f"page{page_no + 1}.jpg"
        pix.save(out, jpg_quality=quality)
        count += 1

    doc.close()
    print(f"Extracted {count} page(s) -> {dest}/page{first}.jpg ... page{last}.jpg")
