# Devtrail 프로젝트 컨텍스트 — 내가 만들고 싶은 최종 방향

이 문서는 앞으로 이 프로젝트를 작업할 때 반드시 참고해야 하는 **제품 방향 / 아키텍처 / 개발 원칙**이다.

단순히 현재 코드의 기능을 구현하는 것이 아니라, 아래 전체 계획 안에서 **Devtrail이 어떤 역할을 해야 하는지 이해한 상태로 설계하고 구현해줘.**

---

# 1. 내가 궁극적으로 만들고 싶은 것

나는 집에 있는 여러 장비를 이용해서 **개인용 AI 개발팀(HomeLab AI Development Team)** 을 구축하고 있다.

현재 주요 노드는 다음과 같다.

* `rpi4`
* `macmini`
* `macbook`

이 장비들은 Tailscale을 통해 서로 연결되어 있고, 앞으로 AI Agent들이 각각의 Worker에서 개발 작업을 수행하게 된다.

최종적으로는 내가 ChatGPT와 지금 대화하듯이 **AI Lead / PM과 아이디어와 요구사항을 논의하면**, 그 내용을 기반으로 AI 개발팀이 작업을 계획하고, 개발하고, 검증하고, 결과를 기록하는 구조를 만들고 싶다.

전체 흐름을 단순화하면 다음과 같다.

```text
User
  ↓
AI Lead / PM
  ↓
Orca
  ↓
Claude Code / Codex 등 Coding Agent
  ↓
OmniRoute
  ↓
Mac mini / MacBook 등의 Worker
  ↓
Repository / Runtime / Test
  ↓
Devtrail
```

여기서 Devtrail은 단순한 로그 뷰어나 작업 관리 도구가 아니다.

**AI 개발팀의 Engineering Memory 역할을 담당해야 한다.**

---

# 2. Devtrail의 핵심 역할

Devtrail의 핵심 목적은 다음 질문에 답할 수 있게 만드는 것이다.

> "이 프로젝트에서 지금까지 무슨 일이 있었고, 왜 그렇게 했으며, 현재 어디까지 진행됐고, 다음에는 무엇을 해야 하는가?"

AI Agent가 세션을 종료하거나 다른 Agent로 교체되어도 프로젝트의 맥락이 사라지지 않아야 한다.

예를 들어 Claude Code가 오늘 어떤 기능을 개발하고 세션을 끝냈다면, 다음 날 Codex가 작업을 이어받더라도 다음을 이해할 수 있어야 한다.

* 어떤 요구사항 때문에 작업을 시작했는지
* 어떤 설계를 선택했는지
* 다른 선택지는 무엇이었는지
* 어떤 파일을 수정했는지
* 어떤 문제가 발생했는지
* 어떤 시도를 했는지
* 무엇이 성공했고 무엇이 실패했는지
* 테스트 결과가 어땠는지
* 현재 남아 있는 문제는 무엇인지
* 다음 Agent가 무엇을 해야 하는지

즉,

```text
Git = 코드의 역사

Devtrail = 엔지니어링 사고와 작업의 역사
```

가 되어야 한다.

---

# 3. Devtrail이 저장해야 하는 정보

단순 Activity Log만 저장해서는 안 된다.

최소한 다음 종류의 Engineering Memory를 구조적으로 관리하고 싶다.

## Project Context

프로젝트 자체의 장기적인 맥락.

예:

* 프로젝트 목적
* 아키텍처
* 사용 기술
* 중요한 제약사항
* 현재 개발 단계
* 장기 목표

---

## Decisions

중요한 기술적 / 제품적 결정.

예:

```text
Decision
OmniRoute를 LLM Gateway로 사용한다.

Reason
여러 Provider와 Local LLM을 통합하고
Failover / 비용 / Session Affinity를 직접 제어하기 위해서.

Rejected
Forge 기반 Gateway 구성
```

단순 결과뿐 아니라 **왜 그렇게 결정했는지**가 중요하다.

---

## Tasks

AI 개발팀이 수행하는 작업.

예:

```text
Implement session affinity

status: in_progress
agent: claude
worker: macmini
repository: omniroute

goal:
같은 세션의 요청을 가능한 동일한 Provider로 유지

related_decision:
DEC-004
```

---

