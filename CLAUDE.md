# CLAUDE.md

**개발 규칙의 정본은 `AGENTS.md`다 — 작업 시작 전 먼저 읽는다.**
아키텍처 지도, 코드 배치·스타일·테스트, 브랜치·커밋·PR 규칙은 전부 그쪽에 있다.
이 파일은 Claude Code 전용 사항(MCP 세션 생명주기, Vault 권한 상세)만 담는다.

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
- 구현 전에는 `write_work_plan`으로 Plan을 남긴다 (PreToolUse plan-check 훅이
  강제한다). 기능 단위(며칠 이상) 계획은 `30_Projects/<P>/Plans/` 별도 md.

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

## Vault 구조 (작업 전 참조)

Obsidian Vault는 모든 Agent가 공유하는 메모리 버스다. 작업 시작 전:
- `{VAULT}/30_Projects/<Project>/Context.md` — 배경·목표·제약 (briefing이 자동 주입)
- `{VAULT}/40_AgentMemory/00_Profile.md` ~ `05_OpenLoops.md` — 전역 AI 메모리·미해결 이슈

### 폴더별 역할과 AI 권한

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
| `60_Candidates/SessionHandoffs/<P>/` | 세션별 Plan/Process | `write_work_plan`/`write_session_process`만 기록. promote 대상 아님 — 다음 세션 briefing이 소비 |
| `70_Tasks/` | 태스크 (`Active.md` + `Done/`) | task 커맨드 경유 — 직접 편집 금지 |

### 후보 흐름

모든 AI 출력은 반드시 `60_Candidates/`를 거친다. 사람이 `list-candidates` →
`promote-candidate` / `apply-memory-patch`로 검토 후 공식 영역에 반영한다.
`session_handoff`(Plan/Process)만 예외 — promote 대상이 아니라
`get_project_briefing`이 다음 세션 시작 시 소비하는 운영 메모리다.

## 프로젝트 산출물

- **새 프로젝트 시작 시** `devtrail init-project <이름> --repo <repo경로>` 실행 —
  문서 스캐폴드 생성 + `.claude/vault.json` 매핑. 직후 Context.md의
  배경·목표·제약을 채운다.
- **사용자 결정이 필요한 부분은 진행하지 말고 질문한다.** 결정 결과는
  `write_session_process`의 project_decisions 또는 decision 후보로 남긴다.
- **오류·수정 내역**은 Process(What Changed / Agent Execution Notes)에 기록 —
  별도 WorkLog를 만들지 않는다.
- **중요한 프롬프트 원문**은 `30_Projects/<P>/PromptLog.md`에 append
  (날짜 · 용도 · 원문 · 결과 링크).
- Context.md가 바뀌면 briefing 품질이 바뀐다 — 배경·목표·제약 변경 시 즉시 갱신.
