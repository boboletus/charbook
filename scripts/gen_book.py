#!/usr/bin/env python3
"""Generate a book manifest from extracted page images.

Workflow (busy parents, bulk text editing):
  1. Extract pages from a PDF:
       .venv/bin/python scripts/extract_pdf.py --name 海底100层 "book.pdf"
     -> app/assets/海底100层/page1.jpg, page2.jpg, ...

  2. Generate the manifest:
       .venv/bin/python scripts/gen_book.py 海底100层
     -> app/assets/海底100层/book.json   (one entry per page; EDIT THIS)

  3. Bulk-edit book.json in any text editor — fill chars for every page
     and set priority once at the book level (top-level "priority" field).
     The app matches that global priority list against each page's characters.
     Column count is auto-calculated by the app from the image aspect ratio.

  4. Refresh the app. Existing edits are preserved; new pages are added
     with empty fields.

Use --reset to wipe char fields back to empty (keeps the page list and priority).

Examples:
    .venv/bin/python scripts/gen_book.py 海底100层
    .venv/bin/python scripts/gen_book.py 海底100层 --reset

Options:
    name         Book name (positional; also the subdirectory under app/assets)
    --pages_dir  Directory containing pageN.jpg (default: app/assets/<name>)
    --base       URL base for page images, relative to app/ (default: assets/<name>)
    --reset      Wipe char fields to empty (keeps the page list and book-level priority)

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
    reset: store_true = False,  # Wipe char fields to empty (keeps the page list and book-level priority)
):
    """Generate book.json from page images for the app."""

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
    old_priority = ""
    old_priority_trad = ""
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_priority = old.get("priority", "")
            old_priority_trad = old.get("priority_trad", "")
            if not reset:
                for entry in old.get("pages", []):
                    existing[int(entry["page"])] = entry
        except (OSError, ValueError, KeyError):
            pass

    page_entries = []
    for p in pages:
        n = _page_num(p)
        if n in existing and not reset:
            e = existing[n]
            page_entries.append({
                "page": n,
                "chars": e.get("chars", ""),
                "chars_trad": e.get("chars_trad", ""),
            })
        else:
            page_entries.append({
                "page": n,
                "chars": "",
                "chars_trad": "",
            })

    manifest = {"book": name, "base": url_base, "priority": old_priority, "priority_trad": old_priority_trad, "pages": page_entries}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    filled = sum(1 for e in page_entries if e["chars"])
    mode = "reset" if reset else ("reconciled" if existing else "created")
    print(f"Book '{name}': {len(page_entries)} page(s) [{mode}] -> {manifest_path}")
    print(f"  chars filled: {filled}/{len(page_entries)}   priority: {old_priority or '(none)'}")
