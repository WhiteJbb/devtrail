# Work Agent — Blog Agent MVP

내 실제 작업 흔적(로컬 문서 · Git 로그 · Notion 메모)을 읽어 기술 블로그 **초안**을 빠르게 만들어 주는 CLI 도구입니다.

"완성형 블로그 자동 발행기"가 아니라, **70~80점짜리 초안을 만들어 5~10분 다듬으면 게시할 수 있게** 하는 것이 목표입니다. LLM은 창작자가 아니라 **작업 기록 정리자**로 동작하며, source에 없는 사실·수치는 만들지 않습니다.

## 흐름

```text
입력                          처리                       출력
Notion 정리 문서(페이지 본문)   →   기술 블로그 초안 생성   →   티스토리 붙여넣기용(HTML/MD)
로컬 docs / Git 로그                (source 기반, 과장 없음)     workspace/blogs/
                                                            + Notion Blog DB(상태 추적)
```

- **Notion = 입력**: 정리해 둔 문서(페이지 본문/블록)를 읽어 초안의 근거로 씁니다.
- **티스토리 = 출력**: 글쓰기 화면에 바로 붙여넣을 HTML/마크다운으로 변환합니다. (티스토리 공식 API는 2024년 종료되어 자동 게시는 지원하지 않습니다.)
- **Notion Blog DB**는 초안 상태(idea→draft→review→published) 추적용으로 함께 씁니다.

이 프로젝트는 개인 생산성 Agent의 첫 모듈이며, 이후 Portfolio / Resume / Todo / Worklog Agent로 확장 가능한 계층 구조로 설계되었습니다.

---

## 1. MVP 범위

| 명령 | 설명 |
| --- | --- |
| `work-agent ask "..."` | 자연어 문장을 해석해 알맞은 명령을 실행(실행 전 확인) |
| `work-agent suggest-topics` | 최근 작업 기록·Git 로그·Notion 메모로 블로그 주제 추천 |
| `work-agent list` | 저장된 초안을 상태/수정일과 함께 목록 출력 |
| `work-agent write-draft "주제"` | 주제로 초안 생성 → `workspace/drafts/`에 Markdown 저장 + Notion 반영 |
| `work-agent revise latest` | 기존 초안을 source 범위 안에서 문장/구조만 다듬기(새 사실 추가 없음) |
| `work-agent preview latest` | 최신(또는 slug 지정) 초안의 메타데이터 + 본문 일부 |
| `work-agent export-tistory latest` | 초안을 티스토리 붙여넣기용(HTML/MD)으로 변환 → `workspace/blogs/` |
| `work-agent publish-done latest --url <주소>` | 티스토리 게시 완료 기록(status=published + URL → 로컬·Notion) |
| `work-agent sync-notion` | 로컬 draft 메타데이터를 Notion Blog DB와 동기화(상태 추적) |
| `work-agent worklog` | 최근 작업(git/worklog/notion)을 자동 회고로 정리 → `workspace/worklogs/` |
| `work-agent todo` | 최근 작업 기반 다음 할 일 제안 → `workspace/todos/` |
| `work-agent portfolio` | 프로젝트 기록 기반 포트폴리오 설명 초안 → `workspace/portfolio/` |
| `work-agent resume` | 작업 기록 기반 이력서 bullet/자기소개서 초안 → `workspace/resume/` |
| `work-agent serve-bot` | 텔레그램 봇 실행(양방향: 폰에서 명령/알림) |
| `work-agent push-digest` | 주제 추천(+선택 회고)을 메신저로 푸시(스케줄러로 정기 실행) |

설계 원칙:

- **LLM 미설정 시 가짜 초안을 만들지 않고** "연결되어 있지 않다"고 안내합니다.
- **Notion 미설정 시 mock(JSON 백엔드)으로 동작**하여 키 없이도 전체 흐름을 쓸 수 있습니다.
- frontmatter가 **단일 진실원천**입니다. draft `.md`의 메타데이터가 그대로 Notion DB 컬럼과 매핑됩니다.

---

## 2. 설치

요구사항: Python 3.11+

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1            # (cmd: .venv\Scripts\activate.bat)
pip install -e ".[dev]"
copy .env.example .env                # 필요한 값 채우기 (없어도 동작)
```

설치 후 `work-agent` 명령이 등록됩니다(`work-agent --help`).

---

## 3. `.env` 설정

`.env.example`를 복사해 사용합니다. **전부 비워도 실행은 됩니다**(LLM은 안내 메시지, Notion은 mock).

```env
# LLM: "openai_compatible" 또는 "ollama". 비우면 미설정 상태.
LLM_PROVIDER=

