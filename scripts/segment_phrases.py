#!/usr/bin/env python3
"""Auto-segment each page's chars into phrases using jieba.

Stores a 'phrases' array per page in book.json. Each phrase is a
contiguous substring of the page's chars; joining all phrases must
reproduce chars exactly.

By default, only pages without an existing 'phrases' field are segmented
(preserves manual edits). Use --reset to re-segment all pages.

Usage:
    .venv/bin/python scripts/segment_phrases.py 哪一个很奇怪

Options:
    name          Book name (positional; also the subdirectory under app/assets)
    --pages_dir   Directory containing book.json (default: app/assets/<name>)
    --reset       Re-segment all pages (overwrites manual edits)
"""
import json
import re
from pathlib import Path

import jieba.posseg as pseg
from fastcore.script import call_parse, store_true


PARTICLE_FLAGS = {"uj", "uv", "ul", "uz", "ug"}

PUNCT = set("，。！？、；：""''「」（）—…《》·")
# POS flag for punctuation in jieba.posseg is 'x'


def clean_chars(s):
    return re.sub(r"\s", "", s)


def segment(text):
    """Segment Chinese text into reading phrases using jieba POS tagging.

    Particles (的/得/地/着/了/过) are merged onto the preceding word so
    that phrases match how a parent reads aloud (e.g. "她的" not "她"+"的").
    Punctuation is kept as individual phrases (one char each).
    """
    text = clean_chars(text)
    if not text:
        return []
    tagged = list(pseg.cut(text))
    phrases = []
    for word, flag in tagged:
        if not word:
            continue
        if flag in PARTICLE_FLAGS and phrases:
            phrases[-1] += word
        else:
            phrases.append(word)
    return phrases


def phrases_join(phrases):
    return "".join(phrases)


def validate(phrases, chars):
    """Check that joining phrases reproduces chars exactly."""
    return phrases_join(phrases) == clean_chars(chars)


@call_parse
def segment_phrases(
    name: str,  # Book name (also the subdirectory under app/assets)
    pages_dir: str = None,  # Directory containing book.json (default: app/assets/<name>)
    reset: store_true = False,  # Re-segment all pages (overwrites manual edits)
):
    """Auto-segment each page's chars into phrases using jieba."""

    pdir = Path(pages_dir) if pages_dir else (Path("app/assets") / name)
    manifest_path = pdir / "book.json"
    if not manifest_path.exists():
        raise SystemExit(f"book.json not found: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    segmented = 0
    preserved = 0
    skipped_empty = 0
    for entry in data.get("pages", []):
        chars = entry.get("chars", "")
        if not chars:
            skipped_empty += 1
            if "phrases" not in entry:
                entry["phrases"] = []
            continue

        existing = entry.get("phrases")
        if existing and not reset:
            preserved += 1
            continue

        phrases = segment(chars)
        if not validate(phrases, chars):
            # Fallback: if segmentation doesn't match (shouldn't happen
            # after clean_chars), fall back to single-char phrases
            phrases = list(chars)
        entry["phrases"] = phrases
        segmented += 1

    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = len(data.get("pages", []))
    print(f"Book '{name}': {manifest_path}")
    print(f"  segmented: {segmented}   preserved: {preserved}   empty: {skipped_empty}   total: {total}")
