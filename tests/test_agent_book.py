"""Tests for the agent_book.py helper functions and tiered OCR logic."""
import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agent_book


# --- CJK helpers ---

def test_cjk_count():
    assert agent_book._cjk_count("嘿我是独角章") == 6
    assert agent_book._cjk_count("hello") == 0
    assert agent_book._cjk_count("嘿a我b") == 2
    assert agent_book._cjk_count("") == 0


def test_has_cjk():
    assert agent_book._has_cjk("嘿我是独角章") is True
    assert agent_book._has_cjk("hello") is False
    assert agent_book._has_cjk("") is False


# --- Tesseract garbage detection ---

def test_is_tesseract_garbage_spaced_chars():
    """Every CJK char separated by spaces = garbage."""
    garbage = "。 旱 角 章 [ 美 ] 凱 文"
    assert agent_book._is_tesseract_garbage(garbage) is True


def test_is_tesseract_garbage_real_text():
    """Connected Chinese text without spaces = not garbage."""
    real = "嘿，我是独角章。我是海底的一只小章鱼。"
    assert agent_book._is_tesseract_garbage(real) is False


def test_is_tesseract_garbage_empty():
    assert agent_book._is_tesseract_garbage("") is True
    assert agent_book._is_tesseract_garbage("a") is True


def test_is_tesseract_garbage_mixed():
    """Text with some spaces but mostly connected = not garbage."""
    mixed = "独角章 妹妹 今天很开心"
    assert agent_book._is_tesseract_garbage(mixed) is False


# --- Script detection ---

def test_detect_script_simp():
    assert agent_book._detect_script("我是独角章") == "simp"


def test_detect_script_trad():
    assert agent_book._detect_script("我是獨角章") == "trad"
    assert agent_book._detect_script("這個") == "trad"
    assert agent_book._detect_script("裡面") == "trad"


def test_detect_script_empty():
    assert agent_book._detect_script("") == "trad"


# --- Page listing ---

