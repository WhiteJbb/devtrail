# Claude Code Prompt — Work Agent MVP (CLI + Notion 중심 Blog Agent)

당신은 내 개인 생산성 Agent 프로젝트의 첫 번째 모듈인 **Blog Agent MVP**를 설계하고 구현하는 시니어 AI/백엔드 엔지니어다.
이 프로젝트의 장기 목표는 **개발 작업 기록, 포트폴리오 자료, 이력서 문구, 블로그 초안, TODO를 통합 관리하는 Personal Work Agent**를 만드는 것이다.

이번 단계에서는 그 첫 MVP로 **CLI + Notion 중심의 Blog Agent**를 구현한다.

---

# 1. 프로젝트 목표

이 프로젝트는 단순한 블로그 글 생성기가 아니다.
장기적으로는 다음과 같은 역할을 하는 개인 Work Agent로 확장될 예정이다.

* 작업 기록 정리
* 블로그 초안 생성
* 포트폴리오 문서 초안 생성
* 이력서 / 자기소개서 문장 정리
* TODO / 다음 행동 추천
* Notion 기반 개인 작업 허브 운영

하지만 **이번 단계의 범위는 Blog Agent MVP**다.

## 이번 MVP의 핵심 목표

사용자가 CLI에서 아래와 같이 명령하면:

* `work-agent suggest-topics`
* `work-agent write-draft "XCoreChat 개발환경 분리"`
* `work-agent sync-notion`
* `work-agent preview latest`

에이전트가 아래를 수행해야 한다.

1. **Notion / 로컬 작업 문서 / Git 로그**에서 관련 정보를 수집한다.
2. 최근 작업을 바탕으로 블로그 주제를 추천한다.
3. 특정 주제에 대한 기술 블로그 초안을 Markdown으로 생성한다.
4. 초안을 로컬 파일로 저장한다.
5. 초안/메타데이터를 Notion 데이터베이스와 동기화할 수 있다.
6. 이후 Portfolio / Resume / Todo Agent로 확장 가능한 구조를 갖는다.

---

# 2. 구현 철학

## 중요한 원칙

이 프로젝트의 목표는 “완성형 블로그 자동 작성기”가 아니다.

목표는 다음과 같다.

* **내 작업 기록과 프로젝트 문맥을 읽고**
* **70~80점짜리 기술 블로그 초안을 빠르게 생성하고**
* **내가 5~10분 다듬어서 게시 가능한 상태로 만드는 것**

즉, “빈 종이에서 멋진 글을 창작하는 시스템”이 아니라,
**내 실제 작업 흔적을 기반으로 초안을 정리하는 Work Agent**를 만드는 것이 핵심이다.

---

# 3. 이번 MVP에서의 사용자 경험

## 3-1. 기본 사용 흐름

사용자는 CLI에서 아래 같은 명령을 실행한다.

### 예시 1: 블로그 주제 추천

```bash id="s4gdxt"
work-agent suggest-topics
```

### 예시 2: 특정 주제로 블로그 초안 작성

```bash id="6vhsye"
work-agent write-draft "XCoreChat 개발환경 분리"
```

### 예시 3: 최신 초안 미리보기

```bash id="67h15w"
work-agent preview latest
```

### 예시 4: Notion과 동기화

```bash id="et02yd"
work-agent sync-notion
```

---

## 3-2. 에이전트가 해야 하는 일

### 블로그 주제 추천 모드

1. 최근 Git 커밋, worklog, project context, Notion 작업 메모/아이디어를 읽는다.
2. 블로그로 쓸 만한 주제 3개 내외를 추천한다.
3. 각 주제마다 아래를 보여준다.

   * 제목 후보
   * 주제 선정 이유
   * 예상 목차
   * 참고한 source refs

### 블로그 초안 작성 모드

1. 요청 주제와 관련된 자료를 수집한다.
2. 블로그 구조를 생성한다.
3. Markdown 초안을 만든다.
4. 로컬 `drafts/`에 저장한다.
5. 해당 draft 메타데이터를 Notion DB에도 반영 가능해야 한다.

---

# 4. MVP 범위

## 이번 MVP에서 반드시 포함할 기능