# openai_compatible (vLLM / OpenAI / Ollama의 /v1 공통)
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# ollama 네이티브
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b-instruct-q4_K_M

CONTEXT_CHAR_BUDGET=12000          # LLM 컨텍스트 문자 예산
LLM_MAX_RETRIES=2                  # LLM HTTP 시도 횟수(일시 오류/5xx 백오프 재시도)

# Notion: 비우면 mock(JSON). 채우면 실제 API.
NOTION_API_KEY=
NOTION_BLOG_DATABASE_ID=          # 초안 상태 추적용 출력 DB
NOTION_IDEA_DATABASE_ID=          # (입력) 아이디어 DB — 각 페이지 본문을 읽음
NOTION_WORKLOG_DATABASE_ID=       # (입력) 작업 메모 DB — 각 페이지 본문을 읽음
NOTION_SOURCE_PAGE_IDS=           # (입력) 정리 문서 페이지 id들(쉼표 구분)

WORKSPACE_DIR=workspace
GIT_LOG_LIMIT=20                   # suggest/draft가 참고할 최근 커밋 수
GIT_INCLUDE_DIFF=true              # 초안 근거로 커밋 diff 일부 포함
GIT_DIFF_MAX_CHARS=800             # 커밋당 diff 최대 문자 수
```

> `suggest-topics`는 이미 초안이 있는 주제를 제외하고 추천하며, 초안 생성 시 커밋 메시지뿐 아니라 **변경 통계와 diff 일부**를 근거로 사용합니다.

### LLM provider 고르기

- **vLLM / OpenAI / 그 밖의 OpenAI 호환 서버** → `LLM_PROVIDER=openai_compatible` + `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`OPENAI_MODEL`
- **로컬 Ollama** → `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL`/`OLLAMA_MODEL`
  - (Ollama의 `/v1` 호환 엔드포인트를 쓰고 싶으면 openai_compatible로 설정해도 됩니다)

---

## 4. 사용법

### 자연어로 지시 (개인 비서처럼)

명령어를 외우지 않고 자유 문장으로 지시할 수 있습니다. LLM이 의도를 분류하고 **실행 전에 확인**을 받습니다.

```bash
work-agent ask "XCoreChat 개발환경 분리로 초안 써줘"
work-agent ask "오늘 작업 회고 정리해줘"
work-agent ask "쓸만한 주제 추천해줘"        # -y 로 확인 생략
```

텔레그램 봇(`serve-bot`)에서도 슬래시 명령 대신 그냥 문장을 보내면 "해석: … 실행할까요? (예/아니오)"로 되묻고 실행합니다. (LLM이 설정돼 있어야 자연어가 동작하며, 미설정 시 슬래시 명령만 됩니다.)

### 개별 명령

```bash
# 1) 주제 추천 (LLM 필요)
work-agent suggest-topics

# 2) 초안 생성 (LLM 필요). --project로 관련 프로젝트, --no-notion으로 Notion 반영 생략
work-agent write-draft "XCoreChat 개발환경 분리" --project XCoreChat

# 3) 미리보기 (LLM 불필요)
work-agent preview latest
work-agent preview 20260622-xcorechat   # slug 지정

# 4) 티스토리 붙여넣기용 변환 (LLM 불필요). --format html|md
work-agent export-tistory latest --format html

# 5) 티스토리에 붙여넣어 게시한 뒤, 완료 기록 (status=published + URL)
work-agent publish-done latest --url https://yourblog.tistory.com/123

# 6) Notion 동기화(상태 추적). --dry-run으로 반영 없이 계획만 확인
work-agent sync-notion --dry-run
work-agent sync-notion
```

상태 흐름: `write-draft`(draft) → `export-tistory`(review) → `publish-done`(published). 각 단계가 frontmatter와 Notion Blog DB에 반영됩니다.

`export-tistory`는 `workspace/blogs/<slug>.html`(또는 `.md`)을 만들고, 제목/태그는 티스토리의 별도 입력란에 넣도록 콘솔에 안내합니다. 본문 파일을 티스토리 글쓰기 화면(HTML 모드 또는 마크다운 모드)에 붙여넣으면 됩니다.

LLM이 설정되지 않은 상태에서 `suggest-topics`/`write-draft`를 실행하면 초안을 지어내지 않고 안내 후 종료합니다.

---

## 5. workspace 문서 구조

에이전트는 `workspace/docs/`의 문서와 Git 로그, (설정 시) Notion을 근거로 사용합니다.

```text
workspace/
├─ docs/
│  ├─ worklog.md           # 작업 기록 (날짜별 무엇을/문제/해결)
│  ├─ project-context.md   # 프로젝트 개요·스택 (사실 위주)
│  └─ blog-ideas.md        # 블로그로 쓰고 싶은 주제 메모
├─ drafts/                 # 생성된 초안(.md, frontmatter 포함) — git 미추적
└─ blogs/                  # 게시/확정 문서 이동용
```

