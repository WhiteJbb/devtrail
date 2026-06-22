# AGENTS.md

## 프로젝트 개요

이 저장소는 개인 생산성 Agent 프로젝트인 **Work Agent**의 첫 번째 MVP를 구현하기 위한 저장소다.

현재 목표는 **Blog Agent MVP**다.
이 Agent는 로컬 작업 기록, Git 로그, 프로젝트 문서, Notion 메모를 읽고 기술 블로그 초안을 생성한다.

장기적으로는 아래 기능으로 확장할 예정이다.

* Blog Agent
* Portfolio Agent
* Resume / Cover Letter Agent
* Todo Agent
* Worklog Agent
* Notion 기반 개인 작업 허브
* 추후 필요 시 Telegram / Discord / Mattermost 같은 채팅 인터페이스

하지만 지금은 **CLI + Notion 중심의 Blog Agent MVP 완성**이 최우선이다.

---

# 1. 현재 단계의 핵심 목표

이번 MVP의 목표는 아래 흐름을 완성하는 것이다.

1. CLI에서 명령을 실행한다.
2. Agent가 로컬 문서, Git 로그, Notion 메모를 읽는다.
3. 최근 작업 기반 블로그 주제를 추천한다.
4. 특정 주제로 기술 블로그 초안을 생성한다.
5. 초안을 Markdown으로 저장한다.
6. 초안 메타데이터를 Notion Blog DB와 동기화한다.

---

# 2. 지금 만들지 말아야 할 것

이번 단계에서 아래 기능은 우선순위가 아니다.

* Telegram Bot
* Discord Bot
* Mattermost Bot
* 웹 UI
* 복잡한 멀티에이전트 오케스트레이션
* 장기 메모리 시스템
* 자동 블로그 발행
* 포트폴리오 / 이력서 Agent 완성
* Notion 전체 워크스페이스 자동화

지금은 **CLI로 안정적으로 동작하는 Blog Agent Core**와 **Notion 메타데이터 연동**이 먼저다.

---

# 3. 개발 우선순위

## 1순위: CLI MVP

아래 명령이 동작해야 한다.

```bash
work-agent suggest-topics
```

최근 작업 기록, Git 로그, Notion 아이디어를 바탕으로 블로그 주제를 추천한다.

```bash
work-agent write-draft "XCoreChat 개발환경 분리"
```

특정 주제로 블로그 초안을 생성하고 `workspace/drafts/`에 Markdown으로 저장한다.

```bash
work-agent preview latest
```

가장 최근 초안의 제목, 메타데이터, 본문 일부를 보여준다.

```bash
work-agent sync-notion
```

로컬 draft 메타데이터와 Notion Blog DB를 동기화한다.

---

## 2순위: Notion 연동

Notion은 이번 MVP에서 단순 placeholder가 아니라 실제 연동 대상이다.

최소한 아래가 가능해야 한다.

1. Notion Blog DB에 draft 메타데이터 생성/업데이트
2. Notion Idea / Worklog DB 또는 Page에서 블로그 아이디어 읽기
3. 로컬 draft와 Notion 상태 동기화

---

## 3순위: Draft / Blog 워크플로우

초안은 먼저 `workspace/drafts/`에 저장한다.
게시 또는 확정된 문서는 나중에 `workspace/blogs/`로 이동할 수 있게 구조를 둔다.

상태값은 다음을 기본으로 한다.

* `idea`
* `draft`
* `review`
* `published`

---

## 4순위: 확장 가능한 구조

지금은 Blog Agent만 구현하지만, 이후 아래 Agent가 추가될 수 있어야 한다.

* Portfolio Agent
* Resume Agent
* Todo Agent
* Worklog Agent

따라서 `blog_generator.py` 하나짜리 스크립트로 끝내지 말고, Agent / Service / Source / Storage 계층을 분리한다.

---

# 4. 구현 원칙

## 4-1. 이 프로젝트는 블로그 자동 생성기가 아니다

목표는 완성형 글을 자동으로 발행하는 것이 아니다.

목표는 다음이다.

> 실제 작업 기록을 바탕으로 70~80점짜리 기술 블로그 초안을 만들고, 사용자가 5~10분 수정해서 게시할 수 있게 한다.

따라서 LLM은 창작자가 아니라 **작업 기록 정리자**로 동작해야 한다.

---

## 4-2. 근거 없는 내용을 만들지 않는다

블로그 초안에는 반드시 실제 source 기반 내용이 들어가야 한다.

사용 가능한 source:

* `workspace/docs/worklog.md`
* `workspace/docs/project-context.md`
* `workspace/docs/blog-ideas.md`
* Git commit log
* Git changed files
* Notion idea / worklog / blog DB

금지:

* 존재하지 않는 성능 수치 생성
* 확인되지 않은 아키텍처 생성
* 실제로 하지 않은 작업을 한 것처럼 작성
* 인터넷 일반론만 길게 작성
* 과장된 마케팅 문체

---

## 4-3. CLI는 얇게 유지한다

