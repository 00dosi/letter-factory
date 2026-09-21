"""legacy_tls boards get the lowered-security adapter; the 소진공 list page (card links) extracts cleanly. No network."""
from pathlib import Path

from requests.adapters import HTTPAdapter

from lf.boards import LegacyTLSAdapter, extract, make_session

FIXTURE = Path(__file__).parent / "fixtures" / "semas_list.html"
URL = "https://www.semas.or.kr/web/board/webBoardList.kmdc?bCd=2001&pNm=BOA0101"


def test_legacy_adapter_only_for_legacy_tls_boards():
    assert isinstance(make_session({"legacy_tls": True}).get_adapter("https://x.kr/"), LegacyTLSAdapter)
    plain = make_session({"name": "x"}).get_adapter("https://x.kr/")
    assert isinstance(plain, HTTPAdapter) and not isinstance(plain, LegacyTLSAdapter)


def test_legacy_adapter_builds_lowered_context():
    import ssl

    context = LegacyTLSAdapter().poolmanager.connection_pool_kw["ssl_context"]
    assert context.get_ciphers()
    assert context.options & getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0) == getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)


def test_semas_cards_extract_title_link_and_dates():
    posts = extract(FIXTURE.read_text(encoding="utf-8"), URL, ["소공인"])
    assert len(posts) == 5
    titles = [p["title"] for p in posts]
    assert titles[0] == "2026년 패션 메이커허브 소공인 코워킹스페이스 입주기업 추가모집 공고"
    assert titles[3] == "2026년 프랜차이즈 수준평가 심사원 모집 공고"  # "신청마감" label stripped
    assert not any(t.startswith(("D - ", "신청마감", "상세보기")) for t in titles)
    assert [p["url"] for p in posts] == [f"https://www.sbiz24.kr/#/pbanc/{n}" for n in (829, 826, 825, 824, 823)]
    assert all(p["js_link"] is None for p in posts)
    assert posts[0]["dates"] == ["2026-09-09", "2026-09-14", "2026-09-28"]  # 공고문 날짜 + 신청기간 시작·끝
    assert posts[0]["keyword_hits"] == ["소공인"]
