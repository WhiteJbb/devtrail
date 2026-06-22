# AGENTS.md

이 저장소에서 작업하는 사람/에이전트를 위한 가이드다. 현재 구조·원칙·확장 방법·작업 방식을 담는다.
(초기 Blog Agent MVP 계획에서 출발했고, 그 원래 기획 문서는 [concept.md](concept.md)에 보존되어 있다.)

---

# 1. 프로젝트 개요

**Work Agent** — 내 실제 작업 흔적(로컬 문서·Git 로그·Notion 문서)을 읽어 기술 블로그 초안·작업 회고·할 일·포트폴리오·이력서 초안을 만들어 주는 개인 생산성 CLI/봇.

핵심 철학은 그대로다: LLM은 창작자가 아니라 **작업 기록 정리자**다. 목표는 "완성형 자동 발행"이 아니라 **70~80점 초안을 빠르게 만들어 5~10분 다듬어 쓰는 것**이다.

## 현재 구현 상태

- **Agent 5종**: Blog / Worklog / Todo / Portfolio / Resume
- **입력(source)**: 로컬 docs, Git 로그(diff 포함), Notion(페이지 본문)
- **출력**: 로컬 마크다운(frontmatter), 티스토리 붙여넣기용(HTML/MD), Notion Blog DB(상태 추적)
- **진입점 3개**: CLI · 텔레그램 봇 · 자연어(`ask`/봇 자유 문장)
- **자동화**: 정기 푸시(`push-digest`)로 주제/회고를 메신저로

### 명령 (15개)
`ask` · `suggest-topics` · `list` · `write-draft` · `revise` · `preview` · `export-tistory` · `publish-done` · `sync-notion` · `worklog` · `todo` · `portfolio` · `resume` · `serve-bot` · `push-digest`

> 흐름: **Notion/로컬/Git(입력) → 초안 → 티스토리(출력)**. Notion은 입력(문서 본문)과 상태 추적(Blog DB) 양쪽으로 선택적으로 쓰인다.

---

# 2. 반드시 지킬 설계 원칙

1. **계층을 분리한다.** CLI/메신저/자연어는 얇은 입구일 뿐, 로직은 agents/services에 둔다. 입구에 LLM 프롬프트 구성·Git 파싱·Notion 호출·Markdown 저장 로직을 직접 넣지 않는다.
2. **근거 없는 내용을 만들지 않는다.** 모든 산출물은 실제 source 기반. 존재하지 않는 수치/아키텍처/성과를 지어내지 않는다. 모르면 모른다고 둔다.
3. **LLM 호출과 비즈니스 로직을 분리한다.** provider는 교체 가능(`openai_compatible` / `ollama`).
4. **수집과 저장/동기화를 분리한다.** content_sources(읽기)와 repositories/storage(쓰기)를 섞지 않는다.
5. **외부 연동은 전용 계층으로 격리한다.** Notion/메신저 코드는 각 계층에 가둔다. 키가 없으면 graceful하게 동작(mock/비활성)한다.
6. **프롬프트는 코드 밖으로.** `app/prompts/*.md`에 두고 `render_prompt`로 `{{토큰}}` 치환한다.
7. **frontmatter가 단일 진실원천(SOT)이다.** draft 메타데이터는 frontmatter에 담고 Notion DB와 매핑한다.

---

# 3. 폴더 구조

