응. 코드까지 보고 나니까 방향이 꽤 선명해졌어. **Devtrail은 새로 갈아엎을 상태가 아니라, 이미 만든 파이프라인 사이의 연결이 몇 군데 끊겨 있어서 “자동으로 기록된다”는 체감이 안 나는 상태**에 가까워.

현재 구조 자체는 상당히 많이 와 있어. `Capture → Distill → Curate → Generate → Deliver`가 있고, Claude Code에서는 MCP로 `write_work_plan → write_session_process`, Learning Recovery, nightly distill, Telegram까지 이미 들어가 있다. 특히 `write_session_process`는 세션 기록을 Worklog에 남기고, 결정과 Agent Execution Note까지 따로 분리해서 저장한다.

근데 지금 우리가 느끼는 문제를 기준으로 보면 **4군데가 핵심 병목**이야.

### 1. 자동 기록의 범위가 사실상 “Claude Code + Git 작업”에 너무 묶여 있음

현재 Stop 훅이 “기록할 작업이 있었는가?”를 판단하는 기준은 거의 정확히 이거야.

```
git dirty?
또는
세션 시작 후 새 commit 있음?
        ↓
YES → write_session_process 요구
NO  → 그냥 종료
```

실제 훅 코드도 Git working tree와 세션 중 commit을 기준으로 판단하고 있어.

그래서 이런 건 잘 잡힘.

```
Claude Code
↓
코드 수정
↓
commit
↓
Process 기록
```

근데 우리가 오늘 홈랩에서 하는 건:

```
ssh rpi4

docker ps
systemctl status ...
micro compose.yaml
docker compose up -d
curl localhost:8123
tail ...
```

이런 거잖아.

**Git commit이 없으면 Devtrail 입장에서는 아무 일도 안 한 것처럼 보일 수 있어.**

심지어 Claude Code 훅도 `.claude/settings.example.json`을 `.claude/settings.json`으로 복사해서 활성화해야 하고, 기본적으로 각 프로젝트/환경에 설치되는 구조야.

그리고 Git post-commit 자동 캡처는 이미 성능과 정보 품질 문제 때문에 일부러 비활성화해놨고.

즉 지금 Devtrail은 **“에이전트가 알고 있는 개발 세션”은 잘 기록하려고 만들어졌는데, “사람이 실제로 컴퓨터에서 하는 작업”은 잘 못 봄.**

이게 첫 번째 문제야.

---

### 2. 더 큰 문제 하나 찾았음: daily distill과 weekly distill의 데이터 생명주기가 이상해

이건 실제로 고쳐야 할 것 같아.

`DistillAgent`는 raw note를 읽을 때:

```python
note.metadata.get("needs_distill") is not False
```

인 것만 읽어. 그리고 처리하고 나면 `mark_distilled()`가 `needs_distill=True`였던 노트를 `False`로 바꿔.

그런데 nightly daily distill은 오늘 세션을 처리한 뒤 저걸 false로 만들잖아.

그러면:

```
월요일 session
nightly
→ needs_distill=False

화요일 session
nightly
→ needs_distill=False

수요일 ...

일요일 weekly-distill
↓
최근 7일을 읽으려고 함
↓
월~토 session들은 이미 False
↓
제외
```

가 가능해.

NightlyDistillAgent는 weekly일 때 분명히 `distill_range(days=7)`를 호출하도록 되어 있는데, 실제 raw note 필터가 이미 처리된 session을 제외하니까 **“7일 종합”이라는 의도와 실제 데이터 접근 방식이 충돌해.**

더 웃긴 건 `capture()`로 만들어지는 일반 memo는 아예 `needs_distill` 필드가 없어.

`mark_distilled()`는 `needs_distill`이 truthy일 때만 False로 바꾸니까, 일반 memo는 계속 distill 대상에 남을 수 있음.

즉 현재는 대략:

```
Session
한 번 처리 후 사라짐

Memo
계속 재처리될 가능성
```

이라는 비대칭이 있어.

이건 먼저 손봐야 함.

---

### 3. 블로그 아이디어 → 실제 블로그 작성 사이가 끊겨 있음

이건 내가 보기엔 **자동 블로그가 별로라고 느끼는 가장 직접적인 원인 중 하나**야.

Distill prompt는 blog idea를 꽤 잘 만들게 되어 있어.

심지어 기준이:

> 여러 작업 세션의 패턴을 종합하는가?
> 

까지 들어가 있음.

그리고 blog idea 안에는:

```
핵심 메시지
독자 대상
목차 초안
관련 노트
source_refs
```

까지 넣어.

좋음.

그런데 `devtrail blog write "주제"`를 실행하면 `WikiBlogAgent`가 `ContextPackBuilder.build(topic)`을 호출해.

그리고 **ContextPackBuilder는 `60_Candidates/`를 명시적으로 제외함.**

그러니까:

```
Sessions
   ↓
Distill
   ↓
┌──────────────────────┐
│ Blog Idea            │
│ 핵심 메시지           │
│ 목차                 │
│ source_refs          │
└──────────────────────┘
   ↓

사용자: 이걸로 글 써줘
   ↓

Blog Writer
   ↓
Blog Idea는 안 읽음  ← ???
   ↓
topic keyword로 다시 검색
```

ㅋㅋㅋㅋ 여기 연결이 끊겨 있음.

AI가 한 번 열심히 **“이 자료들을 이렇게 묶어서 이런 이야기를 하면 된다”**고 판단했는데, 정작 Writer는 그 판단 결과를 버리고 다시 키워드 검색부터 하는 거야.

게다가 ContextPack은 관련 노트 최대 5개, 각 600자 preview 정도야.

그래서 실제 구축기처럼:

```
처음 시도
↓
실패
↓
원인 조사
↓
다른 방식 시도
↓
또 실패
↓
해결
↓
며칠 뒤 추가 개선
```

의 **시간적인 Story**를 복원하기엔 구조가 약해.

---

### 4. 지금 있는 “질문”은 우리가 필요한 질문과 조금 다름

Devtrail에 질문 시스템 자체는 이미 잘 만들어놨어.

`review_question.py`는:

```
AI가 주도적으로 처리한 부분
내가 아직 이해하지 못한 개념
다음에 설명해봐야 할 질문
```

을 다루고, Telegram `/answer`까지 연결되어 있어.

근데 이건 **Learning Recovery**야.

우리가 블로그 자동화를 위해 필요한 건 약간 다른 질문임.

예를 들어 Devtrail이 이렇게 봤다고 해보자.

```
16:12 SSH rpi4
16:14 systemctl restart pi-metrics
16:16 curl :8123
16:17 200 OK
```

우리가 필요한 질문은:

> pi-metrics를 재시작한 이유가 뭐였어?
> 

또는:

> 이 작업으로 최종적으로 해결된 문제가 뭐였어?
> 

이거임.

즉 필요한 건 **Knowledge Question이 아니라 Context Gap Question**이야.

---

# 그래서 나는 Devtrail을 이렇게 바꾸고 싶어

기존 아키텍처는 유지하고 중간에 **`Activity → Story` 계층 하나를 추가**하는 거야.

```
현재

Capture
   ↓
Distill
   ↓
Candidate
   ↓
Blog
```

를:

```
Activity Capture
       ↓
 Session Reconstruction
       ↓
 Context Gap Recovery
       ↓
     Work Story
       ↓
     Distill
       ↓
 ┌─────────────┐
 │ Knowledge   │
 │ Decision    │
 │ Blog Thread │
 │ Career      │
 └─────────────┘
       ↓
 Blog Draft
```

로.

여기서 핵심 단위가 **raw command도 아니고 Markdown note도 아니고 `Work Story`**가 되는 거야.

예:

```yaml
project: Homelab
started_at: 2026-08-24T14:20
ended_at: 2026-08-24T16:10

goal:
  Raspberry Pi 시스템 정보를 Homepage에 표시

problem:
  Docker 컨테이너에서 일부 시스템 정보 접근이 어려움

attempts:
  - Docker 내부에서 metric 수집
  - host API 방식 검토
  - systemd 서비스로 pi-metrics 실행

result:
  port 8123에서 metric API 정상 응답

evidence:
  - systemctl restart pi-metrics
  - curl localhost:8123
  - HTTP 200

unknown:
  - systemd 방식으로 전환한 정확한 이유
```

그리고 unknown이 중요하면:

> systemd 방식으로 바꾼 가장 큰 이유가 뭐였어?
> 

딱 한 번 물어봄.

---

# 1차 개선은 생각보다 작게 갈 수 있음

나는 우선 **새 activity collector부터 만들지 않을 것 같아.**

먼저 지금 깨져 있는 파이프라인부터 이어야 함.

### PR 1 — Distill 생명주기 수정

`needs_distill: bool` 하나로 모든 증류 상태를 표현하지 말자.

예를 들어:

```yaml
distill_state:
  daily: 2026-08-24
  weekly: null
  knowledge: 2026-08-24
  blog: null
```

