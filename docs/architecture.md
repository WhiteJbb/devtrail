# Codex Instructions — Work Agent 리팩토링: Obsidian 기반 LLM Wiki Core

## 0. 현재 상황

이 프로젝트는 기존에 Blog Agent MVP로 시작했다.

현재 이미 구현된 것으로 가정한다.

* CLI 명령
* Telegram Bot 연동
* 자연어 ask 라우팅
* BlogAgent
* Worklog / Todo / Portfolio / Resume 계열 Agent
* Markdown draft 저장
* LLM Provider 구조
* Git log / local docs / Notion / Obsidian 일부 source
* Tistory export 흐름

하지만 이제 프로젝트의 중심 목표가 바뀌었다.

기존 목표:

```text
작업 기록 기반 블로그 초안 생성 Agent
```

새 목표:

```text
Obsidian Vault를 중심으로 하는 LLM Wiki / Personal Knowledge OS
```

따라서 Blog Agent는 중심 기능이 아니라, LLM Wiki Core 위에 올라가는 Output Agent 중 하나가 되어야 한다.

---

# 1. 최종 목표

Obsidian Vault를 개인 지식 OS로 사용하고, 여러 AI가 같은 Vault를 읽고 기록하면서 지식이 누적되도록 만든다.

Claude Code, ChatGPT, Codex, 로컬 LLM, Gemini API, work-agent가 모두 같은 Obsidian Vault를 참조하고, 작업 결과를 다시 Vault에 기록할 수 있어야 한다.

목표 효과:

* 내 프로젝트 문맥이 계속 누적된다.
* AI가 이전 시행착오를 기억한다.
* 블로그/포폴/면접 답변 초안 품질이 좋아진다.
* 작업 로그가 자동으로 지식화된다.
* 지식이 복리처럼 쌓이는 개인 Second Brain을 만든다.

---

# 2. 핵심 설계 철학

이 프로젝트의 중심은 Blog Agent가 아니다.

중심은 다음이다.

```text
Obsidian Vault = 공용 메모리 버스
LLM Wiki Core = 지식 순환 엔진
BlogAgent = Wiki Core를 사용하는 Output Agent
```

LLM Wiki의 핵심은 RAG처럼 매번 raw source에서 새로 찾는 것이 아니라, LLM이 지속적으로 Markdown wiki를 만들고 갱신해서 지식이 누적되게 하는 것이다.

이 프로젝트는 그 패턴을 개인 개발/취업/블로그/포트폴리오 워크플로우에 맞게 구현한다.

---

# 3. 최종 Vault 폴더 구조

원본 LLM Wiki의 단순 구조는 다음과 같다.

```text
raw/
wiki/
outputs/
index.md
log.md
AGENTS.md
```

하지만 이 프로젝트는 개인비서, 블로그, 포폴, AgentMemory까지 고려하므로 아래 확장 구조를 사용한다.

```text
ObsidianVault/
├─ 00_Inbox/
│  ├─ Chats/
│  ├─ Captures/
│  └─ Raw/
│
├─ 10_Worklog/
│  ├─ Daily/
│  ├─ Weekly/
│  └─ GitSummaries/
│
├─ 20_Knowledge/
│  ├─ AI/
│  ├─ RAG/
│  ├─ Agent/
│  ├─ Infra/
│  ├─ Backend/
│  ├─ Frontend/
│  └─ Career/
│
├─ 30_Projects/
│  ├─ XCoreChat/
│  │  ├─ Context.md
│  │  ├─ Architecture.md
│  │  ├─ Decisions/
│  │  ├─ Issues/
│  │  └─ Logs/
│  │
│  ├─ Orbit/
│  ├─ WorkAgent/
│  └─ PortfolioSite/
│
├─ 40_AgentMemory/
│  ├─ 00_Profile.md
│  ├─ 01_CurrentFocus.md
│  ├─ 02_ProjectMap.md
│  ├─ 03_WritingStyle.md
│  ├─ 04_CareerContext.md
│  ├─ 05_OpenLoops.md
│  ├─ Core/
│  └─ ProjectSummaries/
│
├─ 50_Outputs/
│  ├─ Blog/
│  │  ├─ Ideas/
│  │  ├─ Drafts/
│  │  ├─ Review/
│  │  └─ Published/
│  │
│  ├─ Portfolio/
│  ├─ Resume/
│  └─ Interview/
│
├─ 60_Candidates/
│  ├─ Knowledge/
│  ├─ Decisions/
│  ├─ MemoryPatches/
│  └─ BlogIdeas/
│
├─ 90_Templates/
│
├─ index.md
├─ log.md
└─ AGENTS.md
```

