"""MCP server (stdio) that lets Claude Desktop / Cowork run the lf scripts and read or
write text files inside a data folder — on the Windows host, so a Google Drive
streaming folder (H:) works as the data root.

Standard library only (no `mcp` package): the MCP stdio transport is newline-delimited
JSON-RPC 2.0 and the server needs four methods: initialize, tools/list, tools/call, ping.

Long steps (LONG_STEPS) take 2–3 minutes but the Cowork bridge drops a tool call after
about 60 s. So lf_run starts those in the background and returns at once; the model polls
lf_status. State lives in <issue folder>/_run/<step>.json (+ .log / .stderr.log), written
by a detached runner process (`mcp_server.py --run-step <json>`), so it is completed even
if this server is restarted mid-run. _run/ is raw material: never uploaded, never read whole.

    letter-factory-mcp --root "<data folder>"      # installed package (uvx --from git+... letter-factory-mcp)
    uv run lf/mcp_server.py --root "<data folder>" # from a checkout (inline metadata below)

The data folder holds customers/, .env, lf_settings.yaml and the issue folders. Code,
templates and holidays come with the package. Register in claude_desktop_config.json:
    "dosirak-letter": {"command": "C:\\Users\\user\\.local\\bin\\uvx.exe",
                       "args": ["--from", "https://github.com/00dosi/letter-factory/archive/refs/heads/main.zip",
                                "letter-factory-mcp", "--root", "H:\\...\\00 뉴스레터 자동화"],
                       "env": {"PYTHONUTF8": "1"}}
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "PyYAML", "Jinja2"]
# ///
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()  # set from --root / LF_ROOT in main()
PROTOCOL = "2025-06-18"
MAX_OUT = 40_000     # characters of script output returned to the model
MAX_READ = 200_000   # characters of a file returned to the model
SECRET_NAMES = {".env"}
SCRIPTS = ["status", "env_check", "new_issue", "naver_news", "boards", "prev_issue", "digest",
           "quality", "blog", "checks", "render", "stibee", "sync"]
LONG_STEPS = {"naver_news", "boards", "quality", "digest"}  # run detached; args start with <customer> <send_date>
RUN_DIR = "_run"            # <issue folder>/_run/<step>.json|.log|.stderr.log
STALE_MINUTES = 30          # "running" older than this with no live process → start again
TAIL_LINES = 20
LONG_TIMEOUT = 1800         # seconds before the runner gives up on a step
RUNS = {}                   # run_id → status file, for this server's lifetime (lf_status(run_id) fast path)

TOOLS = [
    {
        "name": "lf_run",
        "description": "프로젝트 폴더 루트에서 `python -m lf.<name> <args...>` 를 실행한다. "
                       "name 은 " + ", ".join(SCRIPTS) + " 중 하나. 예: name='status', args=['dosirak'] / "
                       "name='stibee', args=['pack','dosirak','2026-09-28']. "
                       "긴 단계(" + ", ".join(sorted(LONG_STEPS)) + ")는 백그라운드로 띄우고 즉시 "
                       "{run_id, status:'running'} 을 돌려준다 — 결과는 파일에만 쓰이며 lf_status 로 끝났는지 확인한다. "
                       "이미 도는 중이면 status:'already_running' 이 온다. 타임아웃 오류가 떠도 같은 명령을 다시 던지지 말고 lf_status 를 부른다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": SCRIPTS},
                "args": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["name"],
        },
    },
    {
        "name": "lf_status",
        "description": "백그라운드로 띄운 긴 단계의 상태를 돌려준다 (running / done / failed, exit_code, 출력 마지막 20줄). "
                       "run_id 로 찾거나, step + customer + send_date 로 찾는다. 1초 안에 끝난다. "
                       "failed 면 stderr_tail 을 보고 담당자에게 보고한다. 결과 데이터는 호 폴더의 파일에서 읽는다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "step": {"type": "string", "enum": sorted(LONG_STEPS)},
                "customer": {"type": "string"},
                "send_date": {"type": "string"},
            },
        },
    },
    {
        "name": "read_text",
        "description": "프로젝트 폴더 안의 텍스트 파일을 읽는다 (경로는 루트 기준 상대 경로, 예 '02_drafts/Vol21_0928/digest_checked.md'). .env 는 읽지 않는다.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_text",
        "description": "프로젝트 폴더 안에 텍스트 파일을 쓴다(덮어쓰기, 상위 폴더 자동 생성). 경로는 루트 기준 상대 경로. .env 와 폴더 밖은 거부한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "프로젝트 폴더 안의 폴더 내용을 이름·크기·수정 시각과 함께 나열한다. path 를 비우면 루트.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": ""}}},
    },
]


def safe_path(rel):
    path = (ROOT / rel).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"프로젝트 폴더 밖입니다: {rel}")
    if path.name in SECRET_NAMES:
        raise ValueError(f"{path.name} 은 읽거나 쓰지 않습니다")
    return path


def script_env():
    return dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", LF_ROOT=str(ROOT))


def common():
    """lf.common, imported after ROOT is known (it reads LF_ROOT at import time)."""
    os.environ["LF_ROOT"] = str(ROOT)
    try:
        import lf.common as mod
    except ImportError:  # run as a bare script from a checkout: lf/ is on sys.path, its parent is not
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import lf.common as mod
    return mod


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def tail(path, n=TAIL_LINES):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def pid_alive(pid):
    """True if a process with this id exists. On Windows os.kill(pid, 0) would *terminate*
    it, so ask the kernel for the exit code instead."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def status_file_for(step, customer, send_date, create=False):
    folder = common().resolve_issue_dir(customer, send_date, create=create)
    return folder / RUN_DIR / f"{step}.json"