까지 할 필요도 없고 MVP라면:

```yaml
distilled_at: 2026-08-24T23:30
```

을 두고,

```python
daily-distill:
    오늘 생성된 note

weekly-distill:
    distilled 여부와 상관없이 최근 7일 session
```

로 분리하는 게 낫겠어.

즉 weekly는 **aggregation pass**지, 미처리 raw를 처리하는 pass가 아님.

이건 `DistillAgent._raw_notes()`와 `mark_distilled()`를 손보면 됨.

---

# PR 2 — BlogIdea에서 직접 글 쓰게 만들기

이건 꼭 해야 할 것 같음.

지금:

```bash
devtrail blog write "라즈베리파이 홈서버"
```

뿐인데,

추가로:

```bash
devtrail blog write --idea 3
```

가 있어야 함.

그러면:

```
BlogIdea
  │
  ├─ 핵심 메시지
  ├─ 목차
  └─ source_refs ────────┐
                         ↓
                   BlogContextPack
                         ↓
                     Writer
```

이렇게.

**BlogIdea의 source_refs를 정본으로 삼아서 원본 세션을 다시 가져오는 것**이 중요해.

후보에:

```yaml
source_refs:
  - 10_Worklog/Sessions/xxx.md
  - 10_Worklog/Sessions/yyy.md
  - 20_Knowledge/zzz.md
```

가 있다면 그걸 전문 또는 충분한 길이로 읽으면 됨.

기존 `ContextPackBuilder`를 억지로 바꾸기보다 나는 아예:

```
ContextPackBuilder
→ 일반 Q&A / 프로젝트 문맥

BlogContextBuilder
→ 글쓰기용 narrative context
```

로 나눌 것 같아.

BlogContext는 이런 구조:

```
# Blog Thesis

# Timeline

## Session 1
문제 / 시도 / 결과

## Session 2
후속 문제 / 변경 / 결과

## Session 3
최종 상태

# Decisions

# Failures

# Commands / Code Evidence

# Missing Context
```

이게 블로그 Writer한테는 훨씬 먹힘.

---

# PR 3 — `Context Gap Recovery`

기존 `review_question.py`는 그대로 둬.

그건 잘못된 기능이 아니라 목적이 다름.

별도로:

```
app/services/context_question.py
```

정도를 만들자.

질문 타입은 5개면 충분함.

```
WHY
왜 이렇게 했어?

PROBLEM
처음 해결하려던 문제가 뭐였어?

FAILURE
이 시도는 왜 실패했어?

DECISION
A 대신 B를 선택한 이유가 뭐였어?

OUTCOME
최종적으로 뭐가 달라졌어?
```

그리고 매일 밤 session을 보고 **정보 가치가 높은 질문 최대 1~2개만** Telegram으로 보내는 거야.

예:

```
🧩 오늘 기록에서 빠진 맥락

Raspberry Pi 3B+ USB 부팅 테스트

Q. SD카드 문제가 아니라고 판단한 근거가 뭐였어?

[답변] [넘기기]
```

너는:

> 같은 SD카드를 4B에 꽂았을 때 정상 부팅됐음
> 

한 줄.

그럼 Devtrail이 기존 Session에:

```markdown
## Context Recovery

- SD카드 문제가 아니라고 판단한 근거:
  같은 SD카드를 Raspberry Pi 4B에서 정상 부팅시켜 확인함.
```

을 추가.

**이 한 줄 때문에 나중에 블로그 품질이 미친 듯이 올라갈 거야.**

---

# 그리고 그 다음에 Activity Collector

여기부터가 Devtrail을 진짜 자동 기록 시스템으로 만드는 부분.

근데 **command 하나마다 Markdown을 만들면 절대 안 됨.**

내가 제안하는 구조는:

```
Shell / Git / SSH / Docker
            ↓
       Event Collector
            ↓
      local SQLite
            ↓
        Sessionizer
            ↓
    의미 있는 session만
            ↓
        Obsidian Vault
```

예:

```
~/.devtrail/activity.db
```

에:

```
timestamp
hostname
cwd
project
event_type
command_category
exit_code
git_head
```

정도 저장.

명령 전문은 보안 때문에 선택적으로.

예를 들어:

```
16:01 ssh rpi4
16:03 systemctl status ...
16:05 systemctl restart ...
16:06 curl ...
16:08 docker ps
```

를 각각 노트로 만들지 않고,

sessionizer가:

