"""Check a draft before delivery: links, deadlines, duplicates, banned phrases, leftover placeholders.

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
from lf.render import IMAGE, LINK, split_front_matter

DEADLINE = re.compile(r"~\s?(?:(20\d{2})[.\-/])?(\d{1,2})[./\-](\d{1,2})")
BANNED = ["Claude", "클로드", "AI가", "AI 분석", "인공지능이 작성", "!!"]
BRACKET = re.compile(r"\[([^\[\]]*)\]")
PLACEHOLDER_WORDS = ("확인", "미정", "추후", "채울", "입력", "TODO", "TBD", "FIXME", "XXX", "??")


def check_front_matter(meta):
    """The subject line comes from the front matter; an empty title would go out as an empty subject."""
    if not str(meta.get("title") or "").strip():
        return ["머리말 title 없음 — draft.md 머리말 title 필요 (제목 문구를 지어 넣지 않는다)"]
    return []


def check_placeholders(body):
    """Brackets left outside links. '[마감 확인]'-style placeholders must be fixed; other brackets need a look.

    Links are removed first (LINK keeps one level of nested brackets, so '[[기고]제목](url)' goes whole),
    and image lines are skipped. Returns (problems, manual)."""
    problems, manual = [], []
    for number, line in enumerate(body.splitlines(), 1):
        if IMAGE.match(line.strip()):
            continue
        for match in BRACKET.finditer(LINK.sub("", line)):
            mark, inner = match.group(0), match.group(1).strip().upper()
            if not inner or any(word in inner for word in PLACEHOLDER_WORDS):
                problems.append(f"{number}행: 미완성 표시 '{mark}' — 채우거나 지워야 함")
            else:
                manual.append(f"{number}행: 링크가 아닌 대괄호 '{mark}' — 의도한 것인지 확인")
    return problems, manual


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


def image_status(url):
    """Email clients fetch images with no Referer: check the URL answers with an image that way."""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, stream=True, verify=False)
        ctype, size = r.headers.get("Content-Type", ""), int(r.headers.get("Content-Length") or 0)
        r.close()
    except requests.RequestException as exc:
        return url, "broken", exc.__class__.__name__
    if r.status_code != 200 or not ctype.startswith("image/"):
        return url, "broken", f"{r.status_code} {ctype}"
    if size > 1_000_000:
        return url, "manual", f"{size // 1000}KB — 너무 큼, ?type=w773 같은 축소 주소로"
    return url, "ok", f"{ctype} {size // 1000}KB"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    args = parser.parse_args()

    folder = issue_dir(args.customer, args.send_date)
    meta, body = split_front_matter((folder / "draft.md").read_text(encoding="utf-8"))
    send = dt.date.fromisoformat(str(meta.get("send_date", args.send_date)))
    cutoff = send + dt.timedelta(days=1)

    problems, manual = check_front_matter(meta), []
    urls, placed, section = [], [], ""
    for number, line in enumerate(body.splitlines(), 1):
        if line.startswith("## "):
            section = line
        if IMAGE.match(line.strip()):
            continue  # image line: the picture is checked below; its wrapper link repeats the title link on purpose
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

    placeholder_problems, placeholder_manual = check_placeholders(body)
    problems += placeholder_problems
    manual += placeholder_manual

    # The same post may appear once as news and once as a notice; only a repeat inside one section is a mistake.
    duplicates = sorted({u for s, u in placed if placed.count((s, u)) > 1})
    problems += [f"중복 링크 (같은 코너 안): {u}" for u in duplicates]

    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, verdict, detail in pool.map(link_status, sorted(set(urls))):
            if verdict == "broken":
                problems.append(f"깨진 링크 ({detail}): {url}")
            elif verdict == "manual":
                manual.append(f"직접 확인 ({detail}): {url}")

    images = [m.group(2) for m in (IMAGE.match(l.strip()) for l in body.splitlines()) if m]
    for url, verdict, detail in map(image_status, dict.fromkeys(images)):
        if verdict == "broken":
            problems.append(f"이미지 안 열림 ({detail}): {url}")
        elif verdict == "manual":
            manual.append(f"이미지 확인 ({detail}): {url}")
    report = {"links": len(set(urls)), "images": len(set(images)), "cutoff": cutoff.isoformat(), "problems": problems, "manual": manual}
    (folder / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"링크 {report['links']}개 · 이미지 {report['images']}개 · 마감 기준일 {cutoff}")
    for line in problems:
        print(f"  고칠 것: {line}")
    for line in manual:
        print(f"  {line}")
    print("통과" if not problems else f"고칠 것 {len(problems)}건")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
