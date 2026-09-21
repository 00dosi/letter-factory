"""Fetch each board in sources.yaml and pull out dated post links.

    python3 -m lf.boards <customer> <send_date>

Writes issues/<send_date>/candidates_boards.json and a raw snapshot per board in
issues/<send_date>/boards/. Boards that fail are reported, not retried silently —
the editor fixes the settings or checks that board by hand.

Board settings (sources.yaml → boards[]):
    name, url, category, keywords
    method: get | post              default get
    data: {field: value}            form fields for post; {since}/{until} are filled (YYYYMMDD)
    format: html | json             default html
    json: {list: resultList, title: TITLE, id: BC_IDX, dates: [WRITE_DATE]}
    detail_url: ...{id}...          build post links from a JS call or a JSON id
    detail_id_pattern: regex        which number in the JS call is the post id (group 1); a group 2 fills {id2}
    warmup: url                     open this page first (cookies) before the real request
    copy_hidden: [FIELD]            copy these hidden form values from the warmup page into data
    title_cell: n                   for clickable rows without links: which table cell (1-based) is the title
    exclude: [word, ...]            drop a post when its title or row text contains any of these
    require_any: [word, ...]        drop a post unless its title or row text contains at least one of these
    manual: "reason"                skip collecting; the editor checks this board by hand
"""
import argparse
import datetime as dt
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
import urllib3

from lf.common import UA, customer_dir, issue_dir, load_yaml

DATE = re.compile(r"(20\d{2})\s?[.\-/년]\s?(\d{1,2})\s?[.\-/월]\s?(\d{1,2})")
ROW_TAGS = {"tr", "li", "article", "dl"}
NOT_TITLE = re.compile(r"^\s*(D\s*-\s*\d+|상세보기|더보기|새글|NEW|첨부파일.*|사이트 가기|바로가기|사이트 이동|홈페이지 가기)\s*$", re.I)
TITLE_PREFIX = re.compile(r"^(?:D\s*-\s*\d+|새글|NEW)\s+", re.I)  # labels glued in front of titles


