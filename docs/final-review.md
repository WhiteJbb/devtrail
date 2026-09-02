# final.md 검토 — 비전 대비 현재 구현 실측

> 작성: 2026-09-02. `docs/final.md`(제품 방향 문서)가 요구한 "현재 repository
> 분석 → 비전 대비 갭 → 단계별 구현 순서"에 대한 답이다. `dev` 브랜치 코드,
> 실제 Vault(`C:/Users/beaco/git/personal-vault`), 로컬 설치 상태를 직접 읽고
> 실행해 검증했다. **코드는 수정하지 않았다.** 실측 명령과 출력을 그대로
> 남겨 나중에 같은 검증을 재현할 수 있게 했다.

## 0. 핵심 결론

1. final.md §3이 요구하는 Engineering Memory 7종 중 **5종은 이미 구현돼
   있다.** 새 메모리 시스템을 만들 필요가 없다.
2. 자리 자체가 없는 엔티티는 **Problem / Troubleshooting 하나**다.
   Task는 존재하지만 형태(개인 todo)가 비전(프로젝트 1급 엔티티)과 다르다.
3. **가장 중요한 발견: 그 루프가 이 머신에서 켜져 있지 않다.** devtrail
   미설치, MCP 미등록, 훅 미활성, Vault에 handoff 0건, Vault git 2개월 정지.
   `write_work_plan` / `write_session_process` / `record_agent_improvement`의
   산출물이 Vault에 **한 건도 없다**.
4. final.md가 요구하는 DB·HTTP API·Web UI는 `docs/ai-team-pm-design.md` §6이
   2026-08-25에 **명시적으로 배제 확정**한 목록과 정면 충돌한다. 결정 번복인지
   문서 간 정보 격차인지 사람이 판정해야 한다(§9).
5. 따라서 다음 작업의 1순위는 "무엇을 더 만들까"가 아니라 **"이미 만든 것을
   실제로 켜는 것"**이다. 그 전에 스키마를 늘리면 지금 상황의 반복이 된다.

---

## 1. 검증 방법

| 대상 | 방법 |
|------|------|
| 코드 구조 | `app/**/*.py` 직접 읽기(11,245줄), `pyproject.toml` 의존성 확인 |
| MCP 표면 | `app/mcp_server.py` · `app/vault_tools.py` 전문 |
| Vault 실태 | `find` / `ls`로 폴더·노트 수 집계, `git log`로 마지막 활동일 |
| 동작 확인 | `devtrail project-briefing .` 실제 실행 |
| 설치 상태 | `Get-Command devtrail`, `claude mcp list`, `pip list` |

---

## 2. 전제 A — Devtrail은 DB·API·UI 제품이 아니다

final.md §12는 "API 구조에서 필요한 **변경**", "UI/Dashboard 구조에서 필요한
**변경**"을 묻는다. 실측 결과 변경할 대상 자체가 없다.

| 항목 | 실제 |
|------|------|
| HTTP API | **0줄** — fastapi/flask/uvicorn/starlette 의존성 없음 |
| DB | **없음** — 저장소는 Obsidian Vault의 마크다운 파일 |
| 웹 UI | **없음** — `dashboard.py`(22KB)는 Textual **TUI 명령 런처** |
| Agent 인터페이스 | MCP stdio **7 tool**(`app/mcp_server.py`) |
| 사람 인터페이스 | Typer CLI 45개 명령 + Telegram bot |

즉 final.md §7·§12가 요구하는 것은 "변경"이 아니라 **신규 제품 축 추가**다.
리팩터링과 신규 개발은 리스크·비용·되돌리기 난이도가 다르므로, 계획서에서
이 둘을 같은 단어로 부르면 안 된다.

---

## 3. 전제 B — Engineering Memory는 이미 절반 이상 있다

final.md §3의 요구와 현재 구현 대조.

| final.md 요구 | 현재 구현 | 상태 |
|---|---|---|
| Project Context | `30_Projects/<P>/Context.md` → `get_project_briefing`이 600자 요약 주입 + `read_note` 안내 | ✅ |
| Decisions (Reason / Rejected) | `record_note(kind=decision)` → `60_Candidates/Decisions` → `promote-candidate` → `30_Projects/<P>/Decisions` | ✅ |
| Work Sessions | `write_session_process` → `60_Candidates/SessionHandoffs/<P>/` + `10_Worklog/Sessions/` | ✅ |
| Learnings | `60_Candidates/Knowledge` + `40_AgentMemory/06_Lessons.md` | ✅ |
| Handoff | Plan/Process 쌍 + 다음 세션 briefing 재주입 + **미짝 Plan 경고** | ✅ 핵심 루프 완성 |
| Tasks (status·agent·worker·related_decision) | `70_Tasks/Active.md` — 오늘/이번 주/언제든지 3구획 개인 todo | ⚠️ 형태 불일치 |
| **Problems / Troubleshooting** | candidate kind 자체가 없음(`_CANDIDATE_DIRS`에 미등록) | ❌ **진짜 공백** |

