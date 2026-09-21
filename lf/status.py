"""Where is this issue? Reads the issue folder and prints the stage and the next step.

    python3 -m lf.status <customer> [send_date]

Without send_date: the first send date in profile.yaml on or after today.
Stage is decided only by which files exist, so any colleague can pick up a session.
"""
import datetime as dt
import json
import sys

from lf.common import ROOT, customer_dir, load_yaml, resolve_issue_dir

STAGES = [
    # (file, stage label, what to do next)
    ("issue.yaml", "0 호 폴더 생성", "1단계: 수집 (lf.naver_news → lf.boards → 직전 호 → lf.digest → lf.quality)"),
    ("candidates_news.json", "1a 뉴스 수집됨", "lf.boards, 직전 호 링크, lf.digest, lf.quality"),
    ("candidates_boards.json", "1b 게시판 수집됨", "직전 호 링크(prev_issue_urls.txt) → lf.digest → lf.quality"),
    ("prev_issue_urls.txt", "1c 직전 호 반영됨", "lf.digest → lf.quality"),
    ("digest_raw.md", "1d 다이제스트 원자료", "lf.quality → digest.md 작성해 담당자에게 제시"),
    ("quality.json", "1e 품질 검사됨", "digest_checked.md를 읽고 digest.md 작성 → 담당자 선택 대기"),
    ("digest.md", "1f 다이제스트 제시됨 — 담당자 선택 대기", "담당자의 선택·재게재·마감일 답을 받아 selection.md"),
    ("selection.md", "2a 선별 완료", "인사말 후보 4개 → 택1 → draft.md"),
    ("draft.md", "2b 원고 작성됨", "lf.checks 통과 → lf.render → lf.preview"),
    ("letter.html", "2c HTML 생성됨", "lf.stibee pack → Gmail 초안(본인) → 담당자 검수"),
    ("stibee.html", "2d 스티비 패키지 준비됨", "3단계: 주소록 동기화 → 스티비 등록 → 테스트 발송 → lf.stibee testmail → 대표 검수 → 예약"),
]


def stage_of(folder):
    """(stage label, next step, issue.yaml dict) decided only by which files exist."""
    stage, nxt = "시작 전", STAGES[0][2]
    for name, label, todo in STAGES:
        if (folder / name).exists():
            stage, nxt = label, todo
    meta = load_yaml(folder / "issue.yaml") if (folder / "issue.yaml").exists() else {}
    if meta.get("test_sent_at"):
        stage, nxt = "3a 테스트 발송 확인됨", "대표 검수 → 스티비 예약(월 07:30) → issue.yaml scheduled_at 기록"
    if meta.get("scheduled_at"):
        stage, nxt = "3b 예약 완료", "발송 후 Gmail 발송본으로 다음 호 직전 호 기준이 됩니다"
    return stage, nxt, meta


def env_line(today=None):
    """The 환경 line from env_check.json; a check older than today is marked stale."""
    env = ROOT / "env_check.json"
    if not env.exists():
        return "환경: 미점검 → python3 -m lf.env_check 먼저"
    e = json.loads(env.read_text(encoding="utf-8"))
    stale = e["checked_at"][:10] != (today or dt.date.today()).isoformat()
    return f"환경: {e['mode']} (점검 {e['checked_at'][:16]})" + (" (오래됨 — 오늘 다시 점검 권장)" if stale else "")


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "dosirak"
    cdir = customer_dir(slug)
    profile = load_yaml(cdir / "profile.yaml")
    today = dt.date.today()
    if len(sys.argv) > 2:
        send = sys.argv[2]
    else:
        upcoming = [d for d in profile.get("send_dates", []) if dt.date.fromisoformat(str(d)) >= today]
        if not upcoming:
            sys.exit("profile.yaml send_dates 에 오늘 이후 발송일이 없습니다. 발송일을 추가하세요.")
        send = str(upcoming[0])
    folder = resolve_issue_dir(slug, send)

    print(env_line())

    print(f"호: 발송일 {send} · 폴더 {folder.relative_to(ROOT)}")
    if not folder.exists():
        print("단계: 시작 전 → python3 -m lf.new_issue dosirak " + send)
        return
    stage, nxt, meta = stage_of(folder)
    checks = folder / "checks.json"
    if checks.exists():
        c = json.loads(checks.read_text(encoding="utf-8"))
        print(f"검사: 링크 {c['links']}개, 고칠 것 {len(c['problems'])}건, 직접 확인 {len(c['manual'])}건")
    print(f"단계: {stage}")
    print(f"다음: {nxt}")
    for key in ("issue_no", "collected_at", "delivered_at", "test_sent_at", "scheduled_at"):
        if meta.get(key):
            print(f"  {key}: {meta[key]}")
    log = meta.get("log") or []
    if log:
        print(f"마지막 작업자: {log[-1]}")
        if not str(log[-1]).rstrip().endswith("끝"):
            print("  (진행 중으로 기록됨 — 같은 사람이 아니면 계속할지 먼저 묻는다)")
    else:
        print("마지막 작업자: 기록 없음 (issue.yaml log: 에 '- 날짜 시각 이름 N단계 시작' 형식으로 남긴다)")


if __name__ == "__main__":
    main()
