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
| `work-agent suggest-topics` | 최근 작업 기록·Git 로그·Notion 메모로 블로그 주제 추천 |
| `work-agent list` | 저장된 초안을 상태/수정일과 함께 목록 출력 |
| `work-agent write-draft "주제"` | 주제로 초안 생성 → `workspace/drafts/`에 Markdown 저장 + Notion 반영 |
| `work-agent revise latest` | 기존 초안을 source 범위 안에서 문장/구조만 다듬기(새 사실 추가 없음) |
| `work-agent preview latest` | 최신(또는 slug 지정) 초안의 메타데이터 + 본문 일부 |
| `work-agent export-tistory latest` | 초안을 티스토리 붙여넣기용(HTML/MD)으로 변환 → `workspace/blogs/` |
| `work-agent publish-done latest --url <주소>` | 티스토리 게시 완료 기록(status=published + URL → 로컬·Notion) |
| `work-agent sync-notion` | 로컬 draft 메타데이터를 Notion Blog DB와 동기화(상태 추적) |

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

# Notion: 비우면 mock(JSON). 채우면 실제 API.
NOTION_API_KEY=
NOTION_BLOG_DATABASE_ID=          # 초안 상태 추적용 출력 DB
NOTION_IDEA_DATABASE_ID=          # (입력) 아이디어 DB — 각 페이지 본문을 읽음
NOTION_WORKLOG_DATABASE_ID=       # (입력) 작업 메모 DB — 각 페이지 본문을 읽음
NOTION_SOURCE_PAGE_IDS=           # (입력) 정리 문서 페이지 id들(쉼표 구분)

WORKSPACE_DIR=workspace
GIT_LOG_LIMIT=20                   # suggest/draft가 참고할 최근 커밋 수
```

### LLM provider 고르기

- **vLLM / OpenAI / 그 밖의 OpenAI 호환 서버** → `LLM_PROVIDER=openai_compatible` + `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`OPENAI_MODEL`
- **로컬 Ollama** → `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL`/`OLLAMA_MODEL`
  - (Ollama의 `/v1` 호환 엔드포인트를 쓰고 싶으면 openai_compatible로 설정해도 됩니다)

---

## 4. 사용법

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

## 7. 구조

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
├─ models/                # BlogPost, SourceChunk, ...
└─ prompts/*.md           # LLM 프롬프트(코드 밖으로 분리)
```

흐름: `cli → blog_agent → services → (content_sources / llm / repositories / storage / notion)`

자세한 설계 규칙은 [AGENTS.md](AGENTS.md) 참고.

---

## 8. 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

로컬/Git 소스, collector, markdown storage, 저장소, LLM factory, 프롬프트, 서비스, CLI, Notion(mock client/mapping/sync/source)을 커버합니다. Notion 실제 API는 mock과 분리되어 키 없이 테스트됩니다.

---

## 9. 향후 확장

이번 MVP는 Blog Agent이며, 같은 계층 구조 위에 아래를 추가할 수 있게 설계되었습니다.

- **Portfolio Agent** — 프로젝트 기록 기반 포트폴리오 설명 초안
- **Resume / Cover Letter Agent** — 이력서 bullet / 자기소개서 초안
- **Todo Agent** — 최근 작업 기반 다음 할 일 제안
- **Worklog Agent** — 커밋/메모/Notion 기반 자동 회고

새 Agent는 `app/agents/`에 추가하고 기존 `content_sources`/`llm`/`storage`/`notion` 계층을 재사용하면 됩니다.
