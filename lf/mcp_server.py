"""MCP server (stdio) that lets Claude Desktop / Cowork run the lf scripts and read or
write text files inside a data folder — on the Windows host, so a Google Drive
streaming folder (H:) works as the data root.

Standard library only (no `mcp` package): the MCP stdio transport is newline-delimited
JSON-RPC 2.0 and the server needs four methods: initialize, tools/list, tools/call, ping.

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
import json
import os
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

TOOLS = [
    {
        "name": "lf_run",
        "description": "프로젝트 폴더 루트에서 `python -m lf.<name> <args...>` 를 실행하고 출력을 돌려준다. "
                       "name 은 " + ", ".join(SCRIPTS) + " 중 하나. 예: name='status', args=['dosirak'] / "
                       "name='stibee', args=['pack','dosirak','2026-09-28'].",
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


def lf_run(name, args=None):
    if name not in SCRIPTS:
        raise ValueError(f"모르는 스크립트: {name}")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", LF_ROOT=str(ROOT))
    proc = subprocess.run(
        [sys.executable, "-m", f"lf.{name}", *[str(a) for a in (args or [])]],
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
                "serverInfo": {"name": "dosirak-letter", "version": "1.0"}}
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
    args = parser.parse_args()
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
