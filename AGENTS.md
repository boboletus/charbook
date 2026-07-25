# AGENTS.md

## What this is

A static HTML app for Chinese character recognition practice. A parent reads a book page; the child points at characters they recognize. Tapping a card fades its opaque background to reveal the illustration. When all priority characters on a page are found, the rest auto-reveal and all cards fade out to show the full picture.

No build step, no npm, no framework. The app is a static `app/` directory deployed to GitHub Pages.

## Running locally

```bash
source .venv/bin/activate
cd app && python3 -m http.server 8000
```

Open http://localhost:8000. A server is required — the app uses `fetch()` to load `book.json`, which won't work over `file://`.

## Architecture

- `app/index.html` — HTML structure only (toolbar, page area, review screen, edit modal).
- `app/style.css` — all CSS (layout, cards, animations, responsive, reduced-motion).
- `app/app.js` — all JS (state, rendering, event listeners, variant toggle, review screen).
- `app/assets/<book-name>/book.json` — master data: page list, characters, priority. Fetched at runtime. This is the single source of truth; the app does not use `localStorage`.
- `app/assets/<book-name>/pageN.jpg` — page images extracted from PDF.
- `scripts/extract_pdf.py` — render PDF pages to JPGs.
- `scripts/gen_book.py` — generate/sync `book.json` from page images.
- `scripts/convert_dual.py` — convert book.json to dual simplified+traditional format (adds `chars_trad`/`priority_trad` via OpenCC `s2tw`).
- `tests/` — pytest smoke tests for `gen_book.py` and `convert_dual.py`.

## book.json format

```json
{
  "book": "哪一个很奇怪",
  "base": "assets/哪一个很奇怪",
  "priority": "小一不人了",
  "priority_trad": "小一不人了",
  "pages": [
    { "page": 5, "chars": "哪一个很奇怪", "chars_trad": "哪一個很奇怪" }
  ]
}
```

- `priority` is book-level (applies to all pages), not per-page.
- `priority_trad` and `chars_trad` are traditional Chinese variants, generated from the simplified fields via OpenCC (`s2tw`). The app defaults to traditional; a 繁/簡 toggle in the toolbar switches display.
- `cols` is no longer in the schema — the app auto-calculates columns from image aspect ratio to make cards roughly square.
- Punctuation in `chars` is kept and becomes cards like any other character.
- Page numbers in the JSON correspond to `pageN.jpg` filenames (may not start at 1).

## Python scripts

Both scripts use `fastcore.script` and run under the project venv:

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
```

Run tests:

```bash
pytest tests/ -v
```

Dependencies: `pymupdf`, `pillow`, `fastcore`, `opencc-python-reimplemented`, `pytest` (installed in `.venv`).

## Key design constraints

- Cards fade (background to transparent), no flip/spin animation.
- After all priority chars are revealed, remaining cards auto-reveal then all fade out.
- "Reveal All" button works on any page (including pages with no priority chars).
- Toolbar shows priority counter only (e.g. `1 / 5`), not total progress.
- Edit modal shows the page image alongside the form so the parent can read while typing.
- Arrow keys navigate pages when the modal is closed. `T` key toggles 繁/簡.
- Priority review screen: on first load, if priority characters exist, a full-screen review overlay shows each unique priority character as a large flashcard. Tapping a card pops it and marks it reviewed (accent ring). When all are reviewed, the "Start Reading" button becomes primary. The "Review" toolbar button re-opens it at any time. `Escape` exits review.

## Development workflow

For every user request that involves code changes, follow this workflow in order. Do not skip steps.

### 1. Design (if there's a visual/UI element)

Load the relevant design skills before writing any code:
- `better-ui` for layout, surfaces, animations, polish details.
- `better-typography` for text, fonts, spacing, wrapping.
- `apple-design` for gesture-driven UI, springs, materials, motion principles.
- `better-accessibility` for keyboard, ARIA, focus, reduced-motion.

Study existing CSS/JS conventions in `app/style.css` and `app/app.js` before adding new ones. Match the project's styling system (plain CSS, OKLCH colors, `var(--ease)` for timing, `scale(0.96)` for press, concentric border radius, no `transition: all`).

### 2. Develop

Make the code changes. Follow the architecture: HTML structure in `index.html`, styles in `style.css`, logic in `app.js`. No build step, no npm, no framework. Update Python scripts (`scripts/`) and `book.json` data model if the feature touches data.

### 3. Test (unit)

```bash
source .venv/bin/activate
pytest tests/ -v
```

All tests must pass. Add new tests in `tests/` for any new Python script behavior. If a test fails, fix the code — do not skip or weaken the test.

### 4. Integration test (UI)

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

### 5. Code review (refactoring)

Use the `code-review-analysis` skill (in `.agents/skills/code-review-analysis/`) to audit changes for:
- Code quality: readability, complexity, duplicated patterns.
- Security: XSS (use `textContent` not `innerHTML` for user data), error handling.
- Performance: unnecessary DOM lookups, repeated patterns that should be helpers.
- Best practices: no silent catch blocks, no `transition: all`, `will-change` only on compositor-friendly properties.

Fix any issues found before committing. If a previous step introduced a regression (e.g. referencing `dom.*` before `initDomCache()`), fix it here.

### 6. Commit

Commit with a clear message describing what changed and why. If working on a branch per the user's request, squash-merge to `main` after all steps pass.

### 7. Feedback

Report to the user: what was done, what was verified, and any issues or trade-offs. Keep it concise.

## Deployment

GitHub Actions deploys `app/` to GitHub Pages on push to `main` (`.github/workflows/pages.yml`). No build step needed — the `app/` directory is uploaded as-is.

## Gotchas

- The venv uses system Python 3.14 at `/usr/bin/python3.14` (mise's Python 3.14 has a broken venv module). If `python3 -m venv` fails, use `/usr/bin/python3.14 -m venv .venv`.
- `.opencode/`, `.agents/`, `skills-lock.json`, and `*.pdf` are gitignored. `book.js` was removed — do not recreate it; use `book.json` fetched at runtime.
- `book.json` lives inside the book's asset directory (`app/assets/<name>/book.json`), not at the app root.
