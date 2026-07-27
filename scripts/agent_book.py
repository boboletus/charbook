#!/usr/bin/env python3
"""Agent-driven book processing pipeline using Lisette.

Runs an LLM agent loop that orchestrates the full new-book pipeline:
1. Extract PDF pages to JPGs
2. Classify and remove non-story pages (copyright, preface, author intro, etc.)
3. Tiered OCR per page: PDF text extraction -> tesseract -> vision model
4. Generate book.json, segment phrases, recommend words

The agent (an LLM with tool-calling) drives every decision: which pages to
remove, whether OCR results are good enough, what priority/new_words to set.
Lisette's Chat class handles the tool-calling loop automatically.

Usage:
    .venv/bin/python scripts/agent_book.py "嘿我是独角章" "嘿我是独角章.pdf"

    # With explicit models:
    .venv/bin/python scripts/agent_book.py "嘿我是独角章" "嘿我是独角章.pdf" \\
        --agent-model fireworks_ai/accounts/fireworks/models/kimi-k2p6 \\
        --vision-model fireworks_ai/accounts/fireworks/models/qwen2p5-vl-72b-instruct

Options:
    name           Book name (positional; also the subdirectory under app/assets)
    pdf            Path to the PDF file (positional)
    --agent-model  LiteLLM model string for the agent loop (default: kimi-k2p6 on Fireworks)
    --vision-model LiteLLM model string for vision OCR (default: kimi-k2p6 on Fireworks)
    --max-steps    Maximum tool-calling rounds for the agent (default: 30)
    --force        Overwrite existing page images during extraction

Requires:
    - FIREWORKS_API_KEY (or other provider key) in environment
    - lisette, pytesseract, pymupdf, jieba, opencc installed in .venv
    - Tesseract Chinese traineddata in scripts/tessdata/
"""
import json
import os
import re
import sys
from pathlib import Path

# Ensure scripts/ is importable (for segment_phrases, recommend_words modules)
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Set tesseract data path before importing pytesseract
os.environ.setdefault("TESSDATA_PREFIX", str(_SCRIPTS_DIR / "tessdata"))

ASSETS_DIR = Path("app/assets")

# --- Cost tracking ---

class CostTracker:
    """Accumulates LLM API costs across all calls in a run."""

    def __init__(self):
        self.calls = []
        self.total_cost = 0.0
        self.total_tokens = 0

    def add(self, model: str, usage, cost: float):
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        entry = {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": cost,
        }
        self.calls.append(entry)
        self.total_cost += cost
        self.total_tokens += entry["total_tokens"]

    def summary(self) -> str:
        if not self.calls:
            return "No API calls made."
        lines = [
            f"Cost summary: {len(self.calls)} API call(s), "
            f"{self.total_tokens:,} tokens, ${self.total_cost:.4f} total"
        ]
        by_model = {}
        for c in self.calls:
            m = c["model"]
            if m not in by_model:
                by_model[m] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_model[m]["calls"] += 1
            by_model[m]["tokens"] += c["total_tokens"]
            by_model[m]["cost"] += c["cost"]
        for m, stats in sorted(by_model.items()):
            lines.append(
                f"  {m}: {stats['calls']} call(s), {stats['tokens']:,} tokens, "
                f"${stats['cost']:.4f}"
            )
        return "\n".join(lines)


COST_TRACKER = CostTracker()


def _setup_cost_tracking():
    """Register a litellm callback that records cost per API call."""
    import litellm

    def log_success_event(kwargs, completion_response, start_time, end_time):
        try:
            usage = completion_response.usage
            cost = kwargs.get("response_cost", 0.0) or 0.0
            model = kwargs.get("model", "unknown")
            COST_TRACKER.add(model, usage, cost)
        except Exception:
            pass

    # litellm.callbacks expects a list of callback objects or callables
    if not any(getattr(cb, '__name__', '') == 'log_success_event' for cb in litellm.callbacks):
        cb = type('CostCallback', (), {'log_success_event': staticmethod(log_success_event)})()
        litellm.callbacks.append(cb)


# --- Prompts ---

CLASSIFY_PROMPT = (
    "Look at this page from a Chinese picture book. Classify it as one of:\n"
    '- "title": The title page showing the book name\n'
    '- "story": A story page with illustrations and/or story text\n'
    '- "non-story": Copyright, ISBN, barcode, author/illustrator introduction, '
    "table of contents, blank page, or end notes\n\n"
    'Respond in JSON only: {"classification": "...", "reason": "..."}'
)

OCR_PROMPT = (
    "Read all Chinese text visible on this page. "
    "Return ONLY the text characters in natural reading order "
    "(follow the layout of the text on the page — left-to-right or right-to-left "
    "depending on how the text is laid out). "
    "Include punctuation marks. "
    "Do not add any explanation, commentary, or formatting. "
    "If the page has no text, return an empty string."
)