def test_list_page_nums(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in [3, 1, 2]:
        (book / f"page{n}.jpg").write_bytes(b"")
    assert agent_book._list_page_nums("testbook") == [1, 2, 3]


def test_list_page_nums_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    assert agent_book._list_page_nums("nonexistent") == []


# --- book.json read/write ---

def test_write_and_read_book_json(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    data = {
        "book": "test", "base": "assets/test", "script": "simp",
        "priority": "", "new_words": "",
        "pages": [{"page": 1, "chars": "你好", "phrases": []}],
    }
    agent_book._write_book_json("testbook", data)
    assert agent_book._read_book_json("testbook") == data


def test_read_book_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    assert agent_book._read_book_json("nonexistent") is None


# --- Cost tracker ---

def test_cost_tracker():
    tracker = agent_book.CostTracker()
    assert tracker.summary() == "No API calls made."
    # Simulate adding calls
    class FakeUsage:
        prompt_tokens = 100
        completion_tokens = 50
    tracker.add("model-a", FakeUsage(), 0.001)
    tracker.add("model-a", FakeUsage(), 0.002)
    tracker.add("model-b", FakeUsage(), 0.005)
    summary = tracker.summary()
    assert "3 API call(s)" in summary
    assert "$0.0080" in summary
    assert "model-a: 2 call(s)" in summary
    assert "model-b: 1 call(s)" in summary
    assert tracker.total_tokens == 450  # 3 * (100 + 50)


# --- Cache helpers ---

def test_cache_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    agent_book._write_cache("testbook", {"classifications": {"1": "title"}})
    cache = agent_book._read_cache("testbook")
    assert cache["classifications"]["1"] == "title"


def test_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    assert agent_book._read_cache("nonexistent") == {}


# --- Tool: gen_book ---

def test_gen_book_creates_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in [1, 2, 3]:
        (book / f"page{n}.jpg").write_bytes(b"")
    result = agent_book.gen_book("testbook")
    assert "3 page(s)" in result
    data = agent_book._read_book_json("testbook")
    assert len(data["pages"]) == 3
    assert [p["page"] for p in data["pages"]] == [1, 2, 3]
    for p in data["pages"]:
        assert p["chars"] == ""
        assert p["phrases"] == []


def test_gen_book_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"")
    (book / "page2.jpg").write_bytes(b"")
    agent_book.gen_book("testbook")
    data = agent_book._read_book_json("testbook")
    data["pages"][0]["chars"] = "你好"
    data["priority"] = "你"
    agent_book._write_book_json("testbook", data)
    # Re-run gen_book — should preserve chars and priority
    result = agent_book.gen_book("testbook")
    assert "Chars filled: 1/2" in result
    data2 = agent_book._read_book_json("testbook")
    assert data2["pages"][0]["chars"] == "你好"
    assert data2["priority"] == "你"


# --- Tool: set_book_meta ---

def test_set_book_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    data = {
        "book": "test", "base": "assets/test", "script": "trad",
        "priority": "", "new_words": "",
        "pages": [{"page": 1, "chars": "你好", "phrases": []}],
    }
    agent_book._write_book_json("testbook", data)
    result = agent_book.set_book_meta("testbook", "simp", "你好", "世界")
    assert "simp" in result
    data2 = agent_book._read_book_json("testbook")
    assert data2["script"] == "simp"
    assert data2["priority"] == "你好"
    assert data2["new_words"] == "世界"
    # Check cache
    cache = agent_book._read_cache("testbook")
    assert cache.get("meta_set") is True


# --- Tool: remove_pages ---

def test_remove_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in [1, 2, 3]:
        (book / f"page{n}.jpg").write_bytes(b"")
    result = agent_book.remove_pages("testbook", "1,3")
    assert "2" in result
    assert (book / "page2.jpg").exists()
    assert not (book / "page1.jpg").exists()
    assert not (book / "page3.jpg").exists()


def test_remove_pages_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"")
    result = agent_book.remove_pages("testbook", "1,99")
    assert "Not found" in result
    assert "99" in result


def test_remove_pages_also_updates_book_json(tmp_path, monkeypatch):
    """remove_pages should delete entries from book.json too."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in [1, 2, 3]:
        (book / f"page{n}.jpg").write_bytes(b"")
    agent_book.gen_book("testbook")
    data = agent_book._read_book_json("testbook")
    assert len(data["pages"]) == 3
    agent_book.remove_pages("testbook", "1,3")
    data2 = agent_book._read_book_json("testbook")
    assert len(data2["pages"]) == 1
    assert data2["pages"][0]["page"] == 2


# --- Tool: find_story_start ---

def test_find_story_start(tmp_path, monkeypatch):
    """Test that find_story_start skips ahead and back-validates."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in range(1, 11):
        (book / f"page{n}.jpg").write_bytes(b"")

    # Mock classification: page 1=title, 2-4=non-story, 5+=story
    def mock_classify(book_name, page_num):
        if page_num == 1:
            return {"classification": "title", "reason": "title page"}
        elif page_num <= 4:
            return {"classification": "non-story", "reason": "copyright"}
        else:
            return {"classification": "story", "reason": "story page"}
    monkeypatch.setattr(agent_book, "_classify_with_vision", mock_classify)

    result = agent_book.find_story_start("testbook")
    data = json.loads(result)
    assert data["first_story_page"] == 5
    assert data["title_pages"] == [1]
    assert data["pages_to_remove"] == [2, 3, 4]
    assert 1 in data["pages_to_keep"]
    assert 5 in data["pages_to_keep"]


