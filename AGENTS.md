# AGENTS.md — devtrail 개발 규칙

이 파일이 devtrail 레포에서 일하는 모든 코딩 에이전트(Claude Code, Codex,
Cursor 등)의 **유일한 정본 규칙**이다. 도구별 파일(`CLAUDE.md` 등)은 이 파일을
가리키기만 하며 별도 규칙을 두지 않는다.

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

- 제품 방향: `docs/final.md`, 구현 실측 대비 검토: `docs/final-review.md`
- 진행 중 개선 항목: `docs/devtrail-improvement-roadmap.md`

## 아키텍처 지도

| 경로 | 역할 |
|------|------|
| `app/cli.py` | Typer CLI 진입점(약 40개 커맨드). 명령 파싱과 출력만 — 로직은 agent/service로 위임 |
| `app/config.py` | pydantic-settings 설정 로더. 경로·키 접근은 모두 여기 경유 |
| `app/agents/` | 파이프라인 단위 오케스트레이션 (CaptureAgent, DistillAgent, WikiBlogAgent 등). LLM 호출·프롬프트 조립은 여기서 |
| `app/services/` | 순수 로직·저장소 접근 (wiki_service, candidate_writer, retention, task_service, doctor, identity 등). LLM 의존 없이 테스트 가능해야 함 |
| `app/models/` | dataclass 기반 데이터 모델 (ContextPack, SourceChunk) |
| `app/memory/` | ContextPackBuilder, AgentMemory/ProjectMemory 로더 |
| `app/prompts/` | LLM 프롬프트 템플릿(`*.md`) — 프롬프트를 코드에 하드코딩하지 않는다 |
| `app/llm/` | provider 추상화 + task_type 라우팅(`router.py`), 폴백 체인(`fallback.py`) |
| `app/messaging/` | Telegram 봇 라우터·미디어 핸들러 |
| `app/assistant/` | 자연어 의도 분류(`intent.py`)와 어시스턴트 응답 조립 |
| `app/vault_tools.py` | MCP 도구 구현 (get_project_briefing, write_work_plan, write_session_process 등) |
| `app/mcp_server.py` | MCP 서버 진입점 (`devtrail mcp-serve`) |
| `scripts/hooks/` | Claude Code 훅 (plan-check, session-start-briefing, stop-process-check) + git post-commit |
| `scripts/activity/`, `scripts/mac/`, `scripts/windows/` | 셸 활동 훅, 머신별 스케줄러 설치 스크립트 |
| `tests/` | pytest 테스트 (`testpaths = ["tests"]`) |
| `docs/` | 설계·계획 문서 |

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

- 통합 브랜치는 `dev`다. 기능·수정은 `feat/`·`fix/`·`refactor/` 브랜치를 dev에서
  파서 작업하고, **GitHub PR(base: dev)을 올려 squash merge로 반영한다** — 로컬
  직접 merge 금지. main 반영은 dev가 안정된 시점에 별도 PR로.
  문서(md)만 수정할 때는 대상 브랜치 직접 커밋 허용.
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
  결정 결과는 `write_session_process`의 project_decisions 또는 decision 후보로
  남겨 `30_Projects/<P>/Decisions/`에 쌓이게 한다.
- 오류·수정 내역은 Process(What Changed / Agent Execution Notes)에 기록한다 —
  별도 WorkLog 파일을 만들지 않는다.
- 중요한 프롬프트 원문은 `30_Projects/<P>/PromptLog.md`에 append한다
  (날짜 · 용도 · 원문 · 결과 링크).
- 로드맵(`docs/devtrail-improvement-roadmap.md`)에 있는 작업은 해당 항목의
  수용 기준·비범위를 따른다. 범위를 넓히고 싶으면 먼저 제안한다.

## 세션 생명주기

### MCP가 연결된 경우 (1차 경로)

`devtrail mcp-serve`가 붙어 있으면 기록은 MCP 도구로 남긴다.

1. **세션 시작** — `get_project_briefing`을 먼저 호출한다.
2. **구현 전** — `write_work_plan`으로 Plan을 남긴다.
3. **세션 종료·컴팩팅 전** — `write_session_process`를 호출한다.
   SessionHandoffs candidate와 `10_Worklog/Sessions/` 세션 기록을 한 번에
   만들므로 `capture-session`을 따로 실행할 필요가 없다.