SYSTEM_PROMPT = """\
You are a book processing agent for a Chinese character recognition app for children.

Your job: turn a picture-book PDF into a ready-to-use book.json with characters, \
phrases, and metadata.

Follow this workflow step by step:

1. EXTRACT: Call extract_pdf_pages to render the PDF to JPG images. \
If pages already exist and the PDF path matches, this is a no-op (cached).
2. GEN BOOK: Call gen_book to create book.json with all pages (empty chars). \
If book.json already exists, this preserves existing data.
3. FIND STORY START: Call find_story_start to locate the first story page. \
This probes page 1 (almost always the title), then skips ahead 3 pages at a time \
until it finds story content, then back-validates the boundary. It returns the \
list of non-story page numbers to remove. Classification results are cached.
4. CHECK END: Call classify_pages on the last 3-4 pages to find end notes, \
blank pages, or back cover. Remove any non-story pages found.
5. REMOVE: Call remove_pages with the non-story page numbers. This deletes \
both the page images AND their entries from book.json.
6. OCR: Call ocr_all_pages to run tiered OCR on all remaining pages. This tries \
PDF text extraction first, then tesseract, then a vision model. Set \
skip_tesseract=True if tesseract is producing poor results (common for picture \
books with stylized fonts). Pages that already have chars are skipped (cached).
7. REVIEW: Call read_book_json to check results. If any page has empty or \
suspicious results, call model_ocr_page to re-OCR it with the vision model.
8. SEGMENT: Call segment_phrases_tool to segment text into reading phrases.
9. RECOMMEND: Call recommend_words_tool to get priority word suggestions.
10. FINALIZE: Call set_book_meta to set script ("trad" or "simp"), priority \
(3-8 high-frequency characters), new_words (1-4 new characters for the \
reward animation), and custom_words (multi-character words jieba doesn't \
know, like character names "独角章" or compound words "棉花糖"). \
Custom words keep those terms as single phrases during segmentation.
11. REPORT: Call read_book_json one final time and summarize what was done.

Rules:
- Page 1 is almost always the title page (unless damaged/stickers). Trust it.
- Non-story pages: copyright, ISBN/barcode, author/illustrator intro, table of \
contents, blank, end notes. The title page (showing the book name) = KEEP.
- script: "trad" if text uses traditional characters (e.g. 個/這/裡/學/關), \
"simp" if simplified (e.g. 个/这/里/学/关).
- priority: characters that appear frequently in the book and are good for a \
child to learn. Pick 3-8 characters.
- new_words: characters that are new or distinctive to this book, to trigger a \
reward animation. Pick 1-4 characters.
- Always explain your decisions briefly before calling tools.\
"""

# --- Configuration globals (set by main) ---
AGENT_MODEL = "fireworks_ai/accounts/fireworks/models/kimi-k2p6"
VISION_MODEL = "fireworks_ai/accounts/fireworks/models/kimi-k2p6"


# ---------------------------------------------------------------------------
# Helper functions (not exposed as tools)
# ---------------------------------------------------------------------------

def _book_dir(book_name: str) -> Path:
    return ASSETS_DIR / book_name


def _page_path(book_name: str, page_num: int) -> Path:
    return _book_dir(book_name) / f"page{page_num}.jpg"


