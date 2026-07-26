#!/usr/bin/env python3
"""Generate the prize manifest listing all unicorn SVGs in the Prize directory.

A static site cannot list a directory, so this scans app/assets/Prize/*.svg and
writes app/assets/Prize/prize.json. The app fetches it at runtime and picks a
random unicorn on each new-word tap.

Example:
    .venv/bin/python scripts/gen_prize.py

Options:
    prize_dir  Directory containing unicorn SVGs (default: app/assets/Prize)

Run with --help to see the auto-generated usage from fastcore.
"""
import json
from pathlib import Path

from fastcore.script import call_parse

PRIZE_DIR = Path("app/assets/Prize")


@call_parse
def gen_prize(
    prize_dir: str = None,  # Directory containing unicorn SVGs (default: app/assets/Prize)
):
    """Generate prize.json listing all unicorn SVGs for the app."""

    d = Path(prize_dir) if prize_dir else PRIZE_DIR
    if not d.is_dir():
        raise SystemExit(f"Prize directory not found: {d}")

    files = sorted(p.name for p in d.glob("*.svg"))
    manifest = {"svgs": files}
    (d / "prize.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prize: {len(files)} SVG(s) -> {d / 'prize.json'}")
    for f in files:
        print(f"  {f}")
