# 서비스 개선 계획 — 쓰기 전용 Vault에서 공용 프로젝트 메모리 버스로

작성일: 2026-07-04
개정: 2026-07-05 — 계획 검토(improvement-plan-check) 반영. P0 재정의, MCP tool 정본 목록 확정, 세션 기록 소유권·파일 구조 결정, 훅 계층 모델·보존 정책(P4)·Open Questions 추가. 같은 날 실사용 검토를 반영해 session_id 서버 주입, 훅 차단 조건, 브리핑 크기 상한, 전환기 이중 실행 방지, 콜드 스타트 동작을 추가.

관련 문서 (docs/old/로 이동됨):
- [vault-consumption-plan.md](./old/vault-consumption-plan.md) — P2 상세 스펙의 원본. 살아있는 내용은 본 문서 P2에 흡수됨
- [fable_check.md](./old/fable_check.md)
- [implementation-status.md](./old/implementation-status.md)

---

## 0. 결론

Devtrail의 다음 개선 방향은 새 기능을 넓게 늘리는 것이 아니라, 이미 쌓이고 있는 Vault 데이터를 실제 개발 세션에서 AI가 읽고, 검색하고, 기록하고, 다시 활용하게 만드는 것이다.

현재 시스템은 Capture, Distill, Curate, Generate, Deliver 파이프라인이 대부분 구현되어 있다. 부족한 부분은 두 가지다.

1. **Consumption**: Claude Code/Desktop, Telegram, goal-agent 같은 실행 주체가 Vault를 직접 읽고 활용하는 경로
2. **Learning Recovery**: AI가 대신 처리한 구현 중 개발자가 회수해야 할 개념과 질문을 남기고 다시 마주치게 하는 경로

여기에 더해 실제 사용 목표는 단순한 Vault 검색이 아니라 **Agent Session Lifecycle**을 만드는 것이다. 코딩 에이전트가 세션 시작 시 프로젝트 컨텍스트를 자동으로 읽고, 작업 중 의사결정과 고민을 남기며, 컴팩팅 전이나 세션 종료 시 이번 작업의 handoff를 Vault에 기록해 다음 에이전트와 다음 환경이 이어받게 해야 한다.

Claude Code 같은 도구에도 로컬 메모리 기능은 있지만, 그 메모리는 도구와 환경에 묶인다. Devtrail의 역할은 특정 코딩 도구 안의 임시 기억이 아니라, 여러 에이전트와 여러 개발 환경이 공유할 수 있는 **Vault 중심의 장기 프로젝트 메모리**를 운영하는 것이다.

따라서 서비스 개선의 핵심 포지셔닝은 다음과 같다.

> Devtrail은 또 하나의 자율 에이전트 런타임이 아니다. Claude Code, Codex, Cursor, OpenClaw, Hermes Agent, Telegram bot, custom agents가 함께 쓰는 Obsidian-native 공용 프로젝트 메모리 버스다.

여러 코딩 에이전트가 같은 프로젝트 컨텍스트를 읽고, 작업 전 Plan과 종료 전 Process를 남기며, 프로젝트 의사결정과 에이전트 실행 회고를 분리해 기록하고, 검토된 지식만 장기 메모리로 승격하게 한다.

영문 포지셔닝:

```text
Devtrail is not another autonomous agent runtime.
It is an Obsidian-native shared project memory bus for coding agents.

It lets Claude Code, Codex, Cursor, OpenClaw, Hermes Agent, and custom agents
read the same project context, write structured work plans and session processes,
separate project decisions from agent execution notes,
and promote reviewed knowledge into durable project memory.
```

---

## 1. 현황 진단

### 이미 강한 영역

다음 영역은 이미 구현되어 있거나 운영 가능한 수준이다.

- 원본 기록: `capture`, `capture-commit`, `capture-session`, `daily-log`, Telegram 미디어 캡처
- 정제 후보 생성: `distill-today`, `suggest-knowledge`, `suggest-blog-topics`, `suggest-memory-patch`, `build-context`
- 후보 관리: `list-candidates`, `preview-candidate`, `promote-candidate`, `apply-memory-patch`
- 결과물 생성: `write-blog`, `worklog`, `todo`, `resume`, `portfolio`, `interview-questions`
- 자동화와 전송: `nightly-distill`, `push-digest`, `serve-bot`, post-commit hook

즉 서비스의 병목은 "기록이 부족함"이 아니라 "기록된 메모리가 개발 세션에서 자동으로 소비되지 않음"이다.

### 부족한 영역

| 영역 | 현재 상태 | 개선 방향 |
|---|---|---|
| 프로젝트별 세션 시작 | `capture-session`으로 지난 세션 저장은 가능하지만, 다음 세션에서 AI가 프로젝트 맥락을 자동으로 읽는 경로가 약함 | `get_project_briefing(project_or_repo)`로 프로젝트 컨텍스트, 최근 handoff, 결정, open loops를 묶어 제공 |
| 세션 중 기록 | 사람이 CLI를 치는 기록은 가능하지만, AI가 대화 중 결정/지식을 후보로 남기는 경로가 없음 | `record_note`를 `60_Candidates/` 한정 쓰기 도구로 제공 |
| 세션 종료/컴팩팅 전 인계 | 세션 끝에 무엇을 Vault에 업데이트해야 하는지 강제되는 흐름이 약함 | `write_session_process`로 변경 파일, 결정 이유, 남은 일, 다음 시작점을 후보로 저장 |
| 프로젝트 docs 전역 관리 | 각 repo의 `docs/`와 Vault의 `30_Projects/` 역할 구분이 명확하지 않음 | repo docs는 코드와 함께 버전 관리되는 공식 문서, Vault는 에이전트들이 공유하는 장기 메모리로 분리 |
| 에이전트 개선 메모리 | 반복 실수, 좋은 작업 패턴, 프로젝트별 주의사항을 구조적으로 쌓는 경로가 없음 | `record_agent_improvement` 또는 MemoryPatch 후보로 개선점 기록 |
| 학습 회수 | `suggest-knowledge`는 있지만 "AI가 대신 처리해서 내가 놓친 부분"을 추적하지 않음 | Process 스키마(§3d)에 Learning Recovery 섹션 포함, fallback인 `capture-session` 스키마에도 유지 |
| 복습 소비 | 복습 질문을 만들더라도 다시 보게 만드는 채널이 없음 | `nightly-distill`과 `push-digest`에 하루 1개 복습 질문을 합류 |
| 제품 서사 | 개인 지식관리/자동화 도구로 보이면 범위가 넓고 흔함 | "shared project memory bus for coding agents"로 정리 |

