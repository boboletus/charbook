import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def make_book_json(tmp_path, chars_by_page):
    pages = []
    for n, chars in chars_by_page:
        pages.append({"page": n, "chars": chars})
    data = {"book": "testbook", "base": "assets/testbook", "pages": pages}
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return data


def run_segment(tmp_path, name="testbook", extra_args=None):
    import subprocess, sys
    args = [sys.executable, "scripts/segment_phrases.py", name,
            "--pages_dir", str(tmp_path)]
    if extra_args:
        args += extra_args
    subprocess.run(args, check=True, capture_output=True)
    return json.loads((tmp_path / "book.json").read_text("utf-8"))


def test_segments_pages(tmp_path):
    make_book_json(tmp_path, [(1, "独角兽妹妹"), (2, "小猪看电视")])
    data = run_segment(tmp_path)
    for p in data["pages"]:
        phrases = p["phrases"]
        assert isinstance(phrases, list)
        assert "".join(phrases) == p["chars"]


def test_preserves_existing_phrases(tmp_path):
    make_book_json(tmp_path, [(1, "独角兽妹妹")])
    data = run_segment(tmp_path)
    original = data["pages"][0]["phrases"]
    # Overwrite with manual edit
    data["pages"][0]["phrases"] = ["独角兽", "妹妹"]
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_segment(tmp_path)
    assert data2["pages"][0]["phrases"] == ["独角兽", "妹妹"]


def test_reset_overwrites(tmp_path):
    make_book_json(tmp_path, [(1, "独角兽妹妹")])
    data = run_segment(tmp_path)
    data["pages"][0]["phrases"] = ["WRONG"]
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_segment(tmp_path, extra_args=["--reset"])
    assert "".join(data2["pages"][0]["phrases"]) == "独角兽妹妹"
    assert data2["pages"][0]["phrases"] != ["WRONG"]


def test_empty_chars(tmp_path):
    make_book_json(tmp_path, [(1, ""), (2, "你好")])
    data = run_segment(tmp_path)
    assert data["pages"][0]["phrases"] == []
    assert "".join(data["pages"][1]["phrases"]) == "你好"


def test_punctuation_kept(tmp_path):
    make_book_json(tmp_path, [(1, "你好。")])
    data = run_segment(tmp_path)
    assert "".join(data["pages"][0]["phrases"]) == "你好。"


def test_particle_de_merged(tmp_path):
    make_book_json(tmp_path, [(1, "她的外面的小猪")])
    data = run_segment(tmp_path)
    phrases = data["pages"][0]["phrases"]
    # "的" should merge with preceding word, not stand alone
    assert "的" not in phrases
    joined = "".join(phrases)
    assert joined == "她的外面的小猪"
    # Should have merged phrases like "她的", "外面的"
    assert any(p.endswith("的") for p in phrases)


def test_particle_zhe_merged(tmp_path):
    make_book_json(tmp_path, [(1, "嗑着瓜子")])
    data = run_segment(tmp_path)
    phrases = data["pages"][0]["phrases"]
    assert "着" not in phrases
    assert "".join(phrases) == "嗑着瓜子"
    assert any(p.endswith("着") for p in phrases)


def test_particle_le_merged(tmp_path):
    make_book_json(tmp_path, [(1, "闯了进来")])
    data = run_segment(tmp_path)
    phrases = data["pages"][0]["phrases"]
    assert "了" not in phrases
    assert "".join(phrases) == "闯了进来"


def test_particle_di_merged(tmp_path):
    make_book_json(tmp_path, [(1, "蹦蹦跳跳地闯")])
    data = run_segment(tmp_path)
    phrases = data["pages"][0]["phrases"]
    assert "地" not in phrases
    assert "".join(phrases) == "蹦蹦跳跳地闯"


# --- Location suffix merging (flag 'f': 上/下/中/里) ---

def test_location_shang_merged():
    from segment_phrases import segment
    phrases = segment("陆地上")
    assert "上" not in phrases
    assert phrases == ["陆地上"]


def test_location_zhong_merged():
    from segment_phrases import segment
    phrases = segment("家族中")
    assert "中" not in phrases
    assert phrases == ["家族中"]


def test_location_li_merged():
    from segment_phrases import segment
    phrases = segment("海里")
    assert "里" not in phrases
    assert phrases == ["海里"]


def test_location_in_sentence():
    from segment_phrases import segment
    phrases = segment("不管是在陆地上")
    assert "陆地上" in phrases
    assert "".join(phrases) == "不管是在陆地上"


# --- Custom dictionary support ---

def test_custom_words_keeps_compound():
    from segment_phrases import segment
    # Without custom word, "独角章" gets split
    phrases_no_custom = segment("我是独角章")
    assert "独角章" not in phrases_no_custom
    # With custom word, it stays whole
    phrases_custom = segment("我是独角章", custom_words="独角章")
    assert "独角章" in phrases_custom


def test_custom_words_cotton_candy():
    from segment_phrases import segment
    phrases = segment("棉花糖的蓝色", custom_words="棉花糖")
    assert "棉花糖的" in phrases
    assert "".join(phrases) == "棉花糖的蓝色"


def test_custom_words_multiple():
    from segment_phrases import segment
    phrases = segment("独角章喜欢棉花糖", custom_words="独角章 棉花糖")
    assert "独角章" in phrases
    assert "棉花糖" in phrases


def test_custom_words_in_book_json(tmp_path):
    """segment_phrases.py should load custom_words from book.json."""
    pages = [{"page": 1, "chars": "我是独角章"}]
    data = {"book": "test", "base": "assets/test", "pages": pages, "custom_words": "独角章"}
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    run_segment(tmp_path)
    data2 = json.loads((tmp_path / "book.json").read_text("utf-8"))
    assert "独角章" in data2["pages"][0]["phrases"]