```
Homelab / rpi4 maintenance
16:01 ~ 16:08
```

하나로 묶는 거야.

---

## 이게 홈랩에서 특히 잘 먹힘

각 장비에 아주 가벼운 Devtrail collector만 두면:

```
                    Devtrail
                       ↑
            ┌──────────┼──────────┐
            │          │          │
          rpi4       M1       Mac mini
            │          │          │
         shell       shell      shell
         docker      docker     ollama
         systemd       git        git
```

중앙 Vault는 한 군데.

그러면 오늘처럼:

```
Pi3B+ 부팅 테스트
Pi4 저장소 확인
Mac mini 세팅
Docker 서비스 수정
Homepage 수정
```

이런 게 알아서 Homelab Story로 묶임.

이건 지금 Devtrail의 **“coding agents shared memory bus”라는 개념도 안 깨뜨려.** 기존 설계도 이미 여러 에이전트가 같은 Vault를 공유하는 걸 핵심으로 잡고 있어.

Capture Adapter만 하나 늘어나는 거야.

```
Claude Code Adapter
Codex Adapter
Telegram Adapter
Shell Adapter      ← 추가
Git Adapter
Homelab Adapter    ← 나중
```

---

# 마지막으로 `Blog Thread`라는 개념을 넣고 싶음

이게 자동 블로그에 가장 중요할 수도 있어.

지금은 매 nightly마다:

```
오늘 자료
→ BlogIdea?
```

인데,

구축기는 그렇게 안 생겨.

예를 들어:

```
8/18
Raspberry Pi 4B 설치

8/19
Tailscale

8/20
Docker

8/23
Homepage

8/24
선반 / SSD / 3B+ 복구

8/27
Mac mini 추가
```

이게 **한 개의 Story**잖아.

그래서:

```yaml
thread: homelab-build-2026

title: 개인 홈랩 구축기

sessions:
  - rpi4-initial-setup
  - tailscale-setup
  - docker-setup
  - monitoring-setup
  - rpi3b-recovery
  - macmini-join

coverage:
  problem: true
  setup: true
  failure: true
  decisions: true
  result: true

readiness: 87
```

같은 지속 객체를 만들면 좋겠음.

그리고 nightly가:

```
📚 블로그 Thread

개인 홈랩 구축기
████████░░ 82%

새로 추가됨:
• Raspberry Pi 3B+ 복구 시도
• 홈랩 선반 구성

아직 부족:
• Mac mini 최종 역할
• 전체 아키텍처 완성 상태
```

라고 보내줘.

어느 순간:

```
██████████ 96%

초안을 만들기 충분합니다.
[초안 생성]
```

이렇게.

이게 내가 생각하는 **진짜 Devtrail다운 자동 블로그**야.

---

## 그래서 우선순위는 이 순서가 좋아 보여

**지금 바로 할 것**

```
1. daily / weekly distill lifecycle 버그 수정
2. BlogIdea → BlogWriter source_refs 연결
3. BlogContextBuilder 추가
```

이 세 개만 해도 블로그 기능 체감이 많이 달라질 거야.

그다음:

```
4. Context Gap 질문
5. Story Thread
6. shell activity collector
7. homelab multi-node collector
```

순서.

특히 나는 **6번부터 시작하면 안 된다고 봐.** 이벤트는 엄청 많이 모으는데 지금처럼 Story로 바꾸는 계층이 약하면 결국 **“쓰레기 데이터가 더 많아진 Devtrail”**이 돼버림.

반대로 먼저 `Session → Story → Blog` 파이프라인을 제대로 만들면, 나중에 Shell/Git/Docker를 붙일수록 Devtrail이 점점 강해져.

그리고 꽤 재미있는 포인트가, **지금 우리가 실제로 하고 있는 홈랩 구축을 Devtrail의 첫 Activity-to-Story 실사용 벤치마크로 삼으면 됨.** “오늘 내가 아무 기록도 안 했는데 Devtrail이 며칠 뒤 이 홈랩 구축기를 어디까지 복원할 수 있는가?”를 성공 기준으로 두는 거지. 이건 제품 방향 검증으로도 꽤 좋은 테스트 같아.

응. **그건 블로그 자동화랑 같은 파이프라인 위에 얹되, 목적은 따로 분리하는 게 맞아.** 둘을 한 기능으로 묶으면 둘 다 애매해질 가능성이 커.