---

## 2. 개선 원칙

1. CLI, Telegram, 자연어 `ask`는 계속 얇은 입구로 둔다.
2. 공통 비즈니스 로직은 `app/vault_tools.py` 같은 서비스 레이어에 둔다.
3. 공식 영역인 `20_Knowledge/`, `30_Projects/*/Context.md`, `40_AgentMemory/`는 AI가 직접 덮어쓰지 않는다.
4. AI 쓰기는 허용된 MCP write tool을 통해서만 `60_Candidates/` 하위 지정 경로에 기록하고, 사람이 나중에 promote/apply한다.
5. `60_Candidates/`는 검색 범위에 포함하되 `status=candidate`로 라벨링한다.
6. `00_Inbox/`, `10_Worklog/`는 기본 read_scope 밖에 둔다.
7. 새 커맨드를 많이 추가하지 않는다. 먼저 기존 세션 요약, digest, briefing 흐름에 녹인다.
8. 임베딩 검색, 원격 MCP, 범용 일정관리/비서화는 실제 병목이 확인될 때까지 보류한다.
9. 세션 시작과 종료는 "하면 좋은 일"이 아니라 에이전트 작업 프로토콜로 다룬다.
10. 도구별 로컬 메모리에 의존하지 않고 Vault를 프로젝트 기억의 source of truth로 둔다.

### CLI와 MCP 역할 분리

기존 CLI 명령을 그대로 MCP에 1:1로 감싸지 않는다. 사용자 운영 판단이 필요한 명령은 CLI에 남기고, 에이전트가 세션 중 자동 호출해야 하는 기능만 작고 안전한 MCP tool로 노출한다.

기준:

```text
사람이 쓰는 것 = CLI
에이전트가 세션 중 자동으로 쓰는 것 = MCP tool
둘 다 쓰는 핵심 로직 = app/vault_tools.py 같은 service/tool 레이어
```

MCP tool은 다음 조건을 만족해야 한다.

- 세션 시작, 작업 중 조회/기록, 세션 종료 handoff 중 하나에 직접 쓰인다.
- read/write scope가 좁고 명확하다.
- 결과가 구조화되어 에이전트가 다음 행동에 바로 사용할 수 있다.
- destructive action, publish, promote, schedule 등록처럼 사람 승인이 필요한 작업을 수행하지 않는다.
- write tool은 대상 candidate kind와 저장 subdir가 고정되어 있어야 하며, 임의 경로를 받지 않는다.

역할 분리:

| 구분 | 유지/노출 대상 | 이유 |
|---|---|---|
| MCP tool | `get_project_briefing`, `search_vault`, `read_note`, `record_note`, `write_work_plan`, `write_session_process`, `record_agent_improvement` | 에이전트가 세션 중 자동으로 호출해야 하는 읽기/후보 기록/인계 도구 |
| CLI | `init-vault`, `index-vault`, `install-hooks`, `promote-candidate`, `apply-memory-patch`, `publish-ready`, `export-tistory`, `print-schedule`, `serve-bot`, `nightly-distill` | 초기화, 운영, 승격, 배포, 스케줄링처럼 사람 판단이나 명시적 실행이 필요한 도구 |
| 공통 service/tool 레이어 | Vault 검색, note 읽기, candidate 기록, briefing 생성, handoff 생성 | CLI와 MCP가 같은 비즈니스 로직을 공유해 중복과 정책 불일치를 막음 |

MCP tool 정본 목록은 P1의 표 하나로 관리하고, 이 표와 P3은 그 목록을 참조한다. open loops와 suggested next actions는 `get_project_briefing` 출력에 포함되므로 별도 tool로 노출하지 않으며, `get_briefing`과 `build_context`는 CLI·Telegram이 쓰는 서비스 레이어 함수로만 유지한다.

---

## 3. Agent Session Lifecycle

이 개선 계획의 중심 단위는 개별 커맨드가 아니라 코딩 세션의 생명주기다. 성공 기준은 에이전트가 세션을 시작하고 끝낼 때 Vault를 자연스럽게 읽고 쓰는지다.

### 3a. Session Open / Context Intake

세션 시작 시 에이전트는 현재 작업 repo와 project name을 식별하고, Vault에서 프로젝트별 브리핑을 먼저 읽는다.

필수 동작:

- project 매핑은 명시적 설정을 우선한다. repo의 `.claude/` 설정 파일(기존 `github.json` 로드 패턴과 동일)에 project 매핑을 두고, 설정이 없을 때만 repo root, git remote, 디렉터리 이름으로 추론한다.
- 매칭에 실패하거나 확신이 낮으면 다른 프로젝트의 컨텍스트를 주입하지 않고 후보 프로젝트 목록을 반환한다. 잘못 매칭된 컨텍스트 주입은 컨텍스트 없음보다 나쁘다.
- 사용자가 후보 중에서 프로젝트를 확정하면 그 매핑을 repo `.claude/` 설정에 저장하도록 제안해, 다음 세션에서 같은 질문을 반복하지 않는다.
- `30_Projects/<Project>/Context.md` 또는 관련 프로젝트 후보를 찾는다.
- `40_AgentMemory/`의 현재 포커스와 open loops를 함께 읽는다.
- 최근 `60_Candidates/`의 project 관련 decision, memory patch, session handoff를 candidate로 포함한다.
- `60_Candidates/SessionHandoffs/<Project>/`의 최신 Plan/Process N개(기본 2~3)는 검색 점수와 무관하게 반드시 포함한다.
- 결과를 "오늘 작업에 바로 필요한 맥락" 중심으로 요약한다. 브리핑은 LLM 없이 기계적으로 조립되므로(P2) "요약"은 발췌 규칙으로 구현한다: handoff는 전문이 아니라 `Next Session`·`What Changed` 섹션만 발췌하고, 섹션별 출력 상한을 둔다. 무거운 브리핑은 호출 회피로 이어져 루프 전체를 죽인다.
- 프로젝트가 Vault에 아직 없는 콜드 스타트에서는 빈 브리핑 대신 "미등록 프로젝트" 안내와 함께 전역 컨텍스트(`40_AgentMemory/`)만 반환한다. 해당 프로젝트의 `SessionHandoffs/<Project>/` 폴더는 첫 `write_work_plan` 호출이 생성한다.

권장 tool:

```text
get_project_briefing(project_or_repo)
```

출력에 포함할 항목:

- Current Focus
- Project Context
- Recent Decisions
- Open Loops
- Recent Session Handoff
- Latest Plan/Process
- Suggested Next Actions
- Relevant Docs

