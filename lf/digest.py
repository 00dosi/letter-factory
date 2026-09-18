"""Group collected news into a digest the editor can read in one sitting.

    python3 -m lf.digest <customer> <send_date>

Reads issues/<send_date>/candidates_news.json, sources.yaml (axes → keywords),
issues/<send_date>/prev_issue_urls.txt (links of the last sent issue, optional) and
customers/<customer>/blog_used_ids.txt (blog posts already used, optional).
Writes issues/<send_date>/digest_raw.md and prints a short summary.

What it does, in order: drop stories the last issue already ran → drop roundup/politics
noise → assign each story to an axis by its matching keywords → group same-story
coverage by title similarity → rank → list opinion pieces (genre word + topic word in
title) → list notice leads → keyword reach check → blog candidates from the RSS feed.
"""
import argparse
import collections
import datetime as dt
import email.utils
import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from lf.common import UA, customer_dir, issue_dir, load_yaml

NOISE = re.compile(r"\[패트롤\]|주요 소식|브리핑|캘린더|공약|임시회|추경|정례회|의원.*(지적|질타|촉구)|분양|아파트|부고|\[인사\]|동정")
GOV = re.compile(r"\.(go|or)\.kr$|korea\.kr$")
GENRE = re.compile(r"\[사설\]|사설\]|칼럼|기고|시론|오피니언|제언|발언대|데스크|기자수첩|논단|시평")
TOPIC = re.compile(r"도시재생|원도심|마을|협동조합|사회적경제|사회연대|농촌|농어촌|어촌|소멸|상권|골목|전통시장|로컬|노후|공동체|빈집|지방|기본소득|지역")
LEAD = re.compile(r"모집|공모|접수|신청|설명회|참가자|참여자|교육생|아카데미")
NOTLEAD = re.compile(r"선정|확정|수상|결과|마감했|성료|개최했|마쳤")


def url_key(url):
    """Comparable form of a URL; None if it is not one (a stray '[' from pasted markdown
    makes urlparse raise 'Invalid IPv6 URL')."""
    try:
        p = urlparse(url)
    except ValueError:
        return None
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith(("utm_", "ref", "sc", "input"))]
    return urlunparse((p.scheme, p.netloc.replace("www.", ""), p.path, "", urlencode(q), ""))


def norm(text):
    return re.sub(r"[^\w가-힣]", "", text)