매핑은 다음과 같다.

```text
LLM Wiki raw      → 00_Inbox/ + 10_Worklog/
LLM Wiki wiki     → 20_Knowledge/ + 30_Projects/
LLM Wiki outputs  → 50_Outputs/
LLM Wiki schema   → AGENTS.md
index.md          → index.md
log.md            → log.md
```

---

# 4. 가장 중요한 규칙

## 4-1. AI가 직접 수정 가능한 영역

AI는 아래 영역에 자유롭게 쓸 수 있다.

```text
00_Inbox/
10_Worklog/
50_Outputs/Blog/Drafts/
50_Outputs/Portfolio/
50_Outputs/Resume/
50_Outputs/Interview/
60_Candidates/
```

## 4-2. AI가 직접 수정하면 안 되는 영역

AI는 아래 영역을 직접 덮어쓰면 안 된다.

```text
20_Knowledge/
40_AgentMemory/Core/
30_Projects/*/Context.md
```

이 영역은 반드시 candidate 또는 patch를 생성한 뒤, preview/approval을 거쳐 반영해야 한다.

---

# 5. 지식 순환 파이프라인

이 프로젝트는 반드시 아래 흐름을 따른다.

```text
Capture → Distill → Promote
```

## 5-1. Capture

원본 정보를 안전하게 저장하는 단계.

입력:

* Claude Code 작업 결과
* ChatGPT 설계 대화
* Codex 작업 결과
* Git commit
* 수동 메모
* 개발 중 이슈
* 블로그 아이디어

출력:

```text
00_Inbox/
10_Worklog/
50_Outputs/*/Drafts/
```

예시 명령:

```bash
work-agent capture "오늘 XCoreChat 개발환경 분리 작업함" --project XCoreChat
work-agent capture-chat --source chatgpt --project WorkAgent --file chat.md
work-agent capture-chat --source codex --project WorkAgent --file codex.md
work-agent capture-commit --repo ./xcorechat --project XCoreChat
work-agent daily-log
```

---

## 5-2. Distill

최근 기록을 읽고 재사용 가능한 지식 후보로 정리하는 단계.

입력:

* 최근 Inbox
* 최근 Worklog
* Git summaries
* Project Context
* AgentMemory

출력:

```text
60_Candidates/Knowledge/
60_Candidates/Decisions/
60_Candidates/MemoryPatches/
60_Candidates/BlogIdeas/
```

예시 명령:

```bash
work-agent distill-today
work-agent suggest-knowledge
work-agent suggest-blog-topics
work-agent suggest-memory-patch
```

---

## 5-3. Promote

후보 노트를 공식 지식으로 승격하는 단계.

입력:

```text
60_Candidates/
```

출력:

```text
20_Knowledge/
30_Projects/*/Decisions/
40_AgentMemory/
50_Outputs/Blog/Ideas/
```

예시 명령:

```bash
work-agent list-candidates
work-agent preview-candidate "60_Candidates/Knowledge/..."
work-agent promote-candidate "60_Candidates/Knowledge/..."
work-agent apply-memory-patch "60_Candidates/MemoryPatches/..."
```

주의:

* MVP에서는 자동 반영보다 diff/preview 보여주고 승인 후 반영한다.
* 공식 Knowledge/AgentMemory/Core는 바로 수정하지 않는다.