세션 시작 산출물은 만들지 않는다. 이 시점의 목표는 계획 작성이 아니라 컨텍스트 섭취다. 아직 사용자의 이번 요청과 실제 수정 범위가 확정되지 않았으므로, Plan을 쓰지 않고 `get_project_briefing` 결과를 바탕으로 현재 프로젝트 상태만 파악한다.

### 3b. Task Intake / Before Work

사용자의 이번 요청을 확인하고 필요한 파일과 문서를 추가로 읽은 뒤, 실제 코드/문서 수정을 시작하기 전에 Plan을 남긴다.

작업 시작 전 산출물:

```text
Plan
```

모든 코드/문서 작업은 수정 전에 Plan을 남긴다. Plan은 긴 기획서가 아니라 "이번 작업에서 무엇을, 어떤 맥락으로, 어디까지 할 것인가"를 다음 에이전트가 확인할 수 있게 하는 작업 시작 기록이다. 작은 작업은 5줄짜리 mini Plan을 허용한다. 단순 질문 답변, 파일 변경 없는 탐색, 아주 작은 확인 작업은 Plan을 생략할 수 있다.

Plan 기본 구조:

```markdown
# Plan

## Goal
- 이번 세션에서 달성할 것

## Context Read
- 읽은 Vault note / repo docs / 이전 handoff

## Scope
- 수정 예상 파일 또는 모듈
- 건드리지 않을 영역

## Approach
- 실행 순서

## Risks
- 주의할 점
```

권장 tool:

```text
write_work_plan(project, goal, context_read, scope, approach, risks)
```

### 3c. During Work

작업 중에는 모든 것을 기록하지 않고, 다음 세션에서 의미가 있을 정보만 candidate로 남긴다.

기록 대상:

- 되돌리기 어렵거나 이후 구현 방향에 영향을 주는 의사결정
- 고려한 대안과 선택하지 않은 이유
- 프로젝트 docs에 반영해야 할 내용
- 반복 실수, 놓친 전제, 다음부터 먼저 확인할 사항
- 사용자가 중요하다고 명시한 맥락

권장 tool:

```text
record_note(kind, title, body, project="")
record_agent_improvement(project, issue, improvement, evidence="")
```

기록하지 않을 것:

- 단순 진행 상황의 과도한 로그
- 코드 diff만 보면 알 수 있는 사소한 변경
- 확실하지 않은 추측을 확정 사실처럼 쓴 내용
- raw 대화 전체

의사결정과 에이전트 실행 회고는 같은 세션 안에 남길 수 있지만 같은 의미로 취급하지 않는다.

| 구분 | 의미 | 책임 주체 | 승격 후보 |
|---|---|---|---|
| Project Decisions | 프로젝트 방향, 설계 선택, docs에 남길 결정 | 사용자 최종 판단 또는 user-approved agent-assisted 결정 | `60_Candidates/Decisions/` -> `30_Projects/` 또는 repo docs |
| Agent Execution Notes | 에이전트가 막힌 점, 실수, 다음부터 개선할 작업 방식 | 에이전트 자기 회고 | `60_Candidates/MemoryPatches/` -> `40_AgentMemory/` |

원칙:

- 에이전트는 사용자 결정과 자기 실수를 같은 bullet로 섞지 않는다.
- 사용자가 명시적으로 승인하지 않은 판단은 Project Decision이 아니라 candidate 또는 open question으로 남긴다.
- Agent Execution Notes는 프로젝트 공식 결정처럼 promote하지 않는다.

### 3d. Before Compact / Session End

컴팩팅 전 또는 세션 종료 시에는 이번 세션의 Process를 Vault에 남긴다. 이 단계가 없으면 다음 에이전트는 다시 사용자의 설명에 의존하게 되고, Vault는 장기 기억 역할을 하지 못한다.

세션 종료 산출물:

```text
Process
```

모든 의미 있는 코드/문서 작업 세션은 종료 시 Process를 남긴다. Process는 "무엇을 했는가"뿐 아니라 "다음 세션이 이어받기 위해 무엇을 알아야 하는가"를 남기는 handoff 문서다. 작은 작업은 mini Process를 허용하되, 변경 내용과 다음 시작점은 반드시 포함한다.

Process 생략 또는 축약 기준:

- 파일 변경이 없고 단순 질문 답변만 한 경우 Process를 생략할 수 있다.
- 탐색 중 중단되어 다음 행동이 없는 경우 mini Process로 "읽은 것/중단 이유"만 남긴다.
- 오타 수정, 문구 한 줄 수정처럼 다음 세션 인계 가치가 낮은 경우 mini Process를 허용한다.
- 설계 결정, 실패한 접근, 다음 세션 TODO, 에이전트 실수가 있으면 반드시 Process를 남긴다.

Process 기본 구조:

```markdown
# Process

## What Changed
- 실제로 한 작업

## Files Touched
- 변경/추가/삭제된 파일 또는 모듈

## Project Decisions
- 결정:
- 이유:
- 고려한 대안:
- 최종 판단자: user / user-approved agent-assisted / unresolved

## Implementation Trace
- 중요한 구현 흐름
- 해결한 문제나 버그

## Agent Execution Notes
- 막힌 점:
- 에이전트가 한 실수:
- 다음부터 먼저 확인할 점:
- 더 나은 작업 방식:
- evidence:
- scope:
- confidence:
- requires_user_review:

## Docs Update Candidates
- repo docs 후보:
- Vault Project Context 후보:

## Next Session
- 다음에 이어서 볼 것:
- 남은 문제 및 다음 할 일:

## Learning Recovery
- AI가 주도적으로 처리한 부분:
- 아직 완전히 이해하지 못한 개념:
- 다음에 직접 설명해봐야 할 질문:
```

섹션 분리 기준:

- `Project Decisions`는 프로젝트의 의사결정 기록이다. 사용자 결정 또는 사용자 승인 기반 판단만 들어간다.
- `Agent Execution Notes`는 에이전트의 수행 품질 회고다. 실수, 막힌 점, 다음 작업 방식 개선을 적는다.
- `Agent Execution Notes`는 증거와 적용 범위를 함께 적는다. `evidence`, `scope`, `confidence`, `requires_user_review` 필드를 두어 잘못된 자기개선 규칙이 전역 메모리로 승격되는 것을 막는다.
- 둘은 같은 Process 파일 안에 있어도 되지만, 저장/승격 시에는 Decisions와 MemoryPatches로 분리 가능한 구조를 유지한다.

권장 tool:

