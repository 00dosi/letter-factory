"""Turn the last sent issue (pasted from Gmail) into an exclusion list.

    python3 -m lf.prev_issue <customer> <send_date> <pasted_file> [--label "Vol. 20"]

The pasted file is the plain-text/markdown body of the sent newsletter (Gmail's
PLAIN_TEXT view): Stibee tracking links like
https://event.stibee.com/v2/click/.../<base64> are decoded to their real URL.

Which links count:
  * exclusion list (prev_issue_urls.txt): every link that stands next to text on its
    line — article titles, 보러가기 buttons, CTAs. Links with an empty anchor and nothing
    before them on the line are thumbnails / icons (image links) and are dropped, as are
    unsubscribe links.
  * blog posts used (blog_used_ids.txt): only 보러가기 links — `[… 보러가기](url)` or
    `보러가기[](url)`. Thumbnails, footer, SNS and CTA links never count as 게재.
    The block for this issue (`# <label> …`) is replaced if it already exists (upsert),
    so re-running never duplicates it.
If the pasted text has no markdown anchors at all (a bare list of URLs), every link is
kept and every blog link counts, with a warning.
"""
import argparse
import base64
import datetime as dt
import re
from urllib.parse import urlparse

from lf.common import customer_dir, issue_dir

MD_LINK = re.compile(r"\[([^\[\]]*)\]\((https?://[^\s()<>\"']+)\)")
BARE_URL = re.compile(r"https?://[^\s\[\]()<>\"']+")
STIBEE = re.compile(r"event\.stibee\.com/v2/click/[^/\s]+/([A-Za-z0-9_\-]+)")
BLOG_POST = re.compile(r"blog\.naver\.com/[^/\s]+/(\d+)")
UNSUBSCRIBE = re.compile(r"unsubscribe", re.I)
READ_MORE = "보러가기"


def decode(token):
    token += "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token).decode("utf-8", "replace")


def clean(url):
    """Real target of a link (Stibee tracking decoded), or None if it is not a URL."""
    m = STIBEE.search(url)
    if m:
        try:
            url = decode(m.group(1))
        except Exception:  # noqa: BLE001 — a token that is not base64
            return None
    url = url.strip().rstrip("[]()<>\"'.,;:")
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not re.fullmatch(r"[\w.\-]+(:\d+)?", p.netloc or ""):
        return None
    return url


def links_in(text):
    """(url, anchor text, text between the previous link and this one on the same line)
    for each markdown link."""
    out, prev_end = [], 0
    for m in MD_LINK.finditer(text):
        before = text[max(text.rfind("\n", 0, m.start()) + 1, prev_end):m.start()]
        prev_end = m.end()
        before = re.sub(r"^[\s|*·\-]+|[\s|*·\-]+$", "", before)
        out.append((m.group(2), m.group(1).strip(), before))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("pasted_file")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    text = open(args.pasted_file, encoding="utf-8").read()
    links = links_in(text)
    urls, blog_urls, dropped = [], [], 0
    if links:
        for raw, anchor, before in links:
            url = clean(raw)
            if not url or UNSUBSCRIBE.search(url):
                continue
            if not anchor and not before:      # image / icon link
                dropped += 1
                continue
            urls.append(url)
            if READ_MORE in anchor or before.endswith(READ_MORE):
                blog_urls.append(url)
        covered = {m.group(2) for m in MD_LINK.finditer(text)}
        urls += [u for u in (clean(b) for b in BARE_URL.findall(text) if b not in covered) if u and "stibee.com" not in u]
    else:  # bare list of URLs — no anchors to tell thumbnails from content
        urls = [u for u in (clean(b) for b in BARE_URL.findall(text)) if u]
        blog_urls = urls
        print("경고: 마크다운 링크가 없어 썸네일·본문을 구분하지 못합니다. 블로그 링크 전부를 게재분으로 셉니다 — blog_used_ids.txt 를 확인하세요.")
    urls = list(dict.fromkeys(urls))
    blog_ids = list(dict.fromkeys(m.group(1) for u in blog_urls for m in [BLOG_POST.search(u)] if m))

    folder = issue_dir(args.customer, args.send_date)
    (folder / "prev_issue_urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    if blog_ids:
        used = customer_dir(args.customer) / "blog_used_ids.txt"
        label = args.label or args.send_date
        stamp = f"# {label} ({dt.date.today().isoformat()} 기록)"
        blocks = split_blocks(used.read_text(encoding="utf-8") if used.exists() else "")
        key = block_key(label)
        new_block = [stamp, *blog_ids]
        replaced = False
        for i, block in enumerate(blocks):
            if block and block_key(block[0]) == key:
                blocks[i], replaced = new_block, True
        if not replaced:
            blocks.append(new_block)
        used.write_text("\n".join(line for block in blocks for line in block) + "\n", encoding="utf-8")
        print(f"blog_used_ids.txt: {label} 블록 {'교체' if replaced else '추가'} ({len(blog_ids)}편)")
    else:
        print("경고: 보러가기 링크에서 블로그 글을 찾지 못했습니다. blog_used_ids.txt 는 그대로 둡니다.")
    print(f"원문 URL {len(urls)}개 (블로그 {len(blog_ids)}편, 이미지 링크 {dropped}개 제외) -> {folder / 'prev_issue_urls.txt'}")


def split_blocks(text):
    """[[header, id, id, …], …]; the first block may be a headerless preamble."""
    blocks = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("#") or not blocks:
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return blocks


def block_key(header):
    """'# Vol. 20 (2026-09-18 기록)' and '# Vol20 (2026-09-14 발송)' are the same issue."""
    label = header.lstrip("#").split("(")[0]
    return re.sub(r"[^0-9a-z가-힣]", "", label.lower())


if __name__ == "__main__":
    main()
