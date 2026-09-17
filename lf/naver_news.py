"""Collect news and opinion candidates from the Naver Search API.

    python3 -m lf.naver_news <customer> <send_date>

Reads customers/<customer>/sources.yaml (news_keywords, opinion_keywords,
exclude_words, window_days) and writes issues/<send_date>/candidates_news.json.
"""
import argparse
import datetime as dt
import email.utils
import json
import re
import time
from urllib.parse import urlparse

import requests

from lf.common import customer_dir, issue_dir, load_env, load_yaml, strip_tags

API = "https://openapi.naver.com/v1/search/news.json"


def search(query, env, since, max_pages=3):
    """Newest-first pages of 100 until a page reaches back before `since`.

    A busy keyword ("골목형상점가") gets 30 stories in a few days, so a single
    page would miss most of a two-week window.
    """
    items = []
    for page in range(max_pages):
        response = requests.get(
            API,
            params={"query": query, "display": 100, "start": page * 100 + 1, "sort": "date"},
            headers={
                "X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
                "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"],
            },
            timeout=15,
        )
        response.raise_for_status()
        batch = response.json().get("items", [])
        items += batch
        if not batch:
            break
        oldest = min(email.utils.parsedate_to_datetime(i["pubDate"]).date() for i in batch)
        if oldest < since:
            break
        time.sleep(0.2)
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--since", help="수집 시작일 YYYY-MM-DD (기본: 발송일 - window_days)")
    args = parser.parse_args()

    env = load_env()
    sources = load_yaml(customer_dir(args.customer) / "sources.yaml")
    send = dt.date.fromisoformat(args.send_date)
    since = dt.date.fromisoformat(args.since) if args.since else send - dt.timedelta(days=sources.get("window_days", 14))
    exclude = sources.get("exclude_words") or []

    queries = [("news", k) for k in sources.get("news_keywords") or []]
    queries += [("opinion", k) for k in sources.get("opinion_keywords") or []]

    found, errors, off_topic = {}, [], 0
    for kind, keyword in queries:
        try:
            items = search(keyword, env, since)
        except requests.RequestException as exc:
            errors.append({"keyword": keyword, "error": str(exc)})
            continue
        for item in items:
            published = email.utils.parsedate_to_datetime(item["pubDate"]).date()
            title = strip_tags(item["title"])
            if published < since or any(word in title for word in exclude):
                continue
            # Naver splits compound words, so "혁신지구" also returns stories that only
            # mention "지구". Keep a story only if every word of the query appears in it.
            text = re.sub(r"\s", "", title + strip_tags(item["description"]))
            if not all(re.sub(r"\s", "", word) in text for word in keyword.split()):
                off_topic += 1
                continue
            key = re.sub(r"\W", "", title)
            if key in found:
                found[key]["keywords"].append(keyword)
                continue
            url = item.get("originallink") or item["link"]
            found[key] = {
                "kind": kind,
                "title": title,
                "url": url,
                "host": urlparse(url).netloc.removeprefix("www."),
                "published": published.isoformat(),
                "summary": strip_tags(item["description"]),
                "keywords": [keyword],
            }
        time.sleep(0.2)

    items = sorted(found.values(), key=lambda x: x["published"], reverse=True)
    for number, item in enumerate(items, 1):
        item["id"] = f"N{number}"

    out = issue_dir(args.customer, args.send_date) / "candidates_news.json"
    out.write_text(
        json.dumps(
            {
                "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
                "since": since.isoformat(),
                "queries": [k for _, k in queries],
                "errors": errors,
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"뉴스 후보 {len(items)}건 (검색어 {len(queries)}개, {since} 이후, 검색어 불일치 {off_topic}건 제외) -> {out}")
    for error in errors:
        print(f"  실패: {error['keyword']} — {error['error']}")


if __name__ == "__main__":
    main()
