"""Stibee side of an issue: paste package, subscriber sync, test-mail link check.

    python3 -m lf.stibee pack <customer> <send_date>
        letter.html → stibee.html (paste into 스티비 "HTML 직접 입력" 편집기 as one block)
                    → stibee_blocks.md (section-by-section text + image list, for the block editor)
    python3 -m lf.stibee subscribers <csv> [--apply]
        Drive 주소록 CSV → Stibee list. Dry-run by default; --apply POSTs in batches.
        Needs STIBEE_API_KEY and STIBEE_LIST_ID in .env (API is a paid-plan feature).
    python3 -m lf.stibee testmail <customer> <send_date> <pasted_test_mail.txt>
        Decode Stibee click links in the test mail, open each, compare with letter.html.

Stibee has no public API for creating a regular campaign, so the campaign itself is
still created by a person: subject, preheader, paste stibee.html, test send, schedule.
"""
import argparse
import base64
import csv
import datetime as dt
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

from lf.checks import link_status
from lf.common import ROOT, UA, dump_yaml, issue_dir, load_env, load_yaml
from lf.render import CARD_IMG_WIDTH, LINK, split_front_matter

API = "https://api.stibee.com/v1"
CARD_IMG = re.compile(r'<img src="([^"]+)"[^>]*data-lf="card"')
EMBED_WIDTH = CARD_IMG_WIDTH * 2  # retina: twice the displayed width
NO_TITLE = "제목 없음 — draft.md 머리말 title 필요"


def download(url):
    """Bytes of an image the way an email client would fetch it (no Referer). Naver needs ?type=w773."""
    if "pstatic.net" in url and "type=" not in url:
        url += ("&" if "?" in url else "?") + "type=w773"
    r = requests.get(url, headers={"User-Agent": UA["User-Agent"]}, timeout=30)
    r.raise_for_status()
    return r.content


def to_jpeg_data_uri(raw, width=EMBED_WIDTH, quality=80):
    image = Image.open(io.BytesIO(raw))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def embed_images(letter, fetch=download):
    """Replace each card image URL in letter.html with a base64 JPEG. Returns (html, embedded, kept)."""
    done, embedded, kept = {}, 0, 0
    for url in dict.fromkeys(CARD_IMG.findall(letter)):
        try:
            done[url] = to_jpeg_data_uri(fetch(html_unescape(url)))
            embedded += 1
        except Exception as exc:  # noqa: BLE001 — a failed image keeps its URL; the paste still works
            print(f"  경고: 이미지 내장 실패, URL 유지 ({exc.__class__.__name__}: {str(exc)[:80]}) {url}")
            kept += 1
    for url, data in done.items():
        letter = letter.replace(f'<img src="{url}"', f'<img src="{data}"')
    return letter, embedded, kept


def html_unescape(url):
    return url.replace("&amp;", "&")


def pack(args):
    folder = issue_dir(args.customer, args.send_date)
    letter = (folder / "letter.html").read_text(encoding="utf-8")
    meta, body = split_front_matter((folder / "draft.md").read_text(encoding="utf-8"))
    subject = f"{meta.get('title') or ''} {meta.get('issue_label') or ''}".strip()
    preheader = meta.get("preheader") or ""
    warn = "" if subject else f"<!-- !!!!!!!!!! {NO_TITLE} !!!!!!!!!! -->\n"
    if not subject:
        print(f"!!! {NO_TITLE} !!!")

    letter, embedded, kept = embed_images(letter)
    head = (f"<!-- 스티비 붙여넣기용 · {subject} · 발송일 {args.send_date} · 생성 {dt.datetime.now():%Y-%m-%d %H:%M}\n"
            f"     제목: {subject}\n     미리보기 문구: {preheader}\n"
            "     사용법: 스티비 이메일 만들기 → 콘텐츠 → 'HTML 직접 입력'(코드 편집) → 이 파일 내용 전체 붙여넣기 -->\n")
    (folder / "stibee.html").write_text(warn + head + letter, encoding="utf-8")
    print(f"이미지 {embedded}장 내장, {kept}장 URL 유지")

    blocks = [f"# 스티비 블록 편집기용 — {subject}", f"- 제목: {subject}", f"- 미리보기 문구: {preheader}", f"- 발송: {args.send_date}(월) 07:30 예약", ""]
    images = []
    for path in sorted((folder / "blog").glob("*.md")) if (folder / "blog").exists() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("- 이미지 "):
                images.append(f"{path.stem}: {line.split(': ', 1)[1]}")
    if images:
        blocks += ["## 이미지 (블로그 카드뉴스 — 스티비 이미지 블록에 URL 또는 파일로 넣는다)"] + [f"- {i}" for i in images] + [""]
    n = 0
    for line in body.splitlines():
        if line.startswith("## "):
            n += 1
            blocks += ["", f"## 블록 {n}: {line[3:]}", ""]
        else:
            blocks.append(line)
    (folder / "stibee_blocks.md").write_text("\n".join(blocks), encoding="utf-8")
    links = len(set(u for _, u in LINK.findall(body)))
    print(f"stibee.html (HTML 편집기용) · stibee_blocks.md (블록 {n}개, 이미지 {len(images)}장, 링크 {links}개) -> {folder}")
    print(f"제목: {subject}\n미리보기: {preheader}")