```text
app/
├─ cli.py                 # Typer CLI 진입점 (얇게)
├─ config.py              # .env / 환경변수 (pydantic-settings)
├─ agents/                # 요청 단위 흐름 조율
│  ├─ blog_agent.py       #   블로그 파이프라인 전체
│  ├─ worklog/todo/portfolio/resume_agent.py   # 확장 Agent
│  ├─ doc_agent.py        #   'source→마크다운 문서' 공통 베이스
│  └─ context_builder.py  #   source collector 조립 공용
├─ services/              # 기능 단위 로직(추천/초안/다듬기/미리보기/sync/export/digest/요약)
├─ content_sources/       # local_doc / git / notion + collector(예산 trim)
├─ llm/                   # base / factory / openai_compatible / ollama / _http(재시도)
├─ notion/                # client(protocol) / mock / real / mapping / factory
├─ repositories/          # blog_repository(로컬) / notion_blog_repository
├─ storage/               # markdown_storage (frontmatter ↔ BlogPost)
├─ messaging/             # base / telegram / factory / router / bot (메신저 어댑터)
├─ assistant/             # intent / assistant (자연어 의도 라우팅)
├─ models/                # BlogPost, SourceChunk, TopicSuggestion, NotionBlogRow ...
└─ prompts/*.md           # LLM 프롬프트

workspace/                # 사용자 데이터(대부분 git 미추적)
├─ docs/                  #   worklog/project-context/blog-ideas (입력 샘플)
├─ drafts/ blogs/         #   초안 / 티스토리용 산출물
└─ worklogs/ todos/ portfolio/ resume/   # 확장 Agent 출력
```

---

# 4. 계층 책임

- **agents** — 사용자 요청 단위 흐름 조율(소스/서비스/저장소 조립). `BlogAgent`가 중심, 확장 4종은 `DocAgent` 상속.
- **services** — 기능 단위 로직(주제 추천, 초안 생성/다듬기, 미리보기, Notion sync, 티스토리 export, 회고/할일/문서 요약, 다이제스트).
- **content_sources** — 데이터 읽기만. `ContentSource` 프로토콜 → `SourceChunk[]`. `SourceCollector`가 예산 한도로 trim.
- **llm** — provider 교체 가능. `_http.request_with_retry`로 일시 오류 재시도. `services.json_utils.complete_json`로 깨진 JSON 1회 재시도.
- **notion** — `NotionClient` 프로토콜. 키 없으면 `MockNotionClient`(JSON 백엔드), 있으면 `RealNotionClient`.
- **messaging** — 메신저 provider(텔레그램) + 슬래시 명령 라우터 + 봇 루프.
- **assistant** — 자유 문장을 LLM으로 명령에 매핑(intent), 확인 후 실행. 실행은 CommandRouter/Agent 재사용.
- **storage/repositories** — 마크다운 저장, draft/Notion 행 조회·저장.

---

# 5. 외부 연동 규칙

## 5-1. 환경변수 (`.env`, 전부 optional — 비우면 비활성/mock)

```env
# LLM
LLM_PROVIDER=                 # openai_compatible | ollama (비우면 LLM 기능 안내 후 종료)
OPENAI_BASE_URL= OPENAI_API_KEY= OPENAI_MODEL=
OLLAMA_BASE_URL= OLLAMA_MODEL=
CONTEXT_CHAR_BUDGET=12000  LLM_MAX_RETRIES=2

# Notion (입력=문서 본문 / 출력=상태 추적). 비우면 mock.
NOTION_API_KEY= NOTION_BLOG_DATABASE_ID=
NOTION_IDEA_DATABASE_ID= NOTION_WORKLOG_DATABASE_ID= NOTION_SOURCE_PAGE_IDS=

# Git source
GIT_LOG_LIMIT=20  GIT_INCLUDE_DIFF=true  GIT_DIFF_MAX_CHARS=800

# Messenger (텔레그램). 비우면 봇 비활성.
MESSENGER_PROVIDER= TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS= TELEGRAM_CHAT_ID=

WORKSPACE_DIR=workspace
```

새 환경변수를 추가하면 `config.py`, `.env.example`, README에 반드시 함께 문서화한다.

## 5-2. 연동별 주의