지금 Devtrail에도 이미 Learning Recovery가 있어서 세션에 `AI가 주도적으로 처리한 부분 / 내가 아직 이해하지 못한 개념 / 직접 설명해봐야 할 질문`을 남기고, 나중에 `/answer`로 회수하는 구조는 있어. `write_session_process`에도 그 필드가 정식으로 들어가 있고.

근데 현재 구조는 **“질문을 남기는 것”까지는 잘 되어 있는데, 실제로 내가 배웠는지 확인하는 시스템은 약해.**

내가 방향을 잡는다면 Devtrail 안에 두 개의 서로 다른 결과물을 둬.

```
              개발 세션
                 │
         ┌───────┴────────┐
         ↓                ↓
      Work Story      Learning Trail
         │                │
      블로그/회고       이해도 회수
      포트폴리오        복습/질문
```

### 블로그 쪽은 `무슨 일이 있었는가`

```
문제
→ 시도
→ 실패
→ 결정
→ 해결
```

를 복원하는 게 목적이고,

### 학습 쪽은 `내가 뭘 모르고 AI에게 넘겼는가`

를 찾는 게 목적.

이 구분이 꽤 중요해.

---

특히 지금 Learning Recovery의 약점은 **AI가 자기 자신에게 “사용자가 뭘 모를까?”를 쓰게 한다는 것**이야.

예를 들어 Claude Code가:

```python
async with asyncio.TaskGroup() as tg:
    ...
```

를 알아서 넣어줬다고 해도 사용자는 그냥

> 오 되네
> 

하고 넘어갈 수 있잖아.

AI가 Process를 쓸 때도 본인이 그걸 어려운 개념이라고 판단하지 않으면 Learning Recovery에 안 들어갈 수 있어.

그래서 나는 **Learning Debt 탐지**를 별도로 넣는 게 좋다고 봐.

```
AI가 수행한 변경
       ↓
AI contribution 분석
       ↓
사용자가 직접 판단하지 않은 부분 탐지
       ↓
Learning Debt
```

예를 들어:

```yaml
concept: Python asyncio TaskGroup
project: Forge

reason:
  AI가 동시 요청 처리 코드를 직접 설계함

evidence:
  - app/router.py
  - session: abc123

risk:
  medium

question:
  TaskGroup에서 하나의 task가 실패하면 나머지 task는 어떻게 되는가?

status:
  unseen
```

이런 객체를 두는 거지.

나는 이름도 **`LearningDebt`**가 괜찮다고 봄.

기술 부채처럼:

> AI가 대신 구현해서 현재 코드는 동작하지만, 개발자가 아직 소유하지 못한 지식
> 

이라는 의미.

---

그리고 이걸 단순 Q&A로 끝내면 안 돼.

현재 `/answer`는 질문에 답하면 answered 처리하는 정도야.

그 대신 상태를 이렇게 가져가면 좋겠어.

```
unseen
  ↓
reviewed
  ↓
explained
  ↓
verified
  ↓
retained
```

예를 들어 질문:

> Qdrant alias를 이용하면 왜 재색인 중 downtime을 피할 수 있어?
> 

네가 답함:

> 새 컬렉션 만들어서 indexing 끝낸 다음 alias를 새 컬렉션으로 바꾸면 기존 검색을 유지할 수 있어서
> 

LLM:

```
✓ 핵심 이해함

빠진 부분:
alias switch 자체가 원자적으로 수행되는 점도 중요함.

후속 질문:
기존 컬렉션을 바로 재색인하는 것과 비교하면 rollback 측면에서는 어떤 장점이 있을까?
```

이런 식으로.

그러면 그냥 **AI가 설명해주는 공부가 아니라 네가 설명하는 공부**가 됨.

이게 훨씬 중요해.

---

그리고 나는 Devtrail이 **너무 많은 걸 가르치려고 하면 망한다고 봐.**

AI 코딩 하루 종일 하면 Learning Debt 후보가:

```
asyncio
Docker
Pydantic
typing
Git
PostgreSQL
CSS
React
HTTP
...
```

수십 개 나올 수 있음.

그렇게 되면 안 봄 ㅋㅋ.

그래서 scoring이 필요해.

```
Learning Value =
    중요도
  × 재사용 가능성
  × AI 의존도
  × 이해 부족도
```

예:

| 항목 | 처리 |
| --- | --- |
| CSS margin AI가 수정 | 버림 |
| FastAPI route 하나 생성 | 낮음 |
| LangGraph state 설계 | 높음 |
| DB 자기참조 구조 | 높음 |
| 장애 복구 원인 | 높음 |
| Kubernetes probe 동작 | 높음 |

하루에 **1~3개만** 회수.

