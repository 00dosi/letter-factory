# letter-factory — 레터팩토리 뉴스레터 제작 엔진

(주)공공도시 레터팩토리가 고객 소식지를 만드는 파이썬 스크립트 묶음과, 그것을 Claude 데스크톱·Cowork에서 도구로 쓰게 해 주는 MCP 서버다.
코드만 들어 있다. 고객 설정·API 키·호 폴더는 **데이터 폴더**(예: 구글 드라이브의 `00 뉴스레터 자동화`)에 따로 둔다.

## 설치 (Claude 데스크톱, PC마다 한 번)

1. [uv](https://docs.astral.sh/uv/) 설치: PowerShell에서 `winget install -e --id astral-sh.uv`. Git·파이썬은 필요 없다(zip 아카이브로 받고, 파이썬은 uv가 내려받는다). uvx.exe 위치는 `where uvx` 또는 winget 패키지 폴더 `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_…\uvx.exe`
2. 처음 한 번 미리 받아 두기 (첫 실행은 파이썬과 패키지를 내려받아 1~2분 걸린다):
   ```
   uvx --from https://github.com/00dosi/letter-factory/archive/refs/heads/main.zip letter-factory-mcp --root "<데이터 폴더>"
   ```
   다운로드가 끝나면 입력을 기다리며 멈춘다. 정상이며 Ctrl+C 로 끝낸다.
3. `claude_desktop_config.json` 의 `mcpServers` 에 추가하고 앱을 완전히 재시작한다:
   ```json
   "dosirak-letter": {
     "command": "C:\\Users\\<사용자>\\AppData\\Local\\Microsoft\\WinGet\\Packages\\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\\uvx.exe",
     "args": ["--from", "https://github.com/00dosi/letter-factory/archive/refs/heads/main.zip", "letter-factory-mcp",
              "--root", "H:\\...\\00 뉴스레터 자동화"],
     "env": {"PYTHONUTF8": "1"}
   }
   ```
4. 새 버전을 받으려면 `uvx --refresh --from https://github.com/00dosi/letter-factory/archive/refs/heads/main.zip letter-factory-mcp --root "<데이터 폴더>"` 를 한 번 실행한다.

## MCP 도구

| 도구 | 하는 일 |
|---|---|
| `lf_run(name, args)` | 데이터 폴더에서 `python -m lf.<name> <args>` 실행. name: status · env_check · new_issue · naver_news · boards · prev_issue · digest · quality · blog · checks · render · stibee · sync. **긴 단계(naver_news · boards · quality · digest)는 백그라운드로 띄우고 즉시 `{run_id, status: running}`을 돌려준다** — Cowork 브리지가 도구 호출을 약 60초만 기다리기 때문. 같은 단계가 도는 중이면 `already_running` |
| `lf_status(run_id)` 또는 `lf_status(step, customer, send_date)` | 백그라운드 단계의 상태: running / done / failed, exit_code, 출력 마지막 20줄. 기록은 `<호 폴더>/_run/<단계>.json`(+ `.log`, `.stderr.log`). 프로세스가 없고 30분 넘게 running이면 stale로 보고 다시 띄운다 |
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
                                    _run/  백그라운드 단계의 상태·로그 (원자료, 드라이브에 올리지 않음)
```

## draft.md 형식

머리말(`---` 사이, title · issue_label · preheader · send_date · footer) 뒤에 본문. `title`이 비면 `checks`가 "고칠 것"으로 잡는다.

```
## 코너 제목                 섹션
### 소제목                   섹션 안 소제목
- (매체) [제목](링크)         목록 (연속된 줄이 한 목록)
> 강조 문단                  회색 강조 상자
일반 문단                    문단 (빈 줄로 구분). 인라인 [글자](링크), **굵게**
![alt](이미지)               이미지 한 장 (본문 폭). [![alt](이미지)](링크) 로 감쌀 수 있다
:::card                      2단 카드: 왼쪽 이미지 · 오른쪽 글 (블로그 소개, 홍보 배너)
[![대표 이미지](이미지)](글 링크)   첫 줄 = 이미지(선택). 없으면 글만 있는 카드
소개문 첫 단락.

소개문 둘째 단락.
👉 ['…편' 보러가기](글 링크)   같은 단락 안의 줄은 <br> 로 이어진다
:::
```

카드는 `display:inline-block` 두 칸(이미지 240px · 글 276px)이라 좁은 화면에서 세로로 쌓이고, Outlook 용 조건부 표가 같이 들어간다.
`lf.stibee pack`은 카드 이미지를 480px JPEG(품질 80) base64 로 `stibee.html`에 내장한다. 내려받기에 실패한 이미지는 URL 을 유지하고 경고한다.

## 도시락레터 템플릿 (`template: dosirak`)

Vol.20 발송본 실측(`customers/dosirak/design_spec_vol20.md`) 기준. `## 코너 제목`을 profile.yaml `sections[].title`과 맞춰
key(greeting · own_news · news · opinion · notices)별로 다른 모양을 그린다. 고정 이미지·버튼·푸터는 profile.yaml에서 읽는다:

```yaml
template: dosirak
design:
  logo_url: https://img2.stibee.com/...      # 도시락 아이콘 + Dosirak Letter (폭 408)
  slogan_url: https://img2.stibee.com/...    # 손글씨 슬로건 (폭 360)
  skyline_url: https://img2.stibee.com/...   # 인사말 박스 도시 실루엣 (폭 570)
  leaf_url: https://img2.stibee.com/...      # 인사말 뒤 잎 아이콘 (폭 40)
  dove_url: https://img2.stibee.com/...      # 공공도시 소식 뒤 비둘기 (폭 42)
  tagline_url: https://img2.stibee.com/...   # "바쁜 일상 속에서도…" 글자 이미지 (폭 412)
  org_logo_url: https://img2.stibee.com/...  # 꼬리 공공도시 로고 (폭 412)
footer:
  cta_lines: [부담스러운 정책 변화, 막막한 실무, 공공도시가 최고의 길을 함께 고민하겠습니다.]
  cta: {text: 👉 막막한 실무 고민, 프로젝트 문의하기, url: https://00dosi.co.kr}
  orgs:
    - {name: 주식회사 공공도시, address: 서울특별시 동대문구 서울시립대로 117, 206호}
    - {name: 도시정책데이터연구소, address: 인천광역시 서구 원당대로 1035, 306호}
  contact: {h: https://00dosi.co.kr, e: contact@00dosi.co.kr, p: (02)-6925-5251}
  submit: {text: 🙋도시락레터에 전하고 싶은 소식이 있으신가요?🙋, button: 👉 내 소식 도시락에 담기, url: https://...}
  sns:
    - {icon: https://img2.stibee.com/....png, url: https://00dosi.co.kr}
    - {icon: https://img2.stibee.com/....png, url: https://www.facebook.com/...}
```

카드는 왼쪽 이미지 300px · 오른쪽 글. 두 칸은 inline-block 이라 좁은 화면에서 줄바꿈되고, 줄바꿈된 칸은 가운데 정렬된다(미디어쿼리 없음).

스티비 규칙(help.stibee.com/email/edit/html): HTML 편집기는 `<script> <head> <body> <html> <style> <form> <input> <button> <noscript> <meta> <iframe>` 와 `onclick` 같은 이벤트 속성을 받지 않는다.
`lf.stibee pack`은 letter.html 에서 본문 표만 남긴 `stibee.html`을 만들고, 금지 태그가 남으면 "고칠 것"으로 보고하며 exit 1.
템플릿에는 스티비 치환자가 고정으로 들어간다: 머리 안내 `$%permalink%$`, 푸터 `$%unsubscribe%$`(일반 URL 을 넣으면 수신거부가 작동하지 않는다).
원고에도 `$%name%$` 같은 치환자를 쓸 수 있고, render·checks 는 이를 그대로 둔다.

## 개발

```
git clone https://github.com/00dosi/letter-factory
cd <데이터 폴더> && LF_ROOT=. python3 -m lf.status <slug>      # 또는 데이터 폴더에서 python3 -m lf.<name>
uv run lf/mcp_server.py --root <데이터 폴더>                    # MCP 서버를 체크아웃에서 바로
```

템플릿(`lf/templates/`, modern · public · warm · colorful)과 공휴일(`lf/config/holidays_kr.yaml`)은 패키지에 들어 있다.