---

# 6. 노트 타입과 Frontmatter 스키마

## 6-1. Worklog

```yaml
---
type: worklog
date: 2026-06-22
project: XCoreChat
tags: [xcorechat, devlog, rag]
source: manual
status: raw
---
```

용도:

* 오늘 한 일
* 막힌 점
* 해결 과정
* 다음 작업
* 블로그 소재 후보

---

## 6-2. Knowledge

```yaml
---
type: knowledge
domain: rag
topic: hybrid-search
status: stable
source_refs:
  - 10_Worklog/Daily/2026-06-22.md
  - git:abc123
updated_at: 2026-06-22
---
```

용도:

* 재사용 가능한 기술 정리
* AI가 검색해서 참조할 공식 지식
* 블로그/포폴/면접 답변의 근거

---

## 6-3. Project Context

```yaml
---
type: project
project: XCoreChat
status: active
tags: [rag, llm, fastapi, qdrant]
updated_at: 2026-06-22
---
```

용도:

* 프로젝트 개요
* 아키텍처
* 기술 스택
* 현재 상태
* 내가 맡은 역할
* 포폴용 핵심 문맥

---

## 6-4. Decision

```yaml
---
type: decision
project: WorkAgent
topic: obsidian-memory-architecture
status: accepted
date: 2026-06-22
source_refs:
  - 00_Inbox/Chats/2026-06-22-llm-wiki-plan.md
---
```

용도:

* 왜 이 구조를 선택했는지
* 기술 선택 이유
* 나중에 AI가 설계 의도를 이해하게 하기

---

## 6-5. Draft

```yaml
---
type: draft
output: blog
project: XCoreChat
status: draft
tags: [rag, devlog, docker]
source_refs:
  - 10_Worklog/Daily/2026-06-22.md
  - 30_Projects/XCoreChat/Context.md
created_at: 2026-06-22
---
```

용도:

* 블로그 초안
* 포트폴리오 초안
* 자기소개서 초안
* 면접 답변 초안

---

## 6-6. Agent Memory

```yaml
---
type: agent_memory
scope: global
status: active
updated_at: 2026-06-22
---
```

용도:

* 모든 AI가 먼저 읽어야 하는 공통 메모리
* 선호, 현재 목표, 프로젝트 맵, 문체 규칙

---

# 7. AgentMemory 파일 구성

아래 파일은 모든 AI가 먼저 읽어야 하는 작은 공통 메모리다.

```text
40_AgentMemory/
├─ 00_Profile.md
├─ 01_CurrentFocus.md
├─ 02_ProjectMap.md
├─ 03_WritingStyle.md
├─ 04_CareerContext.md
├─ 05_OpenLoops.md
├─ Core/
└─ ProjectSummaries/
```

## 7-1. 00_Profile.md

포함 내용:

* 사용자 정보
* 선호하는 답변 스타일
* 개발 스타일
* 피해야 할 표현
* 자주 하는 프로젝트 유형

## 7-2. 01_CurrentFocus.md

포함 내용:

* 지금 가장 중요한 목표
* 이번 주 우선순위
* 마감 있는 작업
* 현재 집중해야 할 프로젝트

## 7-3. 02_ProjectMap.md

포함 내용:

* XCoreChat
* Orbit
* WorkAgent
* Portfolio Site
* Capstone
* 각 프로젝트 관계와 상태

## 7-4. 03_WritingStyle.md

포함 내용:

* 블로그 문체 규칙
* 포트폴리오 문체 규칙
* 자기소개서 문체 규칙
* 과장 금지 규칙
* 수치 사용 주의 규칙

## 7-5. 04_CareerContext.md

포함 내용:

* 목표 직무
* 지원 기업
* 이력서 핵심 경험
* 면접 대비 포인트

## 7-6. 05_OpenLoops.md

포함 내용:

* 아직 끝나지 않은 일
* 고민 중인 설계
* 나중에 다시 봐야 할 아이디어
* 보류한 프로젝트

---