```text
write_session_process(project, what_changed, files_touched, project_decisions, implementation_trace, agent_execution_notes, docs_update_candidates, next_session, learning_recovery)
```

저장 위치와 소유권 (2026-07-05 결정):

- 에이전트 세션 종료의 단일 작성 지점은 `write_session_process`다. 에이전트는 세션 요약을 한 번만 작성한다.
- 서비스 레이어가 이중 기록한다: ① `60_Candidates/SessionHandoffs/<Project>/`에 Process candidate, ② `10_Worklog/Sessions/`에 세션 기록(기존 capture 파이프라인 로직 재사용). 이로써 nightly-distill/digest 입력과 장기 세션 아카이브가 그대로 유지된다.
- `10_Worklog/` write 금지 원칙은 "에이전트가 임의 경로를 지정할 수 없다"는 뜻이다. worklog 세션 기록은 에이전트가 아니라 서비스 레이어가 capture 계열 로직으로 내부 생성한다.
- `capture-session` CLI는 사람이 수동 실행하는 용도와 MCP 미연결 시 fallback으로 존치한다.
- Plan과 Process는 별도 파일 2개로 남기되, frontmatter의 `session_id`로 짝을 맺는다.
- `session_id`는 에이전트가 아니라 MCP 서버가 관리한다. stdio MCP 서버는 세션당 프로세스 1개로 뜨므로 서버가 시작 시 ID를 생성해 보관하고 모든 write tool 호출에 자동 주입한다. 에이전트에게 ID 전달 책임을 지우면 컴팩팅을 거치며 잊어버리는 것이 가장 확실한 실패 모드다.
- 서버 재시작 등으로 짝이 어긋나면, 짝 없는 Process는 같은 프로젝트의 최근 미짝 Plan에 붙인다.
- 이중 기록되는 `10_Worklog/Sessions/` 세션 기록의 frontmatter에도 `session_id`를 포함해 양쪽에서 짝 추적이 가능하게 한다.
- Plan/Process candidate는 `candidate_type: session_handoff`, `handoff_type: plan | process`, `session_id`, `project`, `source_refs`, `status: candidate`를 frontmatter에 포함한다.
- Process의 `Project Decisions`는 필요하면 `60_Candidates/Decisions/` 후보로 분리 생성한다.
- Process의 `Agent Execution Notes`는 필요하면 `60_Candidates/MemoryPatches/` 후보로 분리 생성한다.
- 공식 `30_Projects/*/Context.md`나 repo docs는 직접 덮어쓰지 않고 patch/promote 후보로 남긴다.

### 3e. Next Session

다음 세션의 첫 동작은 이전 handoff를 소비하는 것이다.

`get_project_briefing`은 일반 검색 결과와 별개로 해당 project의 최신 `SessionHandoffs`를 우선 로드한다. stable 문서가 아니더라도, 직전 세션의 Plan/Process는 다음 에이전트가 이어받기 위해 필요한 운영 메모리이므로 candidate 랭킹 뒤로 밀리지 않아야 한다.

기대 흐름:

```text
세션 시작
  -> get_project_briefing
  -> 사용자 요청 확인 및 필요한 파일/문서 추가 읽기
  -> write_work_plan
  -> 작업 수행
  -> write_session_process
  -> 60_Candidates에 Plan/Process handoff 기록
  -> 다음 세션 시작
  -> get_project_briefing
  -> 최근 Plan/Process, decisions, open loops를 읽고 작업 재개
```

이 흐름이 돌아가면 Claude Code, Codex, Cursor, Telegram 봇처럼 서로 다른 입구를 쓰더라도 Vault가 공통 프로젝트 기억으로 작동한다.

### 3f. Repo Docs와 Vault의 역할 분리

repo의 `docs/`와 Vault의 `30_Projects/`는 경쟁하지 않고 역할을 나눈다.

| 위치 | 역할 |
|---|---|
| repo `docs/` | 코드와 함께 버전 관리되는 공식 프로젝트 문서. 외부 공유와 PR 리뷰에 적합 |
| Vault `30_Projects/` | 여러 에이전트와 환경이 공유하는 장기 프로젝트 메모리. 최근 맥락, 결정 히스토리, open loops, handoff 중심 |
| Vault `60_Candidates/SessionHandoffs/` | 세션별 Plan/Process 후보. 다음 세션 브리핑에서 우선 소비 |
| Vault `60_Candidates/Decisions/` | 사용자 결정 또는 사용자 승인 기반 프로젝트 결정 후보 |
| Vault `60_Candidates/MemoryPatches/` | 에이전트 실수, 개선점, 반복 주의사항 후보 |
| Vault `40_AgentMemory/` | 전역 작업 습관, 반복 실수, 선호하는 개발 방식, 에이전트 개선점 |

원칙:

- repo docs에 바로 넣을 내용도 먼저 candidate로 기록할 수 있다.
- Vault의 candidate는 다음 세션에서 찾을 수 있어야 하지만, 확정 문서처럼 인용하지 않는다.
- 사람이 검토한 뒤 repo docs 또는 `30_Projects/*/Context.md`에 반영한다.
- Plan/Process는 세션 산출물로 함께 보관하되, Project Decisions와 Agent Execution Notes는 승격 경로를 분리한다.
- `SessionHandoffs`는 promote 대상이라기보다 다음 세션 briefing의 운영 메모리다. 오래된 handoff는 P4의 보존 정책으로 관리하고, 공식 지식으로 남길 내용만 Decisions/MemoryPatches/docs 후보로 분리한다.

---

## 4. 우선순위

### P0. 문서 정합성 확인과 링크 정리

`vault-consumption-plan.md`의 `60_Candidates/` read_scope 충돌은 07-02 개정으로 이미 해소되었음을 확인했다(candidate 라벨로 포함, `00_Inbox/`·`10_Worklog/`만 제외로 일관). 따라서 P0는 "충돌 수정"이 아니라 다음으로 재정의한다.

- 본 문서 상단의 관련 문서 링크를 `docs/old/` 경로로 정리한다. (2026-07-05 완료)
- `vault-consumption-plan.md`는 `docs/old/`에 유지한다. 구현에 필요한 상세 스펙(read_scope 정의, 경로 탈출 방지, 테스트 항목)은 본 문서 P2에 흡수되어 있으므로 구현자는 본 문서만 봐도 된다. 두 문서가 어긋나면 본 문서가 우선한다.

완료 기준:

- 본 문서의 링크가 모두 유효하다.
- 구현자가 본 문서만 읽고 read/write scope를 오해할 여지가 없다.

### P1. Agent Session Lifecycle tool 설계