### A. CLI 인터페이스

이번 MVP의 메인 인터페이스는 **CLI**다.
웹 UI, 채팅봇, 텔레그램 봇은 지금 우선순위가 아니다.

반드시 아래 명령 흐름이 있어야 한다.

#### 1) 블로그 주제 추천

```bash id="z64k15"
work-agent suggest-topics
```

#### 2) 특정 주제로 블로그 초안 생성

```bash id="du4r7u"
work-agent write-draft "주제"
```

#### 3) 최근 초안 미리보기

```bash id="bxv6sm"
work-agent preview latest
```

#### 4) Notion 동기화

```bash id="rn6h5p"
work-agent sync-notion
```

---

### B. 데이터 소스

초기 MVP에서 에이전트가 읽는 소스는 아래와 같다.

## 1) 로컬 문서

예시:

* `workspace/docs/worklog.md`
* `workspace/docs/project-context.md`
* `workspace/docs/blog-ideas.md`
* `workspace/docs/todo.md`

## 2) Git 커밋 로그

* 최근 N개 커밋
* 커밋 메시지
* 변경 파일 목록
* 필요하면 diff 일부 요약

## 3) Notion

Notion은 이번 MVP의 **중요한 1급 소스**다.
단순 확장 포인트가 아니라, 이번 MVP에서 실제로 최소한의 연동이 들어가야 한다.

Notion에서 다루고 싶은 데이터는 아래와 같다.

### Notion에서 읽고 싶은 것

* 블로그 아이디어 DB
* 작업 메모 / worklog 페이지
* 프로젝트 관련 메모
* draft 상태의 블로그 문서 메타데이터

### Notion에 쓰고 싶은 것

* 블로그 draft 메타데이터
* draft 링크 / 로컬 파일 경로
* 상태 변경 (`idea` → `draft` → `review` → `published`)
* 태그 / source refs / 프로젝트 연결 정보

---

# 5. Notion 중심 워크플로우

이번 MVP는 **Notion을 단순한 “나중 확장 포인트”가 아니라 실제 워크플로우 허브**로 본다.

## 내가 원하는 Notion 역할

Notion은 아래를 담당한다.

### 1) 블로그 아이디어 허브

예:

* 제목 후보
* 아이디어 메모
* source project
* 상태 (`idea`, `draft_requested`, `draft_generated`, `published`)

### 2) 작업 기록 허브

예:

* 최근 작업 메모
* 문제 상황 / 해결 메모
* 블로그로 승격할 만한 포인트

### 3) 초안 메타데이터 허브

예:

* 로컬 draft 파일 경로
* 생성 시각
* 관련 프로젝트
* 태그
* 초안 상태

---

## 원하는 Notion 사용 시나리오

### 시나리오 A: CLI에서 초안 생성 후 Notion에 등록

```bash id="lf78cm"
work-agent write-draft "XCoreChat 개발환경 분리"
```

결과:

* 로컬 `drafts/`에 Markdown 저장
* Notion Blog DB에 draft row 생성/업데이트
* title / status / source_project / tags / local_path / updated_at 저장

### 시나리오 B: Notion에 적어둔 아이디어 기반 추천

```bash id="qkex8e"
work-agent suggest-topics
```

결과:

* Notion Blog Idea DB + worklog + git log를 종합해서 추천

### 시나리오 C: sync

```bash id="b1exm4"
work-agent sync-notion
```

결과:

* 로컬 draft와 Notion 메타데이터 정합성 맞춤
* 새 draft는 Notion에 등록
* 상태/수정일/태그 동기화

---

# 6. 구현해야 할 Notion 범위

## 이번 MVP에서 Notion은 “placeholder”가 아니라 최소 동작 구현이 필요하다

다만 처음부터 모든 기능을 다 할 필요는 없다.

## MVP Notion 필수 범위

### 1) Notion Blog DB 연동

최소 아래 컬럼과 연동되는 구조를 만든다.

* `Title`
* `Status`
* `Source Project`
* `Tags`
* `Local Path`
* `Created At`
* `Updated At`
* `Source Refs`

### 2) Notion Worklog / Idea source 읽기

최소한 아래 둘 중 하나는 가능해야 한다.

