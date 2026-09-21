"""Quality gate before the editor sees the digest: length, sensitive politics,
relevance, and whether each link really lands where it says.

    python3 -m lf.quality <customer> <send_date> [--workers 8] [--limit N]

Reads digest_raw.md (which news IDs made the digest) and candidates_boards.json (all
board posts). Fetches every page once and writes:
    quality.json        per-item verdicts, display_title (the title as shown on the article page) + title_source
    quality.md          exclusion list + warnings for the editor
    digest_checked.md   digest_raw.md with news titles replaced by display_title and a verdict appended
Rules live in sources.yaml → quality: (min_body_chars, sensitive_strong, sensitive_weak).
"""
import argparse
import datetime as dt
import difflib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
import urllib3

from lf.common import UA, customer_dir, issue_dir, load_yaml

DEFAULT = {
    "min_body_chars": 500,
    # In the title → exclude. Politics, prosecution, scandal.
    "sensitive_strong": ["탄핵", "대통령", "여당", "야당", "국민의힘", "민주당", "혁신당", "개혁신당", "총선", "대선", "지방선거", "공천", "당대표",
                         "특검", "검찰", "수사", "구속", "기소", "압수수색", "비리", "횡령", "뇌물", "직권남용", "내란", "친일", "종북", "고발", "고소"],
    # In the title → warn (editor decides). Conflict framing.
    "sensitive_weak": ["갈등", "반발", "논란", "규탄", "시위", "집회", "파업", "의혹", "폭로", "질타", "지적", "촉구", "비판", "무산", "표류", "특혜"],
}
TOPIC = re.compile(r"도시재생|원도심|마을|협동조합|사회적경제|사회연대|농촌|농어촌|어촌|소멸|상권|골목|전통시장|로컬|노후|공동체|빈집|기본소득|중간지원")
OFFPAGE = re.compile(r"login|signin|member|/main\.do|/index\.(do|jsp|html)$|error|notfound|404", re.I)
ITEM = re.compile(r"^- (?:★ |대안 )?(N\d+|B\d+-\d+) \|.*?\]\((https?://[^)\s]+)\)")
ITEM_LINK = re.compile(r"\) \[(.*)\]\((https?://[^)\s]+)\)")  # the "[title](url)" of a digest item line
META = re.compile(r"<meta\s[^>]*>", re.I)
META_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
MEDIA_HEAD = re.compile(r"^[\[【≪《]([^\]】≫》]{1,25})[\]】≫》]\s*")
TAIL_SEP = re.compile(r"\s+(?:-|–|—|\||::|<)\s+")
MEDIA_WORD = re.compile(r"뉴스|일보|신문|방송|타임[즈스]|저널|투데이|데일리|미디어|닷컴|경제|TV|News|Times|Daily|Post|기사본문", re.I)


def norm(text):
    return re.sub(r"[^\w가-힣]", "", text or "")


def unescape(text):
    """html.unescape, twice when the page double-escaped ("&amp;ldquo;" — seen on ddaily.co.kr)."""
    text = html.unescape(text)
    return html.unescape(text) if re.search(r"&#?\w+;", text) else text


def meta_content(raw, name):
    """content of <meta property=NAME> or <meta name=NAME>: any attribute order, either quote style."""
    for tag in META.finditer(raw):
        attrs = {k.lower(): dq or sq for k, dq, sq in META_ATTR.findall(tag.group(0))}
        if (attrs.get("property") or attrs.get("name") or "").lower() == name and attrs.get("content", "").strip():
            return unescape(attrs["content"]).strip()
    return ""


def page_title(raw):
    """(title, source): og:title, then twitter:title, then <title>. source is og | twitter | title | ''."""
    for name, source in (("og:title", "og"), ("twitter:title", "twitter")):
        title = meta_content(raw, name)
        if title:
            return title, source
    m = HTML_TITLE.search(raw)
    title = unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    return title, ("title" if title else "")