`app/vault_tools.py`를 만들기 전에 tool 목록을 세션 생명주기 기준으로 확정한다. 여기서 말하는 tool은 에이전트가 MCP로 직접 호출할 표면이며, 기존 CLI 명령 전체를 옮기는 것이 아니다.

핵심 tool:

| 함수 | 역할 |
|---|---|
| `get_project_briefing(project_or_repo)` | 세션 시작 시 프로젝트 컨텍스트, 최근 handoff, decision, open loops, suggested next actions 반환 |
| `write_work_plan(...)` | 사용자 요청과 추가 컨텍스트를 확인한 뒤, 작업 시작 전 Plan 산출물을 `60_Candidates/SessionHandoffs/`에 저장 |
| `record_note(kind, title, body, project="")` | 작업 중 결정/지식/아이디어를 `60_Candidates/`에 후보로 기록 |
| `record_agent_improvement(project, issue, improvement, evidence="")` | 반복 실수, 개선할 작업 방식, 프로젝트별 주의사항을 MemoryPatch 후보로 기록 |
| `write_session_process(...)` | 컴팩팅 전/세션 종료 시 Process 산출물을 `60_Candidates/SessionHandoffs/`에 저장 |
| `search_vault(query, limit)` | 세션 중 온디맨드 조회 |
| `read_note(rel_path)` | 검색 결과 또는 브리핑의 상세 노트 읽기 |

위 표의 7개가 MCP tool 정본 목록이다. §2와 P3은 이 목록을 참조하며, 목록 변경은 이 표에서만 한다.

확정된 설계 결정 (2026-07-05):

1. 세션 종료 기록 소유권 — `write_session_process`를 에이전트용 신규 표면으로 만들고, 서비스 레이어가 SessionHandoffs candidate와 `10_Worklog/Sessions/` 세션 기록을 이중 생성한다. `capture-session` CLI는 사람용·fallback으로 존치한다. 이유: 에이전트의 이중 작성 부담을 없애면서 기존 distill/digest 파이프라인 입력과 장기 아카이브를 유지한다. (§3d 참조)
2. Plan/Process 파일 구조 — 세션당 별도 파일 2개를 유지하고 `session_id` frontmatter로 짝을 맺는다. 단일 세션 노트 통합은 CandidateWriter에 update 시맨틱이 필요하므로 Open Questions로 보류한다.
3. 프로젝트 매핑 — repo의 `.claude/` 설정에 명시 매핑을 우선하고, 매칭 실패 시 후보 목록을 반환한다. (§3a 참조)

완료 기준:

- tool 설명에 언제 호출해야 하는지가 들어간다.
- 세션 시작 컨텍스트 인테이크, 작업 시작 전 Plan, 세션 종료 Process tool이 분리된다.
- 에이전트 개선 메모리가 일반 지식 후보와 섞이지 않게 kind 또는 경로 규칙을 둔다.
- Project Decisions와 Agent Execution Notes가 같은 구조 필드에 섞이지 않는다.
- 운영성 명령, 승격 명령, 배포 명령은 MCP tool 목록에서 제외된다.
- CLI와 MCP가 같은 `app/vault_tools.py` 로직을 공유한다.
- §2, P1, P3의 도구 목록이 동일하다(정본은 P1 표).

### P2. Vault tool 레이어 구현

`app/vault_tools.py`를 만들어 MCP, Telegram, goal-agent가 공유하는 공통 서비스를 제공한다.

필수 함수:

| 함수 | 역할 |
|---|---|
| `get_project_briefing(project_or_repo)` | 현재 repo/project 기준 브리핑 반환 |
| `search_vault(query, limit)` | read_scope 안의 노트를 검색하고 `status=stable/candidate`를 함께 반환 |
| `read_note(rel_path)` | scope 안의 노트 전문을 읽음. scope 밖, 절대경로, `..` 탈출은 거부 |
| `get_briefing()` | AgentMemory 기반 현재 프로필, 포커스, 프로젝트, Open Loops 요약 반환 |
| `build_context(topic)` | 기존 ContextPackBuilder 재사용 |
| `record_note(kind, title, body, project="")` | 허용된 candidate kind만 `CandidateWriter` 경유로 `60_Candidates/`에 기록 |
| `write_work_plan(...)` | 작업 시작 전 Plan을 `session_handoff` candidate로 기록 |
| `write_session_process(...)` | 세션 종료 Process를 `session_handoff` candidate로 기록하고, 같은 호출에서 `10_Worklog/Sessions/` 세션 기록을 함께 생성 |
| `record_agent_improvement(...)` | 실수/개선점/작업 패턴을 `memory_patch` candidate로 기록 |

Candidate kind 확장:

| kind | 저장 경로 | 생성 tool | 비고 |
|---|---|---|---|
| `session_handoff` | `60_Candidates/SessionHandoffs/<Project>/` | `write_work_plan`, `write_session_process` | `handoff_type: plan | process`로 구분. 다음 briefing에서 우선 소비 |
| `decision` | `60_Candidates/Decisions/` | `record_note`, `write_session_process`의 분리 후보 | 사용자 결정 또는 사용자 승인 기반 결정만 |
| `memory_patch` | `60_Candidates/MemoryPatches/` | `record_agent_improvement`, `write_session_process`의 분리 후보 | `evidence`, `scope`, `confidence`, `requires_user_review` 포함 |

구현 시 `CandidateWriter`의 `_CANDIDATE_DIRS`와 curator kind normalization에 `session_handoff`를 추가한다. `work_plan`과 `session_process`는 별도 kind로 만들지 않고 `session_handoff`의 `handoff_type`으로 구분한다.

`CandidateWriter`는 kind 추가만으로 끝나지 않는다. 검토에서 확인된 필수 변경:

- `_unique_rel_path`는 kind별 평면 폴더만 지원하므로 `SessionHandoffs/<Project>/` 하위 경로 라우팅을 지원하도록 구조를 바꾼다.
- `find_duplicate`의 dedup(14일 내 제목 유사도 0.85)은 시계열 데이터인 `session_handoff`를 조용히 삼킨다("Plan — vault-mcp 작업" 같은 제목이 반복되면 새 handoff가 유실됨). `session_handoff`는 dedup을 비활성화하고, 제목에 날짜와 `session_id`를 포함한다.
- `CandidateSpec`에 `handoff_type`, `session_id`, `evidence`, `confidence`, `requires_user_review` 같은 kind별 추가 frontmatter 필드를 넣을 수 있게 스키마를 확장한다.
- `session_handoff`는 promote 대상이 아니므로 `list-candidates` 기본 출력에서 제외한다(옵션으로 조회 가능).
- 코드 확인 결과 `CandidateWriter.write()`에는 이미 `dedup` 파라미터가 있어 비활성화 자체는 작다. 단 `write_many()`가 dedup 인자를 넘기지 않으므로 함께 손본다.
- 이중 기록을 위해 `CaptureAgent.capture_session()`에 요약 텍스트를 직접 받는 파라미터를 추가한다. 현재는 `summary_file` 경로만 받아 MCP 경유 시 불필요한 임시 파일이 생긴다. worklog 세션 frontmatter에 `session_id` 필드도 추가한다.

