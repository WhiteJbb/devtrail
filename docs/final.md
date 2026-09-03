# Devtrail 개선 작업 지시 — 홈랩 AI 개발팀의 Engineering Memory Core

지금부터 Devtrail을 단순한 개인 기록/블로그 도구가 아니라, 내가 구축 중인 **Personal AI Engineering Lab의 Engineering Memory Core**라는 관점에서 작업해줘.

단, 중요한 전제가 있다.

**새 시스템을 처음부터 설계하지 마라. 현재 Devtrail은 이미 상당 부분 구현되어 있다.**

이번 작업의 목적은 기존 구조를 갈아엎는 것이 아니라:

> 이미 존재하는 Devtrail의 Memory Loop를 실제 사용 가능한 수준으로 완성하고, 앞으로 AI Lead / Orca / Claude Code / Codex / Control Room이 안정적으로 사용할 수 있게 만드는 것

이다.

---

# 0. 작업 시작 전에 반드시 읽을 것

다음 순서대로 현재 repository를 먼저 읽어라.

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/final.md`
4. `docs/final-review.md`
5. `docs/devtrail-improvement-roadmap.md`
6. `docs/activity-collector-design.md`
7. `docs/ai-team-pm-design.md`
8. `README.md`

`AGENTS.md`가 개발 규칙의 정본이다.

문서와 현재 코드가 충돌하면 **현재 코드 + 더 최근에 갱신된 검토 문서**를 우선해서 판단하되, 임의로 정책을 바꾸지 말고 충돌을 보고해라.

그리고 반드시 현재 HEAD / branch / test 상태도 다시 확인해라.

내가 이 지시를 작성할 당시에는 `main`에 2026-09-03 기준 `dev` 내용이 머지되어 있었고, 관련 머지 커밋에서 테스트가 `513 passed`였다.

**[정정 2026-09-03 실측]** 그 뒤 `dev`에 `devtrail doctor`(#55)가 머지됐다.

```text
dev   b1ae818  feat: devtrail doctor (#55)   ← 판단 기준
main  b04efc7  Merge branch 'dev'            (doctor 없음)

.venv pytest -q → 548 passed
```

`main`은 `dev`보다 1커밋 뒤처져 있다. 따라서 이 문서의 조사·판단 기준은 `main`이 아니라 **`dev`**다.

---

# 1. 내가 구축하고 있는 전체 시스템

내 홈랩의 최종 목적은 집에 있는 장비들을 이용해서 **나만의 AI 개발팀**을 운영하는 것이다.

현재 실제 노드 이름은:

```text
rpi4
macmini
macbook
```

이다.

역할은 현재 다음처럼 잡혀 있다.

```text
rpi4
→ SRE / Monitoring

macmini
→ AI HQ
→ Worker 01
→ Production
→ Storage

macbook
→ Worker 02
→ Sandbox / Staging
```

전체 소프트웨어 구조는 다음 방향이다.

```text
                         USER
                          │
                          ▼
                 AI Team / Control Room
                          │
                          ▼
                    AI Lead / PM
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
          DEVTRAIL                   ORCA
    Engineering Memory          Execution Layer
             │                         │
             │                         ▼
             │               Claude Code / Codex
             │                         │
             │                         ▼
             │                    OmniRoute
             │               Model / Provider Routing
             │                         │
             └──────────────┬──────────┘
                            ▼
                   macmini / macbook
                            │
                            ▼
                  Repository / Runtime
                            │
                            ▼
                           rpi4
                    SRE / Monitoring
```

각 구성요소의 책임을 섞지 마라.

---

# 2. 각 시스템의 책임

## Devtrail

```text
무엇을 했는가
왜 그렇게 했는가
어떤 문제가 있었는가
왜 이런 결정을 했는가
무엇을 배웠는가
현재 무엇이 남아 있는가
다음 Agent가 무엇을 알아야 하는가
```

를 기억한다.

즉:

> Engineering Memory / Organizational Memory

다.

---

## Orca

```text
Task 실행
Agent 실행
Worktree
Worker 선택
Execution lifecycle
```

을 담당한다.

Devtrail 안에 orchestration을 만들지 마라.

---

## OmniRoute

```text
LLM Provider / Model Routing
Failover
Session Affinity
Cost / Quota
Provider 상태
```

를 담당한다.

Forge는 현재 홈랩 v1 아키텍처에서 사용하지 않는다.

Devtrail에서 별도 LLM Gateway를 다시 만들지 마라.

---

## ai-team-control-room

현재 중요한 결정:

**Web Dashboard / DB / HTTP API / 실시간 Agent·Worker 상태 UI는 Devtrail 소관이 아니다.**

별도 repository인:

```text
ai-team-control-room
```

의 책임이다.

Control Room은 향후:

```text
Dashboard
Projects
Tasks
Running Sessions
Agents
Workers
Approval
Execution Status
```

등을 담당한다.

Devtrail은 이 UI를 직접 구현하지 않는다.

현재 `dashboard.py` Textual TUI는 **Devtrail CLI command launcher**로 유지 가능하다.

웹 Control Room과 이것을 혼동하지 마라.

---

# 3. GitHub와 Devtrail의 차이

Git이 이미 잘하는 것:

```text
commit
diff
branch
file history
PR
code review
```

Devtrail이 해야 하는 것:

```text
why
context
decision
problem
failure
solution
learning
handoff
```

Git 기능을 다시 만들지 마라.

예를 들어:

```text
git
→ router.py가 어떻게 바뀌었는지

devtrail
→ 왜 router.py를 이렇게 바꿨는지
```

를 담당해야 한다.

---

# 4. Devtrail은 이미 상당 부분 구현돼 있다

`docs/final-review.md`와 현재 코드를 직접 확인해라.

현재 비전에서 요구하는 주요 Engineering Memory 중 이미 다음이 존재한다.

## Project Context

```text
30_Projects/<P>/Context.md
get_project_briefing
```

---

## Decision

```text
record_note(kind=decision)
→ 60_Candidates/Decisions/
→ promote-candidate
→ 30_Projects/<P>/Decisions/
```

Reason / alternatives / final judge를 기록할 구조도 이미 존재한다.

---

## Work Session

```text
write_session_process
→ SessionHandoff
→ 10_Worklog/Sessions/
```

---

## Learning

```text
60_Candidates/Knowledge/
40_AgentMemory/06_Lessons.md
```

---

## Handoff

```text
write_work_plan
write_session_process
get_project_briefing
```

으로 이미 핵심 루프가 존재한다.

```text
READ
 ↓
PLAN
 ↓
WORK
 ↓
TEST
 ↓
PROCESS
 ↓
NEXT SESSION
```

이 구조를 새로 만들지 마라.

---

# 5. 반드시 유지해야 하는 핵심 불변식

## Candidate → Human Review → Promote

현재 가장 중요한 Devtrail 설계 원칙 중 하나다.

```text
AI Output
   ↓
60_Candidates/
   ↓
Human review
   ↓
Official Memory
```

AI가 바로:

```text
20_Knowledge/
30_Projects/<P>/Decisions/
40_AgentMemory/
```

에 쓰는 경로를 임의로 추가하지 마라.

자동 승격을 확대하는 것은 별도 제품 결정이다.

내 승인 없이 이 원칙을 변경하지 마라.

---

## Raw / Candidate / Stable 구분

이미 MCP 검색에서 다음 개념을 사용한다.

```text
stable
candidate
raw
```

Raw Event와 Engineering Memory를 같은 등급으로 취급하지 마라.

특히:

```text
00_Inbox
shell command
raw session
```

을 그대로 Memory라고 부르지 마라.

---

## Briefing은 인덱스 우선

모든 과거 문서를 Agent context에 통째로 밀어 넣지 않는다.

```text
summary
+
relevant references
+
read_note 필요 시 추가 조회
```

방식을 유지한다.

토큰 절약 때문만이 아니라 noise를 줄이기 위한 설계다.

---

## Session checkpoint 업데이트 방식 유지

같은 MCP session에서:

```text
write_work_plan
write_session_process
```

를 여러 번 호출해도 새로운 파일을 계속 만드는 것이 아니라 같은 handoff를 갱신하는 현재 semantics를 유지한다.

---

# 6. 내 작업 스타일을 반드시 이해할 것

나는 프로젝트를 보통 이렇게 만든다.

```text
아이디어
 ↓
AI와 대화
 ↓
대안 탐색
 ↓
"이건 아닌 것 같은데?"
 ↓
방향 변경
 ↓
새 기술 발견
 ↓
다시 설계
 ↓
결정
 ↓
구현
 ↓
문제 발생
 ↓
수정
 ↓
며칠 뒤 다시 재검토
```

처음부터 PRD가 완성되어 있는 방식이 아니다.

따라서 Devtrail이 기억해야 하는 핵심은 raw conversation 전체가 아니다.

```text
Current State
Decision
Alternative
Reason
Problem
Attempt
Solution
Learning
Open Question
Next Action
```

이다.

중요한 것은:

> 최종 상태뿐 아니라 왜 그 상태에 도달했는가

를 기억하는 것이다.

---

# 7. Devtrail의 기존 목적도 버리지 말 것

Devtrail은 원래 다음 흐름을 가지고 있다.

```text
Capture
 ↓
Distill
 ↓
Curate
 ↓
Generate
 ↓
Deliver
```

그리고:

```text
Blog
Portfolio
Resume
Learning Recovery
Weekly Review
Telegram
```

등의 기능도 존재한다.

Engineering Memory로 발전시킨다고 이것들을 갈아엎지 마라.

오히려:

```text
좋은 Engineering Memory
        ↓
좋은 Blog
좋은 회고
좋은 Portfolio
좋은 Learning Recovery
```

가 되는 방향이다.

특히 내가 Devtrail을 만든 이유 중 하나는:

**AI로 개발하면서 내가 실제로 아무것도 배우지 못하는 상황을 줄이는 것**

도 있다.

따라서 Learning Recovery는 유지해야 한다.

---

# 8. 현재 Devtrail 개선 현황

기존 개선 로드맵에서:

```text
Phase 1 — Pipeline Recovery
Phase 2 — Context Gap Recovery
Phase 3 — Blog Thread
```

는 이미 구현 및 머지된 상태다.

구체적으로 이미 다음이 들어가 있다.

```text
weekly distill aggregation fix

blog write --idea

Context Gap Recovery

Blog Thread

MCP raw read scope

raw search quota

Activity Collector PR A
```

따라서 이것들을 다시 구현하지 마라.

---

# 9. 현재 가장 자연스러운 다음 작업 — Activity Collector 완성

현재 `docs/activity-collector-design.md` 기준으로 Phase 4는:

```text
PR A
shell hook
activity install/uninstall/status
✅ 구현됨

PR B
Sessionizer
⬅️ 다음 구현 후보

PR C
nightly integration
retention
manual sessionize command
⬅️ PR B 이후
```

이다.

Activity Collector가 필요한 이유:

지금까지 Devtrail은 Claude Code + Git 작업은 잘 잡지만:

```text
ssh rpi4

docker compose up -d

systemctl restart ...

curl localhost:8123

vim compose.yaml
```

같은 **commit 없는 홈랩 작업**을 기억하기 어렵다.

하지만 command 한 줄씩 Vault에 넣으면 안 된다.

목표는:

```text
Shell Activity
     ↓
Local JSONL
     ↓
Sessionizer
     ↓
Meaningful Work Session
     ↓
Context Gap Recovery
     ↓
Distill
     ↓
Knowledge / Decision / Blog Thread
```

이다.

---

# 10. Activity Collector PR B 구현 원칙

현재 설계가 유효한지 코드를 먼저 재검증한 뒤 진행한다.

큰 방향은 다음이다.

## Input

```text
~/.devtrail/activity/YYYY-MM-DD.jsonl
```

PR A가 기록한 shell events.

---

## Session grouping

결정적 로직으로 먼저 묶는다.

기본 설계:

```text
same host
+
same shell
+
event gap <= 30 min
```

---

## Noise filtering

다음과 같은 탐색성 command만 있는 세션은 의미 있는 작업으로 보지 않는다.

예:

```text
ls
cd
pwd
clear
history
exit
```

다만 흐름 복원을 위해 raw event에서는 유지할 수 있다.

---

## Minimum useful activity

설계 문서 기준:

```text
실질 명령 < 5
```

이면 Session note를 만들지 않는다.

단 현재 실제 JSONL을 보고 이 기준이 명백하게 잘못된 경우에는 임의 변경하지 말고 먼저 보고해라.

---

## Project inference

cwd와 `.claude/vault.json` 등을 활용한다.

추측 confidence가 낮으면 확정적으로 쓰지 마라.

예:

```text
project: unknown
```

또는 불확실 표시를 남겨라.

---

## LLM은 정리만 한다

LLM에게 command를 보고 실제로 없었던 goal/problem을 만들어내게 하면 안 된다.

원칙:

```text
Evidence에 있는 내용
→ 요약 가능

Evidence에 없는 사실
→ 추측 금지

애매함
→ uncertain
```

---

## Output

결과는 기존 세션 파이프라인이 읽을 수 있어야 한다.

예:

```yaml
type: session
source: activity
project: homelab
host: macmini
created_at: ...
session_id: ...
needs_distill: true
```

그리고 본문은 대략:

```text
Goal
Activity Summary
Commands / Evidence
Problems
Outcome
Uncertain Context
```

가 되도록 한다.

단 기존 Session format과 최대한 맞춰라.

새 Session schema를 별도로 만들지 마라.

---

# 11. MCP Session과 Activity Session 중복

Claude Code로:

```text
docker ...
ssh ...
```

를 실행하면:

```text
MCP write_session_process
+
Activity session
```

두 개가 생길 수 있다.

현재 Phase 4 설계에서는 **우선 둘 다 생성한다.**

처음부터 복잡한 dedup 알고리즘을 만들지 마라.

실사용 후 실제 noise가 확인되면:

```text
same project
+
overlapping time
+
MCP session 존재
```

일 때 activity note를 skip/merge하는 방식을 검토한다.

지금은 실데이터 없이 최적화하지 않는다.

---

# 12. PR C는 PR B 이후 별도 작업

Sessionizer를 구현했다고 한 PR에서 nightly까지 전부 엮지 마라.

PR B:

```text
JSONL
→ sessionization
→ Session note
```

까지만.

테스트와 실제 sample JSONL로 검증.

그 뒤 별도 PR에서:

```text
nightly-distill 앞단 integration
fail-open
activity retention
activity sessionize --date
```

를 연결한다.

각 변경은 되돌리기 쉽게 작게 자른다.

---

# 13. 실제로 기록이 쌓이는 것이 기능 추가보다 우선

Devtrail의 가장 큰 과거 문제는:

> 기능이 부족한 것보다 실제 기록이 계속 쌓이지 않았다는 것

이었다.

따라서 앞으로 판단 기준을:

```text
새로운 기능 개수
```

가 아니라:

```text
실제 세션 기록 수
후보 생성 수
promote 수
다음 세션에서 재사용된 Memory 수
```

로 잡아라.

기록이 없는 상태에서 schema와 feature만 늘리는 것을 피한다.

---

# 14. 멀티 머신 부트스트랩 문제

과거 실제로 발생한 문제:

한 머신에서는:

```text
devtrail
MCP
settings.json
vault.json
hooks
```

가 정상인데 다른 머신에서는 빠져 있어서 기록이 아예 남지 않았다.

특히 `.claude/settings.json` / `.claude/vault.json`이 gitignore되어 있어 머신마다 환경 차이가 생길 수 있다.

그래서 `docs/final-review.md`에 `devtrail doctor` 개선 후보가 있었다.

**[정정 2026-09-03 실측] 이미 구현·머지됐다** — `dev` `b1ae818`(#55).

```text
app/services/doctor.py   397줄, 점검 7종 + --fix 자동 수리
app/cli.py               @app.command("doctor")
tests/test_doctor.py
```

점검 항목: vault 경로 / mcp 패키지 / Claude Code 훅(`settings.json`) /
훅 실행 전제 / 프로젝트 매핑(`vault.json`) / vault 구조 / MCP 등록.

단 `main`에는 아직 없다(§0). 그리고 **셸 activity 훅 설치 여부는 점검하지 않는다** —
`devtrail activity status`가 별도 커맨드로 남아 있다.

원래 의도했던 목적:

```text
CLI installed?
Vault configured?
project mapped?
MCP registered?
hooks active?
settings.json exists?
vault.json exists?
session lifecycle working?
```

를 한 번에 검사한다.

(위 목록 중 `session lifecycle working?`은 현재 doctor가 직접 확인하지 않는다.
훅과 MCP 등록이 살아 있는지까지만 본다.)

남은 일은 새 구현이 아니라 **`dev` → `main` 머지 여부 결정**과,
doctor에 activity 훅 점검을 넣을지 여부다.

---

# 15. 앞으로 필요한 진짜 Memory 공백 — Problem / Troubleshooting

최종 비전 대비 현재 Devtrail에서 가장 명확하게 빠진 1급 Memory는:

```text
Problem / Troubleshooting
```

이다.

내가 원하는 형태는 예를 들어:

```text
Problem
Docker container restart loop

Symptoms
...

Cause
Volume permission mismatch

Attempts
1. restart → fail
2. recreate volume → 위험
3. ownership 변경 → success

Solution
chown 1000:1000

Prevention
compose에서 permission 명시

Related
project
session
commit
component
host
```

이다.

목적은 나중에 AI가:

```text
"예전에 이 문제 있었어?"

"지난번 Tailscale 안 켜졌을 때 어떻게 해결했지?"

"이 프로젝트에서 가장 자주 생기는 장애 유형이 뭐야?"
```

라고 물었을 때 바로 찾기 위함이다.

하지만 이 기능도 Activity 기록이 실제 쌓이기 전에 너무 크게 설계하지 마라.

우선 실사용 데이터를 확보하고 현재 Session / Knowledge / Decision 구조와 어느 정도 중복되는지 검토한 뒤:

```text
problem candidate kind
→ human review
→ stable troubleshooting memory
```

정도의 최소 구조부터 설계해라.

---

# 16. 앞으로 필요한 metadata

향후 여러 Agent / Worker에서 기록이 들어오므로 다음 식별자는 중요하다.

```text
host
agent
component
```

Problem에서는 추가로:

```text
cause_class
```

정도를 고려한다.

예:

```yaml
host: macmini
agent: claude-code
component: docker
cause_class: permission
```

이 정보가 있으면 나중에:

```text
macmini에서 반복되는 문제

Claude가 작업한 최근 Session

Docker 관련 Troubleshooting

가장 흔한 장애 유형
```

같은 조회가 쉬워진다.

하지만 모든 기존 Markdown에 거대한 migration을 만들지 마라.

기존 frontmatter와 backward compatibility를 유지하면서 점진적으로 추가한다.

---

# 17. MCP 인터페이스의 장기 방향

현재 MCP는 이미 핵심 기능을 가지고 있다.

하지만 향후 AI Agent가 반복적으로:

```text
search_vault
read_note
search_vault
read_note
...
```

를 여러 번 호출하는 대신 다음과 같은 read-only convenience tool을 둘 수 있다.

```text
get_recent_sessions(project)

get_decisions(project)

get_known_problems(project)
```

장기적으로는 유용하다.

하지만 **지금 당장 추가하지 마라.**

실제 Devtrail을 일정 기간 사용해서 검색 패턴이 반복된다는 것을 확인한 뒤 추가한다.

지금은 existing MCP를 먼저 충분히 사용한다.

---

# 18. Task Manager는 조심해서 다룰 것

현재:

```text
70_Tasks/
```

가 있지만 개인 todo 성격이다.

최종 비전에서는:

```text
project
status
agent
worker
related_decision
```

등을 가진 Task가 필요해 보일 수 있다.

하지만 여기서 책임 경계를 다시 생각해야 한다.

```text
실행할 Task 관리
→ Orca / Control Room / GitHub

Task가 왜 생겼고 결과가 무엇이었는지
→ Devtrail
```

즉 Devtrail을 범용 Jira로 만들지 마라.

필요하면 Devtrail Session/Handoff에 외부 task ID를 연결하는 방향부터 검토한다.

---

# 19. Candidate Review 병목

현재 candidate/promote 구조는 중요하지만 실제 사용에서 사람이 promote를 하지 않으면:

```text
Candidate만 쌓이고
Stable Memory가 늘지 않는
```

문제가 생긴다.

과거에는 14일 TTL 때문에 검토되지 않은 후보가 삭제되는 문제도 발생했고, 현재 TTL을 임시로 크게 늘린 상태다.

이건 영구 해결책이 아니다.

향후 선택지는:

### A. Review UX 개선

Telegram에서:

```text
승인
보류
삭제
```

를 1tap으로 처리.

기존 불변식을 유지할 수 있다.

### B. Low-risk auto promote

사람이 이미 확정한 Decision 등 일부를 자동 승격.

하지만:

```text
AI는 공식 영역에 직접 쓰지 않는다
```

라는 기존 원칙을 바꾸므로 **사용자 승인 없이는 구현 금지**다.

이번 작업에서는 이 정책을 임의로 결정하지 마라.

필요하다면 두 방향의 trade-off를 정리해서 나에게 물어라.

---

# 20. Open Source 방향

Devtrail은 장기적으로 다른 사람도 사용할 수 있는 오픈소스로 발전시킬 생각이 있다.

하지만 현재 우선순위는:

> 내가 실제로 매일 쓰는 시스템

이다.

따라서 내 홈랩 환경에서 검증되지 않은 범용 기능을 미리 만들지 마라.

원칙:

```text
Personal use first
↓
Real usage
↓
Pattern discovery
↓
Reusable abstraction
↓
Open source generalization
```

이다.

개인 사용성을 희생하면서 처음부터 SaaS형 범용화하지 마라.

---

# 21. 전체 홈랩 Phase와 Devtrail 개발을 혼동하지 말 것

홈랩 인프라 구축에는 별도의 Phase 0~21 계획이 있고 이 순서는 동결되어 있다.

현재 실제 홈랩 진행판에서는:

```text
Phase 1 ✅
Phase 2 ✅
Phase 3 ✅
Phase 4 ✅

NEXT
Phase 5 — Raspberry Pi SRE Node
```

상태다.

Devtrail repository 자체의 제품 개선을 진행하는 것은 가능하지만:

**Devtrail 기능 개발을 했다고 홈랩 전체 구축 Phase가 자동으로 앞으로 진행된 것으로 처리하면 안 된다.**

두 진행축은 분리해서 이해한다.

---

# 22. 이번 세션에서 원하는 구체적인 작업

먼저 코드를 수정하지 말고 다음을 수행해라.

## Step 1 — Reality Check

현재 **`dev`** 기준으로 직접 확인 (**[정정 2026-09-03]** `main`에는 doctor가 없어 아래 마지막 항목이 오답이 된다 — §0):

```text
현재 HEAD
현재 test 결과
Activity Collector PR A 구현 여부
activity JSONL 형식
Session note 생성 코드
nightly integration 상태
Problem candidate 존재 여부
doctor 유사 기능 존재 여부
```

문서만 믿지 말고 실제 코드를 검증한다.

---

## Step 2 — 비전 대비 현재 상태를 다시 정리

아래 형식으로 짧게 보고한다.

```text
ALREADY DONE

PARTIALLY DONE

MISSING

DO NOT BUILD HERE
```

특히 `DO NOT BUILD HERE`에는:

```text
Web Dashboard
HTTP API
DB
Agent orchestration
Worker scheduler
LLM Gateway
```

처럼 Control Room / Orca / OmniRoute 소관 기능을 넣어라.

---

## Step 3 — 다음 구현 단위를 결정

현재 코드가 설계 문서와 일치한다면 기본 우선순위는:

```text
1. Activity Collector PR B — Sessionizer
2. PR B 실데이터 검증
3. Activity Collector PR C — nightly integration + retention
4. devtrail doctor          ← [정정] 구현 완료 (#55). 남은 건 dev→main 머지 결정뿐 (§14)
5. 실제 사용 데이터 확보
6. Problem/Troubleshooting 최소 모델
7. metadata(host/agent/component/cause_class)
8. 실제 사용 후 MCP convenience reads
```

이다.

단, 코드 분석에서 이 순서가 잘못됐다는 **구체적인 근거**가 나오면 근거와 함께 변경안을 제시해라.

그냥 더 멋진 아키텍처가 떠올랐다는 이유로 순서를 바꾸지 마라.

---

# 23. PR 단위 원칙

한 번에 대규모 리팩터링하지 마라.

예:

```text
feat/activity-sessionizer
        ↓
tests
        ↓
PR -> dev
        ↓
실사용
```

그 다음:

```text
feat/activity-nightly
```

같이 진행한다.

각 PR에는:

```text
Goal
Why
Changed
Tests
Acceptance Criteria
Out of Scope
Risk
Rollback
```

을 명확하게 남긴다.

---

# 24. 완료라고 말하는 기준

코드를 작성했다는 이유로 완료라고 하지 마라.

반드시:

```text
tests pass
+
acceptance criteria verified
+
existing behavior regression 없음
```

을 확인한다.

실환경 확인이 필요한 부분을 테스트로만 확인했다면:

```text
unit verified
real environment not verified
```

라고 명시한다.

---

# 25. Devtrail이 앞으로 답할 수 있어야 하는 질문

모든 기능 설계는 결국 다음 질문을 얼마나 잘 답하게 만드는지로 판단한다.

```text
이 프로젝트에서 현재 뭘 하고 있지?

왜 이 아키텍처를 선택했지?

이 결정 전에 어떤 대안을 버렸지?

지난 Agent는 어디까지 했지?

다음 Agent는 무엇부터 하면 되지?

예전에 같은 문제가 있었나?

그때 어떻게 해결했지?

최근 반복되는 장애가 뭐지?

이 프로젝트에서 배운 게 뭐지?

현재 열려 있는 질문은 뭐지?
```

이 질문에 도움을 주지 않는 기능이라면 Devtrail Core에 들어갈 이유가 있는지 다시 생각해라.

---

# 26. 가장 중요한 판단 기준

항상 이것을 기준으로 해라.

> **Devtrail은 AI 개발팀이 프로젝트의 과거를 기억하고, 현재를 이해하고, 다음 작업을 이어갈 수 있게 만드는 Engineering Memory다.**

그리고 동시에:

> **기록을 많이 모으는 시스템이 아니라, 다음 Agent에게 가치 있는 맥락을 남기는 시스템이다.**

Raw data의 양보다:

```text
Why
Decision
Problem
Solution
Learning
Handoff
```

의 품질을 우선한다.

---

# 27. 지금 바로 할 일

이제 repository를 직접 분석하고 다음 순서로 답해줘.

1. 현재 Git HEAD / branch / test 상태
2. 현재 Devtrail 기능 지도
3. 위 최종 아키텍처와 현재 구현의 갭
4. 이미 구현돼 있으므로 건드리면 안 되는 부분
5. Devtrail 밖(Control Room / Orca / OmniRoute)에 있어야 하는 부분
6. 현재 가장 시급한 3가지
7. Activity Collector PR B를 지금 구현하는 것이 맞는지
8. 맞다면 정확한 변경 파일과 데이터 흐름
9. 테스트 계획
10. 이번 PR의 비범위

**분석을 먼저 보여줘.**

내 승인 없이 대규모 리팩터링, 스키마 전면 교체, DB 도입, HTTP API 추가, Web UI 추가, orchestration 기능 추가는 하지 마라.