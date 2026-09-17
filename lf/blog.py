"""Read Naver blog posts (title, date, images, body) through the mobile page, so the
editor never has to paste blog text by hand.

    python3 -m lf.blog <customer> <send_date> <post_id_or_url> [...]

Writes issues/<send_date>/blog/<post_id>.md and prints title + length. The mobile
address m.blog.naver.com serves the body to scripts; the PC address does not.
"""
import argparse
import html
import re
from html.parser import HTMLParser

import requests

from lf.common import UA, customer_dir, issue_dir, load_yaml


class BodyParser(HTMLParser):
    """Text and images inside the SmartEditor container (div.se-main-container)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.inside, self.parts, self.images, self.skip = 0, 0, [], [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and "se-main-container" in cls and not self.inside:
            self.inside = 1
            return
        if self.inside:
            if tag == "div":
                self.inside += 1
            if tag in ("script", "style"):
                self.skip += 1
            if tag == "img":
                src = a.get("data-lazy-src") or a.get("src") or ""
                if src and "pstatic.net" in src and ("se-image-resource" in cls or "phinf" in src or "postfiles" in src or "blogfiles" in src):
                    self.images.append(re.sub(r"\?type=.*$", "", src))
                    self.parts.append(f"\n[이미지 {len(self.images)}]\n")
            if tag in ("p", "br", "li", "h1", "h2", "h3", "h4"):
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.inside:
            if tag in ("script", "style") and self.skip:
                self.skip -= 1
            if tag == "div":
                self.inside -= 1
            if tag in ("p", "li", "h1", "h2", "h3", "h4", "div"):
                self.parts.append("\n")

    def handle_data(self, data):
        if self.inside and not self.skip:
            self.parts.append(data)


def read_post(blog_id, post_id):
    url = f"https://m.blog.naver.com/{blog_id}/{post_id}"
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    raw = r.text
    title = re.search(r'property="og:title"\s+content="([^"]*)"', raw)
    date = re.search(r"(20\d{2}\. ?\d{1,2}\. ?\d{1,2}\.)", raw)
    parser = BodyParser()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t​]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return {
        "url": f"https://blog.naver.com/{blog_id}/{post_id}",
        "title": html.unescape(title.group(1)).strip() if title else "",
        "date": date.group(1).strip() if date else "",
        "images": parser.images,
        "body": text,
        "found_container": "se-main-container" in raw,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("posts", nargs="+", help="글 번호 또는 blog.naver.com 주소")
    args = parser.parse_args()

    profile = load_yaml(customer_dir(args.customer) / "profile.yaml")
    rss = (profile.get("blog") or {}).get("rss") or ""
    blog_id = re.search(r"rss\.blog\.naver\.com/([^.]+)\.xml", rss).group(1) if rss else "00dosi"
    folder = issue_dir(args.customer, args.send_date) / "blog"
    folder.mkdir(exist_ok=True)

    for ref in args.posts:
        m = re.search(r"blog\.naver\.com/([^/]+)/(\d+)", ref)
        bid, pid = (m.group(1), m.group(2)) if m else (blog_id, re.sub(r"\D", "", ref))
        try:
            post = read_post(bid, pid)
        except requests.RequestException as exc:
            print(f"  ✗ {pid}: 읽기 실패 ({exc.__class__.__name__}) — 담당자에게 본문 붙여넣기를 요청")
            continue
        if not post["found_container"] or len(post["body"]) < 100:
            print(f"  ✗ {pid}: 본문 컨테이너 없음/짧음 ({len(post['body'])}자) — 브라우저로 열어 확인")
        out = folder / f"{pid}.md"
        lines = [f"# {post['title']}", f"- URL: {post['url']}", f"- 게시일: {post['date']}", f"- 본문 {len(post['body'])}자 · 이미지 {len(post['images'])}장", ""]
        lines += [f"- 이미지 {i}: {u}" for i, u in enumerate(post["images"], 1)]
        lines += ["", "## 본문", "", post["body"]]
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"  ✓ {pid}: {post['title'][:50]} — {len(post['body'])}자, 이미지 {len(post['images'])}장 -> {out.name}")


if __name__ == "__main__":
    main()
