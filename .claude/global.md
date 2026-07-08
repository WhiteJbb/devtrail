# Global Claude Code Rules
# 새 컴퓨터 설정 시 이 파일 내용을 ~/.claude/CLAUDE.md에 복사한다.

## Session Lifecycle (MCP 우선, capture-session은 fallback)

MCP(`devtrail mcp-serve`)가 연결돼 있으면 세션 종료/컴팩팅 전 기록은
`write_session_process`가 1차 경로다 — SessionHandoffs candidate와
`10_Worklog/Sessions/` 세션 기록을 한 번에 생성하므로 별도로 `capture-session`을
실행할 필요가 없다. 세션 시작 시에는 `get_project_briefing`을 먼저 호출한다.

기록 작성 규칙:
- 여러 항목이 있는 필드(goal, what_changed 등)는 한 문단으로 잇지 말고 markdown
  불릿/번호 리스트로 작성한다 — 기록은 사람이 다시 읽는 문서다.
- Process 기록 후 작업이 더 이어졌다면(커밋 발생) 세션을 끝내기 전에
  `write_session_process`를 **다시 호출**한다. 같은 세션 기록이 갱신되므로
  중복 파일 걱정 없이 최신 상태를 반영하면 된다.
- `agent_execution_notes`의 next_checks/better_approach는 Lessons로 증류되는
  필드다 — 이번 세션 한정 사실이 아니라 다음 세션에도 통하는 교훈으로 쓴다.

`devtrail capture-session --from-agent`는 MCP가 연결되지 않았을 때의 fallback으로
유지한다. 아래 capture-session rule은 이 fallback 경로에 적용된다.

## capture-session rule (fallback: MCP 미연결 시)

`devtrail capture-session --from-agent` 명령을 실행할 때:

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 아래 항목을 포함하는 세션 요약 Markdown을 **충분히 자세하게** 작성한다.

### 작성 기준

**오늘 작업한 내용**
- 무엇을 왜 했는지 서술한다. "X를 구현했다"가 아니라 "X가 없어서 Y 문제가 생겼고, Z 방식으로 해결했다" 수준으로.
- 작업 흐름(어떤 순서로 진행됐는지)도 포함한다.

**변경/추가/삭제된 파일 또는 모듈**
- 파일 경로와 함께 변경 이유를 한 줄씩 기록한다.
- 예: `app/config.py` — Notion/workspace dead 필드 제거 (NotionSource가 존재하지 않아 참조 없음)

**해결한 문제나 버그**
- 증상, 원인, 해결 방법을 모두 기록한다. "버그 수정"이 아니라 "어떤 상황에서 왜 발생했고 어떻게 고쳤는지".

**설계 결정과 그 이유**
- 여러 선택지 중 왜 이 방향을 택했는지 근거를 남긴다.
- 나중에 다시 봤을 때 "왜 이렇게 했지?"가 나오지 않을 수준으로.

**남은 문제 및 다음 할 일**
- 미완성 항목, 알려진 이슈, 다음 세션에서 이어갈 것.

**블로그/포트폴리오 소재**
- 이번 작업 중 기술적으로 흥미롭거나 공유 가치가 있는 것. 제목 수준으로라도 남긴다.

**Learning Recovery**
- AI가 주도적으로 처리한 부분, 아직 완전히 이해하지 못한 개념, 다음에 직접 설명해봐야 할
  질문(2~3개 이하)을 남긴다. 실제로 하지 않은 일이나 이해도를 과장하지 않는다.

