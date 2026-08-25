# AGENTS.md — devtrail 개발 규칙

이 파일이 devtrail 레포에서 일하는 모든 코딩 에이전트(Claude Code, Codex,
Cursor 등)의 정본 규칙이다. 도구별 파일(CLAUDE.md 등)은 이 파일을 보완할 뿐
여기 내용과 충돌하면 이 파일이 우선한다.

## 프로젝트 개요

Obsidian Vault를 단일 지식 저장소로 삼아 작업 흔적을 캡처·정제하고
블로그·포트폴리오·이력서 초안까지 만드는 개인 지식 OS CLI/봇.

```
[ Capture ] → [ Distill ] → [ Curate ] → [ Generate ] → [ Deliver ]
 00_Inbox     60_Candidates   검토→승격    50_Outputs     Telegram·Blog
 10_Worklog
```

핵심 불변식: **LLM은 창작자가 아니라 작업 기록 정리자다. source에 없는
사실·수치를 만들지 않는다.**

현재 진행 중인 개선 방향은 `docs/devtrail-improvement-roadmap.md` 참고.

## 아키텍처 지도

| 경로 | 역할 |
|------|------|
| `app/cli.py` | Typer CLI 진입점. 명령 파싱과 출력만 — 로직은 agent/service로 위임 |
| `app/agents/` | 파이프라인 단위 오케스트레이션 (CaptureAgent, DistillAgent, WikiBlogAgent 등). LLM 호출·프롬프트 조립은 여기서 |
| `app/services/` | 순수 로직·저장소 접근 (wiki_service, candidate_writer, retention 등). LLM 의존 없이 테스트 가능해야 함 |
| `app/models/` | dataclass 기반 데이터 모델 (ContextPack, SourceChunk 등) |
| `app/memory/` | ContextPackBuilder, AgentMemory/ProjectMemory 로더 |
| `app/prompts/` | LLM 프롬프트 템플릿(`*.md`) — 프롬프트를 코드에 하드코딩하지 않는다 |
| `app/llm/` | provider 추상화 + task_type 라우팅(`router.py`), 폴백 체인 |
| `app/messaging/` | Telegram 봇 라우터 |
| `app/vault_tools.py` | MCP 도구 구현 (get_project_briefing, write_work_plan, write_session_process 등) |
| `app/mcp_server.py` | MCP 서버 진입점 |
| `tests/` | pytest 테스트 (`testpaths = ["tests"]`) |
| `scripts/` | git hook, 스케줄러 등 설치 스크립트 |

## 개발 규칙

### 코드 배치

- 새 로직은 계층에 맞는 곳에 둔다: LLM 오케스트레이션 → `app/agents/`,
  vault·파일 조작 → `app/services/`, 데이터 구조 → `app/models/`.
  CLI 명령 함수 안에 비즈니스 로직을 쌓지 않는다.
- LLM 호출은 반드시 `app/llm`의 라우터(`get_task_llm_provider`) 경유.
  provider를 직접 인스턴스화하지 않는다.
- 프롬프트는 `app/prompts/*.md`에 두고 `render_prompt`로 렌더링한다.
- Vault의 `60_Candidates/` 쓰기는 `candidate_writer` 경유. 공식 영역
  (`20_Knowledge/`, `30_Projects/`, `40_AgentMemory/`)에 코드가 직접 쓰는
  경로를 만들지 않는다 — 승격은 항상 `promote-candidate`/`apply-memory-patch`.

### 스타일

- Python 3.11+, pydantic v2, dataclass 위주. 타입 힌트 필수.
- docstring·주석은 한국어. 주석은 코드로 드러나지 않는 제약·이유만 적는다
  ("무엇을 하는지" 반복 금지). 주변 코드의 밀도에 맞춘다.
- 새 외부 의존성 추가는 사전 합의 필요 — stdlib·기존 의존성으로 안 되는지 먼저 확인.
- 비밀값(API 키·토큰)은 코드·로그·테스트 fixture·커밋에 남기지 않는다.
  설정은 `.env` + `app/config.py`(pydantic-settings) 경유.

### 테스트

- 실행: `python -m pytest` (레포 루트에서).
- 로직 변경·추가에는 테스트를 동반한다. 파일 규칙은 `tests/test_<모듈>.py`.
- 테스트는 LLM을 호출하지 않는다 — provider는 fake/monkeypatch로 대체
  (기존 테스트 패턴 참고: `tests/test_distill_agent.py` 등).
- 변경 후 테스트 통과 확인 없이 "완료"라고 보고하지 않는다. 실패하면
  실패 내용을 그대로 보고한다.

### 브랜치 · 커밋 · PR

- 새 Agent / CLI 커맨드 / 계층 구조 변경은 `feat/` 또는 `refactor/` 브랜치에서.
  문서(md)만 수정할 때는 main 직접 커밋 허용.
- 커밋 메시지: `type: 설명` (feat/fix/docs/style/refactor), 본문 한국어.
- 커밋·push는 사용자 요청이 있을 때만.
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를
  넣지 않는다.
- GitHub 작업은 `gh` CLI 사용, squash merge 기본.
- 큰 리팩터링·파일 대량 변경 전에는 계획을 먼저 제시하고 확인받는다.

### 작업 절차

- 구현 전에 Plan을 남긴다 — 세션 단위는 MCP `write_work_plan`, 기능 단위
  (며칠 이상)는 `docs/` 또는 Vault `30_Projects/<P>/Plans/`.
- 사용자의 결정이 필요한 지점(설계 선택, 파괴적 변경)은 진행하지 말고 질문한다.
- 로드맵(`docs/devtrail-improvement-roadmap.md`)에 있는 작업은 해당 항목의
  수용 기준·비범위를 따른다. 범위를 넓히고 싶으면 먼저 제안한다.

## Vault 접근 권한 (요약)

에이전트가 Vault를 다룰 때의 권한. 상세 표는 CLAUDE.md 참고.

- **읽기 전용**: `00_Inbox/`, `10_Worklog/`, `50_Outputs/`
- **직접 수정 금지** (승격 경유): `20_Knowledge/`, `30_Projects/<P>/Context.md`·`Decisions/`, `40_AgentMemory/`
- **AI 생성 허용**: `60_Candidates/` 하위 (모든 AI 출력의 유일한 진입점)
- **예외**: `60_Candidates/SessionHandoffs/`는 `write_work_plan`/`write_session_process` 전용, `70_Tasks/`는 task 커맨드 경유
