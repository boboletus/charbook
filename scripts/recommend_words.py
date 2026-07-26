#!/usr/bin/env python3
"""Recommend the best characters to learn next for a specific book.

Ranks characters by how often they appear in the given book (book frequency),
keeping only those that also appear in a general frequency table
(freq_table.csv) and are not already known (fluency.txt) or in the book's
priority list. A character that recurs throughout the book gives the child
more practice opportunities, so it is recommended before a rarer one even if
the rarer character is more common in general Chinese.

The recommendation set is, in other words:
    (characters in the book, ranked by in-book frequency)
    ∩ (freq_table.csv, within --max-rank)
    − (fluency.txt ∪ book priority list)

Usage:
    .venv/bin/python scripts/recommend_words.py 哪一个很奇怪
    .venv/bin/python scripts/recommend_words.py 哪一个很奇怪 --top 5
    .venv/bin/python scripts/recommend_words.py 哪一个很奇怪 --all

Options:
    name          Book name (positional; also the subdirectory under app/assets)
    --pages_dir   Directory containing book.json (default: app/assets/<name>)
    --freq-file   Path to the frequency CSV (default: scripts/freq_table.csv)
    --fluency-file  Path to a file of pre-known characters, one per line (default: app/assets/fluency.txt)
    --top         Number of characters to recommend (default: 3)
    --max-rank    Maximum frequency rank to consider (default: 1000)
    --all         Show all candidates, not just the top N
"""
import csv
import json
import re
from pathlib import Path

from fastcore.script import call_parse, store_true

DEFAULT_FREQ_FILE = str(Path(__file__).resolve().parent / "freq_table.csv")
DEFAULT_FLUENCY_FILE = str(Path("app/assets") / "fluency.txt")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_cjk(ch):
    return bool(_CJK_RE.match(ch))


def parse_fluency(fluency_path):
    """Parse a fluency file into a set of pre-known characters.

    Each line contains one character (whitespace stripped, blank lines ignored).
    """
    known = set()
    p = Path(fluency_path).expanduser()
    if not p.exists():
        return known
    for line in p.read_text(encoding="utf-8").splitlines():
        ch = line.strip()
        if ch:
            known.add(ch)
    return known


def parse_freq_table(freq_path, max_rank=1000):
    """Parse a frequency CSV into {char: (rank, count, trad_char)}.

    The CSV has columns: rank, char_trad, char_simp, count.
    When char_simp is empty the character is the same in both forms.
    Only entries with rank <= max_rank are kept; the best (lowest) rank wins
    for each unique character (indexed by both simplified and traditional forms).
    """
    freq_by_simp = {}
    with Path(freq_path).expanduser().open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rank = int(row["rank"])
            if rank > max_rank:
                break
            char_trad = row["char_trad"]
            char_simp = row["char_simp"]
            count = int(row["count"])
            simp = char_simp if char_simp else char_trad
            entry = (rank, count, char_trad)
            for key in {simp, char_trad}:
                if key not in freq_by_simp or rank < freq_by_simp[key][0]:
                    freq_by_simp[key] = entry
    return freq_by_simp


def recommend(data, freq_by_simp, top=3, show_all=False, known_chars=None):
    """Return a sorted list of (book_count, rank, simp, trad, count, pages) for
    characters in the book that are not in the priority list or pre-known set
    and have a frequency rank.

    Candidates are ranked by how often they occur in this book (book_count,
    descending) so the child gets the most practice; the general frequency rank
    (ascending) breaks ties. ``book_count`` is the total number of times the
    character appears across all pages.
    """
    priority = data.get("priority", "")
    learnt = set(priority)
    if known_chars:
        learnt |= known_chars

    char_pages = {}
    char_count = {}
    for entry in data.get("pages", []):
        page = entry.get("page", 0)
        for ch in entry.get("chars", ""):
            if _is_cjk(ch):
                char_count[ch] = char_count.get(ch, 0) + 1
                seen = char_pages.setdefault(ch, [])
                if not seen or seen[-1] != page:
                    seen.append(page)

    candidates = []
    for ch, pages in char_pages.items():
        if ch in learnt:
            continue
        info = freq_by_simp.get(ch)
        if info:
            rank, count, char_trad = info
            candidates.append((char_count[ch], rank, ch, char_trad, count, pages))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    n = len(candidates) if show_all else top
    return candidates[:n], len(char_pages), sum(1 for ch in char_pages if ch not in learnt), len(candidates)


@call_parse
def recommend_words(
    name: str,  # Book name (also the subdirectory under app/assets)
    pages_dir: str = None,  # Directory containing book.json (default: app/assets/<name>)
    freq_file: str = DEFAULT_FREQ_FILE,  # Path to the org file with the frequency table
    fluency_file: str = DEFAULT_FLUENCY_FILE,  # Path to a file of pre-known characters (default: app/assets/fluency.txt)
    top: int = 3,  # Number of characters to recommend
    max_rank: int = 1000,  # Maximum frequency rank to consider
    all: store_true = False,  # Show all candidates, not just the top N
):
    """Recommend the next high-frequency characters to learn from a book."""

    pdir = Path(pages_dir) if pages_dir else (Path("app/assets") / name)
    manifest_path = pdir / "book.json"
    if not manifest_path.exists():
        raise SystemExit(f"book.json not found: {manifest_path}")

    freq_path = Path(freq_file).expanduser()
    if not freq_path.exists():
        raise SystemExit(f"Frequency file not found: {freq_path}")

    fluency_path = Path(fluency_file).expanduser()
    known_chars = parse_fluency(fluency_path)

    freq_by_simp = parse_freq_table(freq_path, max_rank)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    results, total, not_learnt, in_top = recommend(
        data, freq_by_simp, top=top, show_all=all, known_chars=known_chars
    )

    book_name = data.get("book", name)
    priority = data.get("priority", "")
    known_str = "".join(sorted(known_chars)) if known_chars else ""
    print(f"Book: {book_name}")
    print(f"Priority (learnt): {priority} ({len(set(priority))} chars)")
    if known_chars:
        print(f"Pre-known (fluency): {known_str} ({len(known_chars)} chars)")
    print(f"Book chars: {total} unique, {not_learnt} not yet learnt, {in_top} in top {max_rank}")
    print()

    if not results:
        print("No recommendations available.")
        return

    label = "All candidates" if all else f"Top {len(results)} recommendations"
    print(f"{label} (ranked by in-book frequency):")
    for i, (book_count, rank, ch, ch_trad, count, pages) in enumerate(results, 1):
        pages_str = ", ".join(str(p) for p in pages[:5])
        if len(pages) > 5:
            pages_str += f", ... ({len(pages)} pages)"
        trad_display = f" ({ch_trad})" if ch_trad != ch else ""
        print(f"  #{i}  {ch}{trad_display}  in-book: {book_count}×  rank #{rank:<5}  count: {count:>12,}  pages: {pages_str}")
