"""Render draft.md into an email-ready letter.html (inline styles, table layout).

    python3 -m lf.render <customer> <send_date> [--template NAME] [--out FILE]

A template is two files: lf/templates/<name>.html (page frame — header, footer) and
lf/templates/<name>.yaml (inline styles for headings, paragraphs, lists, callouts).
The customer's brand color replaces the template's accent. A yaml with `layout: dosirak`
draws each section by its profile.yaml key (greeting, own_news, news, opinion, notices)
the way the 도시락레터 Vol.20 mailing looked; other templates draw every section alike.

draft.md format:
    ---                      front matter: title, issue_label, preheader, send_date, footer
    ## 섹션 제목               section
    ### 소제목                sub-heading inside a section
    - [제목](url) — 매체       list item (consecutive lines form one list)
    > 강조 문단                 callout
    일반 문단                   paragraph (separate with a blank line)
    ![alt](image)             image line, optionally wrapped: [![alt](image)](link)
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
NO_UNSUBSCRIBE = "경고: 수신거부 링크 없음 — 스티비 치환 태그 확인 (profile.yaml unsubscribe_html)"


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


def card_html(image, paragraphs, css, img_width=CARD_IMG_WIDTH, text_width=CARD_TEXT_WIDTH, col_class=None, link_key="link"):
    """Two fluid columns: inline-block divs that sit side by side at full width and stack on narrow screens,
    plus a conditional two-cell table for Outlook, which ignores max-width on divs."""
    cls = f' class="{col_class}"' if col_class else ""
    columns = ""
    if image:
        alt, src, href = image
        img = (f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" width="{img_width}" data-lf="card" '
               f'style="display:block;width:100%;max-width:{img_width}px;height:auto;border:0;{css["card_img"]}">')
        columns += (f'<!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td width="{img_width}" valign="top"><![endif]-->'
                    f'<div{cls} style="display:inline-block;width:100%;max-width:{img_width}px;vertical-align:top;">'
                    + (f'<a href="{html.escape(href)}">{img}</a>' if href else img) + '</div>'
                    f'<!--[if mso]></td><td width="{text_width}" valign="top"><![endif]-->')
    text = "".join(f'<p style="{css["p"]}">{"<br>".join(inline(l, css[link_key]) for l in lines)}</p>' for lines in paragraphs)
    # Padding goes on an inner div: on the column itself it would add to the width and wrap the columns.
    columns += (f'<div{cls} style="display:inline-block;width:100%;max-width:{text_width}px;vertical-align:top;">'
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


def parse(body):
    """draft body → sections [{"title", "items"}]; items are (kind, payload):
    h3 text · p text · ul [items] · callout text · image (alt, src, href) · card (image, paragraphs)."""
    sections, current = [], None
    paragraph, items = [], []

    def new_section(title):
        section = {"title": title, "items": []}
        sections.append(section)
        return section

    def flush():
        if current is None:
            return
        if paragraph:
            current["items"].append(("p", " ".join(paragraph)))
            paragraph.clear()
        if items:
            current["items"].append(("ul", list(items)))
            items.clear()

    card = None  # lines collected between :::card and :::
    for raw in body.splitlines():
        line = raw.strip()
        if card is not None:
            if line == ":::":
                flush()
                current["items"].append(("card", parse_card(card)))
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
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            current["items"].append(("h3", line[4:]))
        elif line.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:])
        elif line.startswith("> "):
            flush()
            current["items"].append(("callout", line[2:]))
        elif IMAGE.match(line):
            flush()
            current["items"].append(("image", IMAGE.match(line).groups()))
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    if card is not None:  # unterminated :::card — render what we have rather than drop it
        current["items"].append(("card", parse_card(card)))
    return sections


def item_html(kind, payload, css, **card_opts):
    """One parsed item as HTML with this section's css."""
    link = css[card_opts.get("link_key", "link")]
    if kind == "p":
        return f'<p style="{css["p"]}">{inline(payload, link)}</p>'
    if kind == "ul":
        return f'<ul style="{css["ul"]}">' + "".join(f'<li style="{css["li"]}">{inline(i, link)}</li>' for i in payload) + "</ul>"
    if kind == "h3":
        return f'<h3 style="{css["h3"]}">{inline(payload, link)}</h3>'
    if kind == "callout":
        return f'<p style="{css["callout"]}">{inline(payload, link)}</p>'
    if kind == "image":
        alt, src, href = payload
        img = f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" width="600" style="{css["image"]}">'
        return f'<a href="{html.escape(href)}">{img}</a>' if href else img
    return card_html(*payload, css, **card_opts)


