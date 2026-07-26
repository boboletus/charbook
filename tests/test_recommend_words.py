import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from recommend_words import parse_freq_table, parse_fluency, recommend, _is_cjk

FREQ_CSV = """rank,char_trad,char_simp,count
1,的,,19612774
2,是,,10906495
3,一,,9206925
4,不,,8654427
5,我,,7184509
6,有,,5943526
7,個,个,5420669
8,這,这,4660570
9,人,,4629727
10,在,,4378562
"""

BOOK_JSON = {
    "book": "testbook",
    "base": "assets/testbook",
    "priority": "一不人",
    "priority_trad": "一不人",
    "pages": [
        {"page": 1, "chars": "我是一个人", "chars_trad": "我是一個人"},
        {"page": 2, "chars": "这个很好", "chars_trad": "這個很好"},
        {"page": 3, "chars": "的有的在", "chars_trad": "的有的在"},
    ],
}


def _write_freq_csv(tmp_path):
    freq_file = tmp_path / "freq_table.csv"
    freq_file.write_text(FREQ_CSV, encoding="utf-8")
    return freq_file


def test_parse_freq_table(tmp_path):
    freq_file = _write_freq_csv(tmp_path)
    freq = parse_freq_table(freq_file, max_rank=10)
    assert freq["的"][0] == 1
    assert freq["是"][0] == 2
    assert freq["个"][0] == 7
    assert freq["这"][0] == 8
    assert freq["個"][0] == 7  # traditional form is also indexed
    assert len(freq) == 12  # 10 trad + 2 extra simp (个, 这)


def test_parse_freq_table_max_rank(tmp_path):
    freq_file = _write_freq_csv(tmp_path)
    freq = parse_freq_table(freq_file, max_rank=5)
    assert "的" in freq
    assert "是" in freq
    assert "我" in freq
    assert "个" not in freq  # rank 7 > 5
    assert "这" not in freq


def test_parse_freq_table_real_file():
    freq_file = Path(__file__).resolve().parent.parent / "scripts" / "freq_table.csv"
    freq = parse_freq_table(freq_file, max_rank=1000)
    assert freq["的"][0] == 1
    assert freq["是"][0] == 2
    assert len(freq) > 1000  # both trad and simp forms indexed


def test_recommend_basic():
    freq = parse_freq_table(Path("/dev/null"))  # empty
    # manually build freq table
    freq = {
        "的": (1, 19612774, "的"),
        "是": (2, 10906495, "是"),
        "一": (3, 9206925, "一"),
        "不": (4, 8654427, "不"),
        "我": (5, 7184509, "我"),
        "有": (6, 5943526, "有"),
        "个": (7, 5420669, "個"),
        "这": (8, 4660570, "這"),
        "人": (9, 4629727, "人"),
        "在": (10, 4378562, "在"),
    }
    results, total, not_learnt, in_top = recommend(BOOK_JSON, freq, top=3)
    # priority = "一不人", so these are excluded
    # book chars: 我 是 一 个 人 这 很 好 的 有 在
    # not learnt: 我 是 个 这 很 好 的 有 在 (一 and 人 and 不 excluded)
    # ranked: 的(1) 是(2) 我(5) 有(6) 个(7) 这(8) 在(10)  [很 and 好 not in freq]
    assert results[0][0] == 1  # 的
    assert results[0][1] == "的"
    assert results[1][0] == 2  # 是
    assert results[1][1] == "是"
    assert results[2][0] == 5  # 我
    assert results[2][1] == "我"
    assert len(results) == 3


def test_recommend_all():
    freq = {
        "的": (1, 19612774, "的"),
        "是": (2, 10906495, "是"),
        "我": (5, 7184509, "我"),
        "个": (7, 5420669, "個"),
        "这": (8, 4660570, "這"),
        "在": (10, 4378562, "在"),
    }
    results, total, not_learnt, in_top = recommend(BOOK_JSON, freq, top=3, show_all=True)
    # 很 and 好 are not in freq, so only 6 candidates
    assert len(results) == 6
    assert results[0][1] == "的"
    assert results[-1][1] == "在"


def test_recommend_no_candidates():
    freq = {}
    results, total, not_learnt, in_top = recommend(BOOK_JSON, freq, top=3)
    assert results == []


def test_recommend_pages():
    freq = {
        "我": (5, 7184509, "我"),
    }
    results, total, not_learnt, in_top = recommend(BOOK_JSON, freq, top=3)
    assert len(results) == 1
    assert results[0][1] == "我"
    assert results[0][4] == [1]  # appears on page 1


def test_is_cjk():
    assert _is_cjk("的")
    assert _is_cjk("我")
    assert not _is_cjk("，")
    assert not _is_cjk("。")
    assert not _is_cjk("T")
    assert not _is_cjk(" ")


def test_parse_fluency(tmp_path):
    fluency_file = tmp_path / "fluency.txt"
    fluency_file.write_text("一\n大\n小\n\n 了 \n", encoding="utf-8")
    known = parse_fluency(fluency_file)
    assert known == {"一", "大", "小", "了"}


def test_parse_fluency_missing_file():
    known = parse_fluency(Path("/nonexistent/fluency.txt"))
    assert known == set()


def test_recommend_with_known_chars():
    freq = {
        "的": (1, 19612774, "的"),
        "是": (2, 10906495, "是"),
        "我": (5, 7184509, "我"),
        "有": (6, 5943526, "有"),
        "个": (7, 5420669, "個"),
        "这": (8, 4660570, "這"),
        "人": (9, 4629727, "人"),
        "在": (10, 4378562, "在"),
    }
    # priority = "一不人"; pre-known adds 是 and 的
    known = {"是", "的"}
    results, total, not_learnt, in_top = recommend(
        BOOK_JSON, freq, top=3, known_chars=known
    )
    # 是 and 的 are now excluded along with 一 and 人
    recommended_chars = [r[1] for r in results]
    assert "是" not in recommended_chars
    assert "的" not in recommended_chars
    assert results[0][1] == "我"  # next highest freq after exclusions