read_scope:

| 경로 | status | 설명 |
|---|---|---|
| `20_Knowledge/` | stable | 승격된 지식 |
| `30_Projects/` | stable | 프로젝트 컨텍스트 |
| `40_AgentMemory/` | stable | 프로필, 포커스, 오픈 루프 |
| `60_Candidates/` | candidate | 미검토 후보. 검색 가능하지만 확정처럼 말하지 않음 |

write_scope:

| 경로 | 허용 여부 | 설명 |
|---|---|---|
| `60_Candidates/Knowledge`, `60_Candidates/Decisions`, `60_Candidates/BlogIdeas`, `60_Candidates/CareerBullets` | 제한 허용 | `record_note`가 허용된 kind로만 기록 |
| `60_Candidates/SessionHandoffs/<Project>/` | 제한 허용 | `write_work_plan`, `write_session_process`만 기록. 임의 경로 입력 금지 |
| `60_Candidates/MemoryPatches` | 제한 허용 | `record_agent_improvement` 또는 `write_session_process`의 분리 후보만 기록 |
| `20_Knowledge/`, `30_Projects/`, `40_AgentMemory/` | 금지 | promote/apply-memory-patch 흐름으로만 반영 |
| `00_Inbox/`, `10_Worklog/` | 금지 | raw 기록/세션 로그는 기존 capture 계열이 담당 |

테스트:

- scope 밖 경로 읽기 거부
- `..`와 절대경로를 통한 vault 탈출 거부
- stable 결과가 candidate보다 우선 정렬
- `60_Candidates/` 검색 결과에 `status=candidate` 포함
- `record_note`가 `60_Candidates/`에만 기록
- `get_project_briefing`이 현재 repo와 project 후보를 안전하게 매칭
- `get_project_briefing`이 해당 project의 최신 `SessionHandoffs` Plan/Process N개를 검색 점수와 무관하게 포함
- `session_handoff` kind가 `60_Candidates/SessionHandoffs/<Project>/`에 기록되고 `handoff_type`으로 plan/process를 구분
- 같은 제목의 handoff가 반복돼도 dedup되지 않고 새 파일로 기록됨
- `write_session_process`가 SessionHandoffs candidate와 `10_Worklog/Sessions/` 세션 기록을 함께 생성함
- `list-candidates` 기본 출력에 `session_handoff`가 나타나지 않음
- Plan과 Process가 같은 `session_id`로 짝지어짐
- `session_id`가 write tool 호출 인자 없이 서버에서 자동 주입됨
- 짝 없는 Process가 같은 프로젝트의 최근 미짝 Plan과 연결됨
- 브리핑 출력이 섹션별 상한을 지키고 handoff는 `Next Session`·`What Changed` 발췌로 포함됨
- 프로젝트 매칭 실패 시 컨텍스트를 주입하지 않고 후보 목록을 반환함
- `write_work_plan`과 `write_session_process`가 공식 프로젝트 문서를 직접 덮어쓰지 않음
- `write_session_process`가 Project Decisions와 Agent Execution Notes를 분리된 필드로 저장
- `record_agent_improvement`가 MemoryPatch 후보로 기록됨
- `record_agent_improvement` 결과에 `evidence`, `scope`, `confidence`, `requires_user_review`가 포함됨
- LLM, Telegram, Notion 네트워크 호출 없음

### P3. MCP 연결

`app/mcp_server.py`와 `mcp-serve` CLI를 추가해 Claude Code/Desktop에서 Vault tool을 직접 호출할 수 있게 한다.

노출할 도구는 P1의 정본 목록 7개와 동일하다:

- `get_project_briefing`
- `search_vault`
- `read_note`
- `record_note`
- `record_agent_improvement`
- `write_work_plan`
- `write_session_process`

핵심 검증 시나리오:

1. Claude Code 세션 시작 시 `get_project_briefing`을 호출한다.
2. 사용자의 이번 요청을 확인하고 필요한 파일/문서를 추가로 읽는다.
3. 실제 수정 전에 작업 Plan을 `write_work_plan`으로 남긴다.
4. 개발 중 "이 결정 기록해둬" 요청에 `record_note`로 후보를 생성한다.
5. 실수나 개선점이 생기면 `record_agent_improvement`로 MemoryPatch 후보를 생성한다.
6. 컴팩팅 전 또는 세션 종료 시 `write_session_process`로 다음 세션 인계를 남긴다.
7. 다음 세션의 `get_project_briefing`이 직전 Plan/Process를 최신 handoff로 포함한다.
8. 같은 세션 또는 다음 세션에서 `search_vault`로 방금 기록한 후보가 `status=candidate`로 잡힌다.
9. candidate 결과는 "초안에 따르면"처럼 확정이 아닌 표현으로 사용된다.

라이프사이클 준수 강제:

지침만으로는 에이전트가 `write_work_plan`·`write_session_process` 호출을 빼먹는 것이 가장 흔한 실패 모드가 된다. 도구별 훅 지원 수준에 따라 계층적으로 강제한다.

| 계층 | 대상 | 방식 |
|---|---|---|
| Tier 1 — 훅 강제 | Claude Code(레퍼런스 구현), Codex CLI | SessionStart 훅으로 briefing 자동 주입, PreCompact/Stop 훅으로 Process 미작성 시 리마인드·차단. 차단은 git dirty 상태이거나 세션 중 파일 편집이 있었을 때만 적용하고, 파일 변경 없는 Q&A 세션은 조용히 통과시킨다(§3d 생략 기준과 일치) |
| Tier 2 — 훅 스크립트 자동화 | Cursor, OpenClaw | stop/session 이벤트 훅이 에이전트를 강제하지는 못하지만, 훅 스크립트가 직접 `devtrail` CLI를 호출해 git 상태 기반의 기계적 mini-Process를 생성. 시작 컨텍스트는 rules/bootstrap 파일로 주입 |
| Tier 3 — 지침 전용 | 훅 미지원 도구 | agent instruction 문서의 프로토콜 지침에만 의존 |
| Tier 0 — 공통 안전망 | 모든 에이전트 | `get_project_briefing`이 직전 세션의 Plan-Process 쌍 누락을 감지해 브리핑 상단에 경고로 표시. 경고 피로를 막기 위해 가장 최근 미짝 Plan 1건만 표시하고, 오래된 미짝 Plan은 P4 cleanup이 정리 |