def emit_generic(sections, style):
    """Every section alike: h2 + items in one table row (warm · modern · public · colorful)."""
    rows = []
    for number, section in enumerate(sections):
        accent = style.accents[number % len(style.accents)]
        css = {key: style.css(key, accent) for key in BLOCK_KEYS}
        heading = f'<h2 style="{css["h2"]}">{inline(section["title"], css["link"])}</h2>' if section["title"] else ""
        body = "".join(item_html(kind, payload, css) for kind, payload in section["items"])
        rows.append(f'<tr><td style="{css["section"]}">{heading}{body}</td></tr>')
    return rows


def blocks(body, style):
    return emit_generic(parse(body), style)


# ---- 도시락레터 layout (Vol.20 mailing) -------------------------------------------------------------

DOSIRAK_KEYS = BLOCK_KEYS + ("blog_link", "gray", "band", "box", "rule", "dotted", "double_dotted", "short_rule", "highlight", "small")


def norm_title(text):
    return re.sub(r"[^\w가-힣]", "", text or "")


def section_keys(sections, profile_sections):
    """profile.yaml sections[].key for each draft section, matched by title (emoji/space-insensitive)."""
    by_title = {norm_title(s.get("title")): s.get("key") for s in profile_sections or [] if s.get("title")}
    return [by_title.get(norm_title(s["title"])) for s in sections]


def emit_dosirak(sections, style, profile):
    design = profile.get("design") or {}
    css = {key: style.css(key) for key in DOSIRAK_KEYS}
    img_w, text_w = int(style.raw.get("card_img_width", 300)), int(style.raw.get("card_text_width", 280))
    keys = section_keys(sections, profile.get("sections"))
    rows = []

    def row(inner, pad="0 15px"):
        rows.append(f'<tr><td style="padding:{pad};">{inner}</td></tr>')

    def area(inner, key):  # gray area / white box
        return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="{css[key]}">{inner}</td></tr></table>'

    def fixed_image(url, width, extra=""):
        return f'<img src="{html.escape(url)}" alt="" width="{width}" style="display:block;margin:0 auto;max-width:100%;height:auto;border:0;{extra}">' if url else ""

    def rule_with(icon_url, width, tagline_url=None):
        inner = f'<div style="{css["rule"]}">&nbsp;</div>'
        if icon_url:
            inner += f'<div style="padding:12px 0 0;">{fixed_image(icon_url, width)}</div>'
        if tagline_url:
            inner += f'<div style="padding:10px 0 0;">{fixed_image(tagline_url, 412)}</div>'
        row(inner, "18px 15px")

    def items_html(items, link_key="link"):
        return "".join(item_html(k, p, css, img_width=img_w, text_width=text_w, col_class="lf-col", link_key=link_key) for k, p in items)

    def h2(title, extra=""):
        return f'<h2 style="{css["h2"]}{extra}">{inline(title, css["link"])}</h2>'

    for index, (section, key) in enumerate(zip(sections, keys)):
        title, items = section["title"], section["items"]
        next_key = keys[index + 1] if index + 1 < len(keys) else None
        if key == "greeting":
            inner = fixed_image(design.get("skyline_url"), 570, "background:#ffffff;")
            inner += f'<p style="{css["p"]}text-align:center;font-weight:700;">&lt; {html.escape(title)} &gt;</p>'
            inner += items_html(items, "blog_link")
            row(area(inner, "gray"))
            rule_with(design.get("leaf_url"), 40)
        elif key == "own_news":
            buffer = [("h2", None)]  # gray area: title + intro; cards break it; trailing text goes back into gray

            def flush_gray():
                if not buffer:
                    return
                inner = "".join(h2(title, "text-align:center;text-decoration:underline;") if k == "h2" else items_html([(k, p)], "blog_link") for k, p in buffer)
                row(area(inner, "gray"), "0 15px 8px")
                buffer.clear()

            for kind, payload in items:
                if kind == "card":
                    flush_gray()
                    row(items_html([(kind, payload)], "blog_link"))
                else:
                    buffer.append((kind, payload))
            flush_gray()
            if next_key == "own_news":
                row(f'<div style="{css["double_dotted"]}">&nbsp;</div>', "12px 15px")
            else:
                rule_with(design.get("dove_url"), 42, design.get("tagline_url"))
        elif key == "news":
            row(f'<div style="{css["band"]}">{inline(title, css["link"])}</div>', "0 15px 8px")
            inner, axes = "", 0
            for kind, payload in items:
                if kind == "h3":
                    if axes:
                        inner += f'<div style="{css["short_rule"]}">&nbsp;</div>'
                    axes += 1
                inner += items_html([(kind, payload)])
            row(area(inner, "box"))
        elif key == "opinion":
            lead = items[0] if items and items[0][0] == "p" else None
            inner = h2(title) + (items_html([lead]) if lead else "")
            row(area(inner, "box"), "0 15px 8px")
            rest = items[1:] if lead else items
            if rest:
                row(area(items_html(rest), "gray"))
            row(f'<div style="{css["dotted"]}">&nbsp;</div>', "16px 15px")
        elif key == "notices":
            row(f'<div style="{css["band"]}">{inline(title, css["link"])}</div>', "0 15px 8px")
            inner = "".join(
                f'<h3 style="{css["h3"]}"><span style="{css["highlight"]}">{inline(p, css["link"])}</span></h3>' if k == "h3" else items_html([(k, p)])
                for k, p in items)
            row(area(inner, "box"))
        else:
            heading = h2(title) if title else ""
            row(f'{heading}{items_html(items)}', "16px 15px")
    return rows