def read_csv(path):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" or b"\x00" not in raw[:100] else raw.decode("utf-16")
    try:
        text.encode("utf-8")
    except UnicodeError:
        text = raw.decode("cp949")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        sys.exit("CSV 가 비어 있습니다.")
    cols = {c.strip().lower(): c for c in rows[0].keys()}
    email_col = next((cols[c] for c in cols if c in ("email", "이메일", "이메일 주소", "e-mail")), None)
    if not email_col:
        sys.exit(f"이메일 열을 찾지 못했습니다. 열: {list(rows[0].keys())}")
    name_col = next((cols[c] for c in cols if c in ("name", "이름", "성명")), None)
    subs, bad = [], []
    for r in rows:
        email = (r.get(email_col) or "").strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            bad.append(email or "(빈칸)")
            continue
        sub = {"email": email}
        if name_col and r.get(name_col):
            sub["name"] = r[name_col].strip()
        for k, v in r.items():
            if k not in (email_col, name_col) and v and v.strip():
                sub[k.strip()] = v.strip()
        subs.append(sub)
    uniq = list({s["email"]: s for s in subs}.values())
    return uniq, bad, len(subs) - len(uniq)


def subscribers(args):
    subs, bad, dup = read_csv(args.csv)
    print(f"CSV: 유효 {len(subs)}명 · 형식 오류 {len(bad)}건 · 중복 제거 {dup}건")
    for b in bad[:10]:
        print(f"  형식 오류: {b}")
    print("  예시: " + json.dumps(subs[0], ensure_ascii=False))
    if not args.apply:
        print("dry-run 입니다. 실제 등록은 --apply 를 붙이세요.")
        return
    env = load_env(required=("STIBEE_API_KEY", "STIBEE_LIST_ID"))
    headers = {"AccessToken": env["STIBEE_API_KEY"], "Content-Type": "application/json"}
    done, failed = 0, []
    for i in range(0, len(subs), 100):
        batch = subs[i:i + 100]
        payload = {"eventOccuredBy": "MANUAL", "confirmEmailYN": "N", "subscribers": batch}
        r = requests.post(f"{API}/lists/{env['STIBEE_LIST_ID']}/subscribers", headers=headers, json=payload, timeout=30)
        if r.status_code != 200 or not r.json().get("Ok", True):
            failed.append(f"{i}-{i + len(batch)}: HTTP {r.status_code} {r.text[:200]}")
        else:
            done += len(batch)
    print(f"등록/갱신 요청 {done}명" + (f", 실패 {len(failed)}묶음" if failed else ""))
    for f in failed:
        print("  " + f)
    print("주의: 이 명령은 추가·갱신만 합니다. 수신거부·삭제는 스티비 화면에서 합니다.")


def decode(token):
    token += "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token).decode("utf-8", "replace")


def testmail(args):
    folder = issue_dir(args.customer, args.send_date)
    text = Path(args.pasted_file).read_text(encoding="utf-8")
    found = []
    for token in re.findall(r"event\.stibee\.com/v2/click/[^/\s)]+/([A-Za-z0-9_\-]+)", text):
        try:
            found.append(decode(token))
        except Exception:  # noqa: BLE001
            pass
    found = list(dict.fromkeys(found))
    _, body = split_front_matter((folder / "draft.md").read_text(encoding="utf-8"))
    expected = list(dict.fromkeys(u for _, u in LINK.findall(body)))
    missing = [u for u in expected if u not in found]
    extra = [u for u in found if u not in expected and "stibee" not in u and "00dosi" not in u]
    print(f"테스트 메일 링크 {len(found)}개 · 원고 링크 {len(expected)}개 · 원고에 있는데 메일에 없음 {len(missing)}개 · 메일에만 있음 {len(extra)}개")
    for u in missing:
        print(f"  누락: {u}")
    broken = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, verdict, detail in pool.map(link_status, found):
            if verdict == "broken":
                broken.append(f"{detail} {url}")
            elif verdict == "manual":
                print(f"  직접 확인 ({detail}): {url}")
    for b in broken:
        print(f"  깨짐: {b}")
    ok = not missing and not broken
    meta = load_yaml(folder / "issue.yaml")
    meta["test_sent_at"] = dt.datetime.now().isoformat(timespec="minutes")
    meta["test_links"] = {"found": len(found), "missing": len(missing), "broken": len(broken)}
    dump_yaml(meta, folder / "issue.yaml")
    print("통과 — 대표 검수 후 예약 발송" if ok else "고칠 것 있음 — 스티비에서 수정 후 테스트 발송을 다시 한다")
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack"); p.add_argument("customer"); p.add_argument("send_date"); p.set_defaults(fn=pack)
    p = sub.add_parser("subscribers"); p.add_argument("csv"); p.add_argument("--apply", action="store_true"); p.set_defaults(fn=subscribers)
    p = sub.add_parser("testmail"); p.add_argument("customer"); p.add_argument("send_date"); p.add_argument("pasted_file"); p.set_defaults(fn=testmail)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
