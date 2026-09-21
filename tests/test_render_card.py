""":::card blocks render as two fluid columns; stibee pack embeds card images; checks flags a missing title. No network."""
import io

from PIL import Image

from lf.checks import check_data_images, check_front_matter
from lf.render import Style, blocks
from lf.stibee import embed_images, external_images

STYLE = Style("warm", {})
CARD = """## 📣 공공도시 소식

:::card
[![대표 이미지](https://postfiles.pstatic.net/a.jpg?type=w773)](https://blog.naver.com/00dosi/224408245713)
소개문 첫 단락.

소개문 둘째 단락 (**굵게** 가능).
👉 ['국내외 상권활성화 정책 동향 편' 보러가기](https://blog.naver.com/00dosi/224408245713)
:::
"""


def render(body):
    return "".join(blocks(body, STYLE))


def test_card_has_image_column_text_column_and_mso_table():
    out = render(CARD)
    assert out.count('<div style="display:inline-block;width:100%;max-width:240px;') == 1
    assert out.count('<div style="display:inline-block;width:100%;max-width:276px;') == 1
    assert '<!--[if mso]><table role="presentation"' in out and '<td width="240" valign="top">' in out and '<td width="276" valign="top">' in out
    assert '<a href="https://blog.naver.com/00dosi/224408245713"><img src="https://postfiles.pstatic.net/a.jpg?type=w773" alt="대표 이미지" width="240" data-lf="card"' in out
    assert "border:0;" in out.split("data-lf")[1].split(">")[0]


def test_card_paragraphs_split_on_blank_line_and_lines_join_with_br():
    out = render(CARD)
    text_column = out.split("max-width:276px")[1]
    assert text_column.count("<p ") == 2
    assert "<strong>굵게</strong>" in text_column
    assert "가능).<br>👉 <a href=" in text_column


def test_card_without_image_has_text_column_only():
    out = render(":::card\n한 줄짜리 배너 문구.\n:::\n")
    assert "max-width:276px" in out and "max-width:240px" not in out and "[if mso]" not in out and "<img" not in out


def test_syntax_outside_cards_is_unchanged():
    body = "## 코너\n\n### 소제목\n\n- [제목](https://a.kr) — 매체\n- 둘째\n\n> 강조\n\n![alt](https://img.kr/a.jpg)\n\n문단 하나\n둘째 줄\n"
    before = render(body)
    after = render(body + "\n:::card\n카드\n:::\n")
    assert after.startswith(before[:-len("</td></tr>")])
    assert '<h2 style=' in before and '<h3 style=' in before and before.count("<li ") == 2 and '<p style="' + STYLE.css("callout") in before
    assert 'width="600"' in before and "<p " in before and "문단 하나 둘째 줄" in before


def png_bytes(width=1000, height=1000):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buf, "PNG")
    return buf.getvalue()


LETTER = ('<p>x</p><img src="https://postfiles.pstatic.net/a.jpg" alt="a" width="240" data-lf="card" style="s">'
          '<img src="https://postfiles.pstatic.net/b.jpg?type=w773" alt="b" width="240" data-lf="card" style="s">'
          '<img src="https://logo.kr/l.png" alt="logo">')


def test_pack_default_keeps_external_urls_and_adds_naver_type():
    out, count = external_images(LETTER)
    assert count == 2 and "data:image" not in out
    assert 'src="https://postfiles.pstatic.net/a.jpg?type=w773"' in out and 'src="https://postfiles.pstatic.net/b.jpg?type=w773"' in out
    assert 'src="https://logo.kr/l.png"' in out


def test_pack_embeds_card_images_as_jpeg_data_uri(capsys):
    out, embedded, kept = embed_images(LETTER, fetch=lambda url: png_bytes())
    assert (embedded, kept) == (2, 0)
    assert out.count('<img src="data:image/jpeg;base64,') == 2 and 'src="https://logo.kr/l.png"' in out
    data = out.split('src="data:image/jpeg;base64,')[1].split('"')[0]
    import base64
    image = Image.open(io.BytesIO(base64.b64decode(data)))
    assert image.format == "JPEG" and image.width == 480


def test_pack_keeps_url_and_warns_when_download_fails(capsys):
    def fetch(url):
        if "b.jpg" in url:
            raise ConnectionError("boom")
        return png_bytes()

    out, embedded, kept = embed_images(LETTER, fetch=fetch)
    assert (embedded, kept) == (1, 1)
    assert 'src="https://postfiles.pstatic.net/b.jpg?type=w773"' in out and out.count("data:image/jpeg") == 1
    assert "경고: 이미지 내장 실패, URL 유지" in capsys.readouterr().out


def test_checks_flags_data_image_urls():
    body = "## 코너\n\n![대표 이미지](data:image/jpeg;base64,/9j/4AAQ)\n\n[![대표 이미지](https://img.kr/a.jpg)](https://b.kr)\n"
    assert check_data_images(body) == ["3행: 이미지가 data: URL — Gmail 이 표시하지 않음, 외부 호스팅 주소로 교체"]


def test_checks_flags_missing_front_matter_title():
    assert len(check_front_matter({"issue_label": "Vol. 21"})) == 1
    assert len(check_front_matter({"title": "  "})) == 1
    assert check_front_matter({"title": "도시락 레터"}) == []
