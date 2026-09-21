"""Posts from before the collection window: still-open ones stay marked as re-post candidates, closed or year-old ones go."""
from lf.boards import outside_window
from lf.digest import board_section

SINCE, CUTOFF, OLDEST = "2026-09-14", "2026-09-29", "2025-09-28"


def post(*dates, **extra):
    return {"id": "B1-1", "title": "x", "url": "https://b.kr/1", "dates": list(dates), **extra}


def test_old_open_post_is_kept_and_marked():
    kept, counts = outside_window([post("2026-09-11")], SINCE, CUTOFF, OLDEST)
    assert kept == [post("2026-09-11", outside_window=True)]
    assert counts == {"outside": 1, "kept": 1, "expired": 0, "closed": 0}


def test_year_old_post_is_dropped():
    kept, counts = outside_window([post("2017-03-02"), post("2025-08-01", "2025-08-20")], SINCE, CUTOFF, OLDEST)
    assert kept == [] and counts == {"outside": 2, "kept": 0, "expired": 2, "closed": 0}


def test_closed_deadline_before_cutoff_is_dropped():
    kept, counts = outside_window([post("2026-08-24", "2026-09-20")], SINCE, CUTOFF, OLDEST)
    assert kept == [] and counts["closed"] == 1


def test_open_deadline_and_in_window_posts_stay_unmarked_or_marked():
    kept, counts = outside_window([post("2026-09-16"), post("2026-06-01", "2026-12-31")], SINCE, CUTOFF, OLDEST)
    assert kept[0] == post("2026-09-16") and "outside_window" not in kept[0]
    assert kept[1].get("outside_window") is True and counts["kept"] == 1


def test_digest_lists_repost_candidates_under_their_own_heading():
    boards = [{"board": "도시재생 공지", "category": "공모", "posts": [
        {"id": "B1-1", "title": "신규", "url": "https://b.kr/1", "dates": ["2026-09-16"]},
        {"id": "B1-2", "title": "가이드라인", "url": "https://b.kr/2", "dates": ["2026-09-11"], "outside_window": True}]}]
    lines = board_section(boards)
    text = "\n".join(lines)
    main, repost = text.split("### 재게재 후보(수집 기간 전 게시) 1건")
    assert "B1-1 | 09-16" in main and "B1-2" not in main
    assert "- B1-2 | 09-11 | (도시재생 공지) [가이드라인](https://b.kr/2)" in repost