## Work Sessions

Claude Code / Codex 등의 실제 작업 세션.

예:

```text
Session
Agent: Claude Code
Worker: macmini
Repo: OmniRoute

Goal
Streaming Failover 구현

Changes
- router.py 수정
- provider_pool.py 추가

Problems
Provider 전환 시 stream이 끊김

Solution
첫 token 이전 failure만 failover 허용

Result
Test 12/12 passed

Next
Provider cooldown 구현
```

---

## Problems / Troubleshooting

실패 기록 역시 중요한 자산이다.

예:

```text
Problem
Qdrant container restart loop

Cause
Volume permission mismatch

Attempts
1. container restart → fail
2. volume recreate → data loss 위험
3. ownership 수정 → success

Solution
chown 1000:1000

Prevention
docker-compose volume permission 명시
```

나중에 같은 문제가 발생하면 AI가 이 기록을 검색해서 바로 활용할 수 있어야 한다.

---

## Learnings

특정 프로젝트에서 얻은 기술적 학습.

예:

```text
Learning

Streaming API에서는
첫 token 이후 provider failover를 시도하면
응답 consistency가 깨질 수 있다.
```

---

## Handoff

Agent가 작업을 끝낼 때 다음 Agent에게 전달하는 상태.

```text
Completed
- Provider abstraction
- OpenAI adapter

Current
- Anthropic adapter

Blocked
- streaming event normalization

Next
1. normalize event schema
2. add integration tests
```

이 Handoff가 매우 중요하다.

AI Agent가 바뀌더라도 사람이 다시 모든 맥락을 설명하지 않아도 작업을 이어갈 수 있어야 한다.

---

# 4. Devtrail은 AI Agent가 읽고 쓰는 시스템이어야 한다

Devtrail은 사람이 UI로 보는 시스템인 동시에 **AI Agent가 사용하는 Memory Infrastructure**여야 한다.

즉 최종적으로 Claude Code / Codex / PM Agent 등이 다음을 수행할 수 있어야 한다.

```text
search_memory(project)

get_project_context(project)

get_recent_sessions(project)

get_decisions(project)

get_open_tasks(project)

get_known_problems(project)

create_decision(...)

create_session(...)

create_problem(...)

create_handoff(...)
```

Agent가 작업을 시작할 때 Devtrail에서 context를 가져오고,

```text
Devtrail
   ↓
Agent Context
   ↓
Coding Agent
```

작업 종료 시 결과를 다시 기록한다.

```text
Coding Agent
   ↓
Session Summary
   ↓
Devtrail
```

결과적으로 다음과 같은 loop가 만들어져야 한다.

```text
READ MEMORY
    ↓
PLAN
    ↓
WORK
    ↓
TEST
    ↓
WRITE MEMORY
    ↓
NEXT AGENT
```

---

# 5. AI 개발팀과의 관계

전체적으로는 이런 역할 분리를 생각하고 있다.

```text
User
 │
 ▼
AI Lead / PM
 │
 ├─ 요구사항 정리
 ├─ 아이디어 구체화
 ├─ 작업 분해
 └─ 우선순위 결정
 │
 ▼
Orca
 │
 ├─ 작업 orchestration
 ├─ Agent 선택
 ├─ Worker 선택
 └─ 실행 관리
 │
 ▼
Coding Agents
Claude Code / Codex / 기타 Agent
 │
 ├─ 코드 분석
 ├─ 구현
 ├─ 테스트
 └─ 디버깅
 │
 ▼
Devtrail
 │
 ├─ Engineering Memory
 ├─ Decisions
 ├─ Sessions
 ├─ Problems
 ├─ Learnings
 └─ Handoff
```

Devtrail이 직접 모든 Agent를 orchestration하려고 하면 안 된다.

**Orchestration과 Engineering Memory의 책임을 분리해야 한다.**

Devtrail은 기본적으로

> "무엇을 실행할 것인가"

보다는

> "무엇을 했고, 왜 했고, 현재 무엇을 알고 있는가"

에 집중한다.

---

# 6. OmniRoute와의 관계

LLM / Agent 요청에 사용하는 Gateway는 **OmniRoute**를 사용한다.

Forge를 사용하지 않는다.