`app/services/candidate_writer.py:22-28`의 kind 목록이 근거다:
`knowledge` / `decision` / `memory_patch` / `blog_idea` / `career_bullet` /
`session_handoff` — `problem`이 없다.

### final.md보다 앞서 있는 부분

§11-5는 "모든 로그를 Memory라고 부르지 말 것"을 원칙으로 제시하는데,
이미 코드로 구현돼 있다(`app/vault_tools.py:41-49`):

```text
_STABLE_PREFIXES    = 20_Knowledge/ 30_Projects/ 40_AgentMemory/
_CANDIDATE_PREFIX   = 60_Candidates/
_RAW_PREFIXES       = 10_Worklog/ 50_Outputs/ 70_Tasks/
_STATUS_RANK        = stable 0 → candidate 1 → raw 2
_RAW_RESULT_QUOTA   = 3   # 정본·후보가 limit을 채워도 raw에 남기는 자리
```

PR #52(read scope 확장)와 PR #54(raw 몫 보장)가 이 3등급 체계를 완성했다.
`00_Inbox/`는 캡처 노이즈라 read scope에서 의도적으로 제외돼 있다.

### 유지해야 할 설계 (건드리지 말 것)

- **candidate → promote 불변식**: AI는 `60_Candidates/`에만 쓰고, 공식 영역
  승격은 사람이 한다. 코드가 이 경계를 강제한다.
- **인덱스 우선 briefing**: 전문을 매 세션 밀어넣지 않고 요약 + `read_note`
  안내. 토큰 예산 관리의 핵심.
- **같은 세션 재호출 = 파일 갱신**: `write_work_plan` / `write_session_process`가
  새 파일을 만들지 않고 기존 handoff를 갱신한다(`vault_tools.py:714-718`,
  `858-867`). 체크포인트를 여러 번 찍어도 파일이 안 쌓인다.
- **훅 강제**: PreToolUse plan-check(Plan 없이 코드 수정 차단),
  Stop/PreCompact stop-process-check(기록 없이 종료 차단).
- **프롬프트 외부화**: `app/prompts/*.md` — 코드에 하드코딩하지 않는다.

---

## 4. 전제 C — 그런데 그 루프가 켜져 있지 않다

final.md는 "이 구조가 돌고 있다"를 암묵 전제한다. 실측은 반대다.

### 4-1. 설치·등록 상태

```text
$ claude mcp list
claude.ai Figma / Google Calendar / Google Drive / Notion / Gmail
→ devtrail-vault 없음

PS> Get-Command devtrail
→ devtrail NOT on PATH

$ .venv/Scripts/python.exe -m pip list | grep -iE "devtrail|mcp|pytest"
→ (없음). 설치된 것은 python-frontmatter / textual / typer 3개뿐

$ python -m pytest -q
→ 36 errors during collection (ModuleNotFoundError: frontmatter …)

$ ls .claude/settings.json .claude/vault.json
→ 둘 다 없음
```

`.claude/settings.json`이 없다 = plan-check · session-start-briefing ·
stop-process-check 훅이 **전부 비활성**이다. 기록 누락을 막는 유일한 강제
장치가 꺼져 있다.

`.claude/vault.json`이 없다 = 이 repo가 어느 Vault 프로젝트인지 매핑이 없다.

### 4-2. 그 결과 briefing이 빈 값을 반환한다

```text
$ devtrail project-briefing .
확신할 수 있는 프로젝트 매칭이 없습니다. 아래 후보 중 하나를 확정하면
`.claude/vault.json`에 저장해 다음 세션에서 같은 질문을 반복하지 않을 수 있습니다.

(등록된 프로젝트 없음)
```

Devtrail 자신의 repo에서 Devtrail의 핵심 tool이 아무것도 돌려주지 못한다.

원인 체인:

