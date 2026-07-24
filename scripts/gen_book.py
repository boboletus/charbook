#!/usr/bin/env python3
"""Generate/compile a book manifest from extracted page images.

Workflow (busy parents, bulk text editing):
  1. Extract pages from a PDF:
       .venv/bin/python scripts/extract_pdf.py --name 海底100层 "book.pdf"
     -> app/assets/海底100层/page1.jpg, page2.jpg, ...

  2. Generate the manifest + compile for the app:
       .venv/bin/python scripts/gen_book.py 海底100层
     -> app/assets/海底100层/book.json   (one entry per page; EDIT THIS)
     -> app/book.js                       (loaded by the app via <script>)

  3. Bulk-edit book.json in any text editor — fill chars/cols/priority for
     every page at once, no page-by-page modal needed.

  4. Recompile and refresh:
       .venv/bin/python scripts/gen_book.py 海底100层
     then reload the app. Existing edits are preserved; new pages are added
     with empty fields.

Use --reset only to wipe all char fields back to empty (keeps the page list).

Examples:
    .venv/bin/python scripts/gen_book.py 海底100层
    .venv/bin/python scripts/gen_book.py 海底100层 --reset
    .venv/bin/python scripts/gen_book.py demo --pages_dir app/assets --base assets

Options:
    name         Book name (positional; also the subdirectory under app/assets)
    --pages_dir  Directory containing pageN.jpg (default: app/assets/<name>)
    --base       URL base for page images, relative to app/ (default: assets/<name>)
    --out        Output path for the compiled book.js (default: app/book.js)
    --cols       Default column count for new pages (default: 3)
    --reset      Wipe all char/priority fields to empty (keeps the page list)

Run with --help to see the auto-generated usage from fastcore.
"""
import json
from pathlib import Path

from fastcore.script import call_parse, store_true


def _page_num(p: Path) -> int:
    return int(p.stem[len("page"):])


@call_parse
def gen_book(
    name: str,  # Book name (also the subdirectory under app/assets)
    pages_dir: str = None,  # Directory containing pageN.jpg (default: app/assets/<name>)
    base: str = None,  # URL base for page images, relative to app/ (default: assets/<name>)
    out: str = "app/book.js",  # Output path for the compiled book.js
    cols: int = 3,  # Default column count for new pages
    reset: store_true = False,  # Wipe all char/priority fields to empty (keeps the page list)
):
    """Generate book.json from page images and compile to book.js for the app."""

    pdir = Path(pages_dir) if pages_dir else (Path("app/assets") / name)
    if not pdir.is_dir():
        raise SystemExit(f"Pages directory not found: {pdir}")

    if base:
        url_base = base
    elif pages_dir:
        try:
            url_base = str(Path(pages_dir).relative_to("app"))
        except ValueError:
            url_base = str(Path(pages_dir))
    else:
        url_base = f"assets/{name}"

    pages = sorted(pdir.glob("page*.jpg"), key=_page_num)
    if not pages:
        raise SystemExit(f"No pageN.jpg files found in {pdir}")

    manifest_path = pdir / "book.json"
    existing: dict[int, dict] = {}
    if manifest_path.exists() and not reset:
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in old.get("pages", []):
                existing[int(entry["page"])] = entry
        except (OSError, ValueError, KeyError):
            existing = {}

    page_entries = []
    for p in pages:
        n = _page_num(p)
        if n in existing and not reset:
            e = existing[n]
            page_entries.append({
                "page": n,
                "chars": e.get("chars", ""),
                "cols": e.get("cols", cols),
                "priority": e.get("priority", ""),
            })
        else:
            page_entries.append({
                "page": n,
                "chars": "",
                "cols": cols,
                "priority": "",
            })

    manifest = {"book": name, "base": url_base, "pages": page_entries}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.BOOK_DATA = " + json.dumps(manifest, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    filled = sum(1 for e in page_entries if e["chars"])
    mode = "reset" if reset else ("reconciled" if existing else "created")
    print(f"Book '{name}': {len(page_entries)} page(s) [{mode}] -> {manifest_path}")
    print(f"  chars filled: {filled}/{len(page_entries)}   compiled -> {out_path}")
