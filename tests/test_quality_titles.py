"""Titles in the digest must be what the reader sees on the article page. No network: HTML strings only."""
from lf.quality import choose_title, page_title, site_name_of, strip_media

API_DAMYANG = "담양군, '국비 지원율 50% 상향'... 2027년 기본소득 공모 총력 대응"
API_MOLIT = "국토부, '27년 도시재생 신규사업 공모…설명회는 17일 대전서"


def test_og_title_keeps_single_quotes_inside_double_quoted_content():
    raw = f'<html><head><meta property="og:title" content="{API_DAMYANG}"></head></html>'
    assert page_title(raw) == (API_DAMYANG, "og")


def test_og_title_single_quoted_content_before_property():
    raw = """<meta content='괴산군 "농어촌기본소득" 유치 총력' property='og:title'>"""
    assert page_title(raw) == ('괴산군 "농어촌기본소득" 유치 총력', "og")


def test_fallback_html_title_then_h1():
    assert page_title('<meta name="twitter:title" content="트위터 제목"><title>문서 제목</title>') == ("문서 제목", "title")
    assert page_title("<title>\n  문서 제목 &amp; 부제  </title>") == ("문서 제목 & 부제", "title")
    assert page_title("<p>no title</p>") == ("", "")


def test_h1_used_when_og_title_and_title_are_missing():
    raw = '<html><body><header><h1 class="tit">[충북일보] 괴산군 <em>\'농어촌기본소득\'</em> 유치 총력</h1></header><p>본문</p></body></html>'
    title, source = page_title(raw)
    assert (title, source) == ("[충북일보] 괴산군 \'농어촌기본소득\' 유치 총력", "h1")
    assert strip_media(title) == "괴산군 \'농어촌기본소득\' 유치 총력"
    display, title_source, warnings = choose_title("괴산군 '농어촌기본소득' 유치 총력", (title, source))
    assert (display, title_source, warnings) == ("괴산군 \'농어촌기본소득\' 유치 총력", "h1", [])


def test_double_escaped_entities_are_decoded():
    raw = '<meta property="og:title" content="&amp;ldquo;서울역 옆&amp;rdquo;&amp;hellip;정비" />'
    assert page_title(raw)[0] == "“서울역 옆”…정비"


def test_media_head_is_removed():
    assert strip_media("[충북일보] 괴산군 '농어촌기본소득' 유치 총력") == "괴산군 '농어촌기본소득' 유치 총력"
    assert strip_media("≪브레이크뉴스≫ 고양시, 소규모주택 정비사업 공공지원 문턱 낮춘다") == "고양시, 소규모주택 정비사업 공공지원 문턱 낮춘다"
    assert strip_media("[김포 소식]사회연대경제 아카데미 수강생 모집 등") == "[김포 소식]사회연대경제 아카데미 수강생 모집 등"


def test_media_tail_is_removed():
    assert strip_media("새마을금고중앙회, ‘2026년 하반기 WM 워크숍’ 개최 - 여성소비자신문") == "새마을금고중앙회, ‘2026년 하반기 WM 워크숍’ 개최"
    assert strip_media("부산시, 협력센터 'K-OceanX' 개소 < 부산 < 전국 < 기사본문 - 국제뉴스", site="국제뉴스") == "부산시, 협력센터 'K-OceanX' 개소"
    assert strip_media("제주시 원도심에 ‘김만덕복합센터’ 16일 개관 - 제주의소리", site="제주의소리") == "제주시 원도심에 ‘김만덕복합센터’ 16일 개관"
    assert strip_media("국토부, 2027년 신규사업 공모 확대 - ㅍㅍㅅㅅ PPSS", host="ppss.kr") == "국토부, 2027년 신규사업 공모 확대"


def test_dash_inside_headline_survives_only_media_tail_cut():
    assert strip_media("도시재생 - 주민이 주인이다 - 한겨레", site="한겨레") == "도시재생 - 주민이 주인이다"


def test_site_name_only_page_title_falls_back_to_api():
    display, source, warnings = choose_title(API_MOLIT, ("TJB 티제이비", "og"), site="TJB", host="tjb.co.kr")
    assert (display, source) == (API_MOLIT, "api")
    assert warnings == []


def test_truncated_api_title_without_page_title_is_flagged():
    display, source, warnings = choose_title("진주시, 성북지구 도시재생 본격화…'유스호스텔' 개관 준...", ("", ""))
    assert source == "api" and warnings == ["원제목 확인 못 함 — 기사 페이지에서 제목 확인"]


def test_page_title_extending_api_title_is_used_without_warning():
    api, page = "OO시 도시재생 뉴딜 3단계 착수…", "OO시 도시재생 뉴딜 3단계 착수…주민협의체 구성 완료"
    assert choose_title(api, (page, "og")) == (page, "og", [])


def test_truncated_api_title_resolved_from_page():
    api, page = "담양군, '국비 지원율 50% 상향'... 2027년 기본소득 공모 총...", "담양군, ‘국비 지원율 50% 상향’... 2027년 기본소득 공모 총력 대응 - 담양뉴스"
    display, source, warnings = choose_title(api, (page, "og"))
    assert display == "담양군, ‘국비 지원율 50% 상향’... 2027년 기본소득 공모 총력 대응"
    assert (source, warnings) == ("og", [])


def test_unrelated_page_title_warns():
    display, source, warnings = choose_title("OO군 마을관리협동조합 출범", ("△△시 버스노선 개편 안내", "og"))
    assert source == "og" and display == "△△시 버스노선 개편 안내"
    assert warnings == ["페이지 제목이 다름 — 다른 기사로 연결됐을 수 있음: △△시 버스노선 개편 안내"]


def test_cut_page_title_falls_back_to_api():
    # og:title shorter than 60% of the API title (a page that itself truncates) is not trusted
    display, source, _ = choose_title("완도군, '1인당 연 180만 원'... 농어촌 기본소득 공모 총력", ("완도군,", "og"))
    assert (display, source) == ("완도군, '1인당 연 180만 원'... 농어촌 기본소득 공모 총력", "api")


def test_site_name_from_og_site_name_or_title_difference():
    assert site_name_of('<meta property="og:site_name" content="국제뉴스"><title>x - 국제뉴스</title>') == "국제뉴스"
    raw = """<meta property="og:title" content="[이달의 기자상] 끝나지 않은 세금잔치 '어촌뉴딜' - 한국기자협회" /><title>[이달의 기자상] 끝나지 않은 세금잔치 '어촌뉴딜'</title>"""
    assert site_name_of(raw) == "한국기자협회"
    assert strip_media("[이달의 기자상] 끝나지 않은 세금잔치 '어촌뉴딜' - 한국기자협회", site=site_name_of(raw)) == "[이달의 기자상] 끝나지 않은 세금잔치 '어촌뉴딜'"
    assert site_name_of('<meta property="og:title" content="제목"><title>제목 < 부산 < 전국 < 기사본문 - 국제뉴스</title>') == "국제뉴스"
    assert site_name_of("<title>제목</title>") == ""