---

그리고 지금 Devtrail에는 이미 좋은 기반이 하나 있어.

Distill prompt가 Learning Recovery에서 나온 내용을 `learning` 태그의 knowledge candidate로 승격할 수 있게 되어 있음.

그러니까 새 시스템도 완전히 따로 만들 필요 없어.

```
AI Coding Session
       ↓
Learning Debt Detector
       ↓
오늘 중요한 것 2개
       ↓
Teach-back
       ↓
검증
       ↓
Learning Knowledge Candidate
       ↓
20_Knowledge
```

이렇게 기존 Knowledge 파이프라인으로 다시 합치면 됨.

---

그리고 **Spaced Repetition 비슷한 것**도 아주 가볍게 붙이면 좋아.

시험 공부 앱처럼 만들 필요는 없고:

```
오늘 이해함
    ↓
3일 후
"이거 아직 설명 가능?"
    ↓
2주 후
프로젝트에서 다시 등장하면 질문
```

정도.

특히 Devtrail의 장점을 살리려면 단순 날짜 기반보다 **context-based recall**이 더 재밌어.

예를 들어 예전에:

> Docker bind mount와 named volume 차이
> 

를 Learning Debt로 배웠는데,

3주 뒤 Claude Code가 또 Docker Compose를 수정하는 세션이면 briefing에서:

```
🧠 이전에 학습한 관련 개념

Docker bind mount vs named volume

이번 변경에서 volume을 사용하고 있습니다.
왜 이 경우 named volume이 적절한지 직접 설명해보세요.
```

라고 뜨는 거임.

이건 Devtrail이 단순 플래시카드보다 훨씬 잘할 수 있는 영역이야.

---

그리고 이 기능은 Devtrail의 제품 정체성에도 꽤 잘 맞는다고 생각해.

지금 문서상 Devtrail은 **coding agents가 공유하는 project memory bus** 방향으로 가고 있잖아.

여기에 하나만 더 붙이면:

> **AI가 프로젝트 기억을 가져가더라도, 개발자의 이해는 남겨두지 않는다.**
> 

가 됨.

즉,

```
Agent Memory
"AI가 다음 세션에서 기억해야 할 것"

Project Memory
"프로젝트가 장기적으로 기억해야 할 것"

Learning Memory
"개발자가 실제로 이해해야 할 것"
```

세 축.

이거 생각보다 Devtrail의 차별점이 될 수도 있음.

요즘 AI 코딩 도구들은 대부분 **“AI가 어떻게 더 많이 기억할까”**에 집중하는데 Devtrail은 반대로 **“AI가 많이 해줄수록 사람이 아무것도 못 배우는 문제”**까지 다루는 거니까.

그래서 다음 개선 작업을 잡는다면 나는 블로그보다도 먼저 **현재 Learning Recovery를 `Learning Debt → Teach-back → Verified Knowledge`로 재설계**하는 걸 한번 제대로 해볼 가치가 있다고 봐. 지금 기능을 버리는 게 아니라, 현재 질문 저장 기능 위에 **탐지·우선순위·검증·재등장** 네 단계만 추가하는 거야.

응. 지금 얘기한 문제까지 합치면 나는 오히려 **GitHub 문서화를 병행하는 쪽이 Devtrail의 제품 방향을 더 좋아지게 만든다**고 봐.

핵심은 **GitHub 문서와 Devtrail이 같은 정보를 중복 저장하게 만들면 안 된다는 것**이야.

지금 Devtrail이 어려운 이유 중 하나가 사실 이것 같아.

```
Claude Code
   ↓
"Devtrail MCP를 써야 함"
   ↓
get_project_briefing 기억해야 함
write_work_plan 기억해야 함
write_session_process 기억해야 함
Learning Recovery 채워야 함
...
```

Devtrail을 만든 우리는 이 프로토콜을 알지만, 새로운 AI agent 입장에서는 **Devtrail이라는 별도 세계의 규칙을 학습해야 하는 셈**이잖아.

실제로 현재 repo도 MCP + Claude Code hook을 이용해서 이걸 강제하려고 꽤 많은 장치를 넣은 상태고.

이건 개인 사용에서는 개선할 수 있지만 오픈소스 adoption에서는 꽤 큰 마찰이야.

## 그래서 역할을 이렇게 나누는 게 좋을 것 같아

