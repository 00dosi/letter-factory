"""testmail reads both click-tracking links (real sends) and plain URLs (test sends). No network."""
import base64

from lf.stibee import mail_links

EXPECTED = ["https://blog.naver.com/00dosi/224408245713", "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K1&infoTypeCd=VALIDATION", "http://www.gnmaeil.com/news/articleView.html?idxno=594851"]


def tracked(url):
    return "https://event.stibee.com/v2/click/MTAwMDAvMTAwMDAvMQ/" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def test_tracking_links_only():
    text = "\n".join(f'<a href="{tracked(u)}">글</a>' for u in EXPECTED)
    found = mail_links(text)
    assert [u for u in EXPECTED if u not in found] == []


def test_plain_hrefs_and_bare_urls_only():
    text = ('<a href="https://blog.naver.com/00dosi/224408245713">보러가기</a>\n'
            '<a href="https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K1&amp;infoTypeCd=VALIDATION">채용</a>\n'
            "링크: http://www.gnmaeil.com/news/articleView.html?idxno=594851.\n"
            '<a href="$%unsubscribe%$">수신거부</a> <a href="https://stibee.com/error/preview">미리보기</a>')
    found = mail_links(text)
    assert [u for u in EXPECTED if u not in found] == []
    assert not any("$%" in u or "error/preview" in u for u in found)


def test_mixed_input():
    text = f'<a href="{tracked(EXPECTED[0])}">a</a> <a href="{EXPECTED[1].replace("&", "&amp;")}">b</a> {EXPECTED[2]}'
    found = mail_links(text)
    assert [u for u in EXPECTED if u not in found] == []
    assert not any("event.stibee.com" in u for u in found)