1. `.claude/vault.json` 없음 → `_load_project_config`가 빈 값 반환
2. → repo 디렉터리명 `work-agent`로 폴백
3. → `ProjectMemoryLoader.find("work-agent")` — Vault에는 `WorkAgent` 폴더가
   있지만 그 안에 `Context.md`가 없어 컨텍스트로 로드되지 않음
4. → `60_Candidates/SessionHandoffs/` 폴더가 없어 handoff 폴더명 매칭도 실패
5. → `matched=False`, 후보 목록도 비어 있음

### 4-3. Vault 실태

```text
60_Candidates/
  BlogIdeas       4
  CareerBullets  23      ← 검토 대기 적체
  Decisions       5
  Knowledge      10
  SessionHandoffs  폴더 자체가 없음   ← write_session_process 산출물 0건
  MemoryPatches    폴더 자체가 없음   ← record_agent_improvement 산출물 0건

40_AgentMemory/  00~05만 존재. 06_Lessons.md 없음
                 ← agent_execution_notes가 증류될 착지점이 없다

30_Projects/     WorkAgent/ 하나(구 이름). Context.md 없이 md 1개
10_Worklog/Sessions/  8건 (구 capture-session 경로 산출물)

$ git -C personal-vault log --oneline -3
726ef66 auto: vault sync 2026-07-03 11:48
1be266e auto: vault sync 2026-07-03 11:38
2d12133 auto: vault sync 2026-07-03 10:18
→ 마지막 활동 2026-07-03. 오늘(2026-09-02) 기준 2개월 정지
```

대조: devtrail repo는 2026-08-25~27에 PR #48~#54와 설계 문서 3건을 머지했다.

> **2개월 동안 기억 인프라를 만들면서 기억을 한 건도 남기지 않았다.**
> 그 2개월치 작업 맥락은 git 커밋과 `docs/`에만 있고, 그것이 정확히
> Devtrail이 대체하려던 저장소다.

---

## 5. 재프레이밍

final.md가 던진 질문:

> "이 비전에 맞게 Devtrail을 어떻게 발전시킬까?"

실측이 가리키는 질문:

> **"이미 완성된 메모리 루프를, 만든 사람 자신이 왜 쓰지 않았는가?"**

전자의 답은 "DB·API·UI를 추가한다"이고, 후자의 답은 "설치·훅·진입 마찰을
없앤다"다. **전자를 먼저 하면 안 쓰이는 시스템 위에 안 쓰일 UI를 얹는 것**이
된다. handoff가 0건인 상태에서 Sessions 페이지를 만들면 빈 화면이 나온다.

원인 가설(검증은 사용자만 가능):

- **설치 마찰**: `pip install -e .` → PATH 등록 → `claude mcp add` 3단계가
  머신마다 반복되고, 이 머신에서는 끝까지 가지 않았다.
- **검토 병목**: CareerBullets 23건이 promote되지 않고 적체 → 후보를 만들수록
  사람 부담이 늘어 루프 자체를 회피하게 된다.
- **가치 미체감(닭-달걀)**: 기록이 0건이면 briefing이 빈 값을 반환하고,
  첫 세션부터 "쓸모없다"는 신호를 받는다. 초기 시드가 없으면 루프가 시작되지
  않는다.

이 세 가설은 각각 다른 처방을 낳는다 — 설치 자동화 / 승격 부담 축소 /
초기 시드 주입. **어느 것이 진짜인지 모른 채 기능을 추가하면 안 된다.**

---

## 6. final.md §12의 10개 질문 답변

1. **현재 구조**: Typer CLI(45 명령) + Textual TUI + Telegram bot + MCP 7 tool.
   계층은 `agents/`(LLM 오케스트레이션) / `services/`(순수 로직, LLM 비의존) /
   `models/`(dataclass) / `memory/`(로더) / `llm/`(provider 추상화·task 라우팅·
   폴백 체인) / `prompts/`(md 템플릿). 저장소는 Vault 마크다운 8폴더.
   테스트 43파일.
2. **비전 대응률**: §3 엔티티 5/7 · §4 tool 루프 완성 · §5 책임 분리 문서로
   확정(`ai-team-pm-design.md` §2) · §7 UI 0% · §11 원칙 대부분 이미 준수.
3. **유지할 것**: §3 후단 "유지해야 할 설계" 참조.
4. **비전과 충돌·중복**:
   (a) `dashboard.py` TUI와 §7 Dashboard는 목적이 다르다(명령 런처 vs 상태 뷰).
   둘 다 유지하면 "Dashboard"라는 이름이 두 개가 된다.
   (b) DB·API·UI 요구가 `ai-team-pm-design.md` §6 배제 목록과 충돌(§9).
   (c) §7의 Agents/Workers 페이지가 §5의 orchestration 경계를 깬다(§8).