def describe(status_path):
    """The status JSON plus what the model needs to act on it (paths, liveness)."""
    data = read_json(status_path)
    if data is None:
        raise FileNotFoundError(f"실행 기록이 없습니다: {rel(status_path)}")
    data["status_file"] = rel(status_path)
    if data.get("status") == "running":
        data["process_alive"] = pid_alive(data.get("pid"))
    proc = RUNS.get(data.get("run_id"), {}).get("proc")
    if proc is not None:
        proc.poll()  # reap the runner once it exits (POSIX zombies)
    return data


def start_long(name, args):
    if len(args) < 2:
        raise ValueError(f"{name} 은 <customer> <send_date> 인자가 필요합니다")
    customer, send_date = args[0], args[1]
    status_path = status_file_for(name, customer, send_date, create=True)
    status_path.parent.mkdir(exist_ok=True)
    previous = read_json(status_path)
    if previous and previous.get("status") == "running":
        alive = pid_alive(previous.get("pid"))
        try:
            started = dt.datetime.fromisoformat(previous["started_at"])
            age_min = (dt.datetime.now().astimezone() - started).total_seconds() / 60
        except (KeyError, ValueError):
            age_min = STALE_MINUTES + 1
        if alive or age_min <= STALE_MINUTES:
            return {"status": "already_running", "run_id": previous.get("run_id"), "step": name,
                    "started_at": previous.get("started_at"), "process_alive": alive,
                    "status_file": rel(status_path), "hint": "새로 띄우지 않았습니다. lf_status 로 확인하세요."}
        # stale: no process and too old — treat the old record as failed and start again
        previous.update(status="failed", finished_at=now_iso(),
                        stderr_tail=(previous.get("stderr_tail") or "") + "\n[프로세스가 사라져 stale 처리]")
        write_json(status_path.with_name(f"{name}.stale-{previous.get('run_id', 'x')}.json"), previous)

    run_id = f"{name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    log, err = status_path.with_suffix(".log"), status_path.with_suffix(".stderr.log")
    record = {
        "run_id": run_id, "step": name, "status": "running",
        "started_at": now_iso(), "finished_at": None, "exit_code": None,
        "stdout_tail": "", "stderr_tail": "",
        "pid": None, "customer": customer, "send_date": send_date,
        "command": [sys.executable, "-m", f"lf.{name}", *[str(a) for a in args]],
        "cwd": str(ROOT), "timeout": LONG_TIMEOUT, "log": rel(log), "stderr_log": rel(err),
    }
    write_json(status_path, record)
    kwargs = {"creationflags": 0x08000000 | 0x00000200} if os.name == "nt" else {"start_new_session": True}  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--run-step", str(status_path)],
        cwd=ROOT, env=script_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs,
    )
    record["pid"] = proc.pid
    write_json(status_path, record)
    RUNS[run_id] = {"path": status_path, "proc": proc}
    return {"status": "running", "run_id": run_id, "step": name, "started_at": record["started_at"],
            "status_file": rel(status_path), "log": rel(log),
            "hint": "백그라운드 실행 중. lf_status(run_id) 로 확인. 타임아웃이 떠도 다시 띄우지 마세요."}


def run_step(status_path):
    """Runner process: execute the recorded command, stream output to the log files,
    then finish the status JSON. Runs detached from the MCP server."""
    status_path = Path(status_path)
    record = read_json(status_path) or {}
    log = status_path.with_suffix(".log")
    err = status_path.with_suffix(".stderr.log")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", LF_ROOT=record.get("cwd", str(ROOT)))
    note = ""
    try:
        with open(log, "w", encoding="utf-8") as out, open(err, "w", encoding="utf-8") as errf:
            proc = subprocess.run(record["command"], cwd=record.get("cwd"), env=env, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=errf, timeout=record.get("timeout", LONG_TIMEOUT))
        code = proc.returncode
    except subprocess.TimeoutExpired:
        code, note = -1, f"[{record.get('timeout', LONG_TIMEOUT)}초 초과로 중단]"
    except Exception as e:  # noqa: BLE001
        code, note = -2, f"[runner 오류] {type(e).__name__}: {e}"
    record = read_json(status_path) or record
    record.update(status="done" if code == 0 else "failed", exit_code=code, finished_at=now_iso(),
                  stdout_tail=tail(log), stderr_tail=(tail(err) + ("\n" + note if note else "")).strip())
    write_json(status_path, record)