3. 요약을 임시 파일로 저장한 뒤 `--summary-file` 옵션으로 전달한다.
4. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 권장 패턴
devtrail capture-session --project <프로젝트명> --from-repo --from-agent --summary-file ./session-summary.md
```

## Vault 구조 (작업 전 참조)

Obsidian Vault는 모든 Agent가 공유하는 메모리 버스다. 작업 시작 전 아래 파일을 먼저 확인한다:
- `{VAULT}/30_Projects/<Project>/Context.md` — 프로젝트 배경·목표·제약 (가장 먼저 읽을 것, briefing이 자동 주입)
- `{VAULT}/40_AgentMemory/00_Profile.md` ~ `05_OpenLoops.md` — 전역 AI 메모리·미해결 이슈

### 폴더별 역할과 AI 권한

| 폴더 | 역할 | AI 권한 |
|------|------|---------|
| `00_Inbox/URLs/` | URL 캡처 노트 | 읽기 전용 |
| `00_Inbox/Memos/` | 텍스트·음성·이미지 캡처 노트 | 읽기 전용 |
| `00_Inbox/Raw/` | 첨부 바이너리 파일 | 읽기 전용 |
| `10_Worklog/Sessions/` | capture-session / write_session_process 출력 (AI 세션 요약) | 읽기 전용 |
| `10_Worklog/Daily/` | daily-log 파일 (사람이 직접 채우는 일지) | 읽기 전용 |
| `10_Worklog/GitSummaries/` | 커밋별 git 요약 | 읽기 전용 |
| `20_Knowledge/` | 승격된 공식 지식 노트 (프로젝트별 하위 폴더) | **직접 수정 금지** — `promote-candidate` 경유 |
| `30_Projects/<P>/Context.md` | 프로젝트 배경·목표·제약 (briefing이 주입) | **직접 수정 금지** — 사람이 관리 |
| `30_Projects/<P>/Decisions/` | 주요 의사결정 이력 (= DecisionLog) | **직접 수정 금지** — `promote-candidate` 경유 |
| `30_Projects/<P>/Plans/` | 기능 단위 구현 계획 (세션 Plan은 SessionHandoffs) | 사람과 협의 후 작성 |
| `30_Projects/<P>/Design/` | IA · UserScenarios · Personas 독립 문서 | 사람과 협의 후 작성 |
| `30_Projects/<P>/Conversations/` | 중요한 대화 발췌 기록 | 사람 요청 시 기록 |
| `30_Projects/<P>/PromptLog.md` | 중요 프롬프트 원문 기록 | append 허용 |
| `40_AgentMemory/` | 전역 AI 메모리 (루트 `00_Profile.md`~`06_Lessons.md`) | **직접 수정 금지** — `apply-memory-patch` 경유 (`--target lessons`는 일하는 방식 교훈, 기본은 OpenLoops) |
| `50_Outputs/Digest/` | daily digest (nightly 자동 생성) | 읽기 전용 |
| `50_Outputs/WeeklyReview/` | weekly 회고 (weekly 자동 생성) | 읽기 전용 |
| `50_Outputs/Blog/` | 블로그 초안·발행본 | 읽기 전용 |
| `50_Outputs/Career/` | 승격된 이력서·포트폴리오 불릿 (career_bullet promote 목적지) | 읽기 전용 |
| `60_Candidates/Knowledge/` | 지식 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/Decisions/` | 결정 기록 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/MemoryPatches/` | OpenLoops 패치 후보 | AI가 생성, `apply-memory-patch`로 반영 |
| `60_Candidates/BlogIdeas/` | 블로그 아이디어 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/CareerBullets/` | 이력서/포트폴리오 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/SessionHandoffs/<Project>/` | 세션별 Plan/Process (session_handoff) | `write_work_plan`/`write_session_process`만 기록. promote 대상 아님 — 다음 세션 briefing이 소비 |

### 후보 흐름
모든 AI 출력(지식 정리, 결정, 블로그 아이디어, 메모리 패치)은 반드시 `60_Candidates/`를 거친다.
사람이 `list-candidates` → `promote-candidate` / `apply-memory-patch`로 검토 후 공식 영역에 반영한다.
`session_handoff`(Plan/Process)은 예외다 — promote 대상이 아니라 `get_project_briefing`이
다음 세션 시작 시 우선 소비하는 운영 메모리이므로 `list-candidates` 기본 출력에서도 제외된다.

## 프로젝트 산출물 규칙

- **새 프로젝트 시작 시** `devtrail init-project <이름> --repo <repo경로>`를 실행한다 —
  `30_Projects/<이름>/` 문서 스캐폴드(Context.md, Decisions/, Plans/, Design/,
  Conversations/, PromptLog.md)를 만들고 repo의 `.claude/vault.json`에 매핑을 저장해
  세션 briefing이 바로 붙는다. 생성 직후 Context.md의 배경·목표·제약을 채운다.
- **구현 전에 반드시 Plan을 남긴다** — 세션 단위는 `write_work_plan`(MCP) 또는
  SessionHandoffs, 기능 단위(며칠 이상 걸리는 작업)는 `30_Projects/<P>/Plans/`에 별도 md.
- **사용자의 결정이 필요한 부분은 진행하지 말고 질문한다.** 결정 결과는
  `write_session_process`의 project_decisions 또는 decision 후보로 남겨
  `30_Projects/<P>/Decisions/`(DecisionLog)에 쌓이게 한다.
- **오류·수정 내역**은 `write_session_process`의 Process(What Changed / Agent Execution
  Notes)에 기록한다 — 별도 WorkLog를 만들지 않는다.
- **중요한 프롬프트 원문**은 `30_Projects/<P>/PromptLog.md`에 append한다
  (날짜 · 용도 · 원문 · 결과 링크).
- **IA · UserScenarios · Personas**는 `30_Projects/<P>/Design/` 독립 문서로 관리하고,
  기능 설계 시 어느 시나리오/페르소나를 위한 것인지 근거를 남긴다.
- **프로젝트 배경·중요 대화**는 `Context.md`와 `Conversations/`에 기록한다.
  Context.md가 바뀌면 briefing 품질이 바뀌므로 배경·목표·제약 변경 시 즉시 갱신한다.

## 브랜치 & PR 규칙

- 기능 추가나 구조에 영향을 주는 큰 변경은 반드시 `feat/` 또는 `refactor/` 브랜치에서 작업한다.
- 문서(md 파일)만 수정할 때는 main에서 직접 커밋해도 된다.
- GitHub 작업(PR 생성/머지, 이슈 등)은 `gh` CLI를 사용한다.
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를 넣지 않는다.
- squash merge 기본 사용.