CLI는 명령을 받아 서비스 계층을 호출하는 역할만 한다.

CLI 안에 아래 로직을 직접 넣지 않는다.

* LLM 프롬프트 구성
* Git 로그 파싱
* Notion API 호출
* Markdown 저장 처리
* 블로그 초안 생성 로직

이 로직은 반드시 Agent / Service / Repository / Storage 계층에 둔다.

---

# 5. 권장 폴더 구조

구조는 필요에 따라 조정할 수 있지만, 아래 방향을 유지한다.

```text
work-agent/
├─ app/
│  ├─ cli.py
│  ├─ main.py
│  ├─ config.py
│  ├─ agents/
│  │  └─ blog_agent.py
│  ├─ services/
│  │  ├─ topic_recommender.py
│  │  ├─ draft_generator.py
│  │  ├─ preview_service.py
│  │  └─ notion_sync_service.py
│  ├─ llm/
│  │  ├─ base.py
│  │  ├─ ollama_provider.py
│  │  └─ openai_compatible_provider.py
│  ├─ content_sources/
│  │  ├─ base.py
│  │  ├─ worklog_source.py
│  │  ├─ project_context_source.py
│  │  ├─ git_source.py
│  │  └─ notion_source.py
│  ├─ repositories/
│  │  ├─ blog_repository.py
│  │  └─ notion_blog_repository.py
│  ├─ storage/
│  │  ├─ markdown_storage.py
│  │  └─ notion_client.py
│  ├─ models/
│  │  ├─ blog_post.py
│  │  ├─ draft_request.py
│  │  ├─ topic_suggestion.py
│  │  └─ notion_models.py
│  └─ prompts/
│     ├─ recommend_topics.md
│     ├─ write_draft.md
│     └─ revise_draft.md
├─ workspace/
│  ├─ docs/
│  │  ├─ worklog.md
│  │  ├─ project-context.md
│  │  └─ blog-ideas.md
│  ├─ drafts/
│  └─ blogs/
├─ tests/
├─ README.md
└─ AGENTS.md
```

---

# 6. 반드시 분리할 계층

## A. Agent 계층

사용자의 요청 단위 흐름을 조율한다.

예:

* 블로그 주제 추천
* 블로그 초안 생성
* 최신 초안 미리보기
* Notion 동기화

## B. Service 계층

실제 기능 단위 로직을 담당한다.

예:

* topic recommendation
* draft generation
* preview
* notion sync

## C. Content Source 계층

데이터를 읽는 역할만 한다.

예:

* Local worklog
* Project context
* Git log
* Notion idea/worklog

## D. Storage / Repository 계층

데이터 저장과 조회를 담당한다.

예:

* Markdown draft 저장
* Blog metadata 조회
* Notion DB row 생성/수정

## E. LLM 계층

LLM provider를 교체 가능하게 만든다.

지원 후보:

* Ollama
* vLLM
* OpenAI-compatible API

---

# 7. Notion 연동 규칙

## 7-1. 필요한 환경 변수

`.env` 기반으로 설정한다.

```env
NOTION_API_KEY=
NOTION_BLOG_DATABASE_ID=
NOTION_IDEA_DATABASE_ID=
NOTION_WORKLOG_DATABASE_ID=

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b-instruct-q4_K_M
```

환경 변수명은 구현 상황에 맞게 조정해도 되지만, README에 반드시 문서화한다.

---

## 7-2. Notion Blog DB 기본 스키마

최소 아래 컬럼을 가정한다.

* `Title`
* `Status`
* `Source Project`
* `Tags`
* `Local Path`
* `Created At`
* `Updated At`
* `Source Refs`

가능하면 아래도 고려한다.

* `Slug`
* `Summary`
* `Notion Page ID`
* `Published URL`

---

## 7-3. Notion에 저장할 것

초기 MVP에서는 Markdown 본문 전체를 Notion에 완벽히 업로드하지 않아도 된다.

하지만 아래는 저장해야 한다.

* 제목
* 상태
* 태그
* 관련 프로젝트
* 로컬 파일 경로
* 생성일
* 수정일
* 참고 source refs

---

# 8. 블로그 메타데이터 규칙

모든 draft는 아래 메타데이터를 가져야 한다.

```yaml
title:
slug:
tags:
source_project:
status:
created_at:
updated_at:
source_refs:
local_path:
notion_page_id:
```

Markdown frontmatter 또는 별도 JSON metadata 파일을 사용할 수 있다.
단, Notion DB와 매핑 가능해야 한다.

---

# 9. 블로그 초안 스타일

## 원하는 스타일

* 기술 블로그 톤
* 실제 작업 회고 기반
* 문제 → 원인 → 해결 → 결과 → 배운 점 구조
* 과장 없는 문체
* 실무 경험 정리 느낌
* 너무 긴 도입부 없이 바로 문제 상황으로 진입

## 피해야 할 스타일