- **LLM 미설정**: 가짜 초안을 만들지 않고 "연결 안 됨"을 명확히 안내한다(설계 원칙 2).
- **Notion**: 실제 API 클라이언트(`RealNotionClient`)는 구조는 있으나 **실제 키 검증은 아직 미완**(현재 mock으로만 검증). 컬럼명은 `notion/mapping.py`의 `COL_*` 상수.
- **티스토리**: 공식 Open API가 2024년 종료되어 **자동 게시 불가**. `export-tistory`로 붙여넣기용 산출물만 생성한다.
- **텔레그램**: `TELEGRAM_ALLOWED_CHAT_IDS`로 본인만 명령하게 제한(미설정 시 경고). 네트워크 호출부는 fake로만 테스트됨(실토큰 검증은 사용자 몫).

---

# 6. 확장하는 법

- **새 'source→문서' Agent**: `agents/doc_agent.py`의 `DocAgent`를 상속해 `prompt_name`과 `_out_dir`만 지정(Worklog/Todo/Portfolio/Resume가 예시). 프롬프트는 `app/prompts/`에 추가.
- **새 content source**: `ContentSource` 프로토콜 구현 → `SourceChunk[]`. 실패는 예외 대신 빈 리스트(파이프라인 안전). `context_builder.build_source_collector`에 배선하면 모든 Agent가 자동 사용.
- **새 명령**: CLI는 `cli.py`에 얇게, 로직은 service/agent에. 자연어로도 쓰이게 하려면 `assistant`의 명령 카탈로그/프롬프트(`intent_route.md`)에 추가.
- **새 메신저 provider**: `MessengerProvider` 프로토콜 구현 + factory에 등록하면 라우터/봇 재사용.

---

# 7. 품질 · 테스트 규칙

- 외부(LLM/Notion/메신저)는 **mock/fake로 분리해 키 없이 테스트**한다. 네트워크 호출은 단위 테스트에서 실제로 나가지 않게 한다.
- 최소한 다음은 항상 테스트 가능해야 한다: content source 읽기, collector 예산/장애 격리, markdown storage round-trip, repository, LLM factory/재시도, 프롬프트 렌더, 서비스, CLI 동작, Notion(mock), 메신저(router/bot), 자연어(assistant).
- 실행: `.venv\Scripts\python.exe -m pytest -q`

---

# 8. Git / PR 작업 방식

- 작업은 **단계별 브랜치 → 커밋 → PR → main 머지** 사이클로 진행한다(`feat/...`, `docs/...`).
- 커밋/PR 문구는 **간결한 한국어**. **AI/생성 도구 푸터·서명·이모지 서명을 넣지 않는다.**
- PR 본문은 진행 보고(구현한 것 / 남은 것 / 실행 방법 / 주의)로 작성한다.
- 머지된 브랜치는 로컬·원격에서 삭제해 `main`만 유지한다.

---

# 9. 블로그 초안 스타일 (변함 없음)

- 기술 블로그 톤, 실제 작업 회고 기반. **문제 → 원인 → 해결 → 결과 → 배운 점** 구조.
- 긴 도입부 없이 바로 문제로. 과장·홍보성·자기계발 에세이 톤·일반론·검증 안 된 수치를 피한다.

---

# 10. 미구현 / 검토 중

- **실제 키 연결 검증** — Notion/Telegram/LLM 모두 mock/fake로만 검증됨. 실제 키로 1회 검증(또는 `doctor` 점검 명령)이 가장 정직한 다음 개선.
- **Obsidian 연동** — 설계 제안만 있음: [docs/obsidian-integration-proposal.md](docs/obsidian-integration-proposal.md).
- **우선순위 아님**: Discord/Mattermost, 웹 UI, 티스토리 자동 게시(브라우저 자동화), 복잡한 멀티에이전트 오케스트레이션.

---

# 11. 최종 판단 기준

구현 중 판단이 필요하면 항상:

1. 이 기능이 실제로 작업/글쓰기 시간을 줄이는가?
2. 기존 계층(agents/services/sources/llm/notion/messaging)을 재사용·확장하는가?
3. 지금 과한 구현으로 늦추는 것은 아닌가?

이 프로젝트는 멋진 데모보다 **실제로 내가 미루지 않게 해주는 도구**가 되는 것이 중요하다.
