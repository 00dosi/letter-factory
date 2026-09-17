"""Turn the last sent issue (pasted from Gmail) into an exclusion list.

    python3 -m lf.prev_issue <customer> <send_date> <pasted_file> [--label "Vol. 20"]

The pasted file is the plain-text body of the sent newsletter (Stibee tracking links
like https://event.stibee.com/v2/click/.../<base64>). Every tracking link is decoded to
its real URL. Writes issues/<send_date>/prev_issue_urls.txt and appends the blog post
ids to customers/<customer>/blog_used_ids.txt (with the issue label) so later issues
skip them too.
"""
import argparse
import base64
import datetime as dt
import re

from lf.common import customer_dir, issue_dir


def decode(token):
    token += "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token).decode("utf-8", "replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("pasted_file")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    text = open(args.pasted_file, encoding="utf-8").read()
    urls = []
    for token in re.findall(r"event\.stibee\.com/v2/click/[^/\s)]+/([A-Za-z0-9_\-]+)", text):
        try:
            urls.append(decode(token))
        except Exception:
            pass
    urls += [u for u in re.findall(r"https?://[^\s)\]]+", text) if "stibee.com" not in u]
    urls = list(dict.fromkeys(urls))

    folder = issue_dir(args.customer, args.send_date)
    (folder / "prev_issue_urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    blog_ids = [m.group(1) for u in urls for m in [re.search(r"blog\.naver\.com/00dosi/(\d+)", u)] if m]
    if blog_ids:
        used = customer_dir(args.customer) / "blog_used_ids.txt"
        stamp = f"{args.label or args.send_date} ({dt.date.today().isoformat()} 기록)"
        with open(used, "a", encoding="utf-8") as f:
            f.write(f"# {stamp}\n" + "\n".join(dict.fromkeys(blog_ids)) + "\n")
    print(f"원문 URL {len(urls)}개 (블로그 {len(set(blog_ids))}편) -> {folder / 'prev_issue_urls.txt'}")


if __name__ == "__main__":
    main()