def test_find_story_start_back_validates(tmp_path, monkeypatch):
    """Test that find_story_start backs up to find the exact boundary."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in range(1, 11):
        (book / f"page{n}.jpg").write_bytes(b"")

    # Probe at page 4 finds story, but page 3 is also story (boundary=3)
    def mock_classify(book_name, page_num):
        if page_num == 1:
            return {"classification": "title", "reason": "title"}
        elif page_num == 2:
            return {"classification": "non-story", "reason": "copyright"}
        else:
            return {"classification": "story", "reason": "story"}
    monkeypatch.setattr(agent_book, "_classify_with_vision", mock_classify)

    result = agent_book.find_story_start("testbook")
    data = json.loads(result)
    assert data["first_story_page"] == 3
    assert data["pages_to_remove"] == [2]


def test_find_story_start_title_and_immediate_story(tmp_path, monkeypatch):
    """Page 1=title, page 2=story — no pages to remove."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in range(1, 6):
        (book / f"page{n}.jpg").write_bytes(b"")

    def mock_classify(book_name, page_num):
        if page_num == 1:
            return {"classification": "title", "reason": "title"}
        return {"classification": "story", "reason": "story"}
    monkeypatch.setattr(agent_book, "_classify_with_vision", mock_classify)

    result = agent_book.find_story_start("testbook")
    data = json.loads(result)
    assert data["first_story_page"] == 2
    assert data["pages_to_remove"] == []


# --- Tool: list_pages ---

def test_list_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"x" * 1024)
    (book / "page2.jpg").write_bytes(b"x" * 2048)
    result = agent_book.list_pages("testbook")
    assert "2 total" in result
    assert "page1.jpg" in result
    assert "page2.jpg" in result


def test_list_pages_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    result = agent_book.list_pages("nonexistent")
    assert "No page images" in result


# --- Tool: segment_phrases_tool ---

def test_segment_phrases_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    data = {
        "book": "test", "base": "assets/test", "script": "simp",
        "priority": "", "new_words": "",
        "pages": [{"page": 1, "chars": "独角兽妹妹", "phrases": []}],
    }
    agent_book._write_book_json("testbook", data)
    result = agent_book.segment_phrases_tool("testbook")
    assert "Segmented" in result
    data2 = agent_book._read_book_json("testbook")
    phrases = data2["pages"][0]["phrases"]
    assert "".join(phrases) == "独角兽妹妹"


# --- Tool: recommend_words_tool ---

def test_recommend_words_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    data = {
        "book": "test", "base": "assets/test", "script": "simp",
        "priority": "小", "new_words": "",
        "pages": [{"page": 1, "chars": "小独角兽妹妹", "phrases": []}],
    }
    agent_book._write_book_json("testbook", data)
    result = agent_book.recommend_words_tool("testbook", top=3)
    assert isinstance(result, str)
    assert len(result) > 0


# --- Tier 1: PDF text extraction ---

def test_tier1_pdf_text_scanned():
    """The test PDF is scanned (no embedded text layer)."""
    pdf = Path("嘿我是独角章.pdf")
    if not pdf.exists():
        pytest.skip("Test PDF not found")
    text = agent_book._tier1_pdf_text(str(pdf), 1)
    assert agent_book._cjk_count(text) == 0


# --- Tier 2: tesseract ---

def test_tier2_tesseract(tmp_path, monkeypatch):
    """Tesseract should find some CJK characters from a real page image."""
    pdf = Path("嘿我是独角章.pdf")
    if not pdf.exists():
        pytest.skip("Test PDF not found")
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    # Extract one page
    agent_book.extract_pdf_pages("test_ts", str(pdf), force=True)
    text = agent_book._tier2_tesseract("test_ts", 1)
    # Tesseract should find at least some CJK characters
    assert isinstance(text, str)


# --- Tool: extract_pdf_pages ---

def test_extract_pdf_pages(tmp_path, monkeypatch):
    pdf = Path("嘿我是独角章.pdf")
    if not pdf.exists():
        pytest.skip("Test PDF not found")
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    result = agent_book.extract_pdf_pages("test_extract", str(pdf), force=True)
    assert "Extracted" in result
    pages = agent_book._list_page_nums("test_extract")
    assert len(pages) == 46