def site_name_of(raw):
    """og:site_name, else the outlet tail that og:title carries and <title> lacks (or the reverse)."""
    site = meta_content(raw, "og:site_name")
    if site:
        return site
    m = HTML_TITLE.search(raw)
    titles = [meta_content(raw, "og:title"), unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""]
    for longer, shorter in (titles, titles[::-1]):
        extra = longer[len(shorter):] if shorter and longer.startswith(shorter) else ""
        if TAIL_SEP.match(extra):
            return TAIL_SEP.split(extra)[-1].strip()
    return ""


def is_media(text, site="", host=""):
    """Does this short piece name the outlet? Matches og:site_name, the host's ASCII name, or an outlet word."""
    text = text.strip()
    if not text or len(text) > 25:
        return False
    if site and (norm(text) in norm(site) or norm(site) in norm(text)):
        return True
    ascii_part = re.sub(r"[^a-z0-9]", "", text.lower())
    if len(ascii_part) >= 3 and ascii_part in host.lower():
        return True
    return bool(MEDIA_WORD.search(text))


def strip_media(title, site="", host=""):
    """Remove the outlet from a page title: '[매체] ' heads and ' - 매체' / ' < 섹션 < 기사본문 - 매체' tails.
    Only a tail that names the outlet (or 기사본문) is cut, so a ' - ' inside the headline survives."""
    title = title.strip()
    m = MEDIA_HEAD.match(title)
    if m and is_media(m.group(1), site, host):
        title = title[m.end():]
    while True:
        seps = list(TAIL_SEP.finditer(title))
        if not seps:
            break
        last = seps[-1]
        tail = title[last.end():]
        if tail.strip() != "기사본문" and not is_media(tail, site, host):
            break
        title = title[:last.start()]
        if last.group(0).strip() == "<":  # '< 섹션 < 기사본문': the whole chain is navigation
            title = TAIL_SEP.split(title)[0] if " < " in title else title
    return title.strip()


def choose_title(api_title, page, site="", host=""):
    """The title the reader sees on the article page, or the API title when the page gives nothing usable.

    page: (title, source) from page_title(). Returns (display_title, title_source, warnings)."""
    api_clean = api_title[:-3].rstrip() if api_title.endswith("...") else api_title
    raw_title, source = page
    cleaned = strip_media(raw_title, site, host) if raw_title else ""
    a, b = norm(cleaned), norm(api_clean)
    usable = cleaned and not is_media(cleaned, site, host) and len(a) >= 0.6 * len(b)
    if not usable:
        warnings = ["원제목 확인 못 함 — 기사 페이지에서 제목 확인"] if api_title.endswith("...") else []
        return api_title, "api", warnings
    warnings = []
    if not a.startswith(b) and difflib.SequenceMatcher(None, a, b).ratio() < 0.6:
        warnings.append(f"페이지 제목이 다름 — 다른 기사로 연결됐을 수 있음: {cleaned[:40]}")
    return cleaned, source, warnings


BODY_BLOCKS = re.compile(
    r"<(article|main)[^>]*>(.*?)</\1>|"
    r"<(div|section)[^>]*(?:itemprop=[\"']articleBody[\"']|id=[\"']article-view-content-div[\"']|id=[\"']articleBody[\"']|"
    r"class=[\"'][^\"']*(?:article-body|article_body|articleBody|news_body|view-content|article-view|content-body|se-main-container)[^\"']*[\"'])[^>]*>(.*?)</\3>",
    re.S | re.I)


