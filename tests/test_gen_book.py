import json
from pathlib import Path

import pytest


def make_page_images(tmp_path, pages):
    for n in pages:
        (tmp_path / f"page{n}.jpg").write_bytes(b"")


def run_gen_book(tmp_path, name="testbook", extra_args=None):
    import subprocess, sys
    args = [sys.executable, "scripts/gen_book.py", name,
            "--pages_dir", str(tmp_path),
            "--base", f"assets/{name}"]
    if extra_args:
        args += extra_args
    subprocess.run(args, check=True, capture_output=True)
    return json.loads((tmp_path / "book.json").read_text("utf-8"))


def test_create_new(tmp_path):
    make_page_images(tmp_path, [1, 2, 3])
    data = run_gen_book(tmp_path)
    assert data["book"] == "testbook"
    assert data["base"] == "assets/testbook"
    assert data["priority"] == ""
    assert len(data["pages"]) == 3
    assert [p["page"] for p in data["pages"]] == [1, 2, 3]
    for p in data["pages"]:
        assert p["chars"] == ""
        assert p["chars_trad"] == ""


def test_reconcile_preserves_chars(tmp_path):
    make_page_images(tmp_path, [1, 2])
    data = run_gen_book(tmp_path)
    data["pages"][0]["chars"] = "你好"
    data["pages"][0]["chars_trad"] = "你好"
    data["priority"] = "你"
    data["priority_trad"] = "你"
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_gen_book(tmp_path)
    assert data2["pages"][0]["chars"] == "你好"
    assert data2["pages"][0]["chars_trad"] == "你好"
    assert data2["priority"] == "你"
    assert data2["priority_trad"] == "你"


def test_reset_wipes_chars(tmp_path):
    make_page_images(tmp_path, [1])
    data = run_gen_book(tmp_path)
    data["pages"][0]["chars"] = "你好"
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    data2 = run_gen_book(tmp_path, extra_args=["--reset"])
    assert data2["pages"][0]["chars"] == ""
    assert data2["priority"] == ""


def test_new_pages_added(tmp_path):
    make_page_images(tmp_path, [1, 2])
    data = run_gen_book(tmp_path)
    data["pages"][0]["chars"] = "你好"
    (tmp_path / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    make_page_images(tmp_path, [1, 2, 3])
    data2 = run_gen_book(tmp_path)
    assert len(data2["pages"]) == 3
    assert data2["pages"][0]["chars"] == "你好"
    assert data2["pages"][2]["chars"] == ""
