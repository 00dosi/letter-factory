"""Create an issue folder and its business-day schedule (D-5 … D).

    python3 -m lf.new_issue <customer> <send_date YYYY-MM-DD> [--sample]
"""
import argparse
import datetime as dt

from lf.common import business_days_before, dump_yaml, issue_dir, issue_no_for

STEPS = [
    (5, "고객 소식 마감 · 자동 수집"),
    (4, "선별 · 원고 · HTML (에디터)"),
    (3, "완성본 납품"),
    (2, "1차 수정 회신"),
    (1, "2차 수정 회신"),
    (0, "고객 발송"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--sample", action="store_true", help="샘플 1호 (고객 소식 없음)")
    args = parser.parse_args()

    send = dt.date.fromisoformat(args.send_date)
    folder = issue_dir(args.customer, args.send_date)
    schedule = {
        ("D" if n == 0 else f"D-{n}"): {
            "date": (send if n == 0 else business_days_before(send, n)).isoformat(),
            "what": what,
        }
        for n, what in STEPS
    }
    meta = {
        "send_date": args.send_date,
        "kind": "sample" if args.sample else "regular",
        "deadline_cutoff": (send + dt.timedelta(days=1)).isoformat(),
        "schedule": schedule,
    }
    vol = issue_no_for(args.customer, args.send_date)
    if vol is not None:
        meta["issue_no"] = vol
    dump_yaml(meta, folder / "issue.yaml")
    print(f"{folder}")
    for key, step in schedule.items():
        print(f"  {key:>4}  {step['date']}  {step['what']}")


if __name__ == "__main__":
    main()