# 8. index.md / log.md 규칙

## 8-1. index.md

`index.md`는 content-oriented catalog다.

역할:

* 위키 전체 페이지 목록
* 각 페이지의 한 줄 요약
* category별 정리
* source count / updated_at / tags 표시 가능

Agent는 query를 처리할 때 먼저 `index.md`를 읽고 관련 페이지를 찾은 뒤, 실제 문서를 읽는다.

업데이트 시점:

* 새 Knowledge 생성 시
* Project Context 변경 시
* Blog Idea 생성 시
* Candidate Promote 후

---

## 8-2. log.md

`log.md`는 chronological append-only record다.

역할:

* ingest 기록
* capture 기록
* distill 기록
* promote 기록
* blog draft 생성 기록
* lint 기록

형식:

```markdown
## [2026-06-22] capture | XCoreChat 개발환경 분리

- source: manual
- project: XCoreChat
- output: 10_Worklog/Daily/2026-06-22.md
```

규칙:

* log.md는 append-only로 운영한다.
* 기존 기록을 임의 수정하지 않는다.

---

# 9. LLM 역할 분담

## 9-1. Local LLM

로컬 LLM은 빠른 사서/분류기 역할이다.

추천:

* Qwen3 4B
* Qwen3 8B

역할:

* 노트 분류
* 태그 추천
* 짧은 요약
* 관련 노트 후보 선별
* AgentMemory 업데이트 후보 생성
* Gemini에 넘길 Context Pack 압축
* 자연어 명령 intent 분류

---

## 9-2. Gemini API

Gemini는 고품질 글쓰기 엔진이다.

역할:

* 블로그 초안 작성
* 포트폴리오 문장화
* 자기소개서 초안
* 면접 답변 정리
* 긴 글 최종 다듬기

기본 원칙:

```text
Local LLM = 사서
Gemini = 작가
Obsidian = 뇌
work-agent = 신경망
```

---

# 10. 모델 라우팅 규칙

```yaml
tasks:
  classify_note: local
  suggest_tags: local
  summarize_short: local
  search_query_expand: local
  intent_routing: local
  build_context_pack: local
  distill_today: local_or_gemini_flash
  suggest_blog_topics: gemini_flash
  write_blog: gemini_flash
  revise_blog: gemini_flash
  portfolio_draft: gemini_flash
  resume_bullets: gemini_flash
  cover_letter: gemini_pro
```

구현 시 LLM Router를 둬서 task별 provider를 교체 가능하게 한다.

---

# 11. Context Pack 설계

Gemini나 Claude에 긴 작업을 맡기기 전에, work-agent가 관련 문맥을 모아 Context Pack을 만든다.

## Context Pack 구성

```markdown
# Context Pack

## User / Agent Memory
- 현재 목표
- 문체 규칙
- 프로젝트 맵

## Project Context
- 프로젝트 개요
- 주요 기술
- 현재 상태

## Relevant Notes
- 관련 Knowledge 요약
- 관련 Worklog 요약
- 관련 Decision 요약

## Source Refs
- 실제 참고한 노트 경로
- Git commit
- 파일 경로

## Task
- 수행할 작업
```

예시 명령:

```bash
work-agent build-context "XCoreChat 개발환경 분리"
work-agent build-context "Orbit 브라우저 에이전트 소개"
```

---

# 12. 기존 기능 재사용 방침

현재 구현된 기능은 최대한 살린다.

살릴 것:

* CLI entry
* Telegram Bot entry
* 자연어 ask 라우터
* LLM Provider 구조
* Markdown storage
* Git source
* Blog draft 생성 프롬프트 일부
* Tistory export
* Worklog/Todo/Portfolio/Resume Agent
* 테스트 구조

바꿀 것:

* Notion 중심 source 구조
* BlogAgent 중심 architecture
* 단일 workspace/docs 중심 입력 구조
* write-draft 중심 workflow

새로 추가할 것:

* ObsidianVaultSource를 1급 Source로 승격
* LLMWikiCore 또는 WikiAgent
* Vault initializer
* Vault indexer
* metadata/BM25 search
* CaptureAgent
* DistillAgent
* CuratorAgent
* ContextPackBuilder
* CandidateWriter
* AgentMemoryLoader
* index.md/log.md updater

---

# 13. 프로젝트 코드 구조 목표

기존 구조를 아래 방향으로 리팩토링한다.

```text
app/
├─ cli.py
├─ config.py
├─ main.py
│
├─ agents/
│  ├─ wiki_agent.py
│  ├─ capture_agent.py
│  ├─ distill_agent.py
│  ├─ curator_agent.py
│  ├─ blog_agent.py
│  ├─ portfolio_agent.py
│  ├─ worklog_agent.py
│  ├─ todo_agent.py
│  └─ resume_agent.py
│
├─ sources/
│  ├─ base.py
│  ├─ obsidian_source.py
│  ├─ git_source.py
│  ├─ local_doc_source.py
│  └─ conversation_source.py
│
├─ index/
│  ├─ metadata_index.py
│  ├─ bm25_index.py
│  ├─ note_graph.py
│  └─ index_updater.py
│
├─ memory/
│  ├─ agent_memory_loader.py
│  ├─ project_memory_loader.py
│  └─ context_pack_builder.py
│
├─ storage/
│  ├─ markdown_writer.py
│  ├─ candidate_writer.py
│  ├─ draft_writer.py
│  └─ log_writer.py
│
├─ llm/
│  ├─ base.py
│  ├─ local_provider.py
│  ├─ gemini_provider.py
│  └─ router.py
│
├─ messaging/
│  ├─ telegram.py
│  ├─ router.py
│  └─ bot.py
│
├─ assistant/
│  ├─ intent.py
│  └─ assistant.py
│
├─ models/
│  ├─ note.py
│  ├─ source_ref.py
│  ├─ context_pack.py
│  ├─ candidate.py
│  └─ draft.py
│
└─ prompts/
   ├─ capture.md
   ├─ distill.md
   ├─ promote.md
   ├─ suggest_blog_topics.md
   ├─ write_blog.md
   ├─ summarize_project.md
   └─ update_agent_memory.md
```

기존 `content_sources` 같은 이름을 유지해도 된다. 단, 논리적으로는 Source 계층이 Obsidian 중심이어야 한다.

---

# 14. CLI 명령어 목표

## 14-1. Vault / Index

```bash
work-agent init-vault
work-agent index-vault
work-agent search "RAG 개발환경"
work-agent related "30_Projects/XCoreChat/Context.md"
```

## 14-2. Capture

```bash
work-agent capture "메모 내용" --project XCoreChat
work-agent capture-chat --source chatgpt --project WorkAgent --file chat.md
work-agent capture-chat --source codex --project WorkAgent --file codex.md
work-agent capture-commit --repo ./xcorechat --project XCoreChat
work-agent daily-log
```

## 14-3. Distill

```bash
work-agent distill-today
work-agent suggest-knowledge
work-agent suggest-blog-topics
work-agent suggest-memory-patch
```

## 14-4. Promote / Curate

```bash
work-agent list-candidates
work-agent preview-candidate "파일경로"
work-agent promote-candidate "파일경로"
work-agent apply-memory-patch "파일경로"
```

## 14-5. Context

```bash
work-agent build-context "XCoreChat 개발환경 분리"
```

## 14-6. Blog

기존 명령은 유지하되 내부 흐름을 바꾼다.

```bash
work-agent suggest-topics
work-agent write-draft "XCoreChat 개발환경 분리"
work-agent write-blog "XCoreChat 개발환경 분리"
work-agent revise-blog "50_Outputs/Blog/Drafts/파일.md"
work-agent publish-ready "50_Outputs/Blog/Drafts/파일.md"
work-agent export-tistory latest
```

`write-draft`는 기존 호환용 alias로 두고, 내부적으로 `write-blog`를 호출해도 된다.