5. **없는 핵심 기능**: Problem 엔티티 / 프로젝트 1급 Task / 읽기 전용 조회 tool
   (`get_recent_sessions`·`get_decisions`·`get_known_problems`) / 노드·에이전트
   식별자.
6. **데이터 모델 확장**: frontmatter에 `host` · `agent` · `component` ·
   `cause_class`. **지금 안 넣으면 과거 기록에 소급이 안 된다** — 가장 싸고
   가장 되돌리기 어려운 항목이라 NOW에 둔다.
7. **API 구조**: 변경이 아니라 신규(§2). 대부분은 MCP tool 추가로 해결되고,
   HTTP는 §9 결정 사항.
8. **UI 구조**: §9 결정 전까지 착수 보류 권고.
9. **Agent integration 인터페이스**: 조회 tool 3종 추가 시 에이전트 왕복이
   3~4회 → 1회. 현재는 `search_vault` + `read_note` 조합으로 매번 재구성해야
   한다.
10. **구현 순서**: §7.

---

## 7. NOW / NEXT / LATER

### NOW — 루프를 켠다 (코드 변경 거의 없음, 1~2세션)

| # | 항목 | 완료 판정 |
|---|------|-----------|
| N1 | `.venv` 재설치(`pip install -e ".[dev]"`) → PATH 등록 → `claude mcp add devtrail-vault -- devtrail mcp-serve` | `claude mcp list`에 devtrail-vault 표시 · `python -m pytest` 통과 |
| N2 | `devtrail init-vault` 재실행 → `SessionHandoffs/` · `MemoryPatches/` · `06_Lessons.md` 생성 | 폴더·파일 존재 |
| N3 | `.claude/vault.json` + `30_Projects/<P>/Context.md` 작성 | `devtrail project-briefing .`이 Context·Decisions를 **실제로 출력** |
| N4 | `cp .claude/settings.example.json .claude/settings.json` | Edit 시도 시 plan-check 훅 발동 |
| N5 | `problem` candidate kind 추가(+ `component`·`cause_class` frontmatter) | 신규 테스트 |
| N6 | Plan/Process/Decision frontmatter에 `host`·`agent` 필드 | 신규 테스트 |

**N1~N4가 끝나기 전에 N5 이후를 하지 않는다.** 아무도 안 쓰는 시스템에 스키마를
늘리는 것이 지금 상황을 만든 패턴이다.

**N2는 사람 결정이 필요하다.** `init-vault`는 `VAULT_DIRS`에 따라
`30_Projects/Devtrail/`을 새로 만드는데, 기존 `30_Projects/WorkAgent/`가 남아
둘이 공존하게 된다. 폴더 이름 변경·이동은 에이전트가 임의로 하지 않는다(§9-③).

N5의 `component` / `cause_class` frontmatter가 있어야 final.md §10의 집계형
질문("최근 이 프로젝트에서 가장 많이 발생한 문제는?")이 나중에 열린다.
자유 텍스트만 남기면 그 질문은 영원히 LLM 전수 스캔이 된다.

### NEXT — 실사용 2주 뒤 판단 (측정 없이 착수 금지)

- **조회 tool 3종**: `get_recent_sessions` / `get_decisions` /
  `get_known_problems`. final.md §4가 요구한 read 쪽 공백.
- **Task 1급화**: `70_Tasks/Active.md`(개인 todo) → project·status·agent·
  related_decision. 단 §11-7("Git과 역할 중복 금지")의 사촌 문제 — GitHub
  Issues와 중복될 수 있으므로 경계를 먼저 정한다.
- **Activity Collector PR B/C**: sessionizer + nightly 통합. 설계 확정됨
  (`docs/activity-collector-design.md` §9). 커밋 없는 작업 캡처 = §3 Raw 계층을
  실제로 채우는 부분.
- **pm-repo**: `docs/pm-repo-design.md`대로 코드 0줄로 시작. MCP API의 첫 외부
  고객이 되어 품질을 dogfooding으로 검증한다.

**측정 기준: 2주 뒤 Vault에 handoff가 몇 건 쌓였는가.** 0건이면 NEXT를 하지
말고 §5의 세 가설 중 무엇이 진짜인지부터 판정한다.

### LATER — AI 개발팀 구축 이후