* 특정 Notion DB에서 블로그 아이디어 목록 읽기
* 특정 Notion 페이지/DB에서 worklog 성격의 메모 읽기

### 3) 로컬 draft → Notion 메타데이터 업로드

초안 파일 자체를 Notion 본문으로 완벽하게 밀어넣지 않아도 된다.
하지만 **초안 메타데이터를 Notion Blog DB row로 반영**하는 것은 구현해라.

---

# 7. 장기 확장 방향

이 프로젝트는 Blog Agent 이후 아래로 확장될 예정이다.

1. **Portfolio Agent**

   * 프로젝트 기록 기반 포트폴리오 설명 초안 생성

2. **Resume / Cover Letter Agent**

   * 이력서 bullet / 자기소개서 초안 생성

3. **Todo Agent**

   * 최근 작업 기반 다음 할 일 제안

4. **Worklog Agent**

   * 커밋 / 메모 / Notion을 기반으로 자동 회고/작업 정리

이번 Blog Agent MVP는 이 확장을 막지 않도록 설계해야 한다.

---

# 8. 기술 스택

## 백엔드

* Python 3.11+
* FastAPI (향후 API 서버 확장용, 이번 MVP에서 반드시 HTTP 기능이 필요하진 않음)

## 인터페이스

* CLI 우선
* FastAPI는 내부 서비스/API 레이어 준비용으로 둘 수 있음
* 이번 단계에서 텔레그램/디스코드/웹UI는 우선순위가 아니다

## LLM

* 로컬 LLM 또는 OpenAI-compatible endpoint를 지원하는 구조
* provider 교체 가능 구조를 원함
* Ollama / vLLM / OpenAI-compatible API 중 하나를 쉽게 교체 가능하게 설계

## 저장

* 로컬 Markdown 파일 저장
* frontmatter 또는 별도 metadata JSON 사용 가능
* Notion DB 메타데이터 동기화

---

# 9. 아키텍처 요구사항

이번 프로젝트는 **Work Agent의 첫 번째 모듈**이다.
그러므로 구조는 “Blog Agent만 겨우 돌아가는 스크립트”가 아니라, 이후 확장 가능한 형태여야 한다.

## 권장 구조 예시

```text id="yeyzc5"
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
│  │ ├─ project_context_source.py
│  │ ├─ git_source.py
│  │ └─ notion_source.py
│  ├─ repositories/
│  │ ├─ blog_repository.py
│  │ └─ notion_blog_repository.py
│  ├─ storage/
│  │ ├─ markdown_storage.py
│  │ └─ notion_client.py
│  ├─ models/
│  │ ├─ blog_post.py
│  │ ├─ draft_request.py
│  │ ├─ topic_suggestion.py
│  │ └─ notion_models.py
│  └─ prompts/
│     ├─ recommend_topics.md
│     ├─ write_draft.md
│     └─ revise_draft.md
├─ workspace/
│  ├─ docs/
│  │ ├─ worklog.md
│  │ ├─ project-context.md
│  │ └─ blog-ideas.md
│  ├─ drafts/
│  └─ blogs/
├─ tests/
└─ README.md
```

구조는 합리적으로 조정해도 되지만 아래 원칙은 반드시 지켜라.

---

# 10. 반드시 지켜야 할 구조 원칙

1. **CLI는 얇고, 핵심 로직은 Agent/Service 계층에 둔다**
2. **LLM 호출 로직과 비즈니스 로직을 분리한다**
3. **콘텐츠 수집 로직(content sources)과 저장/동기화 로직(storage/repository)을 분리한다**
4. **Notion 연동 코드는 전용 계층으로 분리한다**
5. **Blog Agent 외 Portfolio/Todo Agent가 추가될 수 있도록 app 구조를 잡는다**

---

# 11. 실제 구현해야 할 CLI 명령

## 11-1. 주제 추천

```bash id="y8k3eq"
work-agent suggest-topics
```

기대 결과:

* 추천 주제 3개 내외 출력
* 각 주제의 제목 후보 / 추천 이유 / 예상 목차 / source refs 제공

---

## 11-2. 초안 생성

