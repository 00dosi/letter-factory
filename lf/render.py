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
    :::card … :::             card: image on the left, text on the right (blog posts, banners)
        first line  [![alt](image)](link) or ![alt](image) — optional; without it the card is text only
        then paragraphs (blank line between), one <br> per line inside a paragraph
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
BLOCK_KEYS = ("section", "h2", "h3", "p", "ul", "li", "link", "callout", "image", "card", "card_img", "card_text")
# Card columns: image + text must fit the narrowest template body (600 minus section padding = 520).
CARD_IMG_WIDTH, CARD_TEXT_WIDTH = 240, 276  # 516 + 2px card border fits modern (520)
# a line that is only an image, optionally wrapped in a link: ![alt](img) / [![alt](img)](url)
IMAGE = re.compile(r"^(?:\[)?!\[([^\]]*)\]\((https?://\S+?)\)(?:\]\((https?://\S+?)\))?$")


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


def card_html(image, paragraphs, css):
    """Two fluid columns: inline-block divs that sit side by side at 600px and stack on narrow screens,
    plus a conditional two-cell table for Outlook, which ignores max-width on divs."""
    columns = ""
    if image:
        alt, src, href = image
        img = (f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" width="{CARD_IMG_WIDTH}" data-lf="card" '
               f'style="display:block;width:100%;max-width:{CARD_IMG_WIDTH}px;height:auto;border:0;{css["card_img"]}">')
        columns += (f'<!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td width="{CARD_IMG_WIDTH}" valign="top"><![endif]-->'
                    f'<div style="display:inline-block;width:100%;max-width:{CARD_IMG_WIDTH}px;vertical-align:top;">'
                    + (f'<a href="{html.escape(href)}">{img}</a>' if href else img) + '</div>'
                    f'<!--[if mso]></td><td width="{CARD_TEXT_WIDTH}" valign="top"><![endif]-->')
    text = "".join(f'<p style="{css["p"]}">{"<br>".join(inline(l, css["link"]) for l in lines)}</p>' for lines in paragraphs)
    # Padding goes on an inner div: on the column itself it would add to the 280px and wrap the columns.
    columns += (f'<div style="display:inline-block;width:100%;max-width:{CARD_TEXT_WIDTH}px;vertical-align:top;">'
                f'<div style="{css["card_text"]}">{text}</div></div>')
    if image:
        columns += '<!--[if mso]></td></tr></table><![endif]-->'
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;margin:0 0 10px;">'
            f'<tr><td style="{css["card"]}">{columns}</td></tr></table>')


def parse_card(lines):
    """(image or None, paragraphs) from the lines between :::card and :::. Each paragraph is a list of lines."""
    image, paragraphs, current = None, [], []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if index == 0 and IMAGE.match(line):
            image = IMAGE.match(line).groups()
            continue
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(line[2:] if line.startswith("- ") else line)
    if current:
        paragraphs.append(current)
    return image, paragraphs


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

    card = None  # lines collected between :::card and :::
    for raw in body.splitlines():
        line = raw.strip()
        if card is not None:
            if line == ":::":
                flush()
                current["html"].append(card_html(*parse_card(card), current["css"]))
                card = None
            else:
                card.append(raw)
            continue
        if line == ":::card":
            flush()
            if current is None:
                current = new_section(None)
            card = []
            continue
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
        elif IMAGE.match(line):
            flush()
            alt, src, href = IMAGE.match(line).groups()
            img = f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" width="600" style="{css["image"]}">'
            current["html"].append(f'<a href="{html.escape(href)}">{img}</a>' if href else img)
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    if card is not None:  # unterminated :::card — render what we have rather than drop it
        current["html"].append(card_html(*parse_card(card), current["css"]))

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
