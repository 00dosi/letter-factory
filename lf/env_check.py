"""Can this session run the pipeline? Run once at the start of a Cowork session.

    python3 -m lf.env_check [customer]

Checks, in order: Python + packages, .env keys, write access, outbound IP country,
Naver API, two Korean public boards, Naver blog mobile page. Prints one line per
check and a final verdict: 스크립트 모드 / 부분 / 수동 모드. Writes env_check.json
next to this repo's root (git-ignored) so lf.status can show it.
"""
import datetime as dt
import json
import re
import sys

from lf.common import ROOT, UA, customer_dir, issue_dir_template, load_yaml

BOARDS = [
    ("NABIS 채용공고", "https://www.nabis.go.kr/businessJobList.do?menucd=204&menuFlag=Y"),
    ("도시재생종합정보체계 공지", "https://www.city.go.kr/portal/notice/notice/list.do"),
]


def issues_parent(slug):
    """The folder that holds the issue folders: the issue_dir rule up to its first placeholder other than {slug}.
    02_drafts/Vol{vol}_{mmdd} → 02_drafts; the default → customers/<slug>/issues. No issue number is computed."""
    head = issue_dir_template().replace("{slug}", slug).split("{")[0]
    return ROOT / head.rsplit("/", 1)[0] if "/" in head else ROOT


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    slug = argv[0] if argv else "dosirak"
    rows = []

    def add(name, ok, detail):
        rows.append({"check": name, "ok": ok, "detail": detail})
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")

    def run(name, check):
        """One check must not stop the others: a crash becomes a ✗ row and the next check runs."""
        try:
            check()
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            add(name, False, f"{exc.__class__.__name__}: {exc}")

    v = sys.version_info
    add("Python", v >= (3, 9), f"{v.major}.{v.minor}.{v.micro}")
    missing = []
    for mod in ("requests", "yaml", "jinja2"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    add("패키지 requests·pyyaml·jinja2", not missing, "설치됨" if not missing else f"없음: {', '.join(missing)} → pip install requests pyyaml jinja2")

    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, val = line.split("=", 1)
                env[k.strip()] = val.strip()
    add(".env 네이버 키", bool(env.get("NAVER_CLIENT_ID") and env.get("NAVER_CLIENT_SECRET")), "있음" if env.get("NAVER_CLIENT_ID") else f"없음 ({env_file})")
    add(".env 스티비 키 (선택)", bool(env.get("STIBEE_API_KEY") and env.get("STIBEE_LIST_ID")), "있음" if env.get("STIBEE_API_KEY") else "없음 — 주소록 동기화는 수동")

    def write_probe():
        # Write into the folder that holds the issue folders, not into a fake issue (which would need an issue number).
        parent = issues_parent(slug)
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / ".write_test"
        probe.write_text(dt.datetime.now().isoformat(), encoding="utf-8")
        try:
            probe.unlink()
            add("폴더 쓰기", True, str(parent))
        except Exception:  # noqa: BLE001
            # Cowork mounts allow writing but not deleting (2026-09-17). Writing is what the pipeline needs.
            add("폴더 쓰기", True, f"{parent} (삭제는 막힘 — 정상. 남은 .write_test 는 무시)")

    run("폴더 쓰기", write_probe)

    if missing:
        verdict(rows)
        return
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def ip_country():
        info = requests.get("https://ipinfo.io/json", headers=UA, timeout=8).json()
        country = info.get("country", "?")
        add("나가는 IP 국가", country == "KR", f"{country} {info.get('ip', '')} — " + ("한국 게시판 접속 가능" if country == "KR" else "해외 IP: 한국 공공 게시판이 막힐 수 있음"))

    run("나가는 IP 국가", ip_country)

    def naver_api():
        r = requests.get("https://openapi.naver.com/v1/search/news.json", params={"query": "도시재생", "display": 1},
                         headers={"X-Naver-Client-Id": env["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"]}, timeout=10)
        add("네이버 뉴스 API", r.status_code == 200, f"HTTP {r.status_code}" + ("" if r.status_code == 200 else f" {r.text[:80]}"))

    if env.get("NAVER_CLIENT_ID"):
        run("네이버 뉴스 API", naver_api)

    def board(name, url):
        r = requests.get(url, headers=UA, timeout=15, verify=False)
        add(f"게시판 {name}", r.status_code == 200 and len(r.text) > 2000, f"HTTP {r.status_code}, {len(r.text)}자")

    for name, url in BOARDS:
        run(f"게시판 {name}", lambda name=name, url=url: board(name, url))

    def blog():
        rss = (load_yaml(customer_dir(slug) / "profile.yaml").get("blog") or {}).get("rss")
        if not rss:
            return
        xml = requests.get(rss, headers=UA, timeout=20).text
        blog_id = re.search(r"rss\.blog\.naver\.com/([^.]+)\.xml", rss).group(1)
        post = re.search(r"<link>(?:\s*<!\[CDATA\[)?[^<]*?(\d{10,})", xml)
        add("블로그 RSS", bool(post), f"항목 {xml.count('<item>')}개")
        if post:
            r = requests.get(f"https://m.blog.naver.com/{blog_id}/{post.group(1)}", headers=UA, timeout=20)
            body = re.sub(r"<[^>]+>", "", r.text)
            add("블로그 본문 (m.blog)", r.status_code == 200 and "se-main-container" in r.text, f"HTTP {r.status_code}, 본문 컨테이너 {'있음' if 'se-main-container' in r.text else '없음'}, {len(body)}자")

    run("블로그 RSS", blog)
    verdict(rows)


def verdict(rows):
    by = {r["check"]: r["ok"] for r in rows}
    core = all(by.get(k) for k in ("Python", "패키지 requests·pyyaml·jinja2", ".env 네이버 키", "폴더 쓰기", "네이버 뉴스 API"))
    boards = any(ok for name, ok in by.items() if name.startswith("게시판"))
    if core and boards:
        mode = "스크립트 모드"
        note = "수집·검사·렌더를 전부 스크립트로 진행합니다."
    elif core:
        mode = "부분 스크립트 모드"
        note = "뉴스·검사·렌더는 스크립트, 게시판은 브라우저(Claude in Chrome)로 확인합니다."
    else:
        mode = "수동 모드"
        note = "지침의 '수동 모드' 절차대로 진행하고, 같은 파일명으로 결과를 저장합니다."
    print(f"\n판정: {mode} — {note}")
    (ROOT / "env_check.json").write_text(json.dumps({"checked_at": dt.datetime.now().isoformat(timespec="seconds"), "mode": mode, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