`docs/*` 샘플이 들어 있으니 내용을 본인 작업으로 바꿔 쓰면 됩니다. 문서가 풍부할수록 초안 품질이 올라갑니다.

### 초안 메타데이터(frontmatter)

```yaml
title:
slug:
tags: []
source_project:
status: idea | draft | review | published
summary:
source_refs: []
local_path:
notion_page_id:
created_at:
updated_at:
```

---

## 6. Notion 연동

> 키가 없으면 `sync-notion`은 **mock 모드**로 `workspace/.notion_mock.json`에 기록하며 동일한 흐름을 검증할 수 있습니다. 아래는 **실제 Notion**에 붙일 때입니다.

### 6-1. Integration 생성 & 권한

1. https://www.notion.so/my-integrations 에서 **New integration** 생성 → **Internal Integration Secret**을 `NOTION_API_KEY`에 넣습니다.
2. 연동할 DB 페이지에서 우상단 **···** → **Connections** → 만든 integration을 추가합니다(이걸 빼먹으면 권한 오류가 납니다).
3. 실제 API를 쓰려면 notion-client가 필요합니다: `pip install -e ".[notion]"` (dev/extra에 포함).

### 6-2. Blog DB 스키마

`NOTION_BLOG_DATABASE_ID`가 가리키는 DB에 아래 속성(컬럼)을 만듭니다. 이름이 정확히 일치해야 합니다.

| 속성 | 타입 | 비고 |
| --- | --- | --- |
| `Title` | Title | 제목 |
| `Status` | Select | idea / draft / review / published |
| `Source Project` | Text | 관련 프로젝트 |
| `Tags` | Multi-select | 태그 |
| `Local Path` | Text | 로컬 파일 경로 |
| `Source Refs` | Text | 참고 source (쉼표 구분) |
| `Slug` | Text | 매칭 키 |
| `Summary` | Text | 요약 |
| `Created At` | Date | 생성 시각 |
| `Updated At` | Date | 수정 시각 |
| `Published URL` | URL | 게시된 티스토리 글 주소(publish-done 시 기록) |

> DB id는 DB를 풀페이지로 연 뒤 URL의 `notion.so/.../<32자리 hex>?v=...`에서 `<32자리 hex>` 부분입니다. (컬럼명을 바꾸고 싶으면 [app/notion/mapping.py](app/notion/mapping.py)의 `COL_*` 상수를 수정하세요.)

### 6-3. 입력으로 쓸 Notion 문서 붙이기

정리해 둔 Notion 문서를 초안 소스로 읽는 방법은 두 가지입니다(둘 다 6-1의 Connections에 integration 추가 필요).

- **DB 단위**: `NOTION_IDEA_DATABASE_ID` / `NOTION_WORKLOG_DATABASE_ID`를 설정하면 해당 DB 안 **각 페이지의 본문(블록)**을 읽어 근거로 씁니다.
- **페이지 단위**: 특정 문서만 가리키려면 `NOTION_SOURCE_PAGE_IDS`에 페이지 id를 쉼표로 나열합니다(페이지 URL 끝의 32자리 hex).

읽어온 본문은 `suggest-topics`/`write-draft`의 근거(`source_refs`)로 합쳐집니다. 본문이 비어 있으면 DB 행의 제목/요약으로 폴백합니다.

본문의 **이미지 블록**은 마크다운 이미지(`![설명](url)`)로 변환되어 초안에 반영될 수 있고, `export-tistory`에서 `<img>`로 출력됩니다. 단 Notion에 직접 업로드한 이미지는 URL이 임시(만료)일 수 있으니, 안정적으로 게시하려면 **외부 URL 이미지**를 쓰는 걸 권장합니다.

---

## 7. 메신저 봇 (Telegram, 선택)

폰에서 봇에게 명령을 보내 초안을 만들고 결과를 받는 양방향 연동입니다. 공개 서버/웹훅 없이 long-polling으로 동작합니다.

### 7-1. 설정

