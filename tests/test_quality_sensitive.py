"""sensitive_allow phrases are removed before the political word lists are counted. No network."""
from lf.quality import DEFAULT, judge

RULES = {**DEFAULT, "sensitive_allow": ["대통령상", "대통령 표창"]}
PAGE = {"error": None, "status": 200, "final_url": "https://n.kr/1", "hops": 0, "_text": "", "exact": False, "body_chars": 0}


def sensitive(title):
    verdict, reasons = judge({"id": "N1", "title": title, "url": "https://n.kr/1", "kind": "board"}, PAGE, RULES)
    return verdict, [r for r in reasons if "민감어" in r or "갈등" in r]


def test_award_titles_are_not_political():
    assert sensitive("○○군, 대통령상 수상") == ("ok", [])
    assert sensitive("농촌활력지원센터, 대통령 표창 받아") == ("ok", [])


def test_real_political_title_is_still_excluded():
    verdict, reasons = sensitive("대통령 탄핵 촉구 집회")
    assert verdict == "exclude" and reasons[0].startswith("정치·수사 민감어(제목): 탄핵, 대통령")


def test_allow_list_defaults_to_empty():
    assert DEFAULT["sensitive_allow"] == []
    verdict, _ = judge({"id": "N1", "title": "○○군, 대통령상 수상", "url": "https://n.kr/1", "kind": "board"}, PAGE, DEFAULT)
    assert verdict == "exclude"