```bash id="p4n1sv"
work-agent write-draft "XCoreChat 개발환경 분리"
```

기대 결과:

* `workspace/drafts/`에 Markdown 초안 생성
* 메타데이터 생성
* Notion Blog DB row 생성/업데이트 가능

---

## 11-3. 미리보기

```bash id="vctk7u"
work-agent preview latest
```

기대 결과:

* 최신 초안 제목 / 메타데이터 / 본문 일부 출력

---

## 11-4. Notion 동기화

```bash id="shv6z2"
work-agent sync-notion
```

기대 결과:

* 로컬 draft와 Notion Blog DB 메타데이터 정합성 맞춤
* 새 draft 반영
* 상태/수정일/태그 동기화

---

# 12. 블로그 품질 기준

생성 결과는 “예쁜 문장”보다 **기술 블로그로서의 정보 밀도와 작업 기반성**이 중요하다.

## 반드시 반영할 것

* 왜 이 작업을 했는지 드러나야 한다.
* 문제 상황 / 기존 구조 / 제약이 보여야 한다.
* 실제 변경, 시행착오, 판단이 보여야 한다.
* 실제 source 기반으로 쓰여야 한다.
* 과장된 마케팅 문체는 피해야 한다.

## 피해야 할 것

* 존재하지 않는 성능 수치나 결과를 지어내는 것
* 인터넷 일반론만 늘어놓는 것
* source 없이 “그럴듯한 이야기”만 쓰는 것
* 과도하게 자기계발 블로그 같은 톤

---

# 13. 메타데이터 설계

블로그 초안/문서는 최소 아래 메타데이터를 구조적으로 가져야 한다.

* `title`
* `slug`
* `tags`
* `source_project`
* `status` (`idea`, `draft`, `review`, `published`)
* `created_at`
* `updated_at`
* `source_refs`
* `local_path`
* `notion_page_id` (있다면)

이 메타데이터는 로컬 파일과 Notion DB 모두에 매핑 가능해야 한다.

---

# 14. 내가 원하는 산출물

## A. 실행 가능한 CLI MVP

최소 아래가 동작해야 한다.

* `suggest-topics`
* `write-draft`
* `preview latest`
* `sync-notion`

## B. README

README에는 아래가 포함되어야 한다.

1. 프로젝트 목적
2. CLI 사용법
3. Notion 설정 방법
4. `.env` 구성 방법
5. workspace 문서 구조 설명
6. 향후 Portfolio/Todo Agent 확장 방향

## C. 샘플 데이터

최소 아래 샘플 파일을 포함해라.

* `workspace/docs/worklog.md`
* `workspace/docs/project-context.md`
* `workspace/docs/blog-ideas.md`

## D. Notion 연동 가이드

아래를 짧게 정리해라.

* 필요한 Notion integration 권한
* Blog DB 예시 스키마
* worklog / idea DB를 붙이는 방법

---

# 15. 작업 방식

작업을 시작할 때는 아래 순서로 진행해라.

1. 요구사항을 요약하고 MVP 범위를 짧게 정리
2. 파일 구조 / 모듈 구조를 먼저 제안
3. 구현 단계를 3~6단계로 나눠 제시
4. 가장 작은 단위부터 구현 시작
5. 각 단계가 끝날 때마다

   * 무엇을 구현했는지
   * 무엇이 남았는지
   * 어떻게 실행하는지
     짧게 보고

중요:
처음부터 거대한 코드 덩어리를 한 번에 만들지 말고, **CLI MVP 완성까지 필요한 최소 단위로 잘라서 구현**해라.

---

# 16. 최종 판단 기준

구현 중 의사결정이 필요하면 항상 아래 기준으로 판단해라.

1. **이 기능이 실제로 블로그 초안 작성 시간을 줄여주는가?**
2. **이 구조가 Notion 기반 Work Agent로 확장될 수 있는가?**
3. **하지만 지금 MVP를 늦출 정도로 과한 구현은 아닌가?**

이제 위 요구사항을 바탕으로 **CLI + Notion 중심 Blog Agent MVP의 구현 계획을 먼저 제안한 뒤, 실제 프로젝트 구조와 코드 작성을 시작해라.**