앞으로 설계나 코드에서 별도의 LLM Gateway가 필요하다면 기본적으로 OmniRoute를 기준으로 생각해야 한다.

OmniRoute의 방향은 대략 다음과 같다.

* Multi Provider Routing
* Local / Cloud Model 통합
* Streaming Failover
* API Key Cooldown
* Session Affinity
* Cost Limit
* Route Explain
* Prometheus Metrics

하지만 OmniRoute와 Devtrail의 책임은 분리한다.

```text
OmniRoute
= AI 요청 Routing Infrastructure

Devtrail
= Engineering Memory Infrastructure
```

---

# 7. Devtrail UI의 방향

UI 역시 일반적인 프로젝트 관리 SaaS처럼 만들고 싶지는 않다.

내가 원하는 핵심은 **AI 개발팀이 지금 무엇을 하고 있는지 사람이 빠르게 이해하는 것**이다.

예를 들어 Dashboard에서는 다음 정도를 한눈에 보고 싶다.

```text
Project Health

Current Goal

Running / Recent Agent Sessions

Open Tasks

Recent Decisions

Problems / Blockers

Recent Changes

Next Actions
```

그리고 세부 페이지에서 각각 관리한다.

예:

```text
Dashboard
Projects
Tasks
Sessions
Decisions
Problems
Memory
Agents
Workers
```

Dashboard에 모든 기능을 억지로 넣기보다는,

**첫 화면에서는 전체 흐름과 현재 상태를 보고,
각 관리 페이지에서 기능별 세부 내용을 관리하는 구조**를 선호한다.

---

# 8. 내가 중요하게 생각하는 UX

내가 AI와 프로젝트를 만드는 실제 방식은 다음과 같다.

처음부터 완벽한 요구사항 문서를 작성하는 방식이 아니다.

대화를 하면서:

```text
아이디어
↓
질문
↓
설계
↓
대안 비교
↓
결정
↓
구현
↓
문제 발생
↓
수정
↓
다음 설계
```

이런 식으로 발전한다.

따라서 Devtrail도 결과물만 저장하는 시스템보다는 **이 과정에서 만들어진 중요한 Engineering Context를 축적하는 시스템**이어야 한다.

하지만 모든 채팅 로그를 무식하게 저장하는 것도 원하지 않는다.

원본 대화 전체보다,

```text
Decision
Reason
Problem
Solution
Learning
Current State
Next Action
```

처럼 앞으로 필요한 정보가 압축되어 남는 것이 더 중요하다.

---

# 9. Agent가 Devtrail을 사용할 때의 이상적인 흐름

예를 들어 내가 AI PM에게 다음과 같이 말한다.

```text
OmniRoute에 provider failover를 구현하고 싶어.
```

AI PM이 Devtrail을 조회한다.

```text
Relevant Decisions
Recent Sessions
Known Problems
Architecture
```

그 다음 Task를 만든다.

```text
TASK-134
Implement Provider Failover
```

Orca가 Claude Code에게 작업을 맡긴다.

Claude가 Devtrail에서 관련 memory를 읽는다.

작업을 수행한다.

작업 종료 후 Devtrail에 기록한다.

```text
SESSION-283

Goal
Provider Failover 구현

Changed
router.py
provider.py

Decision
첫 token 이전 failure만 failover

Problem
stream mid-flight failover 불가능

Tests
12 passed

Next
cooldown 구현
```

다음 날 Codex가 Task를 이어받는다.

Codex는 SESSION-283을 읽고 바로 이어서 작업할 수 있다.

이것이 내가 원하는 Devtrail의 핵심 경험이다.

---

# 10. 장기적으로 원하는 것

충분한 Engineering Memory가 쌓이면 AI가 이런 질문에도 답할 수 있으면 좋겠다.

```text
왜 우리는 Qdrant를 선택했어?

지난번 Docker permission 문제 어떻게 해결했지?

OmniRoute failover 설계가 왜 이렇게 되어 있어?

최근 이 프로젝트에서 가장 많이 발생한 문제는 뭐야?

현재 기술 부채가 뭐가 있어?

이 프로젝트에서 다음으로 해야 할 일은 뭐야?
```

즉 Devtrail은 단순 기록 DB가 아니라 장기적으로는

**Project Intelligence / Engineering Knowledge Base**

역할까지 발전할 수 있다.

