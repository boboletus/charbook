#!/usr/bin/env python3
"""Auto-segment each page's chars into phrases using jieba.

Stores a 'phrases' array per page in book.json. Each phrase is a
contiguous substring of the page's chars; joining all phrases must
reproduce chars exactly.

By default, only pages without an existing 'phrases' field are segmented
(preserves manual edits). Use --reset to re-segment all pages.

Custom words: if book.json has a "custom_words" field (a string of words
to add to jieba's dictionary), those words are loaded before segmenting.
This is essential for book-specific terms like character names (e.g.
"独角章") that jieba doesn't know.

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

import jieba
import jieba.posseg as pseg
from fastcore.script import call_parse, store_true


# Structural particles: 的/得/地/着/了/过
PARTICLE_FLAGS = {"uj", "uv", "ul", "uz", "ug"}
# Location suffixes: 上/下/中/里/内/外/间/前/后 (jieba flag 'f')
LOCATION_FLAGS = {"f"}

PUNCT = set("，。！？、；：""''「」（）—…《》·")
# POS flag for punctuation in jieba.posseg is 'x'

_ALL_MERGE_BACK = PARTICLE_FLAGS | LOCATION_FLAGS


def clean_chars(s):
    return re.sub(r"\s", "", s)


def _load_custom_words(custom_words_str):
    """Add custom words to jieba's dictionary.

    custom_words_str is a space-separated string of words (e.g.
    "独角章 棉花糖 套圈圈"). Each multi-character word is added to jieba
    so it stays whole during segmentation instead of being split.
    """
    if not custom_words_str:
        return
    for w in custom_words_str.split():
        w = w.strip()
        if len(w) >= 2:
            jieba.add_word(w, freq=1000, tag="nz")


def segment(text, custom_words=None):
    """Segment Chinese text into reading phrases using jieba POS tagging.

    Particles (的/得/地/着/了/过) are merged onto the preceding word so
    that phrases match how a parent reads aloud (e.g. "她的" not "她"+"的").
    Location suffixes (上/下/中/里) are also merged backward (e.g.
    "陆地上" not "陆地"+"上").
    Punctuation is kept as individual phrases (one char each).

    If custom_words is provided, those words are added to jieba's
    dictionary before segmenting. This keeps book-specific terms like
    character names (e.g. "独角章") as single words.
    """
    text = clean_chars(text)
    if not text:
        return []
    if custom_words:
        _load_custom_words(custom_words)
    tagged = list(pseg.cut(text))
    phrases = []
    for word, flag in tagged:
        if not word:
            continue
        if flag in _ALL_MERGE_BACK and phrases:
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

    custom_words = data.get("custom_words", "")
    if custom_words:
        _load_custom_words(custom_words)
        print(f"  Custom words loaded: {custom_words}")

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
            phrases = list(clean_chars(chars))
        entry["phrases"] = phrases
        segmented += 1

    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = len(data.get("pages", []))
    print(f"Book '{name}': {manifest_path}")
    print(f"  segmented: {segmented}   preserved: {preserved}   empty: {skipped_empty}   total: {total}")