공통 지침(모든 계층에 적용):

- agent instruction 문서에 "세션 시작 시 `get_project_briefing`을 먼저 호출한다", "작업 시작 전 `write_work_plan`, 컴팩팅 전 또는 세션 종료 시 `write_session_process`를 호출한다"를 추가한다.
- MCP가 연결되지 않은 경우에는 브리핑 CLI 출력과 `capture-session` 같은 fallback 경로를 안내한다.
- MCP 가동과 동시에 CLAUDE.md의 capture-session 규칙을 `write_session_process` 우선(capture-session은 fallback)으로 갱신한다. P5까지 미루면 전환기 동안 에이전트가 두 경로를 모두 실행해 worklog에 같은 세션이 2건 쌓인다.
- 훅 레퍼런스 구현은 주 사용 환경인 Windows(PowerShell)에서 동작을 검증한다.

### P4. SessionHandoffs·Worklog 보존 정책

세션마다 Plan/Process 2개 파일이 쌓이고 `60_Candidates/`는 read_scope에 포함되므로, 정리 없이는 한 달 안에 검색 노이즈가 실질적으로 늘어난다. 이전에 합의된 worklog 보존 정책(distilled 마킹 + 30일 후 cleanup, 미구현)을 SessionHandoffs까지 확장해 하나의 cleanup 커맨드로 구현한다.

- 대상: `10_Worklog/`(기존 합의)와 `60_Candidates/SessionHandoffs/`
- SessionHandoffs는 프로젝트별 최신 N개를 항상 남기고, distill에 반영된 오래된 handoff부터 정리한다.
- 짝 없는 오래된 Plan(중단된 세션의 고아 산출물)도 정리 대상에 포함한다.
- cleanup은 사람이 실행하는 CLI로만 만든다(destructive action이므로 MCP 노출 금지).

완료 기준:

- 하나의 cleanup 커맨드가 두 영역을 함께 관리한다.
- cleanup 후에도 `get_project_briefing`의 최신 handoff 소비가 깨지지 않는다.

### P5. Learning Recovery 스키마 추가

Learning Recovery의 소스는 §3d Process 스키마다. P1 결정 1에 따라 `write_session_process`가 세션 요약의 단일 작성 지점이고, 이중 기록되는 `10_Worklog/Sessions/` 세션 기록에도 이 섹션이 포함되어 기존 distill/digest 파이프라인이 그대로 소비한다. MCP 미연결 시 fallback인 `capture-session --from-agent` 요약 스키마에도 같은 섹션을 유지한다.

```markdown
## Learning Recovery

### AI가 주도적으로 처리한 부분
- ...

### 내가 아직 완전히 이해하지 못한 개념
- ...

### 다음에 직접 설명해봐야 할 질문
1. ...
2. ...
3. ...

### 관련 Vault 후보
- ...
```

목표는 복습 자료를 많이 만드는 것이 아니라, 실제 세션에서 놓친 개념을 구조적으로 남기는 것이다.

완료 기준:

- Process 스키마와 `capture-session --from-agent` fallback 작성 규칙 양쪽에 Learning Recovery가 포함된다.
- CLAUDE.md의 capture-session 규칙 갱신은 전환기 이중 실행을 막기 위해 P3에서 MCP 가동과 동시에 처리한다. P5에서는 갱신된 규칙에 Learning Recovery가 포함됐는지 확인한다.
- 실제로 하지 않은 일이나 확실하지 않은 이해도를 과장하지 않는다.
- 복습 질문은 2~3개 이하로 제한한다.
- 질문은 "정의하라"보다 "다음 세션에서 설명해볼 수 있는가" 형식으로 쓴다.

### P6. 복습 질문 소비 루프

Learning Recovery가 쌓이기 시작하면 `nightly-distill` 또는 `push-digest --daily`에 하루 1개의 복습 질문을 포함한다. 질문의 소스는 `10_Worklog/Sessions/`의 세션 기록이다(이중 기록으로 기존 파이프라인 입력이 유지되므로 SessionHandoffs를 별도로 읽지 않는다).

예시:

```text
어제의 학습 회수

프로젝트: Devtrail
미해결 개념: MCP stdio server lifecycle
복습 질문:
1. Claude Code가 MCP stdio 서버를 실행하는 방식은 상시 데몬과 무엇이 다른가?
```

원칙:

- 하루 1개만 노출한다.
- 긴 학습 계획이 아니라 다음 개발 세션에서 마주칠 질문으로 만든다.
- Telegram digest를 우선 사용한다.
- 새 복습 앱이나 대량 커맨드는 만들지 않는다.

### P7. Telegram/ask의 Vault Q&A

MCP와 tool 레이어가 안정화된 뒤 Telegram과 `ask`에 Vault 조회 흐름을 얹는다.

기능:

- `/briefing`: `get_briefing()` 결과 전송
- `ask-vault` intent: 자연어 질문 → `search_vault` → 상위 노트 기반 답변 + 출처 경로

주의:

- LLM 쿼터를 고려해 `light` task로 라우팅한다.
- candidate 결과는 확정처럼 말하지 않는다.
- 답변에는 가능한 한 Vault 경로를 포함한다.

### P8. 포지셔닝/README/포트폴리오 서사 정리

MCP와 Learning Recovery가 실제로 돌기 시작한 뒤 README, 블로그, 포트폴리오 설명을 정리한다.

권장 문구:

```text
Devtrail is an Obsidian-native shared project memory bus for coding agents.

It lets Claude Code, Codex, Cursor, OpenClaw, Hermes Agent, and custom agents read the same project context, write structured work plans and session processes, separate project decisions from agent execution notes, and promote reviewed knowledge into durable project memory.
```

한국어 설명:

```text
Devtrail은 여러 코딩 에이전트가 함께 쓰는 Obsidian-native 공용 프로젝트 메모리 버스입니다.

Claude Code, Codex, Cursor, OpenClaw, Hermes Agent, custom agent가 같은 프로젝트 컨텍스트를 읽고, 작업 전 Plan과 종료 전 Process를 남기며, 프로젝트 의사결정과 에이전트 실행 회고를 분리해 장기 프로젝트 메모리로 승격할 수 있게 돕습니다.
```