def bigrams(text):
    t = norm(text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


def blog_candidates(rss_url, used_ids):
    try:
        xml = requests.get(rss_url, headers=UA, timeout=25).text
    except requests.RequestException as exc:
        return [f"- RSS 실패: {exc.__class__.__name__} — 블로그 후보 없음"]
    lines = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:30]:
        title = html.unescape(re.search(r"<title>(.*?)</title>", item, re.S).group(1)).replace("<![CDATA[", "").replace("]]>", "").strip()
        link = re.search(r"<link>(.*?)</link>", item, re.S).group(1).replace("<![CDATA[", "").replace("]]>", "").strip()
        post_id = re.search(r"(\d{10,})", link).group(1)
        day = email.utils.parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", item, re.S).group(1)).date()
        if post_id in used_ids:
            continue
        flag = " ⚠모집글(마감 확인)" if "모집" in title else ""
        lines.append(f"- {day} [{title}](https://blog.naver.com/00dosi/{post_id}){flag}")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--per-axis", type=int, default=22)
    args = parser.parse_args()

    cdir = customer_dir(args.customer)
    folder = issue_dir(args.customer, args.send_date)
    sources = load_yaml(cdir / "sources.yaml")
    profile = load_yaml(cdir / "profile.yaml")
    axes = sources.get("axes") or {}
    kw2axis = {k: a for a, ks in axes.items() for k in ks}
    news_file = json.loads((folder / "candidates_news.json").read_text(encoding="utf-8"))
    news = news_file["items"]

    prev_file = folder / "prev_issue_urls.txt"
    prev = {url_key(l.strip()) for l in prev_file.read_text(encoding="utf-8").splitlines() if l.strip().startswith("http")} if prev_file.exists() else set()
    prev.discard(None)
    used_file = cdir / "blog_used_ids.txt"
    used_ids = set(re.findall(r"\b(\d{12})\b", used_file.read_text(encoding="utf-8"))) if used_file.exists() else set()
    used_ids |= {re.search(r"/(\d+)$", u).group(1) for u in prev if "blog.naver.com/00dosi/" in u and re.search(r"/(\d+)$", u)}

    items, repeated, noisy = [], 0, 0
    for it in news:
        if url_key(it["url"]) in prev:
            repeated += 1
            continue
        if NOISE.search(it["title"]):
            noisy += 1
            continue
        hits = collections.Counter(kw2axis.get(k) for k in it["keywords"] if k in kw2axis)
        it["axis"] = hits.most_common(1)[0][0] if hits else None
        it["core_in_title"] = any(norm(k) in norm(it["title"]) for k in it["keywords"])
        it["tier"] = "1차" if GOV.search(it["host"]) else "2차"
        items.append(it)

    clusters = []
    for it in sorted(items, key=lambda x: (x["tier"] != "1차", x["published"])):
        bg = bigrams(it["title"])
        for c in clusters:
            if c["axis"] == it["axis"] and c["kind"] == it["kind"] and jaccard(bg, c["bg"]) >= 0.3:
                c["members"].append(it)
                break
        else:
            clusters.append({"axis": it["axis"], "kind": it["kind"], "bg": bg, "rep": it, "members": [it]})

    def score(c):
        r = c["rep"]
        return len(c["members"]) * 2 + len(r["keywords"]) + (2 if r["core_in_title"] else 0) + (1 if r["tier"] == "1차" else 0)

    out = [f"# 다이제스트 원자료 — 뉴스 {len(news)}건 → 직전 호 게재 {repeated}건·잡음 {noisy}건 제외 → {len(items)}건 → 묶음 {len(clusters)}개\n"]
    for axis in axes:
        cs = sorted((c for c in clusters if c["axis"] == axis and c["kind"] == "news"), key=score, reverse=True)
        out.append(f"\n## [3] {axis} — 묶음 {len(cs)}개 (기사 {sum(len(c['members']) for c in cs)}건)\n")
        for c in cs[:args.per_axis]:
            r, extra = c["rep"], len(c["members"]) - 1
            out.append(f"- {r['id']} | {r['published'][5:]} | ({r['host']}, {r['tier']}) [{r['title']}]({r['url']})"
                       + (f" 외 {extra}건" if extra else "") + ("" if r["core_in_title"] else " ⚠핵심어 제목에 없음")
                       + f"\n    ↳ {r['summary'][:110]}")

    ops = [c["rep"] for c in clusters if GENRE.search(c["rep"]["title"]) and TOPIC.search(c["rep"]["title"])]
    seen, uniq = set(), []
    for r in sorted(ops, key=lambda x: x["published"], reverse=True):
        key = norm(r["title"])[:25]
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    out.append(f"\n## [4] 사설·칼럼 후보 {len(uniq)}건 (제목에 장르어+주제어)\n")
    for r in uniq[:30]:
        out.append(f"- {r['id']} | {r['published'][5:]} | ({r['host']}) [{r['title']}]({r['url']})\n    ↳ {r['summary'][:110]}")

    leads = sorted((c["rep"] for c in clusters if c["kind"] == "news" and LEAD.search(c["rep"]["title"]) and not NOTLEAD.search(c["rep"]["title"])),
                   key=lambda r: r["published"], reverse=True)
    out.append(f"\n## [5] 뉴스에서 나온 공고 단서 {len(leads)}건 (마감일은 게시판·원문에서 확인)\n")
    for r in leads[:40]:
        out.append(f"- {r['id']} | {r['published'][5:]} | ({r['host']}) [{r['title']}]({r['url']}) · {r['axis']}")

    since = news_file.get("since") or (dt.date.fromisoformat(args.send_date) - dt.timedelta(days=sources.get("window_days", 14))).isoformat()
    out.append(f"\n## 검색어별 건수 · 가장 오래된 게시일 (기간 시작 {since[5:]}보다 늦으면 페이지가 모자란 것)\n")
    cov = collections.defaultdict(list)
    for it in news:
        for k in it["keywords"]:
            cov[k].append(it["published"])
    for k in (sources.get("news_keywords") or []) + (sources.get("opinion_keywords") or []):
        v = cov.get(k, [])
        out.append(f"- {k}: {len(v)}건, 최고 {min(v)[5:] if v else '-'}" + (" ⚠" if v and min(v) > since else ""))

    rss = (profile.get("blog") or {}).get("rss")
    if rss:
        out.append(f"\n## [2] 블로그 후보 (RSS, 이미 실린 {len(used_ids)}편 제외, 최신순)\n")
        out += blog_candidates(rss, used_ids)

    (folder / "digest_raw.md").write_text("\n".join(out), encoding="utf-8")
    print(out[0].lstrip("# "))
    print(f"사설·칼럼 후보 {len(uniq)}건 · 공고 단서 {len(leads)}건 -> {folder / 'digest_raw.md'}")


if __name__ == "__main__":
    main()
