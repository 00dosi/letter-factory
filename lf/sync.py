"""Bookkeeping for copying an issue's human-facing files to the Google Drive folder.

Cowork's shell sees only the PC engine folder; the Drive folder (H:) is reached through
the Google Drive connector, and each upload passes the file through the model once.
So: upload only the files people read, only when they changed, exactly once (the v3 lesson).

    python3 -m lf.sync plan <customer> <send_date>                     what to upload now
    python3 -m lf.sync mark <customer> <send_date> <file> <drive_id>   after each upload
    python3 -m lf.sync mark <customer> <send_date> --folder <folder_id>
    python3 -m lf.sync pulled <customer> <send_date> <file>            after copying a Drive-side edit into the PC folder

State lives in <issue>/_status.json (stage, log, Drive ids); it is always uploaded last.
"""
import argparse
import datetime as dt
import json

from lf.common import ROOT, resolve_issue_dir
from lf.status import stage_of

MANIFEST = [  # (file, mime) — the only files that cross the connector
    ("issue.yaml", "text/yaml"),
    ("digest.md", "text/markdown"),
    ("quality.md", "text/markdown"),
    ("selection.md", "text/markdown"),
    ("draft.md", "text/markdown"),
    ("checks.json", "application/json"),
    ("letter.html", "text/html"),
    ("stibee.html", "text/html"),
    ("stibee_blocks.md", "text/markdown"),
]
STATUS = "_status.json"
STATUS_MIME = "application/json"


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_status(folder):
    path = folder / STATUS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_status(folder, status):
    stage, nxt, meta = stage_of(folder)
    log = meta.get("log") or []
    status.update(
        {
            "send_date": meta.get("send_date"),
            "issue_no": meta.get("issue_no"),
            "folder": folder.name,
            "stage": stage,
            "next": nxt,
            "last_log": log[-1] if log else None,
            "updated_at": now(),
        }
    )
    status.setdefault("uploads", {})
    (folder / STATUS).write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def mtime(path):
    return dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def plan(args):
    folder = resolve_issue_dir(args.customer, args.send_date)
    if not folder.exists():
        raise SystemExit(f"호 폴더가 없습니다: {folder}")
    status = save_status(folder, load_status(folder))
    uploads = status["uploads"]
    drive_folder = status.get("drive_folder_id")
    print(f"PC 폴더: {folder.relative_to(ROOT)}")
    if drive_folder:
        print(f"드라이브 폴더: {folder.name} (id {drive_folder})")
    else:
        print(f"드라이브 폴더: 아직 없음 → 02_drafts 아래에 '{folder.name}' 폴더를 만들고 "
              f"python3 -m lf.sync mark {args.customer} {args.send_date} --folder <id>")
    todo, current = [], []
    for name, mime in MANIFEST:
        path = folder / name
        if not path.exists():
            continue
        rec = uploads.get(name)
        if rec and dt.datetime.fromisoformat(rec["at"]) >= mtime(path):
            current.append(f"  {name:<18} id {rec['id']}  올린 시각 {rec['at'][:16]}")
        else:
            how = f"기존 id {rec['id']} 를 휴지통으로 보낸 뒤 새로 만들기" if rec else "새로 만들기"
            todo.append((name, mime, how))
    rec = uploads.get(STATUS)
    todo.append((STATUS, STATUS_MIME, ("기존 id %s 를 휴지통으로 보낸 뒤 " % rec["id"] if rec else "") + "마지막에 새로 만들기"))
    print(f"올릴 것 {len(todo)}개 — create_file(parentId=드라이브 폴더 id, title=파일 이름, contentMimeType, "
          f"disableConversionToGoogleType=true, textContent=파일 내용 그대로):")
    for name, mime, how in todo:
        print(f"  {name:<18} {mime:<18} {how}")
    print(f"올릴 때마다: python3 -m lf.sync mark {args.customer} {args.send_date} <파일> <새 id>")
    if current:
        print("이미 최신 (드라이브 modifiedTime 이 '올린 시각'보다 늦으면 사람이 드라이브에서 고친 것 → "
              f"내려받아 PC 폴더에 덮어쓰고 python3 -m lf.sync pulled {args.customer} {args.send_date} <파일>):")
        print("\n".join(current))


def mark(args):
    folder = resolve_issue_dir(args.customer, args.send_date)
    status = load_status(folder)
    if args.folder:
        status["drive_folder_id"] = args.folder
    if args.file:
        if not args.drive_id:
            raise SystemExit("드라이브 파일 id 가 필요합니다")
        status.setdefault("uploads", {})[args.file] = {"id": args.drive_id, "at": now()}
    save_status(folder, status)
    print(f"기록: {args.file or '드라이브 폴더'} → {args.drive_id or args.folder}")


def pulled(args):
    folder = resolve_issue_dir(args.customer, args.send_date)
    status = load_status(folder)
    rec = status.get("uploads", {}).get(args.file)
    if not rec:
        raise SystemExit(f"{args.file} 은 올린 기록이 없습니다. 내려받은 파일이면 mark 로 id 를 기록하세요.")
    rec["at"] = now()
    save_status(folder, status)
    print(f"기록: {args.file} 드라이브 판을 PC 폴더에 반영함 ({rec['at'][:16]})")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("customer"); p.add_argument("send_date"); p.set_defaults(fn=plan)
    p = sub.add_parser("mark"); p.add_argument("customer"); p.add_argument("send_date")
    p.add_argument("file", nargs="?"); p.add_argument("drive_id", nargs="?"); p.add_argument("--folder"); p.set_defaults(fn=mark)
    p = sub.add_parser("pulled"); p.add_argument("customer"); p.add_argument("send_date"); p.add_argument("file"); p.set_defaults(fn=pulled)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