def _list_page_nums(book_name: str) -> list[int]:
    d = _book_dir(book_name)
    if not d.is_dir():
        return []
    nums = []
    for p in d.glob("page*.jpg"):
        m = re.match(r"page(\d+)\.jpg", p.name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def _read_book_json(book_name: str) -> dict | None:
    p = _book_dir(book_name) / "book.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _write_book_json(book_name: str, data: dict) -> None:
    p = _book_dir(book_name) / "book.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _cache_path(book_name: str) -> Path:
    return _book_dir(book_name) / ".agent_cache.json"


def _read_cache(book_name: str) -> dict:
    p = _cache_path(book_name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(book_name: str, cache: dict) -> None:
    p = _cache_path(book_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _is_tesseract_garbage(text: str) -> bool:
    """Detect if tesseract output is garbage (reading individual characters, not text).

    Tesseract on stylized Chinese picture-book fonts often produces output where
    every CJK character is a standalone whitespace-separated token — real Chinese
    text has no spaces between characters. If >60% of CJK characters are
    standalone single-char tokens, the output is garbage.
    """
    if not text or _cjk_count(text) < 2:
        return True
    tokens = text.split()
    if not tokens:
        return True
    single_cjk = sum(1 for t in tokens if len(_CJK_RE.findall(t)) == 1)
    total_cjk = _cjk_count(text)
    return single_cjk / total_cjk > 0.6


def _detect_script(combined_chars: str) -> str:
    """Detect whether text is traditional or simplified Chinese.

    Uses opencc to check if t2s conversion changes anything — if it does,
    the text contains traditional-only characters.
    """
    if not combined_chars:
        return "trad"
    try:
        from opencc import OpenCC
        t2s = OpenCC("t2s")
        simplified = t2s.convert(combined_chars)
        return "trad" if simplified != combined_chars else "simp"
    except Exception:
        # Fallback: check common traditional-only characters
        trad_indicators = set("個這裡學過關開門們麼來師應還條國時說話書畫兒節實廣業會運動場飛機車東西兩")
        return "trad" if any(ch in trad_indicators for ch in combined_chars) else "simp"


def _vision_call(image_bytes: bytes, prompt: str) -> str:
    """Send an image + text prompt to the vision model, return text response."""
    from lisette import Chat, contents
    chat = Chat(VISION_MODEL)
    res = chat([image_bytes, prompt])
    return contents(res).content.strip()


# ---------------------------------------------------------------------------
# Tiered OCR helpers
# ---------------------------------------------------------------------------

def _tier1_pdf_text(pdf_path: str, page_num: int) -> str:
    """Tier 1: extract embedded text from PDF (instant, perfect if present)."""
    try:
        import pymupdf as fitz
        doc = fitz.open(pdf_path)
        if page_num - 1 < doc.page_count:
            text = doc[page_num - 1].get_text().strip()
        else:
            text = ""
        doc.close()
        return text
    except Exception as e:
        return f"[tier1 error: {e}]"


def _tier2_tesseract(book_name: str, page_num: int) -> str:
    """Tier 2: tesseract OCR with Chinese language data."""
    import pytesseract
    from PIL import Image
    img_path = _page_path(book_name, page_num)
    if not img_path.exists():
        return ""
    img = Image.open(img_path)
    best = ""
    best_count = 0
    for lang in ("chi_tra", "chi_sim"):
        try:
            text = pytesseract.image_to_string(img, lang=lang).strip()
            count = _cjk_count(text)
            if count > best_count:
                best, best_count = text, count
        except Exception:
            continue
    return best


def _tier3_model_ocr(book_name: str, page_num: int) -> str:
    """Tier 3: vision model OCR (highest accuracy, costs an API call)."""
    img_path = _page_path(book_name, page_num)
    if not img_path.exists():
        return ""
    return _vision_call(img_path.read_bytes(), OCR_PROMPT)


def _classify_with_vision(book_name: str, page_num: int) -> dict:
    """Classify a page using the vision model."""
    img_path = _page_path(book_name, page_num)
    if not img_path.exists():
        return {"classification": "non-story", "reason": "page not found"}
    raw = _vision_call(img_path.read_bytes(), CLASSIFY_PROMPT)
    # Parse JSON from response (model may wrap in markdown code fences)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        # Fallback: search for classification keyword
        lower = raw.lower()
        if "non-story" in lower or "nonstory" in lower:
            return {"classification": "non-story", "reason": raw}
        if "title" in lower:
            return {"classification": "title", "reason": raw}
        return {"classification": "story", "reason": raw}


# ---------------------------------------------------------------------------
# Tool functions (exposed to the agent via Lisette)
# ---------------------------------------------------------------------------

def extract_pdf_pages(
    book_name: str,  # Book name (subdirectory under app/assets)
    pdf_path: str,   # Path to the PDF file
    force: bool = False,  # Overwrite existing page images
) -> str:
    """Extract PDF pages to JPG images under app/assets/<book_name>/.

    Renders every page at 150 DPI. If pages already exist and the PDF path
    matches the cached one, this is a no-op. Use force=True to re-extract.
    """
    import pymupdf as fitz
    pdf = Path(pdf_path).expanduser()
    if not pdf.is_file():
        return f"Error: PDF not found: {pdf}"
    dest = _book_dir(book_name)
    dest.mkdir(parents=True, exist_ok=True)
    existing = sorted(dest.glob("page*.jpg"))
    cache = _read_cache(book_name)

    if existing and not force:
        cached_pdf = cache.get("pdf_path", "")
        if cached_pdf == str(pdf) or cached_pdf == pdf.name:
            pages = _list_page_nums(book_name)
            return (
                f"Already extracted {len(existing)} page(s) from {pdf.name} (cached). "
                f"Page numbers: {pages}. Use force=True to re-extract."
            )
        return (
            f"{len(existing)} page image(s) already in {dest} (from a different PDF). "
            f"Pass force=True to overwrite."
        )
    if force:
        for f in existing:
            f.unlink()
    doc = fitz.open(pdf)
    total = doc.page_count
    zoom = 150 / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    for i in range(total):
        pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
        pix.save(dest / f"page{i+1}.jpg", jpg_quality=85)
    doc.close()
    pages = _list_page_nums(book_name)
    cache["pdf_path"] = str(pdf)
    cache["extracted"] = True
    _write_cache(book_name, cache)
    return f"Extracted {total} page(s) -> {dest}/page1.jpg ... page{total}.jpg. Page numbers: {pages}"


def gen_book(
    book_name: str,  # Book name
) -> str:
    """Generate book.json from page images with all pages included (empty chars).

    Creates book.json with one entry per page image. All chars fields start
    empty. If book.json already exists, existing data (chars, phrases, priority)
    is preserved — new page images are added, removed images are dropped.

    Call this BEFORE classifying/removing pages, so book.json tracks all pages.
    After remove_pages, the removed pages' entries are also removed from book.json.
    """
    nums = _list_page_nums(book_name)
    if not nums:
        return f"No page images found for book '{book_name}'. Run extract_pdf_pages first."

    existing = _read_book_json(book_name)
    old_entries = {}
    old_priority = ""
    old_new_words = ""
    old_script = "trad"
    if existing:
        old_priority = existing.get("priority", "")
        old_new_words = existing.get("new_words", "")
        old_script = existing.get("script", "trad")
        for entry in existing.get("pages", []):
            old_entries[int(entry["page"])] = entry

    pages = []
    for n in nums:
        e = old_entries.get(n)
        if e:
            pages.append({
                "page": n,
                "chars": e.get("chars", ""),
                "phrases": e.get("phrases", []),
            })
        else:
            pages.append({"page": n, "chars": "", "phrases": []})

    data = {
        "book": book_name,
        "base": f"assets/{book_name}",
        "script": old_script,
        "priority": old_priority,
        "new_words": old_new_words,
        "pages": pages,
    }
    _write_book_json(book_name, data)

    cache = _read_cache(book_name)
    cache["gen_book"] = True
    _write_cache(book_name, cache)

    filled = sum(1 for p in pages if p["chars"])
    return (
        f"book.json created with {len(pages)} page(s). "
        f"Chars filled: {filled}/{len(pages)}. "
        f"Priority: {old_priority or '(none)'}. Script: {old_script}."
    )


def classify_pages(
    book_name: str,   # Book name
    page_nums: str,   # Comma-separated page numbers to classify (e.g. "44,45,46")
) -> str:
    """Classify pages as 'title', 'story', or 'non-story' using a vision model.

    Use this to check specific pages (e.g. the last few pages for end notes,
    or a borderline page). For finding the story start automatically, use
    find_story_start instead. Classification results are cached in
    .agent_cache.json — re-classifying the same page is a no-op.
    """
    nums = [int(x.strip()) for x in page_nums.split(",") if x.strip()]
    cache = _read_cache(book_name)
    cached_cls = cache.setdefault("classifications", {})
    results = []
    for n in nums:
        key = str(n)
        if key in cached_cls:
            r = cached_cls[key]
            r["page"] = n
            r["cached"] = True
            results.append(r)
            print(f"  classify page {n}: {r.get('classification', '?')} (cached)",
                  file=sys.stderr)
            continue
        r = _classify_with_vision(book_name, n)
        r["page"] = n
        cached_cls[key] = r
        results.append(r)
        print(f"  classify page {n}: {r.get('classification', '?')} — {r.get('reason', '')[:60]}",
              file=sys.stderr)
    _write_cache(book_name, cache)
    return json.dumps(results, ensure_ascii=False, indent=2)


def find_story_start(
    book_name: str,  # Book name
) -> str:
    """Find the first story page and identify non-story pages to remove.

    Strategy:
    1. Page 1 is almost always the title page — classify it to confirm.
    2. Skip ahead 3 pages at a time, classifying each, until a story page is found.
    3. Back up one page at a time from the first story page found, to find the
       exact boundary between non-story and story content.
    4. Return the list of non-story page numbers (between title and first story
       page) that should be removed.

    The title page is KEPT. Pages between title and first story page (copyright,
    ISBN, author intro, etc.) are removed. Story pages from the first story page
    onward are kept. Classification results are cached in .agent_cache.json.
    """
    nums = _list_page_nums(book_name)
    if not nums:
        return json.dumps({"error": f"No page images found for book '{book_name}'"})

    cache = _read_cache(book_name)
    cached_cls = cache.setdefault("classifications", {})
    classifications = {}

    def classify(n):
        if n in classifications:
            return classifications[n]
        key = str(n)
        if key in cached_cls:
            classifications[n] = cached_cls[key].get("classification", "story")
            print(f"  classify page {n}: {classifications[n]} (cached)",
                  file=sys.stderr)
            return classifications[n]
        r = _classify_with_vision(book_name, n)
        classifications[n] = r.get("classification", "story")
        cached_cls[key] = r
        print(f"  classify page {n}: {classifications[n]} — {r.get('reason', '')[:60]}",
              file=sys.stderr)
        return classifications[n]

    # Step 1: Page 1 is almost always the title
    first, last = nums[0], nums[-1]
    cls_1 = classify(first)
    title_pages = [first] if cls_1 == "title" else []

    # Step 2: Skip ahead 3 pages at a time to find first story page
    probe = first + 3
    first_story = None
    while probe <= last:
        cls = classify(probe)
        if cls == "story":
            first_story = probe
            break
        probe += 3

    if first_story is None:
        # Never found a story page by skipping — scan forward from title
        probe = first + 1
        while probe <= last:
            cls = classify(probe)
            if cls == "story":
                first_story = probe
                break
            probe += 1

    if first_story is None:
        _write_cache(book_name, cache)
        return json.dumps({
            "error": "No story pages found in the book",
            "classifications": classifications,
        }, ensure_ascii=False)

    # Step 3: Back up one page at a time to find exact boundary.
    boundary = first_story
    check = first_story - 1
    while check > first:
        if check not in classifications:
            classify(check)
        if classifications[check] == "story":
            boundary = check
            check -= 1
        else:
            break

    # Step 4: Determine which pages to remove.
    to_remove = []
    for n in nums:
        if n in title_pages:
            continue
        if n >= boundary:
            continue
        if n == first:
            continue
        to_remove.append(n)

    _write_cache(book_name, cache)

    result = {
        "title_pages": title_pages,
        "first_story_page": boundary,
        "pages_to_remove": to_remove,
        "pages_to_keep": [n for n in nums if n not in to_remove],
        "classifications": {str(k): v for k, v in classifications.items()},
    }
    print(f"  Story starts at page {boundary}, removing {len(to_remove)} page(s): {to_remove}",
          file=sys.stderr)
    return json.dumps(result, ensure_ascii=False, indent=2)


def remove_pages(
    book_name: str,   # Book name
    page_nums: str,   # Comma-separated page numbers to remove
) -> str:
    """Remove page image files and their book.json entries.

    Use this to delete non-story pages (copyright, ISBN, author intro, etc.)
    after classifying them. The title page and story pages should be kept.
    Removes both the JPG files AND the corresponding entries from book.json.
    """
    nums = [int(x.strip()) for x in page_nums.split(",") if x.strip()]
    removed = []
    missing = []
    for n in nums:
        p = _page_path(book_name, n)
        if p.exists():
            p.unlink()
            removed.append(n)
        else:
            missing.append(n)

    # Also remove entries from book.json
    data = _read_book_json(book_name)
    if data:
        before = len(data.get("pages", []))
        data["pages"] = [p for p in data.get("pages", []) if p["page"] not in nums]
        after = len(data["pages"])
        if before != after:
            _write_book_json(book_name, data)

    # Update cache
    cache = _read_cache(book_name)
    cache["removed_pages"] = cache.get("removed_pages", []) + removed
    _write_cache(book_name, cache)

    remaining = _list_page_nums(book_name)
    msg = f"Removed {len(removed)} page(s): {removed}"
    if missing:
        msg += f". Not found: {missing}"
    if data:
        msg += f". book.json: {before - after} entr{'y' if before - after == 1 else 'ies'} removed"
    msg += f". Remaining pages: {remaining}"
    return msg


def list_pages(
    book_name: str,  # Book name
) -> str:
    """List all remaining page images with file sizes."""
    nums = _list_page_nums(book_name)
    if not nums:
        return f"No page images found in {_book_dir(book_name)}"
    lines = [f"Pages in {book_name} ({len(nums)} total):"]
    for n in nums:
        p = _page_path(book_name, n)
        size_kb = p.stat().st_size // 1024
        lines.append(f"  page{n}.jpg  ({size_kb} KB)")
    return "\n".join(lines)


def ocr_all_pages(
    book_name: str,  # Book name
    pdf_path: str,   # Path to the PDF file (for tier 1 text extraction)
    skip_tesseract: bool = False,  # Skip tesseract (tier 2), go straight to vision model
    force: bool = False,  # Re-OCR all pages even if chars already exist
) -> str:
    """Run tiered OCR on all pages and write results to book.json.

    For each page, tries in order:
    1. PDF text extraction (instant, perfect if the PDF has a text layer)
    2. Tesseract OCR (local, fast, moderate accuracy) — skipped if skip_tesseract
    3. Vision model OCR (API call, highest accuracy)

    Escalates to the next tier if the current tier returns fewer than 5 CJK
    characters. Pages that already have non-empty chars are skipped (cached)
    unless force=True.
    """
    nums = _list_page_nums(book_name)
    if not nums:
        return f"No page images found for book '{book_name}'"

    data = _read_book_json(book_name) or {
        "book": book_name,
        "base": f"assets/{book_name}",
        "script": "trad",
        "priority": "",
        "new_words": "",
        "pages": [],
    }
    existing = {p["page"]: p for p in data.get("pages", [])}

    # Skip pages that already have chars (unless force or garbage tesseract output)
    pages_to_ocr = []
    cached_pages = []
    for n in nums:
        e = existing.get(n)
        if e and e.get("chars") and not force:
            if _is_tesseract_garbage(e["chars"]):
                pages_to_ocr.append(n)  # re-OCR garbage
            else:
                cached_pages.append(n)
        else:
            pages_to_ocr.append(n)

    if not pages_to_ocr:
        return (
            f"All {len(nums)} page(s) already have chars (cached). "
            f"Use force=True to re-OCR. Pages: {nums}"
        )

    # Probe: check tier 1 on first page to detect scanned PDFs
    probe_text = _tier1_pdf_text(pdf_path, pages_to_ocr[0])
    pdf_has_text = _cjk_count(probe_text) >= 5
    if not pdf_has_text and not skip_tesseract:
        probe_ts = _tier2_tesseract(book_name, pages_to_ocr[0])
        if _cjk_count(probe_ts) < 5 or _is_tesseract_garbage(probe_ts):
            skip_tesseract = True
            print(f"  Probe: tesseract output is low-quality "
                  f"({_cjk_count(probe_ts)} CJK chars, garbage={_is_tesseract_garbage(probe_ts)}) "
                  f"on page {pages_to_ocr[0]}, skipping tesseract for all pages", file=sys.stderr)

    results = []
    combined_chars = ""
    for n in pages_to_ocr:
        text = _tier1_pdf_text(pdf_path, n)
        tier = 1
        if _cjk_count(text) < 5:
            if not skip_tesseract:
                text = _tier2_tesseract(book_name, n)
                tier = 2
            if skip_tesseract or _cjk_count(text) < 5 or _is_tesseract_garbage(text):
                try:
                    text = _tier3_model_ocr(book_name, n)
                except Exception as e:
                    text = ""
                    print(f"  page {n}: tier 3 error: {e}", file=sys.stderr)
                tier = 3
        text = text.strip()
        combined_chars += text
        results.append({"page": n, "tier": tier, "chars": text, "cjk_count": _cjk_count(text)})
        print(f"  OCR page {n}: tier {tier}, {_cjk_count(text)} CJK chars", file=sys.stderr)

    # Update book.json — preserve cached pages, add/update OCR'd pages
    pages = []
    for n in nums:
        entry = existing.get(n, {})
        entry["page"] = n
        if n in [r["page"] for r in results]:
            r = next(r for r in results if r["page"] == n)
            entry["chars"] = r["chars"]
        if "phrases" not in entry:
            entry["phrases"] = []
        pages.append(entry)
    data["pages"] = pages
    data["book"] = book_name
    data["base"] = f"assets/{book_name}"

    # Detect script from all chars (cached + new)
    all_chars = "".join(p.get("chars", "") for p in pages)
    if not data.get("script") or data["script"] == "trad":
        data["script"] = _detect_script(all_chars)
    _write_book_json(book_name, data)

    # Update cache
    cache = _read_cache(book_name)
    ocr_done = set(cache.get("ocr_done", []))
    ocr_done.update(r["page"] for r in results)
    cache["ocr_done"] = sorted(ocr_done)
    _write_cache(book_name, cache)

    tier_counts = {1: 0, 2: 0, 3: 0}
    empty_pages = []
    for r in results:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
        if r["cjk_count"] == 0:
            empty_pages.append(r["page"])

    summary = (
        f"OCR complete: {len(results)} page(s) processed, {len(cached_pages)} cached.\n"
        f"  Tier 1 (PDF text): {tier_counts.get(1, 0)} pages\n"
        f"  Tier 2 (tesseract): {tier_counts.get(2, 0)} pages\n"
        f"  Tier 3 (vision model): {tier_counts.get(3, 0)} pages\n"
        f"  Empty results: {empty_pages if empty_pages else 'none'}\n"
        f"  Detected script: {data['script']}\n"
        f"  book.json: {len(pages)} total pages"
    )
    return summary


def model_ocr_page(
    book_name: str,  # Book name
    page_num: int,   # Page number to re-OCR
) -> str:
    """Re-OCR a single page using the vision model (tier 3).

    Use this when a page has empty or poor OCR results and you want to
    force the highest-quality OCR. Updates book.json.
    """
    img_path = _page_path(book_name, page_num)
    if not img_path.exists():
        return f"Error: page {page_num} not found for book '{book_name}'"
    try:
        text = _tier3_model_ocr(book_name, page_num)
    except Exception as e:
        return f"Error: vision model failed for page {page_num}: {e}"

    data = _read_book_json(book_name)
    if data is None:
        return f"Error: book.json not found for book '{book_name}'"
    for entry in data.get("pages", []):
        if entry["page"] == page_num:
            entry["chars"] = text.strip()
            break
    else:
        data.setdefault("pages", []).append(
            {"page": page_num, "chars": text.strip(), "phrases": []}
        )
    _write_book_json(book_name, data)
    return f"Re-OCR'd page {page_num} with vision model: {len(text)} chars, {_cjk_count(text)} CJK. book.json updated."


def read_book_json(
    book_name: str,  # Book name
) -> str:
    """Read and return the current book.json content."""
    data = _read_book_json(book_name)
    if data is None:
        return f"No book.json found for book '{book_name}'. Run ocr_all_pages first."
    return json.dumps(data, ensure_ascii=False, indent=2)


def segment_phrases_tool(
    book_name: str,  # Book name
) -> str:
    """Segment each page's chars into reading phrases using jieba.

    Stores a 'phrases' array per page in book.json. Each phrase is a
    contiguous substring; joining all phrases reproduces the page's chars.
    Uses custom_words from book.json to keep book-specific terms (e.g.
    character names) as single words.
    """
    from segment_phrases import segment, validate, clean_chars, _load_custom_words
    data = _read_book_json(book_name)
    if data is None:
        return f"Error: book.json not found for book '{book_name}'"
    custom_words = data.get("custom_words", "")
    if custom_words:
        _load_custom_words(custom_words)
    segmented = 0
    skipped = 0
    for entry in data.get("pages", []):
        chars = entry.get("chars", "")
        if not chars:
            skipped += 1
            entry["phrases"] = []
            continue
        phrases = segment(chars)
        if not validate(phrases, chars):
            phrases = list(clean_chars(chars))
        entry["phrases"] = phrases
        segmented += 1
    _write_book_json(book_name, data)
    cache = _read_cache(book_name)
    cache["segmented"] = True
    _write_cache(book_name, cache)
    return f"Segmented {segmented} page(s), skipped {skipped} empty page(s). book.json updated."


def recommend_words_tool(
    book_name: str,  # Book name
    top: int = 5,    # Number of recommendations
) -> str:
    """Recommend high-frequency characters to add to the priority list.

    Ranks characters by how often they appear in this book, filtered by
    a general frequency table and excluding already-known characters.
    Returns the top recommendations with page numbers.
    """
    from recommend_words import recommend, parse_freq_table, parse_fluency, DEFAULT_FREQ_FILE, DEFAULT_FLUENCY_FILE
    data = _read_book_json(book_name)
    if data is None:
        return f"Error: book.json not found for book '{book_name}'"
    freq_by_simp = parse_freq_table(DEFAULT_FREQ_FILE)
    known = parse_fluency(DEFAULT_FLUENCY_FILE)
    results, total, not_learnt, in_top = recommend(data, freq_by_simp, top=top, known_chars=known)
    if not results:
        return "No recommendations available."
    lines = [f"Top {len(results)} recommendations (ranked by in-book frequency):"]
    for i, (book_count, rank, ch, ch_trad, count, pages) in enumerate(results, 1):
        pages_str = ", ".join(str(p) for p in pages[:5])
        if len(pages) > 5:
            pages_str += f", ... ({len(pages)} pages)"
        lines.append(f"  #{i}  {ch}  in-book: {book_count}x  rank #{rank}  pages: {pages_str}")
    return "\n".join(lines)


def set_book_meta(
    book_name: str,      # Book name
    script: str,         # Script: "trad" or "simp"
    priority: str,       # Priority characters (3-8 characters, no spaces)
    new_words: str,      # New word characters (1-4 characters, no spaces)
    custom_words: str = "",  # Custom words for jieba segmentation (e.g. character names like "独角章")
) -> str:
    """Set book-level metadata in book.json.

    - script: "trad" for traditional Chinese, "simp" for simplified.
    - priority: high-frequency characters the child is learning (3-8 chars).
    - new_words: new characters that trigger a reward animation (1-4 chars).
    - custom_words: multi-character words jieba doesn't know (e.g. "独角章",
      "棉花糖"). These are loaded into jieba before phrase segmentation
      so they stay as single words instead of being split.
    """
    data = _read_book_json(book_name)
    if data is None:
        return f"Error: book.json not found for book '{book_name}'"
    data["script"] = script
    data["priority"] = priority
    data["new_words"] = new_words
    if custom_words:
        data["custom_words"] = custom_words
    _write_book_json(book_name, data)
    cache = _read_cache(book_name)
    cache["meta_set"] = True
    _write_cache(book_name, cache)
    meta_parts = [
        f"script={script}",
        f"priority={priority} ({len(set(priority))} chars)",
        f"new_words={new_words} ({len(set(new_words))} chars)",
    ]
    if custom_words:
        meta_parts.append(f"custom_words={custom_words}")
    return f"Metadata set: {', '.join(meta_parts)}. book.json updated."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    extract_pdf_pages,
    gen_book,
    find_story_start,
    classify_pages,
    remove_pages,
    list_pages,
    ocr_all_pages,
    model_ocr_page,
    read_book_json,
    segment_phrases_tool,
    recommend_words_tool,
    set_book_meta,
]


def run_agent(book_name: str, pdf_path: str, agent_model: str,
              vision_model: str, max_steps: int = 30, force: bool = False):
    """Run the agent loop to process a book."""
    global AGENT_MODEL, VISION_MODEL, COST_TRACKER
    AGENT_MODEL = agent_model
    VISION_MODEL = vision_model
    COST_TRACKER = CostTracker()
    _setup_cost_tracking()

    from lisette import Chat, contents

    user_msg = (
        f"Process the book '{book_name}' from the PDF at '{pdf_path}'.\n"
        f"The book directory is app/assets/{book_name}/.\n"
        + ("Existing page images will be overwritten.\n" if force else "")
        + "Follow the workflow: extract, gen_book, find story start, check end "
        "pages, remove non-story pages, OCR all pages (tiered), review, segment, "
        "recommend, finalize, and report. Previous results are cached — skipped "
        "steps are normal on re-runs."
    )

    chat = Chat(AGENT_MODEL, sp=SYSTEM_PROMPT, tools=ALL_TOOLS, ns=globals())
    print(f"Agent model: {AGENT_MODEL}", file=sys.stderr)
    print(f"Vision model: {VISION_MODEL}", file=sys.stderr)
    print(f"Book: {book_name}", file=sys.stderr)
    print(f"PDF: {pdf_path}", file=sys.stderr)
    print(f"Max steps: {max_steps}", file=sys.stderr)
    print("---", file=sys.stderr)

    res = chat(user_msg, max_steps=max_steps)
    agent_text = contents(res).content

    # Print cost summary to stderr
    print("\n--- Cost ---", file=sys.stderr)
    print(COST_TRACKER.summary(), file=sys.stderr)

    # Save cost to cache
    cache = _read_cache(book_name)
    cache["cost"] = {
        "total": round(COST_TRACKER.total_cost, 6),
        "tokens": COST_TRACKER.total_tokens,
        "calls": len(COST_TRACKER.calls),
        "by_model": {},
    }
    for c in COST_TRACKER.calls:
        m = c["model"]
        if m not in cache["cost"]["by_model"]:
            cache["cost"]["by_model"][m] = {"calls": 0, "tokens": 0, "cost": 0.0}
        cache["cost"]["by_model"][m]["calls"] += 1
        cache["cost"]["by_model"][m]["tokens"] += c["total_tokens"]
        cache["cost"]["by_model"][m]["cost"] = round(
            cache["cost"]["by_model"][m]["cost"] + c["cost"], 6
        )
    _write_cache(book_name, cache)

    return agent_text


if __name__ == "__main__":
    from fastcore.script import call_parse, store_true

    @call_parse
    def main(
        name: str,  # Book name (subdirectory under app/assets)
        pdf: str = "",  # Path to the PDF file (omit with --cost to view last run)
        agent_model: str = "fireworks_ai/accounts/fireworks/models/kimi-k2p6",  # LiteLLM model for the agent loop
        vision_model: str = "fireworks_ai/accounts/fireworks/models/kimi-k2p6",  # LiteLLM model for vision OCR
        max_steps: int = 30,  # Maximum tool-calling rounds
        force: store_true = False,  # Overwrite existing page images
        cost: store_true = False,  # Show cost summary from last run and exit
    ):
        """Run the agent-driven book processing pipeline."""
        if cost:
            cache = _read_cache(name)
            c = cache.get("cost")
            if not c:
                print("No cost data found. Run the agent first.")
                return
            print(f"Last run cost for '{name}':")
            print(f"  {c['calls']} API call(s), {c['tokens']:,} tokens, ${c['total']:.4f}")
            for m, stats in sorted(c.get("by_model", {}).items()):
                print(f"    {m}: {stats['calls']} call(s), {stats['tokens']:,} tokens, ${stats['cost']:.4f}")
            return
        if not pdf:
            print("Error: pdf path is required (unless using --cost)", file=sys.stderr)
            return
        if "FIREWORKS_API_KEY" not in os.environ:
            print("Warning: FIREWORKS_API_KEY not set. Set it before running.", file=sys.stderr)
        result = run_agent(name, pdf, agent_model, vision_model, max_steps, force)
        print("\n=== Agent Result ===")
        print(result)