def test_extract_pdf_pages_no_overwrite(tmp_path, monkeypatch):
    pdf = Path("嘿我是独角章.pdf")
    if not pdf.exists():
        pytest.skip("Test PDF not found")
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    agent_book.extract_pdf_pages("test_no_ovr", str(pdf), force=True)
    result = agent_book.extract_pdf_pages("test_no_ovr", str(pdf), force=False)
    assert "cached" in result.lower() or "already" in result.lower()


# --- Tiered OCR logic (with mocked tier 3) ---

def test_ocr_all_pages_tiered(tmp_path, monkeypatch):
    """Test that ocr_all_pages escalates from tier 1 to tier 3 when tiers 1&2 fail."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "test_ocr"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"fake")
    (book / "page2.jpg").write_bytes(b"fake")

    # Mock all tiers
    monkeypatch.setattr(agent_book, "_tier1_pdf_text", lambda pdf, n: "")
    monkeypatch.setattr(agent_book, "_tier2_tesseract", lambda bk, n: "")
    tier3_calls = []
    def mock_tier3(book_name, page_num):
        tier3_calls.append(page_num)
        return f"mock text page {page_num}"
    monkeypatch.setattr(agent_book, "_tier3_model_ocr", mock_tier3)

    result = agent_book.ocr_all_pages("test_ocr", "fake.pdf")
    assert "OCR complete" in result
    assert "Tier 3" in result
    assert len(tier3_calls) == 2  # both pages escalated to tier 3
    data = agent_book._read_book_json("test_ocr")
    for entry in data["pages"]:
        assert entry["chars"].startswith("mock text")


def test_ocr_all_pages_skip_tesseract(tmp_path, monkeypatch):
    """Test skip_tesseract goes straight to tier 3."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "test_skip_ts"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"fake")
    (book / "page2.jpg").write_bytes(b"fake")

    tier2_calls = []
    monkeypatch.setattr(agent_book, "_tier1_pdf_text", lambda pdf, n: "")
    monkeypatch.setattr(agent_book, "_tier2_tesseract",
                        lambda bk, n: tier2_calls.append(n) or "")
    call_log = []
    def mock_tier3(book_name, page_num):
        call_log.append(page_num)
        return f"vision text {page_num}"
    monkeypatch.setattr(agent_book, "_tier3_model_ocr", mock_tier3)

    result = agent_book.ocr_all_pages("test_skip_ts", "fake.pdf", skip_tesseract=True)
    assert "Tier 3" in result
    assert "Tier 2 (tesseract): 0 pages" in result
    assert len(tier2_calls) == 0  # tesseract never called
    assert len(call_log) == 2     # both pages OCR'd via tier 3


def test_ocr_all_pages_tier1_success(tmp_path, monkeypatch):
    """Test that tier 1 text is used when PDF has a text layer."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "test_t1"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"fake image")

    # Mock tier 1 to return text
    def mock_tier1(pdf_path, page_num):
        return "这是第一页的文字"
    monkeypatch.setattr(agent_book, "_tier1_pdf_text", mock_tier1)

    # Mock tier 3 to track if it's called (should NOT be)
    def mock_tier3(book_name, page_num):
        raise AssertionError("Tier 3 should not be called when tier 1 succeeds")
    monkeypatch.setattr(agent_book, "_tier3_model_ocr", mock_tier3)

    result = agent_book.ocr_all_pages("test_t1", "fake.pdf")
    assert "Tier 1" in result
    data = agent_book._read_book_json("test_t1")
    assert data["pages"][0]["chars"] == "这是第一页的文字"


# --- OCR caching ---

def test_ocr_all_pages_skips_cached(tmp_path, monkeypatch):
    """Pages with existing chars should be skipped (cached)."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "test_cache"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"fake")
    (book / "page2.jpg").write_bytes(b"fake")

    # Create book.json with page 1 already having chars
    agent_book.gen_book("test_cache")
    data = agent_book._read_book_json("test_cache")
    data["pages"][0]["chars"] = "已有的文字"
    agent_book._write_book_json("test_cache", data)

    # Mock tiers — tier 3 should only be called for page 2
    monkeypatch.setattr(agent_book, "_tier1_pdf_text", lambda pdf, n: "")
    monkeypatch.setattr(agent_book, "_tier2_tesseract", lambda bk, n: "")
    tier3_calls = []
    def mock_tier3(book_name, page_num):
        tier3_calls.append(page_num)
        return f"new text {page_num}"
    monkeypatch.setattr(agent_book, "_tier3_model_ocr", mock_tier3)

    result = agent_book.ocr_all_pages("test_cache", "fake.pdf", skip_tesseract=True)
    assert "1 cached" in result
    assert len(tier3_calls) == 1  # only page 2 was OCR'd
    assert tier3_calls[0] == 2
    # Page 1's chars should be preserved
    data2 = agent_book._read_book_json("test_cache")
    assert data2["pages"][0]["chars"] == "已有的文字"
    assert data2["pages"][1]["chars"] == "new text 2"


