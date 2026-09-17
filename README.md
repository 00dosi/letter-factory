# letter-factory — 레터팩토리 뉴스레터 제작 엔진

(주)공공도시 레터팩토리가 고객 소식지를 만드는 파이썬 스크립트 묶음과, 그것을 Claude 데스크톱·Cowork에서 도구로 쓰게 해 주는 MCP 서버다.
코드만 들어 있다. 고객 설정·API 키·호 폴더는 **데이터 폴더**(예: 구글 드라이브의 `00 뉴스레터 자동화`)에 따로 둔다.

## 설치 (Claude 데스크톱, PC마다 한 번)

1. [uv](https://docs.astral.sh/uv/) 설치: PowerShell에서 `winget install -e --id astral-sh.uv`
2. 처음 한 번 미리 받아 두기 (첫 실행은 파이썬과 패키지를 내려받아 1~2분 걸린다):
   ```
   uvx --from git+https://github.com/00dosi/letter-factory letter-factory-mcp --root "<데이터 폴더>"
   ```
   다운로드가 끝나면 입력을 기다리며 멈춘다. 정상이며 Ctrl+C 로 끝낸다.
3. `claude_desktop_config.json` 의 `mcpServers` 에 추가하고 앱을 완전히 재시작한다:
   ```json
   "dosirak-letter": {
     "command": "C:\\Users\\<사용자>\\.local\\bin\\uvx.exe",
     "args": ["--from", "git+https://github.com/00dosi/letter-factory", "letter-factory-mcp",
              "--root", "H:\\...\\00 뉴스레터 자동화"],
     "env": {"PYTHONUTF8": "1"}
   }
   ```
4. 새 버전을 받으려면 `uvx --refresh --from git+https://github.com/00dosi/letter-factory letter-factory-mcp --root "<데이터 폴더>"` 를 한 번 실행한다.

## MCP 도구

| 도구 | 하는 일 |
|---|---|
| `lf_run(name, args)` | 데이터 폴더에서 `python -m lf.<name> <args>` 실행. name: status · env_check · new_issue · naver_news · boards · prev_issue · digest · quality · blog · checks · render · stibee · sync |
| `read_text(path)` | 데이터 폴더 안 텍스트 파일 읽기 (`.env` 제외) |
| `write_text(path, content)` | 데이터 폴더 안에 텍스트 파일 쓰기 (`.env`·폴더 밖 거부) |
| `list_dir(path)` | 폴더 내용 나열 |

## 데이터 폴더 구조

```
<데이터 폴더>/
  .env                          NAVER_CLIENT_ID · NAVER_CLIENT_SECRET · (선택) STIBEE_API_KEY · STIBEE_LIST_ID
  lf_settings.yaml              (선택) 호 폴더 위치. 예 issue_dir: 02_drafts/Vol{vol}_{mmdd}
  customers/<slug>/profile.yaml 고객 정보·어조·코너·템플릿·발송일·호 번호
  customers/<slug>/sources.yaml 검색어·게시판·품질 규칙
  customers/<slug>/issues/<발송일>/   (기본 호 폴더) issue.yaml → candidates_*.json → digest → selection → draft.md → letter.html
```

## 개발

```
git clone https://github.com/00dosi/letter-factory
cd <데이터 폴더> && LF_ROOT=. python3 -m lf.status <slug>      # 또는 데이터 폴더에서 python3 -m lf.<name>
uv run lf/mcp_server.py --root <데이터 폴더>                    # MCP 서버를 체크아웃에서 바로
```

템플릿(`lf/templates/`, modern · public · warm · colorful)과 공휴일(`lf/config/holidays_kr.yaml`)은 패키지에 들어 있다.
