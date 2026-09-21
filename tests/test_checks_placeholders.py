"""Leftover placeholders in draft.md ([마감 확인] etc.) must fail lf.checks. No network: check_placeholders is pure."""
from lf.checks import check_placeholders


def test_deadline_placeholder_after_link_is_problem():
    problems, manual = check_placeholders("(지역) [공고 제목](https://a.kr) ~[마감 확인]")
    assert problems == ["1행: 미완성 표시 '[마감 확인]' — 채우거나 지워야 함"]
    assert manual == []


def test_region_placeholder_is_problem():
    problems, manual = check_placeholders("(부산) [공고 제목](https://a.kr) ~10/12 [지역 확인]")
    assert len(problems) == 1 and "[지역 확인]" in problems[0]
    assert manual == []


def test_nested_brackets_inside_link_title_are_ignored():
    assert check_placeholders("(이로운넷) [[기고]경로당의 밥이 달라져야 합니다](https://b.kr) · 최준 사무국장") == ([], [])


def test_link_title_with_angle_bracket_is_ignored():
    assert check_placeholders("(전남일보) [기고·문애준〉지워진 경계선, 남아 있는 격차](https://c.kr)") == ([], [])


def test_image_line_is_ignored():
    assert check_placeholders("![대표 이미지](https://img.kr/a.jpg)") == ([], [])


def test_other_bracket_is_manual_not_problem():
    problems, manual = check_placeholders("이번 호는 [특집] 입니다")
    assert problems == []
    assert manual == ["1행: 링크가 아닌 대괄호 '[특집]' — 의도한 것인지 확인"]


def test_empty_bracket_is_problem():
    problems, manual = check_placeholders("[ ]")
    assert len(problems) == 1 and manual == []


def test_line_numbers_follow_body_lines():
    body = "## 코너\n\n(지역) [제목](https://a.kr) ~[마감 확인]\n[TODO]"
    problems, _ = check_placeholders(body)
    assert [p.split("행")[0] for p in problems] == ["3", "4"]


def test_merge_tag_links_and_title_are_not_flagged():
    from lf.checks import check_front_matter

    assert check_placeholders("[수신거부]($%unsubscribe%$) · 안녕하세요 $%name%$ 님") == ([], [])
    assert check_front_matter({"title": "도시락 레터 $%name%$"}) == []
