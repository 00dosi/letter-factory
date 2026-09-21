"""Shared helpers: project paths, secrets, YAML, text cleanup, Korean business days."""
import datetime as dt
import html
import os
import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parent            # code: lf/, lf/templates/, lf/config/
# Data root: customers/, .env, lf_settings.yaml, issue folders. LF_ROOT env wins (the MCP server
# sets it from --root); otherwise the current directory (run `python3 -m lf.<name>` from the workspace).
ROOT = Path(os.environ.get("LF_ROOT") or Path.cwd()).resolve()
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
}


def customer_dir(slug):
    path = ROOT / "customers" / slug
    if not path.exists():
        sys.exit(f"고객 폴더가 없습니다: {path}  (/lf-intake 로 먼저 만드세요)")
    return path


def issue_dir_template():
    """Where issue folders live. Default customers/<slug>/issues/<send_date>.
    A root-level lf_settings.yaml can redirect them, e.g. in the Cowork engine folder
    where the folder name must match the Google Drive folder:
        issue_dir: 02_drafts/Vol{vol}_{mmdd}
    Placeholders: {slug} {send_date} {vol} {mmdd}. Relative to the project root."""
    settings = ROOT / "lf_settings.yaml"
    if settings.exists():
        data = yaml.safe_load(settings.read_text(encoding="utf-8")) or {}
        if data.get("issue_dir"):
            return str(data["issue_dir"])
    return "customers/{slug}/issues/{send_date}"


def issue_no_for(slug, send_date):
    """Vol number of an issue: profile.yaml issue_no_base {send_date, vol} plus the
    distance between the two dates in send_dates. None if it cannot be derived."""
    profile = load_yaml(customer_dir(slug) / "profile.yaml")
    base = profile.get("issue_no_base") or {}
    dates = [str(d) for d in profile.get("send_dates", [])]
    if str(base.get("send_date")) not in dates or str(send_date) not in dates:
        return None
    return int(base["vol"]) + dates.index(str(send_date)) - dates.index(str(base["send_date"]))


def resolve_issue_dir(slug, send_date, create=False):
    template = issue_dir_template()
    vol = issue_no_for(slug, send_date)
    if "{vol}" in template and vol is None:
        sys.exit(f"호 번호를 정할 수 없습니다: profile.yaml 의 send_dates 에 {send_date} 와 issue_no_base.send_date 가 모두 있어야 합니다.")
    mmdd = str(send_date)[5:7] + str(send_date)[8:10]
    path = ROOT / template.format(slug=slug, send_date=send_date, vol=vol, mmdd=mmdd)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def issue_dir(slug, send_date):
    return resolve_issue_dir(slug, send_date, create=True)


def load_env(required=("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")):
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("NAVER_", "STIBEE_"))})
    missing = [k for k in required if not env.get(k)]
    if missing:
        sys.exit(f".env 에 {', '.join(missing)} 값이 없습니다.")
    return env


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(data, path):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=4096)  # never fold issue.yaml log lines


def strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def holidays():
    data = load_yaml(PKG / "config" / "holidays_kr.yaml")
    days = set()
    for year_days in data.values():
        days.update(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)) for d in year_days)
    return days, set(data.keys())


def business_days_before(day, n):
    """Return the date n business days before `day` (weekends and holidays skipped)."""
    off, years = holidays()
    if day.year not in years:
        print(f"경고: {day.year}년 공휴일이 lf/config/holidays_kr.yaml 에 없습니다. 주말만 제외합니다.")
    current = day
    while n > 0:
        current -= dt.timedelta(days=1)
        if current.weekday() < 5 and current not in off:
            n -= 1
    return current