def test_ocr_all_pages_force_reocr(tmp_path, monkeypatch):
    """force=True should re-OCR even pages with existing chars."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "test_force"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"fake")

    agent_book.gen_book("test_force")
    data = agent_book._read_book_json("test_force")
    data["pages"][0]["chars"] = "old text"
    agent_book._write_book_json("test_force", data)

    monkeypatch.setattr(agent_book, "_tier1_pdf_text", lambda pdf, n: "")
    monkeypatch.setattr(agent_book, "_tier2_tesseract", lambda bk, n: "")
    monkeypatch.setattr(agent_book, "_tier3_model_ocr", lambda bk, n: "new text")

    result = agent_book.ocr_all_pages("test_force", "fake.pdf", skip_tesseract=True, force=True)
    assert "0 cached" in result
    data2 = agent_book._read_book_json("test_force")
    assert data2["pages"][0]["chars"] == "new text"


# --- Classification caching ---

def test_classify_pages_caches(tmp_path, monkeypatch):
    """classify_pages should cache results and return cached on second call."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    (book / "page1.jpg").write_bytes(b"")

    call_count = 0
    def mock_classify(book_name, page_num):
        nonlocal call_count
        call_count += 1
        return {"classification": "title", "reason": "title page"}
    monkeypatch.setattr(agent_book, "_classify_with_vision", mock_classify)

    # First call — should invoke vision model
    result1 = agent_book.classify_pages("testbook", "1")
    data1 = json.loads(result1)
    assert call_count == 1

    # Second call — should use cache
    result2 = agent_book.classify_pages("testbook", "1")
    data2 = json.loads(result2)
    assert call_count == 1  # vision model not called again
    assert data2[0].get("cached") is True


def test_find_story_start_uses_cache(tmp_path, monkeypatch):
    """find_story_start should use cached classifications from a previous run."""
    monkeypatch.setattr(agent_book, "ASSETS_DIR", tmp_path)
    book = tmp_path / "testbook"
    book.mkdir()
    for n in range(1, 8):
        (book / f"page{n}.jpg").write_bytes(b"")

    # Pre-populate cache with classifications
    agent_book._write_cache("testbook", {
        "classifications": {
            "1": {"classification": "title", "reason": "cached title"},
            "4": {"classification": "story", "reason": "cached story"},
        }
    })

    call_count = 0
    def mock_classify(book_name, page_num):
        nonlocal call_count
        call_count += 1
        if page_num == 1:
            return {"classification": "title", "reason": "title"}
        return {"classification": "story", "reason": "story"}
    monkeypatch.setattr(agent_book, "_classify_with_vision", mock_classify)

    result = agent_book.find_story_start("testbook")
    data = json.loads(result)
    # Page 1 and 4 were cached. Probe hits page 4 (cached story), then
    # back-validation walks: page 3 (vision call), page 2 (vision call),
    # page 1 (cached title, stop). So first_story = 2, 2 new vision calls.
    assert call_count == 2  # pages 3 and 2 needed vision calls
    assert data["first_story_page"] == 2