def lf_status(run_id=None, step=None, customer=None, send_date=None):
    if run_id:
        if run_id in RUNS:
            return describe(RUNS[run_id]["path"])
        pattern = re.sub(r"\{\w+\}", "*", common().issue_dir_template()) + f"/{RUN_DIR}/*.json"
        for path in ROOT.glob(pattern):
            data = read_json(path)
            if data and data.get("run_id") == run_id:
                return describe(path)
        raise FileNotFoundError(f"run_id 를 찾지 못했습니다: {run_id}")
    if step and customer and send_date:
        return describe(status_file_for(step, customer, send_date))
    raise ValueError("run_id 또는 step+customer+send_date 가 필요합니다")


def lf_run(name, args=None):
    if name not in SCRIPTS:
        raise ValueError(f"모르는 스크립트: {name}")
    args = [str(a) for a in (args or [])]
    if name in LONG_STEPS:
        return json.dumps(start_long(name, args), ensure_ascii=False, indent=2), False
    env = script_env()
    proc = subprocess.run(
        [sys.executable, "-m", f"lf.{name}", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    out = proc.stdout
    if proc.stderr.strip():
        out += ("\n[stderr]\n" if out else "[stderr]\n") + proc.stderr
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n… (출력 {len(out)}자 중 앞 {MAX_OUT}자만)"
    return f"[exit {proc.returncode}]\n{out}".rstrip(), proc.returncode != 0


def read_text(path):
    text = safe_path(path).read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ:
        text = text[:MAX_READ] + f"\n… (파일 {len(text)}자 중 앞 {MAX_READ}자만)"
    return text


def write_text(path, content):
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"저장: {target.relative_to(ROOT)} ({len(content)}자)"


def list_dir(path=""):
    folder = safe_path(path or ".")
    rows = []
    for p in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
        if p.name in SECRET_NAMES or p.name == "__pycache__":
            continue
        st = p.stat()
        when = __import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        rows.append(f"{'📁' if p.is_dir() else '  '} {p.name:<40} {'' if p.is_dir() else st.st_size:>8} {when}")
    return "\n".join(rows) or "(빈 폴더)"


def call_tool(name, arguments):
    a = arguments or {}
    if name == "lf_run":
        return lf_run(a.get("name"), a.get("args"))
    if name == "lf_status":
        return json.dumps(lf_status(a.get("run_id"), a.get("step"), a.get("customer"), a.get("send_date")),
                          ensure_ascii=False, indent=2), False
    if name == "read_text":
        return read_text(a["path"]), False
    if name == "write_text":
        return write_text(a["path"], a["content"]), False
    if name == "list_dir":
        return list_dir(a.get("path", "")), False
    raise ValueError(f"모르는 도구: {name}")


def handle(msg):
    method, params, mid = msg.get("method"), msg.get("params") or {}, msg.get("id")
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dosirak-letter", "version": "1.1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            text, is_error = call_tool(params.get("name"), params.get("arguments"))
        except Exception as e:  # noqa: BLE001 — errors go back to the model as tool errors
            text, is_error = f"{type(e).__name__}: {e}", True
        return {"content": [{"type": "text", "text": text}], "isError": is_error}
    if mid is None:  # notifications (e.g. notifications/initialized) need no reply
        return None
    raise LookupError(method)


def main():
    global ROOT
    parser = argparse.ArgumentParser(description="letter-factory MCP server (stdio)")
    parser.add_argument("--root", default=os.environ.get("LF_ROOT"), help="데이터 폴더 (customers/, .env, 호 폴더). 기본값: LF_ROOT 또는 현재 폴더")
    parser.add_argument("--run-step", metavar="STATUS_JSON", help=argparse.SUPPRESS)  # internal: detached runner
    args = parser.parse_args()
    if args.run_step:
        run_step(args.run_step)
        return
    ROOT = Path(args.root or Path.cwd()).resolve()
    if not (ROOT / "customers").is_dir():
        sys.exit(f"--root 에 customers/ 폴더가 없습니다: {ROOT}")
    stdin = open(sys.stdin.fileno(), encoding="utf-8", errors="replace")
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = msg.get("id")
        try:
            result = handle(msg)
            if mid is None:
                continue
            reply = {"jsonrpc": "2.0", "id": mid, "result": result}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {e}"}}
        except Exception as e:  # noqa: BLE001
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    main()
