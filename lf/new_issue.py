"""Create an issue folder and its business-day schedule (D-5 … D).

    python3 -m lf.new_issue <customer> <send_date YYYY-MM-DD> [--sample]

issue.yaml is the issue's ledger (schedule, issue_no, work log, delivery/scheduling stamps
written by later steps). When it already exists nothing in it is overwritten: only keys it
lacks are added, and schedule counts as one key. A different send_date inside is an error.
"""
import argparse
import datetime as dt
import sys

from lf.common import business_days_before, dump_yaml, issue_dir, issue_no_for, load_yaml

STEPS = [
    (5, "고객 소식 마감 · 자동 수집"),
    (4, "선별 · 원고 · HTML (에디터)"),
    (3, "완성본 납품"),
    (2, "1차 수정 회신"),
    (1, "2차 수정 회신"),
    (0, "고객 발송"),
]


def defaults(customer, send_date, sample=False):
    """What a fresh issue.yaml holds for this send date."""
    send = dt.date.fromisoformat(send_date)
    meta = {
        "send_date": send_date,
        "kind": "sample" if sample else "regular",
        "deadline_cutoff": (send + dt.timedelta(days=1)).isoformat(),
        "schedule": {
            ("D" if n == 0 else f"D-{n}"): {
                "date": (send if n == 0 else business_days_before(send, n)).isoformat(),
                "what": what,
            }
            for n, what in STEPS
        },
    }
    vol = issue_no_for(customer, send_date)
    if vol is not None:
        meta["issue_no"] = vol
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--sample", action="store_true", help="샘플 1호 (고객 소식 없음)")
    args = parser.parse_args(argv)

    folder = issue_dir(args.customer, args.send_date)
    path = folder / "issue.yaml"
    fresh = defaults(args.customer, args.send_date, args.sample)
    if not path.exists():
        dump_yaml(fresh, path)
        meta, summary = fresh, f"새로 만듦: {path}"
    else:
        meta = load_yaml(path)
        if str(meta.get("send_date")) != args.send_date:
            sys.exit(f"issue.yaml 의 send_date({meta.get('send_date')})와 인자({args.send_date})가 다릅니다 — 다른 호 폴더인지 확인하세요")
        filled = [key for key in fresh if key not in meta]  # existing keys (log, schedule, stamps) are never touched
        for key in filled:
            meta[key] = fresh[key]
        if filled:
            dump_yaml(meta, path)
        summary = "기존 파일 유지, " + (f"채운 칸: {', '.join(filled)}" if filled else "채운 칸 없음")
    print(summary)
    for key, step in (meta.get("schedule") or {}).items():
        print(f"  {key:>4}  {step['date']}  {step['what']}")


if __name__ == "__main__":
    main()
