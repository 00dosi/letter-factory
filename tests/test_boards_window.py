"""Old and closed board posts (2017~2025 results in 광역 고시공고 searches) are dropped; open ones stay."""
from lf.boards import outside_window

SINCE, CUTOFF = "2026-09-14", "2026-09-29"


def post(*dates):
    return {"title": "x", "dates": list(dates)}


def test_old_posts_are_dropped():
    kept, dropped = outside_window([post("2017-03-02"), post("2025-08-01", "2025-08-20"), post("2026-09-16")], SINCE, CUTOFF)
    assert dropped == 2 and kept == [post("2026-09-16")]


def test_old_posting_with_open_deadline_is_kept():
    kept, dropped = outside_window([post("2026-06-01", "2026-12-31"), post("2026-06-01", "2026-09-30")], SINCE, CUTOFF)
    assert dropped == 0 and len(kept) == 2


def test_single_date_is_the_posting_date():
    kept, dropped = outside_window([post("2026-09-10"), post("2026-09-14")], SINCE, CUTOFF)
    assert dropped == 1 and kept == [post("2026-09-14")]
