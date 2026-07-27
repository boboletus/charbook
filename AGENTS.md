# AGENTS.md

## What this is

A static HTML app for Chinese character recognition practice. A parent reads a book page; the child points at characters they recognize. Tapping a card fades its opaque background to reveal the illustration. When all priority characters on a page are found, the rest auto-reveal and all cards fade out to show the full picture. New word cards trigger a unicorn animation on tap.

No build step, no npm, no framework. The app is a static `app/` directory deployed to GitHub Pages.

## Running locally

```bash
source .venv/bin/activate
cd app && python3 -m http.server 8000
```

A server is required — the app uses `fetch()` to load `book.json`, which won't work over `file://`.

## Architecture

- `app/app.js` — all JS (state, rendering, event listeners, variant toggle, review screen, unicorn animation). **The active book is hardcoded on line 1** as `BOOK_JSON`; there is no book-switching UI. To change books, edit that constant to point at a different `assets/<name>/book.json`.
- `app/index.html` — HTML structure only (toolbar, page area, review screen, edit modal).
- `app/style.css` — all CSS (layout, cards, animations, responsive, reduced-motion).
- `app/assets/<book-name>/book.json` — master data: page list, characters, priority, new words. Fetched at runtime. Single source of truth; the app does not use `localStorage`.
- `app/assets/<book-name>/pageN.jpg` — page images extracted from PDF.
- `app/assets/Prize/` — shared reward assets, **not a book**. Holds the unicorn SVG collection (every `*.svg` is a candidate, picked at random on each new-word tap) and `prize.json` (the generated manifest of those SVGs, loaded by `loadPrizeSvgs()` via the `PRIZE_DIR` constant). Icons come from OpenSVG, which permits commercial and personal use with no attribution requirement.
- `app/assets/fluency.txt` — newline-delimited list of characters the child already knows; `recommend_words.py` excludes these from recommendations.
- `scripts/extract_pdf.py` — render PDF pages to JPGs.
- `scripts/gen_book.py` — generate/sync `book.json` from page images.
- `scripts/convert_dual.py` — convert book.json to dual simplified+traditional format (adds `chars_trad`/`priority_trad`/`new_words_trad` via OpenCC `s2tw`).
- `scripts/recommend_words.py` — recommend high-frequency characters to add to priority list (reads `scripts/freq_table.csv` and `app/assets/fluency.txt`).
- `scripts/segment_phrases.py` — auto-segment each page's `chars` into phrases using jieba, stored as `phrases` array per page in `book.json`.
- `scripts/gen_prize.py` — generate `app/assets/Prize/prize.json` manifest listing every unicorn `*.svg` so the static app can pick one at random.
- `docs/flows.org` — human-facing org-mode notes: the user flow and this development workflow. Update the user flow there when a feature changes user-facing behavior.
- `tests/` — pytest smoke tests for `gen_book.py`, `gen_prize.py`, `convert_dual.py`, `recommend_words.py`, and `segment_phrases.py`.

## book.json format

```json
{
  "book": "哪一个很奇怪",
  "base": "assets/哪一个很奇怪",
  "priority": "小一不人了",
  "priority_trad": "小一不人了",
  "new_words": "奇怪",
  "new_words_trad": "奇怪",
  "pages": [
    { "page": 5, "chars": "哪一个很奇怪", "chars_trad": "哪一個很奇怪", "phrases": ["哪", "一个", "很", "奇怪"], "phrases_trad": ["哪", "一個", "很", "奇怪"] }
  ]
}
```

- `priority` is book-level (applies to all pages), not per-page.
- `new_words` is book-level; tapping a new-word card triggers a unicorn animation.
- `priority_trad`, `chars_trad`, and `new_words_trad` are traditional Chinese variants, generated from the simplified fields via OpenCC (`s2tw`). The app defaults to traditional; a 繁/簡 toggle in the toolbar switches display.
- `cols` is no longer in the schema — the app auto-calculates columns from image aspect ratio to make cards roughly square.
- Punctuation in `chars` is kept and becomes cards like any other character.
- Page numbers in the JSON correspond to `pageN.jpg` filenames (may not start at 1).

## Python scripts

All scripts use `fastcore.script` and run under the project venv:

```bash
source .venv/bin/activate

# Extract PDF pages to JPGs
python scripts/extract_pdf.py --name 哪一个很奇怪 "book.pdf"

# Generate or reconcile book.json from page images
python scripts/gen_book.py 哪一个很奇怪
# Use --reset to wipe chars back to empty (keeps page list + priority)

# Convert book.json to dual simplified+traditional format
python scripts/convert_dual.py 哪一个很奇怪
# Use --reset-trad to re-convert all traditional fields from simplified

# Auto-segment each page's chars into phrases
python scripts/segment_phrases.py 哪一个很奇怪
# Use --reset to re-segment all pages (overwrites manual edits)

# Recommend high-frequency characters to add to priority
python scripts/recommend_words.py 哪一个很奇怪
# Use --top N to change count, --all to see all candidates, --fluency-file to override the known-chars list
```

Run tests:

```bash
pytest tests/ -v
```

Dependencies: `pymupdf`, `pillow`, `fastcore`, `opencc-python-reimplemented`, `jieba`, `pytest` (installed in `.venv`; see `requirements.txt`).

## Key design constraints

