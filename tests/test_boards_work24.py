"""고용24 unified search rows ("사이트 가기" icon link + title link to the same post, deadline only) and board filters. No network."""
from lf.boards import extract, filter_posts

BASE = "https://www.work24.go.kr/cm/f/c/0100/selectUnifySearch.do"


def work24_li(no, org, title, deadline):
    href = f"/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo={no}&amp;infoTypeCd=VALIDATION&amp;infoTypeGroup="
    return f"""<li><dl class="dl_list">
      <dt><strong>{org}</strong><a href="{href}" class="btn_link" target="_blank"><span class="blind">사이트 가기</span></a></dt>
      <dd><a href="{href}" class="btn_txt">
            {title}
          </a><span class="tbl_label gray">D-9</span><span class="s1_r">({deadline} 마감)</span></dd>
    </dl><div class="vline_group"><span>계약직</span></div></li>"""


PAGE = "<ul class='srch_list_default'>" + "".join([
    work24_li("K172222609150025", "(사)홍성지역협력네트워크", '홍성군 <span class="u_search_point_color">도시재생지원센터</span> 직원 채용 공고', "2026.09.30"),
    work24_li("KJ2167260915", "보령지역자활센터", "보령지역자활센터 사회복지사 채용", "2026.09.21"),
    work24_li("KJBF00260916", "OO병원", "(초)단시간 병원동행 전문가 모집", "2026.09.29"),
]) + "</ul>"


def test_work24_rows_take_real_title_and_absolute_url():
    posts = extract(PAGE, BASE, ["도시재생"])
    assert [p["title"] for p in posts] == ["홍성군 도시재생지원센터 직원 채용 공고", "보령지역자활센터 사회복지사 채용", "(초)단시간 병원동행 전문가 모집"]
    assert posts[0]["url"] == "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K172222609150025&infoTypeCd=VALIDATION&infoTypeGroup="
    assert all(p["url"].startswith("https://www.work24.go.kr/wk/a/b/1500/") for p in posts)
    assert posts[0]["dates"] == ["2026-09-30"] and posts[0]["keyword_hits"] == ["도시재생"]


def test_exclude_drops_matching_posts():
    kept, dropped = filter_posts(extract(PAGE, BASE, []), exclude=["자활", "요양"])
    assert dropped == 1 and [p["title"] for p in kept] == ["홍성군 도시재생지원센터 직원 채용 공고", "(초)단시간 병원동행 전문가 모집"]


def test_require_any_drops_posts_without_any_word():
    kept, dropped = filter_posts(extract(PAGE, BASE, []), require_any=["사회적경제", "도시재생", "지원센터"])
    assert dropped == 2 and [p["title"] for p in kept] == ["홍성군 도시재생지원센터 직원 채용 공고"]


def test_exclude_wins_over_require_any():
    kept, dropped = filter_posts(extract(PAGE, BASE, []), exclude=["자활"], require_any=["자활", "도시재생"])
    assert dropped == 2 and [p["title"] for p in kept] == ["홍성군 도시재생지원센터 직원 채용 공고"]


def test_no_filters_keeps_everything():
    posts = extract(PAGE, BASE, [])
    assert filter_posts(posts) == (posts, 0)


def test_table_rows_with_onclick_and_card_links_still_work():
    table = """<table><tr onclick="viewData(1425)"><td>12</td><td>2026년 마을관리협동조합 설립 지원 공모</td><td>2026.09.10</td></tr></table>"""
    posts = extract(table, "https://x.kr/list.do", [], detail_url="https://x.kr/view.do?id={id}")
    assert [(p["title"], p["url"], p["dates"]) for p in posts] == [("2026년 마을관리협동조합 설립 지원 공모", "https://x.kr/view.do?id=1425", ["2026-09-10"])]
    card = """<div><a class="card" href="/notice/77"><ul><li>도시재생 뉴딜 주민공모 안내</li><li>2026-09-12</li></ul></a></div>"""
    posts = extract(card, "https://y.kr/board", [])
    assert [(p["title"], p["url"]) for p in posts] == [("도시재생 뉴딜 주민공모 안내", "https://y.kr/notice/77")]