기록 작성 규칙:

- 여러 항목이 있는 필드(goal, what_changed 등)는 한 문단으로 잇지 말고 markdown
  불릿/번호 리스트로 쓴다 — 기록은 사람이 다시 읽는 문서다.
- Process 기록 후 작업이 더 이어졌다면(커밋 발생) 세션을 끝내기 전에
  `write_session_process`를 **다시 호출**한다. 같은 세션 기록이 갱신되므로
  중복 파일 걱정 없이 최신 상태를 반영하면 된다.
- `agent_execution_notes`의 next_checks/better_approach는 Lessons로 증류되는
  필드다 — 이번 세션 한정 사실이 아니라 다음 세션에도 통하는 교훈으로 쓴다.

### 훅이 강제하는 것

`.claude/settings.example.json`을 `.claude/settings.json`으로 복사하면 활성화된다
(`.claude/*`는 gitignore 대상이라 클론 직후엔 없다 — `devtrail doctor`가 진단한다).

| 훅 | 시점 | 역할 |
|----|------|------|
| `session-start-briefing` | SessionStart | 프로젝트 briefing 자동 주입 |
| `plan-check` | PreToolUse (Edit/Write) | Plan 미기록 상태의 구현 차단 |

| `stop-process-check` | Stop · PreCompact | 세션 기록 누락 경고 |

MCP 서버는 첫 tool 호출 시 `.claude/.vault-mcp/mcp_sessions/` 아래에 프로세스별 마커를 만든다.
훅은 같은 repo에서 최근 12시간 안에 갱신됐고 PID가 살아 있는 MCP 마커가 정확히 하나일
때만 그 상태를 사용한다. 마커가 없거나 여러 개이거나 프로세스 상태를 확인할 수 없으면
강제하지 않는다(MCP 미연결 fallback 포함). 새 SessionStart 훅은 다른 MCP 프로세스의
마커를 삭제하지 않는다.

Claude hook payload의 `session_id`와 MCP 서버 내부 session ID는 서로 다른 값이고,
현재 MCP 설정에는 둘을 명시적으로 연결하는 경로가 없다. 따라서 같은 repo에서 Claude
세션 여러 개가 각각 MCP 서버를 실행하면 live 마커가 여러 개가 되어 plan/stop enforcement가
fail-open 된다. 동시 세션별 enforcement가 필요하면 MCP 설정에 명시적 session binding을
추가해야 한다.

### capture-session fallback (MCP 미연결 시)

`devtrail capture-session --from-agent` 실행 시:

1. 세션에서 실제로 수행한 일을 되돌아보고, 아래 항목을 포함한 요약 Markdown을
   충분히 자세하게 작성한다:
   - **오늘 작업한 내용** — 무엇을 왜 했는지, 작업 흐름 포함. "X를 구현했다"가
     아니라 "X가 없어서 Y 문제가 생겼고, Z 방식으로 해결했다" 수준으로.
   - **변경/추가/삭제된 파일** — 경로 + 변경 이유 한 줄씩.
   - **해결한 문제나 버그** — 증상·원인·해결 방법 모두.
   - **설계 결정과 그 이유** — 나중에 "왜 이렇게 했지?"가 안 나올 수준으로.
   - **남은 문제 및 다음 할 일**
   - **블로그/포트폴리오 소재** — 제목 수준으로라도.
   - **Learning Recovery** — AI가 주도적으로 처리한 부분, 아직 이해 못 한 개념,
     직접 설명해봐야 할 질문(2~3개 이하). 이해도를 과장하지 않는다.
2. 요약을 임시 파일로 저장한 뒤 `--summary-file`로 전달한다.
3. 실제로 하지 않은 일은 절대 쓰지 않는다. 불확실하면 `확실하지 않음`으로 표시.

```bash
devtrail capture-session --project <프로젝트명> --from-repo --from-agent --summary-file ./session-summary.md
```

## Vault 구조와 권한

Obsidian Vault는 모든 Agent가 공유하는 메모리 버스다. 작업 시작 전:

- `{VAULT}/30_Projects/<Project>/Context.md` — 배경·목표·제약 (briefing이 자동 주입)
- `{VAULT}/40_AgentMemory/00_Profile.md` ~ `06_Lessons.md` — 전역 AI 메모리·미해결 이슈

| 폴더 | 역할 | AI 권한 |
|------|------|---------|
| `00_Inbox/URLs/` | URL 캡처 노트 | 읽기 전용 |
| `00_Inbox/Memos/` | 텍스트·음성·이미지 캡처 노트 | 읽기 전용 |
| `00_Inbox/Raw/` | 첨부 바이너리 파일 | 읽기 전용 |
| `10_Worklog/Sessions/` | capture-session / write_session_process 출력 | 읽기 전용 |
| `10_Worklog/Daily/` | daily-log (사람이 직접 채우는 일지) | 읽기 전용 |
| `10_Worklog/GitSummaries/` | 커밋별 git 요약 | 읽기 전용 |
| `20_Knowledge/` | 승격된 공식 지식 노트 | **직접 수정 금지** — `promote-candidate` 경유 |
| `30_Projects/<P>/Context.md` | 프로젝트 배경·목표·제약 | **직접 수정 금지** — 사람이 관리 |
| `30_Projects/<P>/Decisions/` | 의사결정 이력 (DecisionLog) | **직접 수정 금지** — `promote-candidate` 경유 |
| `30_Projects/<P>/Plans/` | 기능 단위 구현 계획 | 사람과 협의 후 작성 |
| `30_Projects/<P>/Design/` | IA · UserScenarios · Personas | 사람과 협의 후 작성 |
| `30_Projects/<P>/Conversations/` | 중요한 대화 발췌 | 사람 요청 시 기록 |
| `30_Projects/<P>/PromptLog.md` | 중요 프롬프트 원문 | append 허용 |
| `40_AgentMemory/` | 전역 AI 메모리 | **직접 수정 금지** — `apply-memory-patch` 경유 (`--target lessons`는 일하는 방식 교훈, 기본은 OpenLoops) |
| `50_Outputs/` | Digest · WeeklyReview · Blog · Career | 읽기 전용 |
| `60_Candidates/` | 지식·결정·메모리패치·블로그·커리어 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/SessionHandoffs/<P>/` | 세션별 Plan/Process | `write_work_plan`/`write_session_process` 전용. promote 대상 아님 |
| `70_Tasks/` | 태스크 (`Active.md` + `Done/`) | task 커맨드 경유 — 직접 편집 금지 |

### 후보 흐름

모든 AI 출력은 반드시 `60_Candidates/`를 거친다. 사람이 `list-candidates` →
`promote-candidate` / `apply-memory-patch`로 검토 후 공식 영역에 반영한다.

`session_handoff`(Plan/Process)만 예외다 — promote 대상이 아니라
`get_project_briefing`이 다음 세션 시작 시 우선 소비하는 운영 메모리이므로
`list-candidates` 기본 출력에서도 제외된다.

### 새 프로젝트 연결

`devtrail init-project <이름> --repo <repo경로>` 실행 — `30_Projects/<이름>/`
문서 스캐폴드(Context.md, Decisions/, Plans/, Design/, Conversations/,
PromptLog.md)를 만들고 repo의 `.claude/vault.json`에 매핑을 저장해 세션
briefing이 바로 붙는다. 생성 직후 Context.md의 배경·목표·제약을 채운다.
Context.md가 바뀌면 briefing 품질이 바뀐다 — 배경·목표·제약 변경 시 즉시 갱신.

## 머신 설정 진단

여러 머신(데스크톱·노트북·rpi4·macmini)에서 같은 레포로 작업한다. 훅·vault 매핑
파일은 git에 없으므로 새 머신에서는 조용히 기록이 0건이 될 수 있다.

```bash
devtrail doctor          # 설치·훅·vault 매핑 진단
devtrail doctor --fix    # 자동 수리 가능한 항목 복구
```

세션 기록에는 host(머신 이름)와 agent(어떤 코딩 에이전트인지)가 함께 남는다
(`app/services/identity.py`). 값을 확신할 수 없으면 빈 문자열이며, 추측해서
채우지 않는다.