* 홍보성 문체
* 자기계발 에세이 톤
* “이 기술은 현대 소프트웨어 개발에서 매우 중요하다” 같은 일반론
* 실제 작업과 무관한 설명
* 검증되지 않은 수치
* 너무 긴 코드 블록 남발

---

# 10. 프롬프트 관리 규칙

LLM 프롬프트는 코드 안에 직접 길게 하드코딩하지 않는다.

아래 파일에 분리한다.

```text
app/prompts/recommend_topics.md
app/prompts/write_draft.md
app/prompts/revise_draft.md
```

프롬프트에는 반드시 아래 제약을 포함한다.

* source 기반으로만 작성
* 모르면 모른다고 표시
* 존재하지 않는 수치 생성 금지
* 과장 금지
* 기술 블로그 톤 유지
* source refs를 결과에 반영

---

# 11. 샘플 데이터

초기 개발 검증을 위해 아래 파일을 반드시 만든다.

## `workspace/docs/worklog.md`

예시 내용:

* XCoreChat 개발/운영 환경 분리
* 운영 DB와 개발 DB 분리
* 원격 vLLM 연결
* Qdrant 개발 인스턴스 구성
* Docker Compose 수정
* PowerShell curl 이슈
* 서버 재부팅 후 연결 정상화

## `workspace/docs/project-context.md`

예시 내용:

* XCoreChat 프로젝트 개요
* 사내 규정 RAG 시스템
* FastAPI / React / Qdrant / PostgreSQL / vLLM / BGE-m3
* 온프레미스 LLM 기반 구조
* 하이브리드 검색 구조
* 문서 관리 / 챗봇 / 관리자 기능

## `workspace/docs/blog-ideas.md`

예시 내용:

* RAG 개발환경 분리 과정
* vLLM 원격 연결 문제 해결
* Qdrant 개발/운영 분리
* 사내 규정 RAG 검색 품질 개선

---

# 12. 테스트 전략

처음부터 테스트를 과하게 만들 필요는 없다.

하지만 최소한 아래는 테스트 가능해야 한다.

* local content source가 문서를 읽는지
* git source가 최근 커밋 정보를 읽는지
* markdown storage가 draft를 저장하는지
* blog metadata가 생성되는지
* notion sync service가 mock client로 테스트 가능한지

Notion API는 실제 호출 테스트와 mock 테스트를 분리한다.

---

# 13. README 필수 내용

README에는 반드시 아래를 포함한다.

1. 프로젝트 목적
2. MVP 범위
3. 폴더 구조
4. 설치 방법
5. `.env` 설정 방법
6. CLI 명령어
7. Notion Integration 생성 방법
8. Notion DB 스키마
9. 샘플 workspace 문서 설명
10. 향후 확장 계획

---

# 14. 구현 순서

Claude Code는 아래 순서로 작업한다.

## 1단계

요구사항을 요약하고 MVP 범위를 확정한다.

## 2단계

파일 구조와 모듈 책임을 제안한다.

## 3단계

기본 프로젝트 구조를 생성한다.

## 4단계

local content source, git source, markdown storage를 구현한다.

## 5단계

LLM provider 인터페이스와 draft generator를 구현한다.

## 6단계

CLI 명령을 구현한다.

## 7단계

Notion client / repository / sync service를 구현한다.

## 8단계

README와 샘플 데이터를 작성한다.

---

# 15. 진행 보고 규칙

각 단계가 끝날 때마다 아래를 짧게 보고한다.

* 구현한 것
* 아직 남은 것
* 실행 방법
* 주의할 점

---

# 16. 금지 사항

아래는 하지 않는다.

* Telegram / Discord / Mattermost를 이번 MVP에 넣기
* 웹 UI부터 만들기
* Notion 연동을 모든 기능보다 먼저 구현하기
* 핵심 로직을 CLI 파일에 몰아넣기
* 모든 파일을 무작정 읽어서 LLM에 넣기
* source 없는 내용을 생성하기
* 지나친 추상화로 MVP를 늦추기
* README 없이 코드만 만들기

---

# 17. 완료 기준

이번 MVP는 아래가 되면 1차 완료로 본다.

1. `work-agent suggest-topics`가 동작한다.
2. `work-agent write-draft "주제"`가 Markdown 초안을 생성한다.
3. `work-agent preview latest`로 최신 초안을 볼 수 있다.
4. `work-agent sync-notion`이 Notion Blog DB와 메타데이터를 동기화한다.
5. README에 실행 방법과 Notion 설정 방법이 정리되어 있다.
6. 구조상 Portfolio / Todo / Resume Agent로 확장 가능하다.

---

# 18. 최종 기준

구현 중 판단이 필요하면 항상 아래 기준을 따른다.

1. 이 기능이 실제로 블로그 초안 작성 시간을 줄이는가?
2. Notion 기반 Work Agent로 확장 가능한가?
3. 지금 MVP를 늦출 만큼 과한 구현은 아닌가?

이 프로젝트는 멋진 데모보다 **실제로 내가 블로그를 미루지 않게 해주는 도구**가 되는 것이 중요하다.