---

## 5. 당장 만들지 않을 것

| 항목 | 보류 이유 |
|---|---|
| `quiz-me`, `unknowns-list`, `review-later` 등 다수의 새 학습 커맨드 | CLI 표면적만 늘고 실제 소비가 약할 가능성이 큼 |
| 에이전트 전용 기능을 CLI 명령으로만 추가 | 세션 중 자동 호출되지 않으면 다시 수동 운영 도구가 됨. 에이전트용 표면은 MCP tool이 우선 |
| 기존 CLI 명령 전체를 MCP에 1:1 노출 | promote, publish, schedule 같은 작업은 사람 판단이 필요하고 tool 표면이 불필요하게 커짐 |
| 범용 비서/캘린더 앱화 | Devtrail의 차별점인 개발 세션 운영과 멀어짐 |
| 초기 임베딩 검색 | keyword recall 병목이 실사용에서 확인된 뒤 Phase 4로 처리 |
| 원격 MCP | 로컬 Vault를 인터넷에 노출해야 하므로 인증/호스팅 부담이 큼 |
| 공식 영역 직접 쓰기 도구 | 설계 원칙 위반. candidate/patch 흐름을 유지해야 함 |
| `10_Worklog/` 전체 read_scope 포함 | raw 성격이 강하고 노이즈가 큼. 필요하면 `10_Worklog/Sessions/`만 조건부 검토 |

---

## 6. 성공 기준

서비스 개선이 성공했는지는 커맨드 수가 아니라 루프가 실제로 도는지로 판단한다.

### 세션 연속성

- 새 개발 세션 시작 시 AI가 `get_project_briefing`으로 현재 프로젝트 맥락을 확인한다.
- 사용자가 설명하지 않아도 최근 포커스, 오픈 루프, 프로젝트 상태를 반영한다.
- "지난번 결정 뭐였지?" 질문에 `search_vault`/`read_note`로 답한다.

### 세션 중 기록

- 개발 중 생긴 결정이나 지식이 `record_note`로 `60_Candidates/`에 남는다.
- 방금 기록한 후보가 같은 세션에서 검색된다.
- candidate와 stable이 답변에서 구분된다.

### 세션 인계

- 사용자 요청과 추가 컨텍스트를 확인한 뒤, 실제 수정 전에 `write_work_plan`이 호출된다.
- 컴팩팅 전 또는 세션 종료 시 `write_session_process`가 호출된다.
- 변경 파일, Project Decisions, Agent Execution Notes, 남은 일, 다음 시작점이 candidate로 남는다.
- 다음 세션의 `get_project_briefing`이 이전 Plan/Process를 포함한다.
- 준수 여부는 Plan-Process 쌍 완결률(Plan이 있는 세션 중 Process가 존재하는 비율)로 측정하고, 누락은 다음 브리핑의 경고 표시로 드러난다.

### 에이전트 개선

- 반복 실수나 작업 방식 개선점이 MemoryPatch 후보로 남는다.
- 프로젝트별 주의사항이 다음 브리핑에 반영된다.
- 특정 도구의 로컬 메모리가 초기화되어도 Vault에서 개선점이 복구된다.

### 학습 회수

- `capture-session` 결과물에 AI 주도 처리 영역과 미해결 개념이 남는다.
- 다음 날 digest에서 복습 질문 1개가 노출된다.
- 질문이 실제 다음 개발 세션의 설명/복습으로 이어진다.

### 서사

- README/포트폴리오에서 "개인 지식관리 도구"나 "자율 에이전트 런타임"이 아니라 "shared project memory bus for coding agents"로 설명된다.
- 기능 목록보다 문제 해결 루프가 먼저 보인다.

---

## 7. 실행 순서 요약

1. 문서 정합성 확인과 링크 정리를 마친다. (P0 — 2026-07-05 완료)
2. Agent Session Lifecycle 기준으로 tool 목록과 호출 시점을 확정한다. (P1 — 정본 목록 7개와 설계 결정 3건 확정됨)
3. `feat/vault-mcp` 브랜치에서 `app/vault_tools.py`와 테스트를 구현한다. CandidateWriter의 dedup 예외, 하위 폴더 라우팅, 스키마 확장, 이중 기록을 포함한다. (P2)
4. `mcp-serve`와 MCP 서버를 추가해 Claude Code/Desktop에서 시작 브리핑·작업 전 Plan 작성·작업 중 기록·Process 작성 왕복을 검증하고, Claude Code SessionStart/Stop 훅 레퍼런스 구현과 Tier 0 누락 감지를 붙인다. CLAUDE.md의 capture-session 규칙도 이때 함께 갱신한다. (P3)
5. worklog·SessionHandoffs 통합 cleanup 커맨드를 구현한다. (P4)
6. Process 스키마의 Learning Recovery를 확정한다. (P5)
7. `push-digest --daily`에 복습 질문 1개를 포함한다. (P6)
8. Telegram/ask의 `ask-vault` 흐름을 붙인다. (P7)
9. 실제 루프가 검증된 뒤 README/블로그/포트폴리오 서사를 재작성한다. (P8)

---

## 8. Open Questions

당장 결정하지 않지만 사라지면 안 되는 항목.

- 멀티에이전트 동시 쓰기 — 포지셔닝은 "여러 에이전트가 함께 쓰는 버스"지만, Vault git sync와 동시 쓰기 충돌 처리는 미설계 상태다. 단일 사용자 환경에서는 당장 위험이 낮으나, 두 번째 동시 에이전트가 생기는 시점에 재검토한다.
- Plan/Process 단일 세션 노트 통합 — 파일 수가 절반이 되고 "계획 대비 실제"를 한 파일에서 읽을 수 있지만, CandidateWriter에 update 시맨틱이 필요하다. 2파일 운영 경험 후 재검토한다. (P1 결정 2)
- Tier 2/3 도구의 준수율 — Cursor·OpenClaw의 훅 스크립트 자동화와 훅 미지원 도구의 지침 전용 방식에서 프로토콜 준수율이 실제로 얼마나 나오는지, Tier 0 감지만으로 충분한지 관찰이 필요하다.

---

## 9. 한 줄 판단

지금 필요한 것은 Devtrail을 새 프로젝트처럼 다시 설계하는 것이 아니라, 이미 완성된 기록·정제·출력 자동화를 AI 개발 세션 안에서 실제로 소비되는 루프로 전환하는 것이다. 가장 작고 강한 다음 수는 `Agent Session Lifecycle + vault_tools.py + MCP + Learning Recovery`다.