class RowParser(HTMLParser):
    """Collects rows (table rows, list items) and card links (<a> wrapping a whole item)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.stack, self.link, self.card, self.cell = [], [], None, None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and not self.stack and self.card is None:
            # A link that wraps the whole item, e.g. <a class="card" href=...><ul><li>title…
            self.card = {"href": attrs.get("href") or "", "onclick": attrs.get("onclick") or "", "chunks": []}
            return
        if tag in ROW_TAGS:
            self.stack.append({"text": [], "links": [], "onclick": attrs.get("onclick") or "", "cells": []})
        elif tag in ("td", "th") and self.stack:
            self.cell = []
        elif tag == "a" and self.stack:
            self.link = {"href": attrs.get("href") or "", "onclick": attrs.get("onclick") or "", "text": []}

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None and self.stack:
            self.link["text"] = " ".join("".join(self.link["text"]).split())
            self.stack[-1]["links"].append(self.link)
            self.link = None
        elif tag in ("td", "th") and self.cell is not None and self.stack:
            self.stack[-1]["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag in ROW_TAGS and self.stack:
            row = self.stack.pop()
            text = " ".join(" ".join(row["text"]).split())
            if self.stack:
                self.stack[-1]["text"].append(text)
            elif self.card is not None:
                self.card["chunks"].append(text)
            self.rows.append((text, row["links"], row["onclick"], row["cells"]))
        elif tag == "a" and self.card is not None and not self.stack:
            chunks = [c for c in self.card["chunks"] if c]
            title = next((c for c in chunks if len(c) >= 6 and not NOT_TITLE.match(c)), "")
            link = {"href": self.card["href"], "onclick": self.card["onclick"], "text": title}
            self.rows.append((" ".join(chunks), [link], "", []))
            self.card = None

    def handle_data(self, data):
        if self.stack:
            self.stack[-1]["text"].append(data)
        elif self.card is not None and data.strip():
            self.card["chunks"].append(" ".join(data.split()))
        if self.cell is not None:
            self.cell.append(data)
        if self.link is not None:
            self.link["text"].append(data)


def fetch(url, method="get", data=None, session=None, referer=None):
    http = session or requests
    # Search URLs carry Korean words; headers must be ASCII, so percent-encode both.
    url = requests.utils.requote_uri(url)
    kwargs = {"headers": {**UA, "Referer": requests.utils.requote_uri(referer or url)}, "timeout": 20}
    if method == "post":
        kwargs["data"] = data or {}
    try:
        response = http.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = http.request(method, url, verify=False, **kwargs)
    if response.encoding in (None, "ISO-8859-1"):
        response.encoding = response.apparent_encoding
    return response


def resolve_js(js_link, detail_url, id_pattern=None):
    """Turn javascript:goDetail(1437) into a real URL using the board's detail_url pattern.

    id_pattern picks the post number when the link holds several numbers,
    e.g. "list_no=(\\d+)" for LH links that also contain mid=a10601010000.
    """
    if not detail_url or not js_link:
        return None
    id2 = ""
    if id_pattern:
        match = re.search(id_pattern, js_link)
        post_id = match.group(1) if match else None
        if match and match.lastindex and match.lastindex >= 2:
            id2 = match.group(2)  # second value the detail page needs, e.g. viewData('47728','P') → gosiGbn
    else:
        numbers = re.findall(r"-?\d+", js_link)
        post_id = numbers[0] if numbers else None
    if not post_id or post_id.startswith("-"):
        return None
    return detail_url.format(id=post_id, id2=id2)


def dates_in(text):
    return sorted({f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in DATE.findall(text)})


def extract(page, base, keywords, detail_url=None, id_pattern=None, title_cell=None):
    parser = RowParser()
    parser.feed(page)
    posts, seen = [], set()
    for text, links, row_onclick, cells in parser.rows:
        dates = dates_in(text)
        if not dates:
            continue
        if not links and row_onclick:
            # Whole row is clickable (<tr onclick="viewData(...)">) and the title is plain cell text.
            if title_cell and len(cells) >= title_cell:
                title = cells[title_cell - 1]
            else:
                titles = [c for c in cells if len(c) >= 6 and not DATE.fullmatch(c.strip()) and not NOT_TITLE.match(c)]
                title = max(titles, key=len) if titles else ""
            if title:
                links = [{"text": title, "href": "", "onclick": row_onclick}]
        # One row may link the same post several times (an icon "사이트 가기" plus the title): keep the longest title per URL.
        candidates = {}
        for link in links:
            title, href = TITLE_PREFIX.sub("", link["text"]), link["href"]
            if len(title) < 6 or NOT_TITLE.match(title):
                continue
            real_href = href and not href.startswith(("javascript", "#"))
            url = urljoin(base, href) if real_href else None
            # Links like href="#view" often rely on an onclick on the link or on the row itself.
            js_link = None if url else (link["onclick"] or (href if href.startswith("javascript") else "") or row_onclick)
            url = url or resolve_js(js_link, detail_url, id_pattern)
            key = url or (title, js_link)
            if key not in candidates or len(title) > len(candidates[key][0]):
                candidates[key] = (title, url, js_link)
        for key, (title, url, js_link) in candidates.items():
            if key in seen or (title, dates[0]) in seen:
                continue
            seen.update({key, (title, dates[0])})
            posts.append(
                {
                    "title": title,
                    "url": url,
                    "js_link": js_link or None,
                    "dates": dates,
                    "keyword_hits": [k for k in keywords if k in text],
                    "row_text": text[:240],
                }
            )
    return posts


def filter_posts(posts, exclude=None, require_any=None):
    """Board-level noise filter on title + row text. Returns (kept posts, number dropped)."""
    kept = []
    for post in posts:
        blob = post["title"] + " " + (post.get("row_text") or "")
        if any(w in blob for w in exclude or []):
            continue
        if require_any and not any(w in blob for w in require_any):
            continue
        kept.append(post)
    return kept, len(posts) - len(kept)


def extract_json(payload, fields, keywords, detail_url=None):
    items = payload
    for key in (fields.get("list") or "").split("."):
        if key:
            items = items.get(key, []) if isinstance(items, dict) else []
    posts = []
    for item in items or []:
        title = " ".join(str(item.get(fields.get("title"), "")).split())
        if not title:
            continue
        dates = sorted({d for f in fields.get("dates") or [] for d in dates_in(str(item.get(f, "")))})
        post_id = str(item.get(fields.get("id"), "") or "")
        blob = " ".join(str(v) for v in item.values())
        posts.append(
            {
                "title": title,
                "url": detail_url.format(id=post_id) if detail_url and post_id else None,
                "js_link": None,
                "dates": dates,
                "keyword_hits": [k for k in keywords if k in blob],
                "row_text": title[:240],
            }
        )
    return posts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    args = parser.parse_args()

    sources = load_yaml(customer_dir(args.customer) / "sources.yaml")
    folder = issue_dir(args.customer, args.send_date)
    (folder / "boards").mkdir(exist_ok=True)
    send = dt.date.fromisoformat(args.send_date)
    window = {
        "{since}": (send - dt.timedelta(days=sources.get("window_days", 14))).strftime("%Y%m%d"),
        "{until}": send.strftime("%Y%m%d"),
    }

    def fill(value):
        for placeholder, date in window.items():  # search URLs and form fields may carry the issue's date window
            value = value.replace(placeholder, date)
        return value

    results = []
    for number, board in enumerate(sources.get("boards") or [], 1):
        url = fill(board["url"])
        method = board.get("method", "get")
        data = {k: fill(str(v)) for k, v in (board.get("data") or {}).items()}
        entry = {"board": board["name"], "url": url, "category": board.get("category")}
        if board.get("manual"):
            entry.update(status="manual", note=board["manual"], posts=[])
            results.append(entry)
            print(f"  [manual] {board['name']}: {board['manual']}")
            continue
        try:
            session, referer = requests.Session(), None
            if board.get("warmup"):
                # Some boards only answer a POST after their search page has set a cookie and a hidden token.
                referer = fill(board["warmup"])
                warm = fetch(referer, session=session)
                for field in board.get("copy_hidden") or []:
                    found = re.search(rf'name="{re.escape(field)}"[^>]*value="([^"]*)"', warm.text)
                    if found:
                        data[field] = found.group(1)
            response = fetch(url, method, data, session=session, referer=referer)
            entry["http_status"] = response.status_code
            suffix = "json" if board.get("format") == "json" else "html"
            (folder / "boards" / f"{number:02d}.{suffix}").write_text(response.text, encoding="utf-8")
            keywords = board.get("keywords") or []
            if board.get("format") == "json":
                posts = extract_json(response.json(), board.get("json") or {}, keywords, board.get("detail_url"))
            else:
                posts = extract(
                    response.text, response.url, keywords,
                    board.get("detail_url"), board.get("detail_id_pattern"), board.get("title_cell"),
                )
            posts, entry["filtered_out"] = filter_posts(posts, board.get("exclude"), board.get("require_any"))
            for index, post in enumerate(posts, 1):
                post["id"] = f"B{number}-{index}"
            entry["posts"] = posts
            # Filtered down to nothing is still a good answer, so "ok" + filtered_out, not no_posts_found.
            found = posts or entry["filtered_out"]
            entry["status"] = "ok" if response.ok and found else ("no_posts_found" if response.ok else "http_error")
        except (requests.RequestException, ValueError) as exc:
            entry.update(status="fetch_failed", error=str(exc), posts=[])
        results.append(entry)
        dropped = f" (필터 제외 {entry['filtered_out']}건)" if entry.get("filtered_out") else ""
        print(f"  [{entry['status']}] {board['name']}: 게시글 {len(entry['posts'])}건{dropped}")

    out = folder / "candidates_boards.json"
    out.write_text(
        json.dumps(
            {"collected_at": dt.datetime.now().isoformat(timespec="seconds"), "boards": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"게시판 {len(results)}곳 -> {out}")


if __name__ == "__main__":
    main()