## 14-7. Portfolio / Career

```bash
work-agent summarize-project XCoreChat
work-agent portfolio-draft XCoreChat
work-agent interview-questions XCoreChat
work-agent resume
```

---

# 15. Telegram Bot 명령어 목표

기존 Telegram Bot은 유지한다.

기존 명령:

```text
/list
/topics
/draft <주제>
/revise [slug]
/preview [slug]
/export [slug]
/publish <url>
/sync
/help
```

추가 명령:

```text
/search <검색어>
/capture <메모>
/distill
/context <주제>
/candidates
/promote <candidate_path>
```

Telegram Bot은 직접 로직을 갖지 않는다. CLI와 같은 Agent/Service 계층을 호출하는 얇은 어댑터로 유지한다.

---

# 16. 환경 변수 목표

기존 `.env`를 아래 방향으로 확장한다.

```env
OBSIDIAN_VAULT_PATH=C:/Users/username/Documents/ObsidianVault

LOCAL_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

WRITER_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_FLASH_MODEL=gemini-2.5-flash
GEMINI_PRO_MODEL=gemini-2.5-pro

DEFAULT_TIMEZONE=Asia/Seoul

MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_CHAT_ID=

LEGACY_NOTION_ENABLED=false
```

Notion 관련 환경 변수는 제거하지 말고 legacy/optional로 유지한다.

---

# 17. MVP 리팩토링 순서

## Phase 0. 안전 조치

* 새 브랜치 생성
* 기존 기능 테스트 실행
* README 현재 상태 확인
* Notion 기능은 바로 삭제하지 말고 legacy로 둔다.

브랜치 예시:

```bash
git checkout -b refactor/llm-wiki-core
```

---

## Phase 1. 문서/설정 중심축 변경

목표:

* README를 Blog Agent 중심에서 LLM Wiki Core 중심으로 수정
* AGENTS.md를 새 규칙으로 교체
* `.env.example`에 OBSIDIAN_VAULT_PATH, Gemini, local LLM routing 추가
* Notion은 legacy optional로 표기

완료 기준:

* 문서상 프로젝트 중심이 Obsidian LLM Wiki로 바뀐다.

---

## Phase 2. Vault 초기화

목표:

* `work-agent init-vault` 구현

동작:

* OBSIDIAN_VAULT_PATH에 폴더 구조 생성
* index.md 생성
* log.md 생성
* AGENTS.md 생성 또는 템플릿 생성
* 40_AgentMemory 기본 파일 생성
* 90_Templates 기본 템플릿 생성

완료 기준:

```bash
work-agent init-vault
```

명령 한 번으로 Vault 기본 구조가 생성된다.

---

## Phase 3. Obsidian Source / Index / Search

목표:

* Obsidian Vault의 Markdown 파일을 읽고 검색 가능하게 만든다.

구현:

* Markdown parser
* YAML frontmatter parser
* Wiki link parser
* metadata index
* BM25 또는 간단 keyword search
* index.md updater

완료 기준:

```bash
work-agent index-vault
work-agent search "RAG"
```

가 동작한다.

---

## Phase 4. Capture Agent

목표:

* 대화, 메모, 커밋을 안전한 위치에 저장한다.

구현:

* `capture`
* `capture-chat`
* `capture-commit`
* `daily-log`
* log.md append

완료 기준:

* capture 결과가 00_Inbox 또는 10_Worklog에 Markdown으로 저장된다.
* log.md에 기록된다.

---

## Phase 5. Distill Agent / Candidates

목표:

* 최근 기록을 읽어 Knowledge/Decision/MemoryPatch/BlogIdea 후보를 만든다.

구현:

* `distill-today`
* `suggest-knowledge`
* `suggest-blog-topics`
* `suggest-memory-patch`
* CandidateWriter

완료 기준:

* `60_Candidates/` 아래 후보 노트가 생성된다.
* 공식 Knowledge를 바로 수정하지 않는다.

---

## Phase 6. Context Pack Builder