def page_text(raw):
    """(body text, exact) — exact is False when no article block was found and
    the whole page (menus included) had to be used, so a 'short' verdict is not reliable."""
    raw = re.sub(r"<(script|style|noscript|header|footer|nav)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)

    def clean(chunk):
        return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", chunk))).strip()

    blocks = [clean(m.group(2) or m.group(4) or "") for m in BODY_BLOCKS.finditer(raw)]
    best = max(blocks, key=len) if blocks else ""
    if len(best) >= 300:
        return best, True
    return clean(raw), False


def fetch(item):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    out = {"id": item["id"], "url": item["url"], "kind": item["kind"], "final_url": item["url"], "status": None, "hops": 0, "body_chars": 0,
           "page_title": "", "page_title_source": "", "site_name": ""}
    try:
        r = requests.get(item["url"], headers=UA, timeout=20, allow_redirects=True, verify=False)
        out.update(final_url=r.url, status=r.status_code, hops=len(r.history))
        if r.status_code < 400:
            r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
            (out["page_title"], out["page_title_source"]), out["site_name"] = page_title(r.text), site_name_of(r.text)
            text, out["exact"] = page_text(r.text)
            out["body_chars"] = len(text)
            out["_text"] = text[:20000]
    except requests.RequestException as exc:
        out["error"] = exc.__class__.__name__
    return out


def judge(item, page, rules):
    """Return (verdict, reasons). verdict: ok | warn | exclude."""
    reasons, verdict = [], "ok"
    title = item["title"]

    def bump(level, why):
        nonlocal verdict
        reasons.append(why)
        if level == "exclude" or (level == "warn" and verdict == "ok"):
            verdict = level if level == "exclude" or verdict != "exclude" else verdict

    # 1. link really lands
    if page.get("error"):
        bump("exclude", f"링크 실패 {page['error']}")
    elif page["status"] and page["status"] >= 400:
        bump("warn" if page["status"] in (401, 403, 405, 429) else "exclude", f"HTTP {page['status']}" + (" 직접 확인" if page["status"] in (401, 403, 405, 429) else ""))
    else:
        src, dst = urlparse(item["url"]), urlparse(page["final_url"])
        if src.netloc.replace("www.", "") != dst.netloc.replace("www.", "") and dst.netloc.replace("www.", "") not in src.netloc:
            bump("warn", f"다른 사이트로 리다이렉트 → {dst.netloc}")
        elif page["hops"] and OFFPAGE.search(dst.path + "?" + dst.query):
            bump("exclude", f"게시글이 아닌 페이지로 리다이렉트 → {page['final_url'][:70]}")
        elif page["hops"] and dst.path.rstrip("/") in ("", "/") :
            bump("exclude", "첫 화면으로 리다이렉트")
    # 2. sensitive politics (title strong → exclude; title weak → warn; body many strong → warn)
    strong = [w for w in rules["sensitive_strong"] if w in title]
    weak = [w for w in rules["sensitive_weak"] if w in title]
    if strong:
        bump("exclude", "정치·수사 민감어(제목): " + ", ".join(strong))
    if weak:
        bump("warn", "갈등·비판 표현(제목): " + ", ".join(weak))
    text = page.get("_text", "")
    if text:
        body_strong = {w for w in rules["sensitive_strong"] if text.count(w) >= 2}
        if len(body_strong) >= 2:
            bump("warn", "본문에 정치·수사 민감어: " + ", ".join(sorted(body_strong)))
    if item["kind"] == "news":
        # 3. length
        if text and page.get("exact") and page["body_chars"] < rules["min_body_chars"]:
            bump("warn", f"본문 짧음 {page['body_chars']}자 (단신)")
        # 4. relevance: a core keyword in the title, or in the body at least twice, or a topic word in the title
        kws = item.get("keywords") or []
        in_title = [k for k in kws if norm(k) in norm(title)]
        in_body = [k for k in kws if text and (k in text or k.replace(" ", "") in text)]
        topic_body = TOPIC.search(text) if text else None
        if in_title or TOPIC.search(title):
            pass
        elif in_body or topic_body:
            bump("warn", "핵심어가 본문에만 있음: " + ", ".join(in_body[:3] or [topic_body.group(0)]))
        else:
            bump("exclude" if text and page.get("exact") else "warn", "관련성 낮음 (핵심어가 제목·본문에 없음)")
    return verdict, reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="테스트용: 앞의 N건만")
    args = parser.parse_args()

    cdir = customer_dir(args.customer)
    folder = issue_dir(args.customer, args.send_date)
    rules = {**DEFAULT, **(load_yaml(cdir / "sources.yaml").get("quality") or {})}

    news = {it["id"]: it for it in json.loads((folder / "candidates_news.json").read_text(encoding="utf-8"))["items"]}
    boards = json.loads((folder / "candidates_boards.json").read_text(encoding="utf-8"))["boards"] if (folder / "candidates_boards.json").exists() else []
    posts = {p["id"]: {**p, "kind": "board", "board": b["board"]} for b in boards for p in b.get("posts", []) if (p.get("url") or "").startswith("http")}

    digest_lines = (folder / "digest_raw.md").read_text(encoding="utf-8").splitlines()
    wanted = {}
    for line in digest_lines:
        m = ITEM.match(line)
        if m and m.group(1) in news:
            wanted[m.group(1)] = news[m.group(1)]
    items = list(wanted.values()) + list(posts.values())
    if args.limit:
        items = items[:args.limit]
    print(f"검사 대상: 뉴스 {len(wanted)}건 + 게시글 {len(posts)}건 → 페이지 열기 ({args.workers}개 동시)")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pages = {p["id"]: p for p in pool.map(fetch, items)}

    results, counts = {}, {"ok": 0, "warn": 0, "exclude": 0}
    for it in items:
        p = pages[it["id"]]
        verdict, reasons = judge(it, p, rules)
        display, source = it["title"], "board"
        if it["kind"] == "news":
            display, source, notes = choose_title(it["title"], (p["page_title"], p["page_title_source"]), p["site_name"], urlparse(p["final_url"]).netloc)
            reasons += notes
            if notes and verdict == "ok":
                verdict = "warn"
        counts[verdict] += 1
        results[it["id"]] = {"verdict": verdict, "reasons": reasons, "title": it["title"], "display_title": display, "title_source": source,
                             "url": it["url"], "final_url": p["final_url"], "status": p["status"], "body_chars": p["body_chars"],
                             "page_title": p["page_title"], "kind": it["kind"]}
    (folder / "quality.json").write_text(json.dumps({"checked_at": dt.datetime.now().isoformat(timespec="seconds"), "rules": rules, "counts": counts, "items": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    mark = {"ok": "✓", "warn": "⚠", "exclude": "✖"}
    out = []
    for line in digest_lines:
        m = ITEM.match(line)
        if m and m.group(1) in results:
            r = results[m.group(1)]
            if r["kind"] == "news" and r["display_title"] != r["title"]:
                line = ITEM_LINK.sub(lambda lm: f") [{r['display_title']}]({lm.group(2)})", line, count=1)
            line += f"  {mark[r['verdict']]}" + (" " + "; ".join(r["reasons"]) if r["reasons"] else "")
        out.append(line)
    (folder / "digest_checked.md").write_text("\n".join(out), encoding="utf-8")

    md = [f"# 품질 검사 — {args.send_date} (뉴스 {len(wanted)} + 게시글 {len(posts)}) · ✓{counts['ok']} ⚠{counts['warn']} ✖{counts['exclude']}\n",
          "## ✖ 제외 권고 (다이제스트에 올리지 않는다)\n"]
    md += [f"- {i} | {r['title'][:60]} — {'; '.join(r['reasons'])}" for i, r in results.items() if r["verdict"] == "exclude"] or ["- 없음"]
    md += ["\n## ⚠ 주의 (올리되 표시한다)\n"]
    md += [f"- {i} | {r['title'][:60]} — {'; '.join(r['reasons'])}" for i, r in results.items() if r["verdict"] == "warn"] or ["- 없음"]
    md += ["\n## 게시글 링크 검사\n"]
    for b in boards:
        ids = [p["id"] for p in b.get("posts", []) if p["id"] in results]
        bad = [i for i in ids if results[i]["verdict"] != "ok"]
        md.append(f"- {b['board']}: {len(ids)}건 열어 봄, 문제 {len(bad)}건" + (f" ({', '.join(bad[:6])})" if bad else ""))
    from_page = sum(1 for r in results.values() if r["kind"] == "news" and r["title_source"] != "api")
    from_api = [r for r in results.values() if r["kind"] == "news" and r["title_source"] == "api"]
    unresolved = sum(1 for r in from_api if r["title"].endswith("..."))
    md.append(f"\n제목 출처 — 페이지 {from_page} · API {len(from_api)} (그중 원제목 확인 못 함 {unresolved})")
    (folder / "quality.md").write_text("\n".join(md), encoding="utf-8")
    print(f"✓ {counts['ok']} · ⚠ {counts['warn']} · ✖ {counts['exclude']} -> {folder / 'quality.md'}, digest_checked.md")


if __name__ == "__main__":
    main()