1. 텔레그램에서 **@BotFather**에게 `/newbot` → 봇 토큰을 받아 `TELEGRAM_BOT_TOKEN`에 넣습니다.
2. `MESSENGER_PROVIDER=telegram`로 설정합니다.
3. 본인 **chat id**를 `TELEGRAM_ALLOWED_CHAT_IDS`에 넣어 **나만 명령할 수 있게** 제한합니다(비우면 누구나 명령 가능 — 권장하지 않음). chat id는 봇에게 아무 메시지나 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates`에서 확인할 수 있습니다.
4. 알림(outbound)을 받을 기본 대상은 `TELEGRAM_CHAT_ID`에 넣습니다.

```env
MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_CHAT_ID=123456789
```

### 7-2. 실행

```bash
work-agent serve-bot     # Ctrl+C로 종료
```

### 7-3. 봇 명령

```
/list              초안 목록
/topics            주제 추천
/draft <주제>      초안 생성
/revise [slug]     초안 다듬기
/preview [slug]    미리보기
/export [slug]     티스토리용 변환
/publish <url>     게시 완료 기록(최신 초안)
/sync              Notion 동기화
/help              도움말
```

슬래시 없이 **자유 문장**을 보내면 의도를 해석해 "실행할까요? (예/아니오)"로 확인 후 실행합니다(LLM 필요).

> 봇은 CLI와 같은 `BlogAgent`를 호출하는 얇은 어댑터입니다. provider를 교체하면(예: Mattermost) 같은 라우터를 재사용할 수 있습니다.

### 7-4. 정기 푸시 (pull → push)

`push-digest`는 주제 추천(+`--worklog` 시 작업 회고)을 메신저로 **먼저 보내주는** 일회성 명령입니다. `TELEGRAM_CHAT_ID`(대상)와 LLM 설정이 필요합니다.

```bash
work-agent push-digest            # 주제 추천만
work-agent push-digest --worklog  # 회고도 함께
```

OS 스케줄러로 정기 실행하면 "오늘의 주제"가 매일 폰에 도착합니다.

- **Windows (작업 스케줄러)** — 매주 월요일 오전 9시:
  ```powershell
  schtasks /create /tn "work-agent-digest" /tr "C:\path\to\.venv\Scripts\work-agent.exe push-digest --worklog" /sc weekly /d MON /st 09:00
  ```
- **cron (Linux/macOS)**:
  ```cron
  0 9 * * 1 /path/to/.venv/bin/work-agent push-digest --worklog
  ```

---

## 8. 구조

CLI는 얇게 유지하고, 로직은 계층으로 분리했습니다.

```text
app/
├─ cli.py                 # 인자 파싱·출력만 (얇게)
├─ config.py              # .env 설정
├─ agents/blog_agent.py   # 요청 단위 흐름 조율(계층 조립)
├─ services/              # topic_recommender / draft_generator / preview / notion_sync / tistory_exporter
├─ content_sources/       # local_doc / git / notion(페이지 본문) + collector(예산 trim)
├─ llm/                   # base / factory / openai_compatible / ollama
├─ notion/                # client(protocol) / mock / real / mapping / factory
├─ repositories/          # blog_repository(로컬) / notion_blog_repository
├─ storage/markdown_storage.py   # frontmatter ↔ BlogPost
├─ messaging/             # base / telegram / factory / router / bot (메신저 어댑터)
├─ assistant/             # intent / assistant (자연어 의도 라우팅)
├─ models/                # BlogPost, SourceChunk, ...
└─ prompts/*.md           # LLM 프롬프트(코드 밖으로 분리)
```

흐름: `cli(또는 messaging) → blog_agent → services → (content_sources / llm / repositories / storage / notion)`

자세한 설계 규칙은 [AGENTS.md](AGENTS.md) 참고.

---

## 9. 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

로컬/Git 소스, collector, markdown storage, 저장소, LLM factory, 프롬프트, 서비스, CLI, Notion(mock client/mapping/sync/source), 메신저(router/bot)를 커버합니다. Notion 실제 API와 메신저 네트워크는 mock/fake로 분리되어 키 없이 테스트됩니다.

---

## 10. 향후 확장

Blog Agent를 시작으로, 같은 계층 구조 위에 Agent를 추가합니다.

- **Worklog Agent** — 커밋/메모/Notion 기반 자동 회고 ✅ (`work-agent worklog`)
- **Todo Agent** — 최근 작업 기반 다음 할 일 제안 ✅ (`work-agent todo`)
- **Portfolio Agent** — 프로젝트 기록 기반 포트폴리오 설명 초안 ✅ (`work-agent portfolio`)
- **Resume / Cover Letter Agent** — 이력서 bullet / 자기소개서 초안 ✅ (`work-agent resume`)

'source → 마크다운 문서' 형태 Agent는 [app/agents/doc_agent.py](app/agents/doc_agent.py)의 `DocAgent`를 상속해 프롬프트명과 출력 경로만 지정하면 됩니다(Portfolio/Resume가 이 방식). source 조립은 [app/agents/context_builder.py](app/agents/context_builder.py)의 `build_source_collector`, 그 밖에 기존 `llm`/`storage`/`notion` 계층을 재사용합니다.