목표:

* 특정 주제에 필요한 문맥을 자동 수집한다.

구현:

* AgentMemoryLoader
* ProjectMemoryLoader
* related note search
* source_refs 정리
* context pack 생성

완료 기준:

```bash
work-agent build-context "XCoreChat 개발환경 분리"
```

가 관련 노트와 source_refs를 포함한 Context Pack을 만든다.

---

## Phase 7. 기존 BlogAgent를 Wiki Core 위로 이동

목표:

* 기존 `suggest-topics`, `write-draft`를 유지하되 내부적으로 Wiki Core를 사용하게 한다.

새 흐름:

```text
suggest-topics
→ AgentMemory
→ Worklog
→ Knowledge
→ Candidate BlogIdeas
→ Gemini/Local LLM으로 추천

write-draft / write-blog
→ build-context
→ Gemini writer
→ 50_Outputs/Blog/Drafts 저장
→ source_refs frontmatter 기록
→ log.md append
```

완료 기준:

* 기존 CLI 명령이 깨지지 않는다.
* 새 Obsidian Vault source_refs가 draft에 남는다.

---

## Phase 8. Telegram Router 확장

목표:

* 기존 Telegram Bot은 유지하고 Wiki Core 명령을 추가한다.

추가:

```text
/search
/capture
/distill
/context
/candidates
/promote
```

완료 기준:

* 폰에서 메모 capture 가능
* 폰에서 blog topic 추천 가능
* 폰에서 search/context 요청 가능

---

## Phase 9. Curator / Promote

목표:

* Candidate를 공식 Knowledge/Decision/Memory로 승격한다.

구현:

* list-candidates
* preview-candidate
* promote-candidate
* apply-memory-patch
* index.md update
* log.md append

완료 기준:

* 승인된 candidate만 공식 영역에 반영된다.
* index.md/log.md가 갱신된다.

---

# 18. 구현 중 금지사항

* Telegram/CLI를 버리지 말 것
* 기존 BlogAgent를 삭제하지 말고 Wiki Core 위에 얹을 것
* Notion 코드를 즉시 삭제하지 말고 legacy optional로 둘 것
* AI가 20_Knowledge, 40_AgentMemory/Core를 바로 덮어쓰게 하지 말 것
* source_refs 없는 블로그 초안 생성 금지
* LLM 미설정 시 가짜 초안 생성 금지
* 모든 Vault 파일을 무작정 LLM에 넣지 말 것
* Context Pack 없이 긴 글쓰기 모델을 호출하지 말 것

---

# 19. 테스트 목표

기존 테스트를 유지하고 아래 테스트를 추가한다.

* init-vault가 폴더/파일을 생성하는지
* ObsidianSource가 markdown/frontmatter/wiki link를 읽는지
* index-vault가 index를 생성하는지
* search가 관련 노트를 반환하는지
* capture가 안전한 위치에 파일을 쓰는지
* log.md가 append-only로 기록되는지
* distill-today가 candidates를 만드는지
* write-blog가 source_refs를 포함하는지
* Telegram router가 새 명령을 Agent로 위임하는지

---

# 20. 최종 완료 기준

1차 리팩토링 완료 기준:

```bash
work-agent init-vault
work-agent index-vault
work-agent search "검색어"
work-agent capture "오늘 한 일" --project XCoreChat
work-agent distill-today
work-agent build-context "주제"
work-agent suggest-blog-topics
work-agent write-blog "주제"
```

위 명령이 동작해야 한다.

또한 Telegram에서 아래가 가능해야 한다.

```text
/capture 메모
/search 검색어
/distill
/context 주제
/topics
/draft 주제
```

최종적으로 이 프로젝트는 단순 Blog Agent가 아니라 다음으로 설명될 수 있어야 한다.

```text
Work Agent is an Obsidian-based LLM Wiki and Personal Knowledge OS.
It captures work traces, distills them into durable knowledge, and uses that knowledge to generate blog, portfolio, resume, and interview drafts.
```
