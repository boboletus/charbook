import json
import subprocess
import sys


def run_gen_prize(tmp_path):
    subprocess.run(
        [sys.executable, "scripts/gen_prize.py", "--prize_dir", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    return json.loads((tmp_path / "prize.json").read_text("utf-8"))


def test_lists_svgs_sorted(tmp_path):
    (tmp_path / "b.svg").write_text("<svg/>")
    (tmp_path / "a.svg").write_text("<svg/>")
    data = run_gen_prize(tmp_path)
    assert data["svgs"] == ["a.svg", "b.svg"]


def test_empty_when_no_svgs(tmp_path):
    data = run_gen_prize(tmp_path)
    assert data["svgs"] == []


def test_excludes_non_svg(tmp_path):
    (tmp_path / "unicorn.svg").write_text("<svg/>")
    (tmp_path / "prize.json").write_text("{}")
    (tmp_path / "attribution.json").write_text("{}")
    data = run_gen_prize(tmp_path)
    assert data["svgs"] == ["unicorn.svg"]


def test_rerun_excludes_own_manifest(tmp_path):
    (tmp_path / "unicorn.svg").write_text("<svg/>")
    run_gen_prize(tmp_path)
    data = run_gen_prize(tmp_path)
    assert data["svgs"] == ["unicorn.svg"]