---

# 11. 중요한 개발 원칙

앞으로 이 repository를 수정할 때 다음 원칙을 지켜줘.

### 1. 현재 코드를 먼저 이해할 것

기존 구조를 무시하고 새로 만들지 말 것.

먼저 repository 전체를 분석해서

* 현재 구현
* 데이터 모델
* API
* UI
* 기존 설계 의도

를 파악할 것.

---

### 2. 필요 이상으로 복잡하게 만들지 말 것

최종 비전은 크지만 지금 당장 모든 것을 구현하려 하지 않는다.

현재 코드베이스에서 자연스럽게 확장 가능한 구조를 만든다.

---

### 3. 미래 확장을 막지 않을 것

특히 아래 기능은 앞으로 연결될 수 있도록 고려한다.

* Claude Code integration
* Codex integration
* Orca integration
* OmniRoute integration
* Worker / Node management
* Agent session ingestion
* MCP / API 기반 Agent access
* Semantic memory search

단, 아직 필요 없는 기능을 미리 과도하게 구현하지 않는다.

---

### 4. Agent-first 구조를 유지할 것

사람이 UI에서 입력해야만 동작하는 구조가 되어서는 안 된다.

대부분의 데이터는 향후 Agent가 API 또는 Tool을 통해 읽고 쓸 수 있어야 한다.

---

### 5. 모든 로그를 Memory라고 부르지 말 것

다음을 구분해야 한다.

```text
Raw Event
Activity
Session
Decision
Problem
Learning
Task
Handoff
Memory
```

각각 목적이 다르다.

검색 가치가 없는 raw event가 Engineering Memory를 오염시키면 안 된다.

---

### 6. 설명 가능한 데이터 구조

AI가 나중에 읽었을 때 의미를 이해할 수 있어야 한다.

단순 문자열 blob 하나에 모든 것을 넣는 구조보다 필요한 경우 구조화된 metadata를 사용한다.

---

### 7. Git과 역할을 중복하지 말 것

Git이 이미 잘하는 것:

```text
commit
diff
branch
file history
```

Devtrail이 해야 하는 것:

```text
why
context
decision
problem
learning
handoff
```

---

# 12. 현재 작업 시 네가 먼저 해야 할 것

이 내용을 읽고 바로 대규모 리팩터링부터 하지 마라.

먼저 현재 repository를 충분히 분석한 뒤 다음을 정리해줘.

1. 현재 Devtrail이 어떤 구조로 구현되어 있는지
2. 현재 구현된 기능이 위 비전 중 어디까지 대응되는지
3. 이미 잘 설계되어 있어서 유지해야 할 부분
4. 비전과 맞지 않거나 중복되는 부분
5. 아직 없는 핵심 기능
6. 데이터 모델에서 확장이 필요한 부분
7. API 구조에서 필요한 변경
8. UI / Dashboard 구조에서 필요한 변경
9. AI Agent integration을 위해 앞으로 필요한 interface
10. 위 내용을 기반으로 한 단계별 구현 순서

그리고 반드시 구분해줘.

```text
NOW
현재 바로 구현해야 하는 것

NEXT
다음 단계에서 구현할 것

LATER
AI 개발팀 전체 구축 이후 연결할 것
```

최종 비전을 한 번에 구현하려 하지 말고, **현재 repository 상태에서 가장 자연스럽고 안전한 다음 단계부터 제안해줘.**

---

# 13. 가장 중요한 한 문장

Devtrail을 설계할 때 항상 이것을 기준으로 판단해라.

> Devtrail은 AI 개발팀이 프로젝트의 과거를 기억하고, 현재를 이해하고, 다음 작업을 이어갈 수 있게 만드는 Engineering Memory다.

기능을 추가할 때마다

> "이 기능이 다음 Agent가 프로젝트를 더 잘 이해하고 작업을 이어가는 데 도움이 되는가?"

를 기준으로 필요성을 판단해줘.

---

이제 현재 repository 전체를 분석하고, 위 방향과 현재 구현을 비교해서 **Devtrail을 이 비전에 맞게 발전시키기 위한 구체적인 다음 작업 계획**부터 작성해줘.

아직 코드를 수정하지 말고 먼저 분석 결과와 구현 계획을 보여줘.
