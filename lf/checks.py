"""Check a draft before delivery: links, deadlines, duplicates, banned phrases.

    python3 -m lf.checks <customer> <send_date>

Exit code 1 when something must be fixed. Links that answer 403/429 or fail TLS
are listed as "직접 확인" — many public-sector sites block scripts but open fine
in a browser.
"""
import argparse
import datetime as dt
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

from lf.common import UA, issue_dir
from lf.render import LINK, split_front_matter

DEADLINE = re.compile(r"~\s?(?:(20\d{2})[.\-/])?(\d{1,2})[./\-](\d{1,2})")
BANNED = ["Claude", "클로드", "AI가", "AI 분석", "인공지능이 작성", "!!"]


def link_status(url):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        response = requests.get(url, headers=UA, timeout=15, allow_redirects=True, stream=True, verify=False)
        response.close()
        code = response.status_code
    except requests.RequestException as exc:
        return url, "broken", exc.__class__.__name__
    if code < 400:
        return url, "ok", code
    if code in (401, 403, 405, 429):
        return url, "manual", code
    return url, "broken", code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    args = parser.parse_args()

    folder = issue_dir(args.customer, args.send_date)
    meta, body = split_front_matter((folder / "draft.md").read_text(encoding="utf-8"))
    send = dt.date.fromisoformat(str(meta.get("send_date", args.send_date)))
    cutoff = send + dt.timedelta(days=1)

    problems, manual = [], []
    urls, placed, section = [], [], ""
    for number, line in enumerate(body.splitlines(), 1):
        if line.startswith("## "):
            section = line
        for title, url in LINK.findall(line):
            urls.append(url)
            placed.append((section, url))
            # Naver's API cuts long titles with ASCII "..."; a real headline may end in "…" itself.
            if title.rstrip().endswith("..."):
                problems.append(f"{number}행: 제목이 잘림 (네이버 API 요약 제목) — 기사 페이지의 원제목으로 교체: {title[:40]}")
        for year, month, day in DEADLINE.findall(line):
            year = int(year) if year else (send.year + 1 if int(month) < send.month - 6 else send.year)
            try:
                deadline = dt.date(year, int(month), int(day))
            except ValueError:
                problems.append(f"{number}행: 마감일을 읽을 수 없음 — {line.strip()[:60]}")
                continue
            if deadline < cutoff:
                problems.append(f"{number}행: 마감 {deadline} < 기준일 {cutoff} — 빼야 함")
        for phrase in BANNED:
            if phrase in line:
                problems.append(f"{number}행: 금지 표현 '{phrase}'")

    # The same post may appear once as news and once as a notice; only a repeat inside one section is a mistake.
    duplicates = sorted({u for s, u in placed if placed.count((s, u)) > 1})
    problems += [f"중복 링크 (같은 코너 안): {u}" for u in duplicates]

    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, verdict, detail in pool.map(link_status, sorted(set(urls))):
            if verdict == "broken":
                problems.append(f"깨진 링크 ({detail}): {url}")
            elif verdict == "manual":
                manual.append(f"직접 확인 ({detail}): {url}")

    report = {"links": len(set(urls)), "cutoff": cutoff.isoformat(), "problems": problems, "manual": manual}
    (folder / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"링크 {report['links']}개 · 마감 기준일 {cutoff}")
    for line in problems:
        print(f"  고칠 것: {line}")
    for line in manual:
        print(f"  {line}")
    print("통과" if not problems else f"고칠 것 {len(problems)}건")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