- **멀티 노드**: 현재 Vault 동기화는 주기적 git sync이고
  `scripts/mac/sync-vault.sh`는 **충돌 시 중단 + Telegram 알림**이다.
  rpi4·macmini·macbook이 동시에 쓰면 이 구조는 깨진다.
  `activity-collector-design.md` §8의 방향(노드는 로컬 append-only, 중앙이
  Tailscale로 pull)이 맞고, 메모리 엔티티도 같은 모델로 가야 한다.
  **final.md는 이 구조적 한계를 다루지 않는다.**
- **Web UI / HTTP API**: §9-① 결정 후.
- **Semantic search**: 현재는 전수 키워드 스캔(`wiki_service._score_note`).
  노트 수백 개까지는 버틴다. 체감 임계를 넘은 뒤에 도입한다.

---

## 8. final.md 내부의 모순 — Dashboard와 orchestration 경계

§5는 "Devtrail이 직접 모든 Agent를 orchestration하려고 하면 안 된다"고 못
박는다. 그런데 §7 Dashboard는 `Running / Recent Agent Sessions`, `Agents`,
`Workers` 페이지를 요구한다.

"지금 돌고 있는 세션"은 Orca만 아는 **런타임 상태**다. Devtrail이 그것을
표시하려면 Orca와 결합되고, §5의 경계를 스스로 깬다.

해소 경로:

| 안 | 내용 | 대가 |
|----|------|------|
| **(a)** | Devtrail은 "끝난 세션의 기록"만 소유. Dashboard는 Orca 런타임 + Devtrail 기록을 합치는 **제3의 앱** | 경계 유지, 앱이 하나 늘어남 |
| (b) | Devtrail이 read-only ingest endpoint를 열고 Orca가 상태를 push | 앱은 안 늘지만 Devtrail이 런타임 관심사를 갖게 됨 |

**(a)를 권한다.** `ai-team-pm-design.md` §7의 OSS 정체성("devtrail에
orchestration 코드 금지")과도 일치한다.

---

## 9. 사람이 결정해야 할 것

### ① 8/25 결정과의 충돌

`docs/ai-team-pm-design.md` §6은 2026-08-25에 이렇게 확정했다:

> "OmniRoute, HTTP API, PM 전용 UI, ChatGPT 대화 자동 수집, 복잡한 multi-agent
> 협업, agent 성능 학습, 자동 모델 벤치마킹, Knowledge Graph, 새 Vector DB,
> Browser Extension, 범용 Task Manager, 새 Memory DB — **전부 제외**"

final.md는 이 배제 목록의 절반을 다시 요구한다. 셋 중 무엇인가:

- **(a) 의도적 번복** → 번복 이유를 Decision으로 남겨야 한다. 그래야 다음
  세션이 "왜 두 문서가 다른가"를 다시 묻지 않는다.
- **(b) 정보 격차** — final.md가 그 문서를 모르고 쓰였다 → 두 문서를 정합시킨다.
- **(c) 시간축 차이** — final.md는 LATER 비전이고 8/25 결정이 NOW로 유효하다
  → §7 계획이 그대로 맞다.

### ② Dashboard 소유권

§8의 (a) 별도 앱 / (b) Devtrail 확장 중 어느 쪽인가.

### ③ `30_Projects/WorkAgent` → `Devtrail`

폴더 이름을 옮길지, 둘 다 둘지. 파일 이동·삭제는 사용자 승인 없이 하지 않는다.

---

## 10. 이 문서의 한계

- **머신 1대 기준이다.** macmini·rpi4의 설치·Vault 상태는 확인하지 않았다.
  다만 Vault가 공용 git repo(`WhiteJbb/personal-vault`)이고 마지막 sync가
  2026-07-03이라, 다른 노드에서 활발히 기록 중일 가능성은 낮다고 본다.
- **테스트를 실행하지 못했다.** `.venv`에 pytest·mcp가 없고 시스템 python은
  3.10(프로젝트 요구 3.11+)이라 43개 테스트 파일의 통과 여부는 **미확인**이다.
  코드 건강 상태에 대한 판단은 이 문서에 없다.
- **§5의 원인 가설 3개는 검증되지 않았다.** 왜 루프를 안 썼는지는 사용자만
  안다. 처방이 가설마다 다르므로, NOW N1~N4를 켜본 뒤 실제 행동으로 판별하는
  것을 전제로 한다.
- 이 문서의 설계 판단도 `pm-repo-design.md` §0의 교훈을 따른다 —
  **"이것만 고치면 됨"은 실제로 돌려보기 전까지 가설이다.**
