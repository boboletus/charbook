#!/usr/bin/env python3
"""Convert book.json to dual simplified+traditional format.

Adds 'chars_trad' to each page and 'priority_trad' at book level
by converting simplified Chinese to traditional (Taiwan) using OpenCC.

Existing traditional fields are preserved unless --reset-trad is given.

Usage:
    .venv/bin/python scripts/convert_dual.py 哪一个很奇怪

Options:
    name          Book name (positional; also the subdirectory under app/assets)
    --pages_dir   Directory containing book.json (default: app/assets/<name>)
    --reset-trad  Re-convert all traditional fields from simplified (overwrites existing)
"""
import json
from pathlib import Path

from fastcore.script import call_parse, store_true
from opencc import OpenCC


@call_parse
def convert_dual(
    name: str,  # Book name (also the subdirectory under app/assets)
    pages_dir: str = None,  # Directory containing book.json (default: app/assets/<name>)
    reset_trad: store_true = False,  # Re-convert all traditional fields from simplified
):
    """Convert book.json to dual simplified+traditional format."""

    pdir = Path(pages_dir) if pages_dir else (Path("app/assets") / name)
    manifest_path = pdir / "book.json"
    if not manifest_path.exists():
        raise SystemExit(f"book.json not found: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    cc = OpenCC("s2tw")

    # Book-level priority
    simp_priority = data.get("priority", "")
    if simp_priority and (reset_trad or not data.get("priority_trad")):
        data["priority_trad"] = cc.convert(simp_priority)
    elif not data.get("priority_trad"):
        data["priority_trad"] = ""

    # Per-page chars
    converted = 0
    skipped = 0
    for entry in data.get("pages", []):
        simp = entry.get("chars", "")
        trad = entry.get("chars_trad", "")
        if simp and (reset_trad or not trad):
            entry["chars_trad"] = cc.convert(simp)
            converted += 1
        elif not trad:
            entry["chars_trad"] = ""
        else:
            skipped += 1

    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Book '{name}': {manifest_path}")
    print(f"  converted: {converted}   preserved: {skipped}   empty: {len(data.get('pages', [])) - converted - skipped}")
    print(f"  priority_trad: {data.get('priority_trad', '') or '(none)'}")
