"""Render draft.md into an email-ready letter.html (inline styles, table layout).

    python3 -m lf.render <customer> <send_date> [--template NAME] [--out FILE]

A template is two files: lf/templates/<name>.html (page frame — header, footer) and
lf/templates/<name>.yaml (inline styles for headings, paragraphs, lists, callouts).
The customer's brand color replaces the template's accent.

draft.md format:
    ---                      front matter: title, issue_label, preheader, send_date, footer
    ## 섹션 제목               section
    ### 소제목                sub-heading inside a section
    - [제목](url) — 매체       list item (consecutive lines form one list)
    > 강조 문단                 callout
    일반 문단                   paragraph (separate with a blank line)
Inline: [text](url), **bold**.
"""
import argparse
import datetime as dt
import html
import re

import jinja2
import yaml

from lf.common import PKG, customer_dir, issue_dir, load_yaml

# [text](url) where text may itself contain [brackets], e.g. [[기획] 제목](url)
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\((https?://[^)\s]+)\)")
BLOCK_KEYS = ("section", "h2", "h3", "p", "ul", "li", "link", "callout")


def split_front_matter(text):
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        return yaml.safe_load(front) or {}, body.strip()
    return {}, text.strip()


def mix(color, other, amount):
    a = [int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(other.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


class Style:
    """Template styles with {accent}, {tint}, {deep}, {font}… filled in."""

    def __init__(self, name, brand):
        raw = load_yaml(PKG / "templates" / f"{name}.yaml")
        accent = brand.get("color") or raw["accent"]
        self.tokens = {
            "accent": accent,
            "accent2": raw.get("accent2", accent),
            "tint": mix(accent, "#ffffff", 0.9),
            "deep": mix(accent, "#000000", 0.25),
            "font": raw["font"],
            "heading_font": raw.get("heading_font", raw["font"]),
        }
        self.raw = raw
        self.accents = [a.format(**self.tokens) for a in raw.get("accents", [])] or [accent]

    def css(self, key, section_accent=None):
        return self.raw[key].format(section_accent=section_accent or self.tokens["accent"], **self.tokens)


def inline(text, link_css):
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # The whole line was escaped above, so the URL's & is already &amp; — don't escape it twice.
    return LINK.sub(lambda m: f'<a href="{m.group(2)}" style="{link_css}">{m.group(1)}</a>', text)


def blocks(body, style):
    sections, current = [], None
    paragraph, items = [], []

    def new_section(title):
        accent = style.accents[len(sections) % len(style.accents)]
        css = {key: style.css(key, accent) for key in BLOCK_KEYS}
        section = {"title": title, "css": css, "html": []}
        sections.append(section)
        return section

    def flush():
        if current is None:
            return
        css = current["css"]
        if paragraph:
            current["html"].append(f'<p style="{css["p"]}">{inline(" ".join(paragraph), css["link"])}</p>')
            paragraph.clear()
        if items:
            lis = "".join(f'<li style="{css["li"]}">{inline(i, css["link"])}</li>' for i in items)
            current["html"].append(f'<ul style="{css["ul"]}">{lis}</ul>')
            items.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            flush()
            current = new_section(line[3:])
            continue
        if current is None:
            current = new_section(None)
        css = current["css"]
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            current["html"].append(f'<h3 style="{css["h3"]}">{inline(line[4:], css["link"])}</h3>')
        elif line.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:])
        elif line.startswith("> "):
            flush()
            current["html"].append(f'<p style="{css["callout"]}">{inline(line[2:], css["link"])}</p>')
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()

    rows = []
    for section in sections:
        css = section["css"]
        heading = f'<h2 style="{css["h2"]}">{inline(section["title"], css["link"])}</h2>' if section["title"] else ""
        rows.append(f'<tr><td style="{css["section"]}">{heading}{"".join(section["html"])}</td></tr>')
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--template", help="profile.yaml 의 template 대신 사용 (비교용)")
    parser.add_argument("--out", help="출력 파일 이름 (기본 letter.html)")
    args = parser.parse_args()

    profile = load_yaml(customer_dir(args.customer) / "profile.yaml")
    folder = issue_dir(args.customer, args.send_date)
    meta, body = split_front_matter((folder / "draft.md").read_text(encoding="utf-8"))
    name = args.template or profile.get("template") or "modern"
    style = Style(name, profile.get("brand") or {})
    send = dt.date.fromisoformat(str(meta.get("send_date", args.send_date)))

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(PKG / "templates"), autoescape=True)
    letter = env.get_template(f"{name}.html").render(
        title=meta.get("title") or profile["org_name"],
        issue_label=meta.get("issue_label", ""),
        date_label=f"{send.year}년 {send.month}월 {send.day}일",
        preheader=meta.get("preheader", ""),
        org_name=profile["org_name"],
        logo_url=(profile.get("brand") or {}).get("logo_url"),
        blocks=[jinja2.utils.markupsafe.Markup(r) for r in blocks(body, style)],
        footer=meta.get("footer") or profile["org_name"],
        **style.tokens,
    )
    out = folder / (args.out or "letter.html")
    # Write pure ASCII: every Korean character becomes &#x...; so the file survives mail
    # attachments, downloads and editors that re-encode to Latin-1 (which turned 한글 into ???).
    letter = letter.encode("ascii", "xmlcharrefreplace").decode("ascii")
    out.write_text(letter, encoding="ascii")
    print(f"{out} ({len(letter):,} bytes, template={name})")
    if "&amp;amp;" in letter:
        print("경고: 링크 주소가 이중으로 escape 됐습니다 (&amp;amp;). 링크가 깨집니다 — render.py 를 확인하세요.")


if __name__ == "__main__":
    main()
