import json
from pathlib import Path

import pytest


def make_book_json(tmp_path, chars_by_page, priority="小一不人了的"):
    pages = []
    for n, chars in chars_by_page:
        entry = {"page": n, "chars": chars}
        pages.append(entry)
    data = {"book": "testbook", "base": "assets/testbook",
            "priority": priority, "pages": pages}
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return data


def run_convert_dual(tmp_path, name="testbook", extra_args=None):
    import subprocess, sys
    args = [sys.executable, "scripts/convert_dual.py", name,
            "--pages_dir", str(tmp_path)]
    if extra_args:
        args += extra_args
    subprocess.run(args, check=True, capture_output=True)
    return json.loads((tmp_path / "book.json").read_text("utf-8"))


def test_adds_traditional_fields(tmp_path):
    make_book_json(tmp_path, [(1, "哪一个很奇怪"), (2, "我们是一对")])
    data = run_convert_dual(tmp_path)
    assert data["priority_trad"] == "小一不人了的"
    assert data["pages"][0]["chars_trad"] == "哪一個很奇怪"
    assert data["pages"][1]["chars_trad"] == "我們是一對"


def test_preserves_existing_traditional(tmp_path):
    make_book_json(tmp_path, [(1, "哪一个很奇怪")])
    data = run_convert_dual(tmp_path)
    original_trad = data["pages"][0]["chars_trad"]
    data["pages"][0]["chars"] = "另一个很奇怪"
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_convert_dual(tmp_path)
    assert data2["pages"][0]["chars_trad"] == original_trad


def test_reset_trad_reconverts(tmp_path):
    make_book_json(tmp_path, [(1, "哪一个很奇怪")])
    data = run_convert_dual(tmp_path)
    data["pages"][0]["chars_trad"] = "WRONG"
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_convert_dual(tmp_path, extra_args=["--reset_trad"])
    assert data2["pages"][0]["chars_trad"] == "哪一個很奇怪"


def test_empty_chars_stay_empty(tmp_path):
    make_book_json(tmp_path, [(1, ""), (2, "哪一个")])
    data = run_convert_dual(tmp_path)
    assert data["pages"][0]["chars_trad"] == ""
    assert data["pages"][1]["chars_trad"] == "哪一個"