- Cards fade (background to transparent), no flip/spin animation.
- After all priority chars are revealed, remaining cards auto-reveal then all fade out.
- Revisiting a completed page shows the illustration directly (no cards). Reset clears this.
- "Reveal All" button works on any page (including pages with no priority chars).
- Toolbar shows priority counter only (e.g. `1 / 5`), not total progress.
- Edit modal shows the page image alongside the form so the parent can read while typing.
- Keyboard: ←/→ arrows navigate pages when the modal is closed; ↑/↓ arrows move a gentle reading spotlight through the page's phrases in reading order (right-to-left, top-to-bottom), clamping at the ends; `Space` reveals the spotlit phrase's cards and advances the spotlight to the next phrase; `T` toggles 繁/簡; `R` reveals all; `Ctrl/Cmd+Enter` saves the edit modal; `Escape` closes the modal or exits review. The spotlight is disabled while the review screen or edit modal is open.
- Priority review screen: on first load, if priority characters exist, a full-screen review overlay shows each unique priority character as a large flashcard. Tapping a card pops it and marks it reviewed (accent ring). When all are reviewed, the "Start Reading" button becomes primary. The "Review" toolbar button re-opens it at any time.
- New word cards trigger a unicorn icon (a random SVG from `assets/Prize/` via `prize.json`) in a random bright OKLCH color theme, with one of 5 random CSS animations on tap. Monochrome (`currentColor`) SVGs adopt the theme color; multi-color SVGs keep their colors with a themed glow. No visual hint before tap. Reduced-motion skips the animation. Falls back to 🦄 emoji if every SVG fails to load.
- CSS uses `transform` shorthand (not individual `scale`/`translate`/`rotate` properties) for Firefox Android compatibility.

## Development workflow

For every user request that involves code changes, follow this workflow in order. Do not skip steps.

### 1. Design (if there's a visual/UI element)

Load the relevant design skills before writing any code:
- `better-ui` for layout, surfaces, animations, polish details.
- `better-typography` for text, fonts, spacing, wrapping.
- `apple-design` for gesture-driven UI, springs, materials, motion principles.
- `better-accessibility` for keyboard, ARIA, focus, reduced-motion.

Study existing CSS/JS conventions in `app/style.css` and `app/app.js` before adding new ones. Match the project's styling system (plain CSS, OKLCH colors, `var(--ease)` for timing, `scale(0.96)` for press, concentric border radius, no `transition: all`).

### 2. Document

If the change affects user-facing behavior, add or modify the matching user flow in `docs/flow.org` before coding.

### 3. Develop

Make the code changes. Follow the architecture: HTML structure in `index.html`, styles in `style.css`, logic in `app.js`. No build step, no npm, no framework. Update Python scripts (`scripts/`) and `book.json` data model if the feature touches data.

### 4. Test (unit)

```bash
source .venv/bin/activate
pytest tests/ -v
```

All tests must pass. Add new tests in `tests/` for any new Python script behavior. If a test fails, fix the code — do not skip or weaken the test.

### 5. Integration test (UI)

Launch the local server and verify the app renders and features work:

```bash
python3 -m http.server 8000 --directory app &
```

Use headless Chromium to verify the DOM renders correctly:

```bash
chromium --headless --no-sandbox --disable-gpu --dump-dom http://localhost:8000/ | grep -oE 'card-wrapper|review-card|book-page|unicorn'
```

Check for:
- No JS console errors (a silent page with no cards means a script crash).
- All expected DOM elements present (cards, review screen, toolbar buttons).
- New feature elements render (e.g. `unicorn-overlay` after tap, `editNewWords` in modal).
- Kill the server after testing: `fuser -k 8000/tcp`.

### 6. Code review (refactoring)

Use the `code-review-analysis` skill (in `.agents/skills/code-review-analysis/`) to audit changes for:
- Code quality: readability, complexity, duplicated patterns.
- Security: XSS (use `textContent` not `innerHTML` for user data), error handling.
- Performance: unnecessary DOM lookups, repeated patterns that should be helpers.
- Best practices: no silent catch blocks, no `transition: all`, `will-change` only on compositor-friendly properties.

Fix any issues found before committing. If a previous step introduced a regression (e.g. referencing `dom.*` before `initDomCache()`), fix it here.

### 7. Commit

Commit with a clear message describing what changed and why. If working on a branch per the user's request, squash-merge to `main` after all steps pass.

### 8. Feedback

Report to the user: what was done, what was verified, and any issues or trade-offs. Keep it concise.

## Deployment

GitHub Actions deploys `app/` to GitHub Pages on push to `main` (`.github/workflows/pages.yml`). No build step needed — the `app/` directory is uploaded as-is.

## Gotchas

- The venv uses system Python 3.14 at `/usr/bin/python3.14` (mise's Python 3.14 has a broken venv module). If `python3 -m venv` fails, use `/usr/bin/python3.14 -m venv .venv`.
- `.opencode/`, `.agents/`, `.claude/`, `skills-lock.json`, and `*.pdf` are gitignored. `book.js` was removed — do not recreate it; use `book.json` fetched at runtime.
- `book.json` lives inside the book's asset directory (`app/assets/<name>/book.json`), not at the app root.
- The active book is hardcoded in `app/app.js` line 1 (`BOOK_JSON`). There is no runtime book selector — switching books is a code edit, not a user action.
- `app/assets/Prize/` contains shared reward assets: the unicorn SVG collection (all `*.svg` are used, picked randomly) and the generated `prize.json` manifest. Run `scripts/gen_prize.py` after adding or removing SVGs.
