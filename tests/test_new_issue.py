"""new_issue must never overwrite an existing issue.yaml: it only fills missing keys."""
import pytest
import yaml

import lf.common as common
from lf.new_issue import main

SEND = "2026-09-28"


@pytest.fixture
def root(tmp_path, monkeypatch):
    customer = tmp_path / "customers" / "t"
    customer.mkdir(parents=True)
    (customer / "profile.yaml").write_text(f"send_dates: ['{SEND}']\nissue_no_base: {{send_date: '{SEND}', vol: 21}}\n", encoding="utf-8")
    monkeypatch.setattr(common, "ROOT", tmp_path)
    return tmp_path


def issue_file(root):
    return root / "customers" / "t" / "issues" / SEND / "issue.yaml"


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_creates_file_with_six_step_schedule(root, capsys):
    main(["t", SEND])
    meta = read(issue_file(root))
    assert meta["send_date"] == SEND and meta["issue_no"] == 21 and meta["deadline_cutoff"] == "2026-09-29"
    assert list(meta["schedule"]) == ["D-5", "D-4", "D-3", "D-2", "D-1", "D"]
    assert capsys.readouterr().out.startswith("새로 만듦: ")


def test_existing_log_schedule_and_stamps_survive_rerun(root, capsys):
    path = issue_file(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        f"send_date: '{SEND}'\nkind: regular\ndeadline_cutoff: '2026-09-29'\n"
        "schedule:\n  D-7:\n    date: '2026-09-15'\n    what: 연휴 전 미리 수집\n  D:\n    date: '2026-09-28'\n    what: 고객 발송\n"
        "issue_no: 21\nscheduled_at: '2026-09-26T09:00:00+09:00'\n"
        "log:\n- 2026-09-15 10:00 김 1단계 시작\n- 2026-09-15 12:00 김 1단계 끝\n- 2026-09-17 09:30 박 2단계 시작\n",
        encoding="utf-8",
    )
    original = path.read_bytes()
    before = read(path)
    main(["t", SEND])
    after = read(path)
    assert after == before
    assert path.read_bytes() == original  # nothing was written
    assert list(after) == list(before)
    assert capsys.readouterr().out.splitlines()[0] == "기존 파일 유지, 채운 칸 없음"


def test_fills_only_missing_issue_no(root, capsys):
    path = issue_file(root)
    path.parent.mkdir(parents=True)
    path.write_text(f"send_date: '{SEND}'\nkind: regular\ndeadline_cutoff: '2026-09-29'\nschedule:\n  D:\n    date: '{SEND}'\n    what: 고객 발송\nlog:\n- 2026-09-15 10:00 김 1단계 시작\n", encoding="utf-8")
    before = read(path)
    main(["t", SEND])
    after = read(path)
    assert after.pop("issue_no") == 21
    assert after == before
    assert list(after) == list(before)
    assert capsys.readouterr().out.splitlines()[0] == "기존 파일 유지, 채운 칸: issue_no"


def test_send_date_mismatch_exits_without_writing(root, capsys):
    path = issue_file(root)
    path.parent.mkdir(parents=True)
    original = "send_date: '2026-09-21'\nlog:\n- 2026-09-15 10:00 김 1단계 시작\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["t", SEND])
    assert exc.value.code == "issue.yaml 의 send_date(2026-09-21)와 인자(2026-09-28)가 다릅니다 — 다른 호 폴더인지 확인하세요"
    assert path.read_bytes() == original.encode("utf-8")


def test_log_entries_with_colon_space_stay_strings(root):
    path = issue_file(root)
    path.parent.mkdir(parents=True)
    entries = ["- 10:40 담당자 1단계 끝", "2026-09-21 10:40 김 1단계 시작: 수집", "10:40 담당자 1단계 끝"]
    path.write_text(yaml.safe_dump({"send_date": SEND, "log": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    main(["t", SEND])  # fills kind/deadline_cutoff/schedule/issue_no, so the file is re-saved
    after = read(path)
    assert after["log"] == entries and all(isinstance(e, str) for e in after["log"])
    assert after["issue_no"] == 21
