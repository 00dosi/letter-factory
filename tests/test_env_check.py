"""env_check must finish and save env_check.json even with a {vol} issue-folder rule or a crashing check. No network."""
import datetime as dt
import json

import pytest

import lf.common as common
import lf.env_check as env_check
import lf.status as status


class FakeResponse:
    status_code = 200
    text = "<html>" + "x" * 3000 + "</html>"

    def json(self):
        return {"country": "KR", "ip": "1.2.3.4"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "lf_settings.yaml").write_text("issue_dir: 02_drafts/Vol{vol}_{mmdd}\n", encoding="utf-8")
    customer = tmp_path / "customers" / "dosirak"
    customer.mkdir(parents=True)
    (customer / "profile.yaml").write_text("send_dates: ['2026-09-28']\n", encoding="utf-8")
    for module in (common, env_check, status):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    return tmp_path


def test_vol_rule_runs_to_the_end_and_saves(root, capsys):
    env_check.main(["dosirak"])
    saved = json.loads((root / "env_check.json").read_text(encoding="utf-8"))
    names = [r["check"] for r in saved["rows"]]
    assert "폴더 쓰기" in names and "게시판 NABIS 채용공고" in names
    write = next(r for r in saved["rows"] if r["check"] == "폴더 쓰기")
    assert write["ok"] and write["detail"] == str(root / "02_drafts")
    assert (root / "02_drafts").is_dir() and not list((root / "02_drafts").iterdir())  # parent made, no fake issue folder
    assert "판정:" in capsys.readouterr().out


def test_default_rule_probes_customer_issues_folder(root):
    (root / "lf_settings.yaml").unlink()
    assert env_check.issues_parent("dosirak") == root / "customers" / "dosirak" / "issues"


def test_crashing_network_check_is_recorded_and_others_continue(root, monkeypatch):
    def get(url, *a, **k):
        if "ipinfo" in url:
            raise RuntimeError("boom")
        return FakeResponse()

    monkeypatch.setattr("requests.get", get)
    env_check.main(["dosirak"])
    saved = json.loads((root / "env_check.json").read_text(encoding="utf-8"))
    by = {r["check"]: r for r in saved["rows"]}
    assert by["나가는 IP 국가"]["ok"] is False and "RuntimeError" in by["나가는 IP 국가"]["detail"]
    assert by["게시판 NABIS 채용공고"]["ok"] is True


def test_status_marks_old_check_as_stale(root):
    today = dt.date(2026, 9, 21)
    (root / "env_check.json").write_text(json.dumps({"checked_at": "2026-09-21T09:00:00", "mode": "스크립트 모드", "rows": []}), encoding="utf-8")
    assert status.env_line(today) == "환경: 스크립트 모드 (점검 2026-09-21T09:00)"
    (root / "env_check.json").write_text(json.dumps({"checked_at": "2026-09-20T09:00:00", "mode": "스크립트 모드", "rows": []}), encoding="utf-8")
    assert status.env_line(today) == "환경: 스크립트 모드 (점검 2026-09-20T09:00) (오래됨 — 오늘 다시 점검 권장)"
