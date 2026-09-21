"""dosirak layout: section-specific wrappers in Vol.20 order; other templates stay byte-identical. No network."""
from pathlib import Path

import pytest

from lf.render import render_letter, split_front_matter
from lf.stibee import embed_images, forbidden, strip_document

FIXTURES = Path(__file__).parent / "fixtures"
META, BODY = split_front_matter((FIXTURES / "regression_draft.md").read_text(encoding="utf-8"))
PROFILE = {
    "org_name": "(주)공공도시", "brand": {"color": "#C8512B", "logo_url": ""},
    "sections": [{"key": "greeting", "title": "인사말"}, {"key": "own_news", "title": "📰 공공도시 소식"}, {"key": "news", "title": "📊 업계 동향"},
                 {"key": "opinion", "title": "💭 오늘의 생각 한 술"}, {"key": "notices", "title": "📢 정책·공모 알림"}],
    "design": {"logo_url": "https://i.kr/logo.png", "slogan_url": "https://i.kr/slogan.png", "skyline_url": "https://i.kr/sky.png",
               "leaf_url": "https://i.kr/leaf.png", "dove_url": "https://i.kr/dove.png", "tagline_url": "https://i.kr/tag.png", "org_logo_url": "https://i.kr/org.png"},
    "footer": {"cta_lines": ["부담스러운 정책 변화, 막막한 실무", "공공도시가 최고의 길을 함께 고민하겠습니다."],
               "cta": {"text": "문의하기", "url": "https://00dosi.co.kr"},
               "orgs": [{"name": "주식회사 공공도시", "address": "서울"}], "contact": {"h": "https://00dosi.co.kr", "e": "c@00dosi.co.kr", "p": "02"},
               "submit": {"text": "소식이 있으신가요?", "button": "담기", "url": "https://x.kr"},
               "sns": [{"icon": "https://i.kr/f.png", "url": "https://fb.com"}]},
}


@pytest.fixture(scope="module")
def letter():
    html, warnings = render_letter(PROFILE, META, BODY, "dosirak", issue_no=21)
    assert warnings == []
    return html


def ascii(text):
    """The renderer writes pure ASCII: Korean becomes decimal character references."""
    return text.encode("ascii", "xmlcharrefreplace").decode("ascii")


def positions(html, markers):
    found = [html.find(m) for m in markers]
    assert all(p >= 0 for p in found), [m for m, p in zip(markers, found) if p < 0]
    return found


def test_sections_and_separators_come_in_vol20_order(letter):
    order = [
        ascii("이 메일이 잘 안보이시나요?"),
        'src="https://i.kr/logo.png"', "Vol. 21",
        'src="https://i.kr/sky.png"', "&lt; " + ascii("인사말") + " &gt;",
        'src="https://i.kr/leaf.png"',                                                  # 잎
        "text-align:center;text-decoration:underline;",                                 # own_news 제목
        'data-lf="card"', "border-top:1px dotted #747579;border-bottom:1px dotted #747579",  # 카드, 이중 점선
        'src="https://i.kr/dove.png"', 'src="https://i.kr/tag.png"',                    # 비둘기 + 글자 이미지
        "background:#f2f3f5;padding:10px 20px;",                                        # news 회색 띠
        "border:3px solid #d6dbe4;", "width:145px;margin:14px auto;border-top:1px solid #747579",  # 흰 박스, 축 사이 짧은 선
        "border-top:1px dotted #747579;height:0;",                                      # opinion 뒤 점선
        "display:inline-block;background:#f2f3f5;padding:2px 10px;font-weight:700",     # notices 소분류 하이라이트
        'src="https://i.kr/org.png"', "$%unsubscribe%$", 'src="https://i.kr/f.png"',
    ]
    assert positions(letter, order) == sorted(positions(letter, order))


def test_own_news_has_two_groups_and_cards_use_300px_image(letter):
    assert letter.count("text-align:center;text-decoration:underline;") == 2
    assert letter.count('data-lf="card"') == 2
    assert 'width="300" data-lf="card"' in letter and "max-width:300px" in letter
    assert "@media" not in letter and "<style" not in letter and "class=" not in letter  # no media query: Stibee strips <style>
    assert "border:3px solid #f2f3f5;padding:0;text-align:center;" in letter and "padding:12px 16px 0;text-align:left;" in letter
    assert letter.count("border-top:1px dotted #747579;border-bottom:1px dotted #747579") == 1


def test_list_items_carry_font_and_article_links_are_black_without_underline(letter):
    li_styles = [s for s in letter.split("<li style=\"")[1:]]
    assert li_styles and all("font-family:AppleSDGothic" in s.split('"')[0] for s in li_styles)
    assert '<a href="https://n.kr/1" style="color:#000000;text-decoration:none;">' in letter
    assert '<a href="https://blog.naver.com/00dosi/1" style="color:#0000ff;font-weight:700;text-decoration:none;">' in letter


def test_stibee_merge_tags_are_fixed_in_the_template_and_kept_from_the_draft(letter):
    assert '<a href="$%permalink%$"' in letter
    assert letter.count('<a href="$%unsubscribe%$"') == 2 and ascii("수신거부") in letter and "Unsubscribe" in letter
    body = BODY.replace("담당자 님, 안녕하세요.", "안녕하세요 $%name%$ 님,")
    html, _ = render_letter({**PROFILE}, {**META, "title": "도시락 레터 $%name%$"}, body, "dosirak", issue_no=21)
    assert "$%name%$ " + ascii("님") + "," in html and "<title>" + ascii("도시락 레터") + " $%name%$</title>" in html


def test_stibee_package_has_no_forbidden_tags(letter):
    packed, embedded, kept = embed_images(strip_document(letter), fetch=lambda url: (_ for _ in ()).throw(ConnectionError("offline")))
    assert forbidden(packed) == []
    assert packed.startswith("<span") and packed.endswith("</table>")
    assert "$%permalink%$" in packed and "$%unsubscribe%$" in packed and 'data-lf="card"' in packed
    assert forbidden('<table><tr><td onclick="x()"><style>a{}</style><form></form></td></tr></table>') == ["스티비 금지 태그 <form> 1개", "스티비 금지 태그 <style> 1개", "이벤트 속성(onclick 등) 1개"]


def test_unknown_section_falls_back_to_generic_block():
    html, _ = render_letter(PROFILE, META, "## 기타 코너\n\n문단.\n", "dosirak", issue_no=21)
    assert "<h2 style=" in html and ascii("기타 코너") in html


@pytest.mark.parametrize("name", ["warm", "modern", "public", "colorful"])
def test_other_templates_are_byte_identical_to_before(name):
    profile = {"org_name": "(주)공공도시", "brand": {"color": "#C8512B", "logo_url": ""}}
    html, warnings = render_letter(profile, META, BODY, name)
    assert warnings == []
    assert html == (FIXTURES / f"regression_{name}.html").read_text(encoding="ascii")
