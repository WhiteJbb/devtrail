# Devtrail 개선 로드맵

> 작성: 2026-08-25. `docs/devtrail-improvement-plan.md`(GPT 상의 초안)를 바탕으로
> 실제 코드 검증을 거쳐 재구성한 실행 계획이다. 초안과 달라진 부분은
> [부록 A](#부록-a--초안-대비-수정된-진단)에 근거와 함께 정리했다.

## 1. 배경 — 무엇이 문제인가

Devtrail의 `Capture → Distill → Curate → Generate → Deliver` 파이프라인은
골격이 이미 완성돼 있다. 문제는 새 기능 부재가 아니라 **기존 단계 사이의
연결이 몇 군데 끊겨 있어 "자동으로 기록되고, 그 기록이 결과물로 이어진다"는
체감이 나지 않는 것**이다.

코드로 확인된 핵심 병목은 두 개다.

### 1-1. weekly distill이 지난 세션을 못 읽는다 (버그)

- `DistillAgent._raw_notes()`는 `needs_distill is not False`인 노트만 읽는다
  (`app/agents/distill_agent.py:200`).
- 증류가 끝나면 `mark_distilled()`가 노트를 `needs_distill=False`로 마킹한다
  (`app/agents/distill_agent.py:96-97`, `app/services/wiki_service.py:77-85`).
- nightly daily가 매일 그날 세션을 마킹하므로, 일요일 weekly의
  `distill_range(days=7)`는 월~토 세션을 전부 건너뛴다. **"7일 종합"이라는
  의도와 실제 데이터 접근이 충돌한다.**
- 단, weekly **digest**는 별도 경로(`nightly_distill_agent.py:346`
  `_week_sessions()`)로 `needs_distill`을 무시하고 7일치를 읽으므로 정상이다.
  깨진 것은 **weekly 후보 증류(knowledge/blog_idea 등) 쪽만**이다.

### 1-2. BlogIdea → BlogWriter 연결이 끊겨 있다

- Distill은 BlogIdea 후보에 핵심 메시지·독자·목차·`source_refs`까지 담아
  `60_Candidates/BlogIdeas/`에 저장한다.
- 그런데 `devtrail blog write`는 topic 문자열만 받고(`app/cli.py:648-652`),
  `ContextPackBuilder`는 `60_Candidates/`를 명시적으로 제외한다
  (`app/memory/context_pack_builder.py:51`).
- 결과: **AI가 "이 자료를 이렇게 묶어 이런 이야기를 하라"고 판단해 둔 결과물을
  Writer가 통째로 버리고 키워드 검색부터 다시 시작한다.**
- 추가로 ContextPack은 관련 노트 최대 5개 × 600자 미리보기
  (`context_pack_builder.py:13-14`)라 "시도 → 실패 → 원인 → 해결"의 시간적
  스토리를 복원하기엔 구조적으로 약하다.

### 1-3. 자동 기록 범위가 "Claude Code + Git 커밋"에 묶여 있다

Stop 훅의 기록 판단 기준이 git dirty / 세션 중 커밋 여부라서, SSH·Docker·
systemd 조작 같은 **커밋 없는 작업(홈랩 운영 등)은 Devtrail 입장에서 아무
일도 없었던 것처럼 보인다.** 이건 버그가 아니라 설계 범위의 한계이며,
후반 Phase(Activity Collector)에서 다룬다.

### 1-4. 지금의 질문 시스템은 Learning Recovery이지 Context Gap Recovery가 아니다

`review_question.py` + Telegram `/answer`는 "내가 이해 못 한 개념"을 회수하는
학습용이다. 블로그·기록 품질에 필요한 것은 별개의 질문이다 —
"이 재시작을 왜 했는가", "최종적으로 해결된 문제가 무엇인가" 같은
**기록에서 빠진 맥락을 채우는 질문**. 기존 기능은 그대로 두고 별도로 추가한다.

## 2. 전체 그림과 원칙

```
Phase 1  파이프라인 복구        ← 지금 바로. 작은 PR 2~3개
Phase 2  Context Gap Recovery   ← 기록 품질을 올리는 질문 1~2개/일
Phase 3  Blog Thread            ← 여러 세션을 하나의 구축기로 묶기
Phase 4  Activity Collector     ← 커밋 없는 작업 캡처 (홈랩)
Track B  제품 방향 (별도 트랙)  ← Learning Debt 재설계, Repo-native 문서 연동
```

원칙:

1. **Collector(수집)보다 Story(가공)를 먼저 고친다.** 이벤트를 아무리 모아도
   Story로 바꾸는 계층이 약하면 쓰레기 데이터만 늘어난다. Phase 4가 마지막인
   이유다.
2. **기존 구조를 최대한 재사용한다.** `_critic_filter`, 후보 흐름,
   `/answer` 인프라, Knowledge 승격 경로는 이미 있다. 새 계층은 이 위에 얹는다.
3. **각 PR은 실패 시 되돌리기 쉬운 최소 단위로 자른다.** 점수·게이지·상태머신
   같은 장식은 해당 기능이 실사용에서 돌아간 뒤에 붙인다.
4. 실사용 벤치마크: **지금 진행 중인 홈랩 구축을 기준으로 "내가 기록을 안 했는데
   Devtrail이 며칠 뒤 구축기를 어디까지 복원하는가"를 성공 기준으로 삼는다.**

---

## Phase 1 — 파이프라인 복구 (지금 바로)

### PR 1: weekly distill을 aggregation pass로 분리

**목적**: weekly가 "미처리 raw를 처리하는 pass"가 아니라 "최근 7일을 종합하는
pass"가 되도록 생명주기를 바로잡는다.

**설계** (초안의 `distilled_at` 타임스탬프 전환까지 갈 필요 없음 — 필터 예외로 충분):

- `DistillAgent._raw_notes()`에 aggregation 모드를 추가한다.
  `days > 0`(range 증류)일 때는 `needs_distill` 필터를 건너뛰고 기간 내
  세션을 전부 읽는다. `today_only`(daily) 경로는 기존 그대로.
- **weekly 경로는 `mark_distilled()`를 호출하지 않는다.** 생명주기 마킹은
  daily의 단독 책임으로 남긴다. 그래야 일요일 weekly가 그날 daily보다 먼저
  돌아도 미처리 노트를 소진하지 않는다.
- 이미 증류된 세션을 다시 읽어도 중복 후보는 기존 `_critic_filter`
  (`distill_agent.py:138`)와 `_find_related_knowledge` 링크가 걸러낸다 —
  weekly 프롬프트(`distill_candidates`, kind=all + days=7)에 "개별 세션의
  단일 사실이 아니라 여러 세션을 관통하는 패턴만 후보로 만들 것" 지시를
  한 줄 보강한다.

**변경 파일**:

| 파일 | 변경 |
|------|------|
| `app/agents/distill_agent.py` | `_raw_notes()` days>0 시 needs_distill 필터 skip, `_distill()` range 모드에서 mark_distilled 생략 |
| `app/prompts/distill_candidates.*` | weekly(kind=all, 기간 증류) 시 종합 패턴 우선 지시 보강 |
| `tests/test_distill_agent.py` | 아래 수용 기준 테스트 추가 |

**수용 기준**:

- 월~토 `needs_distill=False` 세션 + 일요일 미처리 세션이 있는 vault에서
  `distill_range(days=7)`가 7일치 세션을 모두 컨텍스트에 포함한다.
- weekly 실행 후 어떤 노트의 `needs_distill`도 바뀌지 않는다.
- daily(`today_only=True`) 동작은 기존 테스트가 그대로 통과한다.

**비범위**: `distilled_at`/`distill_state` 같은 다단계 상태 필드. 지금 필요
없고, Phase 3(Thread)에서 kind별 추적이 정말 필요해지면 그때 도입한다.

### PR 2: `blog write --idea` — BlogIdea를 정본으로 삼는 글쓰기

**목적**: Distill이 만들어 둔 BlogIdea(핵심 메시지·목차·source_refs)를 버리지
않고 그대로 Writer의 입력으로 쓴다. 블로그 품질 체감에 가장 직접적인 개선.

**설계**:

- CLI: `devtrail blog write`에 `--idea <파일명|경로>` 옵션을 추가한다.
  값은 `60_Candidates/BlogIdeas/` 하위 파일명(부분 일치 허용) 또는 vault 상대
  경로. `--idea` 지정 시 topic 인자는 생략 가능(제목은 idea에서 가져옴).
- 후보 확인은 기존 `devtrail list-candidates`가 이미 BlogIdeas를 보여주므로
  별도 목록 명령은 만들지 않는다.
- `WikiBlogAgent`에 `write_blog_from_idea(idea_rel_path)`를 추가한다:
  1. BlogIdea 노트에서 핵심 메시지, 독자 대상, 목차, `source_refs`를 파싱.
  2. **`source_refs`에 나열된 원본 노트를 keyword 검색 없이 직접 로드**한다.
     각 노트는 미리보기 600자가 아니라 노트당 상한(예: 4,000자)까지 본문을
     싣고, 세션 노트는 날짜순으로 정렬해 시간 흐름을 보존한다.
  3. 프롬프트에 `Thesis(핵심 메시지) / Outline(목차) / Sources(세션 원문,
     시간순)` 구조로 전달한다. 기존 blog write 프롬프트를 변형해 사용.
  4. 생성된 초안의 `source_refs`는 idea의 source_refs + idea 파일 자신으로
     기록해 근거 추적을 유지한다.
- `ContextPackBuilder`는 건드리지 않는다 — Q&A/프로젝트 문맥용 범용 빌더의
  역할은 그대로 두고, idea 경로는 전용 로직으로 분리한다.

**변경 파일**:

| 파일 | 변경 |
|------|------|
| `app/cli.py` | `blog write --idea` 옵션, idea 해석(파일명 부분 일치) |
| `app/agents/wiki_blog_agent.py` | `write_blog_from_idea()` — source_refs 직접 로드, 시간순 정렬, 노트당 상한 |
| `app/prompts/` (blog write 계열) | Thesis/Outline/Sources 구조 프롬프트 |
| `tests/test_wiki_blog_agent.py` 등 | 수용 기준 테스트 |

**수용 기준**:

- `--idea`로 생성한 초안의 컨텍스트에 idea의 source_refs 원문이 (상한 내에서)
  포함되고, keyword 검색 결과가 아니라 refs 순서·전문 기반이다.
- source_refs 중 존재하지 않는 경로는 건너뛰되 경고를 출력한다.
- 기존 `blog write "topic"` 경로는 동작 불변.

**비범위**: 별도 `BlogContextBuilder` 클래스. PR 2 산출물이 부족하다고
판단될 때만 아래 PR 3으로 진행한다.

### PR 3 (조건부): BlogContextBuilder — narrative 컨텍스트 전용 빌더

**착수 조건**: PR 2 이후 실제 초안 2~3편을 뽑아 보고, "세션 원문 시간순
나열"만으로 시도/실패/결정의 서사가 살지 않는다고 확인된 경우에만.

**설계**: 글쓰기 전용 컨텍스트 구조를 만든다.

```
# Blog Thesis
# Timeline
  ## Session 1 — 문제 / 시도 / 결과
  ## Session 2 — 후속 문제 / 변경 / 결과
# Decisions
# Failures
# Commands / Code Evidence
# Missing Context   ← 채워지지 않은 부분을 명시해 Writer가 지어내지 않게 함
```

세션 노트의 구조화 필드(What Changed / Agent Execution Notes / Decisions)를
섹션별로 재배치하는 결정적(비-LLM) 변환으로 시작하고, 부족하면 LLM 요약
pass를 한 단계만 추가한다. `Missing Context` 섹션은 Phase 2의 질문 대상과
직결된다.

---

## Phase 2 — Context Gap Recovery

**목적**: 기록에서 빠진 맥락(왜 했는가, 무엇이 해결됐는가)을 하루 1~2개
질문으로 회수해 세션 노트에 다시 기록한다. 이 한 줄들이 나중 블로그·회고
품질을 좌우한다.

**기존과의 관계**: `review_question.py`(Learning Recovery)는 목적이 다르므로
그대로 둔다. 인프라(Telegram 발송, `/answer` 회수 흐름)는 재사용한다.

**설계**:

- `app/services/context_question.py` 신설. 질문 타입은 5개로 고정한다:

  | 타입 | 질문 |
  |------|------|
  | WHY | 왜 이렇게 했어? |
  | PROBLEM | 처음 해결하려던 문제가 뭐였어? |
  | FAILURE | 이 시도는 왜 실패했어? |
  | DECISION | A 대신 B를 선택한 이유가 뭐였어? |
  | OUTCOME | 최종적으로 뭐가 달라졌어? |

- nightly가 그날 세션 노트를 보고 **정보 가치가 높은 질문 최대 1~2개만**
  생성해 Telegram으로 보낸다. 개수 상한은 하드 리밋 — 안 지키면 안 읽게 된다.
- 답변은 `/answer`(또는 전용 `/context` 명령)로 회수해 해당 세션 노트에
  `## Context Recovery` 섹션으로 append한다. 세션 노트는 읽기 전용 영역이지만
  이 append는 시스템(회수 파이프라인)이 수행하는 정형 기록이므로 허용 경로로
  명시한다.
- 질문·답변·상태(pending/answered/skipped)는 Learning Recovery와 같은 저장
  방식을 따른다.

**수용 기준**:

- 커밋 있는 세션 하루치에서 질문이 2개를 넘지 않는다.
- 답변이 세션 노트 `## Context Recovery`에 반영되고, 이후 distill 컨텍스트에
  포함된다(재기록 시 `needs_distill` 재활성 로직 `vault_tools.py:301-302`와
  같은 방식으로 세션에 새 내용이 들어오면 다시 증류 대상이 되게 한다).

---

## Phase 3 — Blog Thread

**목적**: 구축기는 하루짜리가 아니다. 여러 날의 세션을 하나의 스토리 단위로
묶어, "이 주제로 글을 쓸 재료가 충분히 쌓였는가"를 추적한다.

**설계 (최소형부터)**:

- 1단계: **thread를 frontmatter 필드 하나로 시작한다.**
  BlogIdea 후보에 `thread: homelab-build-2026` 같은 슬러그를 부여하고,
  nightly distill이 새 BlogIdea를 만들 때 기존 thread와 같은 주제면 새 후보를
  만드는 대신 **기존 thread 후보에 세션 ref를 append**하도록 프롬프트와
  writer를 조정한다.
- 2단계: nightly digest에 thread 현황을 한 블록으로 표시한다 —
  "이 thread에 새로 추가된 세션 / 아직 빠져 보이는 요소".
- 3단계 (검증 후): thread가 실제로 쌓이는 게 확인되면 그때 coverage 체크
  (problem/setup/failure/decisions/result)와 초안 생성 제안을 붙인다.
- **readiness 87% 같은 점수 체계는 만들지 않는다** — 묶기 자체가 돌아간 뒤
  필요성이 증명되면 도입. (YAGNI)

**PR 2와의 연결**: thread 후보는 결국 source_refs가 긴 BlogIdea다.
`blog write --idea`가 그대로 thread의 초안 생성기가 된다 — 별도 Writer 불필요.

---

## Phase 4 — Activity Collector (커밋 없는 작업 캡처)

**목적**: SSH·Docker·systemd 같은 커밋 없는 작업을 캡처해 홈랩 운영까지
기록 범위를 넓힌다. **Phase 1~3이 안정된 뒤에만 착수한다** — Story 계층이
약한 상태에서 수집만 늘리면 노이즈만 커진다.

**설계 방향** (착수 시 상세 설계):

- command 하나마다 Markdown을 만들지 않는다. 구조는:

  ```
  Shell/Git/SSH/Docker → Event Collector → local SQLite(~/.devtrail/activity.db)
                       → Sessionizer → 의미 있는 세션만 Vault로
  ```

- 이벤트 스키마: timestamp, hostname, cwd, project, event_type,
  command_category, exit_code, git_head. **명령 전문은 기본 저장하지 않고
  opt-in** (비밀값 유출 방지).
- Sessionizer가 시간 근접성 + 호스트 + cwd로 묶어 "Homelab / rpi4 maintenance
  16:01~16:08" 단위의 세션 노트 하나를 만든다. 이 노트는 기존
  `10_Worklog/Sessions/` 형식을 따르므로 Phase 1~3 파이프라인(distill,
  context question, thread)을 그대로 탄다.
- 멀티 노드(rpi4, Mac mini 등)는 각 장비에 collector만 두고 Vault는 중앙
  한 곳 — 기존 "shared memory bus" 개념과 충돌 없음. Capture Adapter가
  하나 늘어나는 것.
- 시작은 **로컬 PowerShell/bash 히스토리 훅 단일 노드**로 하고, 멀티 노드
  수집은 그 다음이다.

---

## Track B — 제품 방향 (별도 트랙, 이번 라운드와 분리)

아래 두 건은 방향은 좋지만 규모가 크고 Phase 1~4와 독립적이다. 섞지 말고
각각 별도 설계 문서를 만들어 진행한다.

### B-1. Learning Recovery → Learning Debt 재설계

- 현재: AI가 스스로 "사용자가 모를 것"을 적는 구조라 탐지가 새기 쉽다.
- 방향: AI contribution 분석 기반 **Learning Debt 탐지** + scoring
  (중요도 × 재사용성 × AI 의존도 × 이해 부족도)으로 **하루 1~3개만** 회수 +
  Teach-back(사용자가 설명 → LLM이 검증·후속 질문) + 상태 전이
  (unseen → reviewed → explained → verified → retained) + context-based recall
  (같은 주제가 다시 등장하는 세션의 briefing에서 복습 질문).
- 기존 자산 재사용: 질문 저장·`/answer`·`learning` 태그 knowledge 승격 경로는
  이미 있다. 추가되는 것은 탐지·우선순위·검증·재등장 네 단계다.

### B-2. Repo-native Memory + Devtrail 증강 (오픈소스 방향)

- 원칙: **GitHub 문서(README/AGENTS.md/docs/) = 현재 무엇이 사실인가의 정본,
  Devtrail = 어떻게 여기까지 왔고 무엇을 배워야 하는가의 시간축 기억.**
  같은 정보를 중복 저장하지 않는다.
- `devtrail init`이 기존 repo를 분석해 AGENTS.md에 작은 블록만 추가 —
  Devtrail 전용 명령 20개를 가르치는 게 아니라, Devtrail 없이도 repo 문서만으로
  agent가 일할 수 있고 Devtrail이 있으면 더 좋아지는 구조.
- Documentation drift 감지: 작업 종료 시 "이번 변경으로 repo 정본 문서가
  바뀌어야 하는가"를 판단해 제안.
- 제품 분리: **Devtrail Core**(Git + AGENTS.md + docs만으로 동작, Obsidian
  불필요) / **Devtrail Vault**(현재의 Obsidian·Telegram·Blog·Career 전체 =
  Power User Mode).
- 포지셔닝 문안: "Devtrail turns AI coding sessions into project memory and
  developer knowledge."

---

## 3. 실행 순서 요약

| 순서 | 항목 | 규모 | 상태 (2026-08-25) |
|------|------|------|--------|
| 1 | PR 1 — weekly distill aggregation 분리 | 소 | ✅ dev 머지 (52d8822) |
| 2 | PR 2 — `blog write --idea` | 중 | ✅ PR #48 머지 |
| 3 | PR 3 — BlogContextBuilder | 중 | ⏸ 보류 — 실데이터+flash급 모델로 초안 재평가 후 판단 (테스트는 flash-lite라 불공정 조건) |
| 4 | Phase 2 — Context Gap Recovery | 중 | ✅ PR #49 머지 (Telegram 명령은 `/gap` — `/context`는 ContextPack 조회가 선점) |
| 5 | Phase 3 — Blog Thread (1~2단계) | 중 | ✅ PR #50 머지 + 후속 PR #51 (thread 연속 후보 critic 우회) |
| 6 | Phase 4 — Activity Collector | 대 | 별도 설계 후 |
| — | Track B | 대 | 별도 설계 문서부터 |

e2e 검증(2026-08-25, testvault + 실 Gemini): 전 기능 통과. 발견 이슈 2건 —
critic의 thread 연속 후보 탈락(PR #51로 수정), 재기록 시 Context Recovery 소실
(PR #49에 보존 로직 포함). 남은 개선 후보: `write_wiki_blog_from_idea.md` 문체
가이드 보강(사용자 톤 확정 후), Gemini flash 503 시 fallback 키 확보.

각 단계 완료 시점에 홈랩 벤치마크("기록 안 한 홈랩 작업을 얼마나 복원하는가")로
체감을 확인하고 다음 단계 착수를 판단한다.

---

## 부록 A — 초안 대비 수정된 진단

초안(`devtrail-improvement-plan.md`)의 주장을 2026-08-25 코드 기준으로 검증한 결과.

| 초안 주장 | 검증 결과 |
|-----------|-----------|
| weekly distill이 이미 처리된 세션을 제외한다 | **사실.** `distill_agent.py:200` 필터 + daily의 `mark_distilled` 조합으로 재현된다. 단 weekly digest는 별도 경로(`_week_sessions`)라 정상 — 깨진 건 후보 증류만. |
| `capture()` memo에는 `needs_distill` 필드가 없어 계속 재처리된다 | **낡은 정보.** 현재 모든 capture 경로가 `needs_distill: True`를 세팅한다 (`capture_agent.py:193, 353, 429, 526`). memo도 정상 마킹된다. PR 1 범위에서 제외. |
| ContextPackBuilder가 60_Candidates를 제외해 BlogIdea가 버려진다 | **사실.** `context_pack_builder.py:51`. `blog write`에 `--idea` 경로 없음(`cli.py:648-652`). |
| 노트 5개 × 600자로는 서사 복원이 약하다 | **사실.** `context_pack_builder.py:13-14`. |
| 세션 재기록 시 distill 재활성이 필요하다 | **이미 구현됨.** `vault_tools.py:301-302`가 재기록 시 `needs_distill=True`로 되돌린다. |
| `distilled_at` 타임스탬프로 생명주기 전환 | **채택 안 함.** weekly를 aggregation pass로 만드는 필터 예외만으로 충분. 다단계 상태가 필요해지는 시점(Phase 3 이후)에 재검토. |
| readiness 점수(87%) 게이지 | **보류.** thread 묶기가 실사용에서 돌아간 뒤 도입 판단. |