def issue_number(meta, folder=None):
    """issue.yaml issue_no, else the digits of the front-matter issue_label ("Vol. 21" → 21)."""
    if folder and (folder / "issue.yaml").exists():
        no = load_yaml(folder / "issue.yaml").get("issue_no")
        if no is not None:
            return no
    found = re.search(r"\d+", str(meta.get("issue_label") or ""))
    return found.group(0) if found else ""


def render_letter(profile, meta, body, name, send_date=None, issue_no=""):
    """(letter html, warnings). The dosirak layout also needs profile design/footer/web_view_url/unsubscribe_html."""
    style = Style(name, profile.get("brand") or {})
    send = dt.date.fromisoformat(str(meta.get("send_date", send_date)))
    dosirak = style.raw.get("layout") == "dosirak"
    sections = parse(body)
    rows = emit_dosirak(sections, style, profile) if dosirak else emit_generic(sections, style)
    warnings = []
    if dosirak and not (profile.get("unsubscribe_html") or "").strip():
        warnings.append(NO_UNSUBSCRIBE)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(PKG / "templates"), autoescape=True)
    letter = env.get_template(f"{name}.html").render(
        title=meta.get("title") or profile["org_name"],
        issue_label=meta.get("issue_label", ""),
        issue_no=issue_no,
        date_label=f"{send.year}년 {send.month}월 {send.day}일",
        preheader=meta.get("preheader", ""),
        org_name=profile["org_name"],
        logo_url=(profile.get("brand") or {}).get("logo_url"),
        blocks=[jinja2.utils.markupsafe.Markup(r) for r in rows],
        footer=meta.get("footer") or profile["org_name"],
        design=profile.get("design") or {},
        pfooter=profile.get("footer") if isinstance(profile.get("footer"), dict) else {},
        web_view_url=profile.get("web_view_url") or "",
        unsubscribe_html=jinja2.utils.markupsafe.Markup(profile.get("unsubscribe_html") or ""),
        style=style,
        **style.tokens,
    )
    # Write pure ASCII: every Korean character becomes &#x...; so the file survives mail
    # attachments, downloads and editors that re-encode to Latin-1 (which turned 한글 into ???).
    letter = letter.encode("ascii", "xmlcharrefreplace").decode("ascii")
    if "&amp;amp;" in letter:
        warnings.append("경고: 링크 주소가 이중으로 escape 됐습니다 (&amp;amp;). 링크가 깨집니다 — render.py 를 확인하세요.")
    return letter, warnings


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
    letter, warnings = render_letter(profile, meta, body, name, args.send_date, issue_number(meta, folder))
    out = folder / (args.out or "letter.html")
    out.write_text(letter, encoding="ascii")
    print(f"{out} ({len(letter):,} bytes, template={name})")
    for line in warnings:
        print(line)


if __name__ == "__main__":
    main()