```
Repository
│
├── README.md
├── AGENTS.md
├── docs/
│   ├── architecture.md
│   ├── decisions/
│   ├── development.md
│   └── ...
│
│        ↑↓
│
└──── Devtrail ───────────────────────
          │
          ├── Session Memory
          ├── Learning Debt
          ├── Work Story
          ├── Open Loops
          ├── Blog Threads
          └── Personal Knowledge
```

### GitHub = 프로젝트의 정본

여기에는 이런 걸 둠.

- 시스템 구조
- 실행 방법
- 중요한 설계 결정
- 개발 규칙
- 프로젝트 현 상태
- 에이전트가 반드시 알아야 할 내용

### Devtrail = 시간에 따라 흐르는 기억

여기에는:

- 오늘 뭘 했는지
- 왜 막혔는지
- 시행착오
- AI가 대신 한 부분
- 아직 내가 모르는 부분
- 다음에 할 일
- 블로그 소재
- 개인적으로 기억할 내용

이렇게.

**GitHub는 "현재 무엇이 사실인가"**

**Devtrail은 "어떻게 여기까지 왔고 내가 무엇을 배워야 하는가"**

로 구분하면 굉장히 깔끔해.

---

그리고 이건 오픈소스 관점에서도 오히려 유리해.

지금은 AGENTS.md라는 형식 자체가 상당히 널리 사용되고 있어. AGENTS.md 공식 사이트는 6만 개 이상의 오픈소스 프로젝트에서 사용된다고 설명하고 있고 Codex, Copilot, Cursor, Gemini CLI, Aider 등 여러 도구가 지원한다고 명시하고 있어. (Agents)

GitHub Copilot도 현재 `AGENTS.md`를 agent instructions로 지원하고, root의 `CLAUDE.md`나 `GEMINI.md`도 지원해. (GitHub Docs)

그러니까 Devtrail이 굳이

> 모든 AI 도구에게 Devtrail 사용법을 가르친다
> 

를 할 필요가 없어.

대신:

> **이미 AI들이 이해하는 repo-native documentation에 Devtrail이 연결된다.**
> 

가 훨씬 세.

---

# 예를 들어 설치하자마자

```bash
devtrail init
```

하면:

```
AGENTS.md
.devtrail/
docs/
```

정도를 보고 Devtrail이 기존 repo를 분석해서 AGENTS.md에 아주 작은 블록만 추가하는 거야.

```markdown
## Project Memory

Persistent project context is managed by Devtrail.

Before significant implementation:
- Read relevant docs under `docs/`.
- Check current project context with Devtrail if available.

After significant implementation:
- Ensure repository documentation still reflects the implementation.
- Record decisions that are not obvious from the code.
```

중요한 건 **여기에 Devtrail 전용 명령 20개를 적는 게 아님.**

Agent가 Devtrail을 몰라도:

```
README
AGENTS
docs
code
```

만 읽어서 최소한 정상적으로 일할 수 있어야 함.

Devtrail이 연결되어 있으면 **더 좋아지는 구조**여야지,

Devtrail이 없으면 프로젝트 문맥이 증발하는 구조면 adoption이 어렵다고 봐.

---

# 그러면 Devtrail의 역할이 더 재밌어짐

예를 들어 Claude Code가 작업함.

```
기존
─────────────────────

Claude
 ↓
Devtrail MCP
 ↓
Vault
```

에서

```
새 방향
────────────────────────────────────

                  ┌→ Repo Docs
                  │
Claude ─→ Devtrail
                  │
                  ├→ Session Memory
                  ├→ Learning Memory
                  └→ Personal Knowledge
```

Devtrail이 작업이 끝났을 때:

> 이번 작업으로 repo 정본 문서도 바뀌어야 하는가?
> 

를 판단하는 거지.

예를 들어:

```
FastAPI
   ↓
Redis 추가
   ↓
캐시 아키텍처 도입
```

하면 Devtrail이:

```
Documentation drift detected

docs/architecture.md
현재:
API → PostgreSQL

실제 코드:
API → Redis → PostgreSQL

[업데이트 제안 보기]
```

를 띄워.

이거 꽤 가치 있어.

---

# 그리고 Learning Recovery에도 GitHub docs가 도움됨

AI가 뭘 대신했는지를 판단할 때 그냥 diff만 보면 부족하다고 했잖아.

Repo docs를 기준으로 잡으면:

```
Repository Knowledge
       │
       ↓
"이 프로젝트에서 개발자가 알아야 하는 것"
       │
       ↓
이번 AI 변경
       │
       ↓
Learning Gap
```

을 볼 수 있음.

예를 들어 `docs/architecture.md`에:

```
요청 라우팅
→ 모델 후보 생성
→ capability filter
→ cost/latency scoring
→ failover
```

가 있는데 AI가 routing 코드를 대규모로 변경함.

그러면 Devtrail:

> 이번 변경은 Forge 핵심 라우팅 경로에 영향을 줍니다.
> 

> 그런데 이번 세션에서 사용자가 직접 결정하거나 설명한 흔적이 없습니다.
> 

그래서 Learning Debt 생성:

```
🔥 중요

Forge의 모델 선택 scoring 변경

확인할 것:
"현재 모델 후보가 어떤 단계로 필터링되는지 설명해보세요."
```

이건 단순히 AI가

> asyncio를 썼으니까 asyncio 공부하세요
> 

하는 것보다 훨씬 품질이 높아.

**프로젝트에서 정말 알아야 하는 내용인지 repo docs로 중요도를 판단할 수 있으니까.**

---

# 그리고 오픈소스로는 나는 아예 2단계 제품으로 갈 것 같아

### Devtrail Core

설치 부담 거의 없음.

```bash
pip install devtrail
cd project
devtrail init
```

그리고:

```
Git
AGENTS.md
docs/
AI coding agent
```

만 있으면 됨.

기능:

```
Session capture
Decision capture
Documentation drift
Learning debt
Project briefing
```

Obsidian 없어도 됨.

### Devtrail Vault

원하는 사람만.

```
Obsidian
Telegram
Blog
Career
Long-term personal memory
Cross-project knowledge
Weekly review
```

지금 Devtrail이 하고 있는 상당 부분은 사실 **Power User Mode**에 가까워.

처음 써보는 사람이:

```
Obsidian Vault 만들어라
환경변수 설정해라
MCP 등록해라
Claude hook 설치해라
Telegram bot 설정해라
nightly scheduler 등록해라
candidate promote해라
```

를 보면 아무리 좋아도 접을 가능성이 높음 ㅋㅋ.

반면:

```bash
devtrail init

✓ AGENTS.md detected
✓ Git repository detected
✓ Claude Code detected

Devtrail is ready.
```

하고 끝나면 얘기가 달라지지.

---

## 그래서 오히려 지금 포지셔닝을 약간 수정하는 게 좋을 수도 있어

현재 문서의:

> Obsidian-native shared project memory bus for coding agents
> 

도 기술적으로는 잘 맞는데, 일반 개발자가 봤을 때 약간 추상적임.

내가 지금까지 얘기한 방향을 한 줄로 하면 오히려:

> **Devtrail turns AI coding sessions into project memory and developer knowledge.**
> 

정도가 더 직관적이야.

한국어로 풀면:

> **AI가 코드를 대신 짜도, 프로젝트의 맥락과 개발자의 배움은 사라지지 않게 한다.**
> 

그리고 결과가 세 갈래.

```
                 AI Coding
                     │
                     ↓
                  Devtrail
                     │
       ┌─────────────┼──────────────┐
       ↓             ↓              ↓
 Project Memory  Developer Memory  Work History
       │             │              │
    Git Docs      Learning       Blog/Portfolio
    AGENTS.md      Recovery
    Decisions
```

이거면 제품 서사가 상당히 좋아져.

---

그리고 **“사람들이 쓸까?”**에 대해서는, 현재 Devtrail 그대로면 나는 솔직히 대중적으로 쓰기 어렵다고 봐.

기능이 부족해서가 아니라 **초기 개념 비용이 너무 높아서** 그래.

반면

> `기존 repo에 설치 → 평소 Claude/Codex/Cursor 그대로 사용 → 알아서 개발 기록과 learning debt가 쌓임`
> 

까지 내려가면 꽤 흥미로운 오픈소스가 될 수 있다고 봐.

특히 다른 도구들이 **AI를 더 잘 일하게 만드는 것**에 집중한다면 Devtrail은

> AI와 같이 일했을 때 **사람과 프로젝트에 무엇이 남는가**
> 

를 해결한다는 점에서 방향이 꽤 독특하고.

그래서 다음 대규모 개선은 기능 추가보다 **`Devtrail 없이도 읽히는 Repo-native Memory + Devtrail이 뒤에서 증강`**으로 아키텍처를 다시 잡는 게 맞는 것 같아.

그리고 이 방향이면 지금까지 만든 Vault/MCP/Learning Recovery를 버리는 것도 아님. 오히려 **Vault를 코어에서 분리해서 고급 기능으로 살리는 것**이라 지금 투자한 코드도 대부분 가져갈 수 있어.