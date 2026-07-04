# Goal Agent 도입 계획 — CLI 자동화에서 목표 기반 실행 루프로

작성일: 2026-07-01
관련 논의: `docs/vault-ai-integration.md`(브리핑 파일), `docs/architecture.md`(Vault/파이프라인 원본 설계)

---

## 0. 이 문서가 다시 짚는 전제

원래 제안(대화에서 받은 구조)은 "지금은 Level 0 CLI 자동화이고, Agent가 되려면 Observe→Plan→Act→Verify→Reflect→Persist 루프와 `VaultGateway`/`VaultPolicy`, `app/agent_runtime/`, `app/tools/`를 새로 만들어야 한다"는 그림이었다. 코드를 실제로 읽어보면 두 가지가 다르다.

1. **이미 Level 1은 구현돼 있다.** `app/assistant/assistant.py`의 `Assistant.interpret()`/`execute()`가 자연어 → intent 분류 → 기존 Agent 실행을 하고 있고, `serve-bot`/`ask` 명령이 이를 쓴다. "자연어 라우터"는 새로 만들 게 아니라 이미 있는 걸 목표 기반 실행의 기반으로 재사용하면 된다.
2. **"쓰기 경계" 강제는 이미 존재한다.** `CandidateWriter`는 `60_Candidates/` 바깥에 쓰지 못하게 생성자 수준에서 막아뒀고(`app/services/candidate_writer.py`), `CuratorAgent.promote_candidate`/`apply_memory_patch`가 `20_Knowledge`/`30_Projects`/`40_AgentMemory`로의 유일한 반영 경로다. 새 `VaultGateway`/`VaultPolicy` 클래스를 또 만들면 이 로직을 중복 구현하게 된다. → **새로 만들지 않고, 기존 경계를 그대로 상속받는 쪽으로 설계를 바꾼다.**

그래서 이 문서는 "완전히 새로운 런타임을 만드는 계획"이 아니라, **"이미 있는 Agent들을 tool로 감싸는 얇은 오케스트레이션 레이어 하나를 추가하는 계획"**이다. 이렇게 범위를 좁히면 첫 번째 목표("포트폴리오 정리")는 새 LLM 판단 로직이 거의 없이도 동작한다.

### 사람이 결정할 부분 vs AI가 채울 부분

- **사람이 정할 것**: 어떤 goal을 1차로 지원할지, `--approve` 없이 실행해도 되는 위험도 기준, plan 미리보기를 CLI로만 볼지 Telegram에도 노출할지, LLM Planner를 언제부터 붙일지(고정 recipe로 시작 vs 처음부터 자유 planner).
- **AI/코드가 할 것**: 기존 Agent 시그니처 조사, tool registry 매핑, AgentRun 마크다운 생성, self-check 규칙, 테스트 작성.

아래 계획은 이 구분을 전제로 "AI가 할 것" 위주로 구체화했고, 사람이 정할 부분은 8장에 별도로 모아뒀다.

---

## 1. 목표

```
work-agent run-goal "<목표>"            # 실행 계획만 출력 (파일 생성 없음)
work-agent run-goal "<목표>" --approve  # 계획대로 실행, AgentRun 기록 저장
```

목표 문자열을 받으면:

1. 관련 프로젝트/컨텍스트를 읽고 (Observe)
2. 어떤 기존 Agent를 어떤 순서로 부를지 계획을 세우고 (Plan)
3. `--approve`가 있을 때만 실제로 실행하고 (Act)
4. 결과물이 source 기반인지, 쓰기 경계를 넘지 않았는지 확인하고 (Verify)
5. 이번 실행에서 부족했던 부분을 정리하고 (Reflect)
6. `50_Outputs/AgentRuns/`에 실행 기록을 남긴다 (Persist)

---

## 2. 왜 새 모듈이 최소화될 수 있는가 — 기존 자산 매핑

| 루프 단계 | 원래 제안 | 실제로 쓸 것 |
|---|---|---|
| Observe | 새 `state.py`가 Vault 전체를 읽음 | `ContextPackBuilder.build(topic)` — 이미 AgentMemory + ProjectContext + 관련 노트를 모아 `ContextPack`으로 반환함 (`app/memory/context_pack_builder.py`) |
| Plan | LLM planner 신규 구현 | 1차는 **고정 recipe 매핑**(아래 5장), 2차는 `Assistant.interpret()`와 동일한 `complete_json` 패턴으로 LLM planner 추가 |
| Act | `executor.py` + `tools/*.py` 신규 | 기존 `ProjectAgent`, `CareerBulletAgent`, `OpenLoopsAgent`, `CaptureAgent` 등을 그대로 호출하는 `ToolRegistry` 딕�셔너리 하나 |
| Verify | `verifier.py` 신규 | 규칙 체크(쓰기 경로가 tool의 선언된 scope 안인지) + LLM self-check 1회 |
| Reflect | `reflector.py` 신규 | Verify 결과 + 실행 로그를 요약하는 짧은 LLM 호출 (별도 모듈 불필요, `loop.py` 안 함수로 충분) |
| Persist | `state.py`의 AgentRun 모델 | `ProjectAgent._save()`와 동일한 패턴으로 `50_Outputs/AgentRuns/`에 markdown 저장 |
| 안전 경계 | `VaultGateway`/`VaultPolicy` 신규 클래스 | `CandidateWriter`(60_Candidates 전용 쓰기) + `CuratorAgent`(승격 전용 경로) 그대로 재사용. run-goal은 이 두 경계를 우회하는 tool을 등록하지 않는다 |

결론: 새로 만드는 코드는 "tool 목록 정의 + 실행 루프 + AgentRun 기록"뿐이다.

---

## 3. 새 모듈 구조

```
app/agent_runtime/
├── __init__.py
├── registry.py     # TOOL_REGISTRY: 이름 → ToolSpec(호출 함수, 인자 스키마, write_scope)
├── planner.py       # goal → Plan(고정 recipe 매칭 우선, 없으면 LLM fallback)
├── executor.py       # Plan을 순서대로 실행, 각 단계 결과를 ToolResult로 수집
├── verifier.py       # ToolResult 목록 → SelfCheck (규칙 + LLM)
├── loop.py           # run_goal(goal, approve) — 위 모듈을 엮는 진입점, reflect도 여기서 처리
└── state.py          # AgentRun 데이터클래스 + markdown 저장 (ProjectAgent._save 패턴 재사용)
```

`app/tools/` 디렉터리는 만들지 않는다. tool은 기존 `app/agents/*.py` 클래스이고, `registry.py`는 그것들을 감싸는 매핑일 뿐 새 비즈니스 로직을 담지 않는다.

### 3a. `registry.py` — ToolSpec

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    call: Callable[..., Any]          # 예: lambda project: ProjectAgent().portfolio_draft(project)
    write_scope: tuple[str, ...] | None  # None이면 읽기 전용. 예: ("50_Outputs/Portfolio/",)
    description: str                   # planner/사용자 미리보기에 쓸 한 줄 설명

TOOL_REGISTRY: dict[str, ToolSpec] = {
    "build_context": ToolSpec("build_context", ..., write_scope=None, ...),
    "portfolio_draft": ToolSpec("portfolio_draft", ..., write_scope=("50_Outputs/Portfolio/",), ...),
    "interview_questions": ToolSpec("interview_questions", ..., write_scope=("50_Outputs/Interview/",), ...),
    "suggest_career_bullets": ToolSpec("suggest_career_bullets", ..., write_scope=("60_Candidates/CareerBullets/",), ...),
    "update_open_loops": ToolSpec("update_open_loops", ..., write_scope=("60_Candidates/MemoryPatches/",), ...),
    "capture_session": ToolSpec("capture_session", ..., write_scope=("10_Worklog/Sessions/",), ...),
    "list_candidates": ToolSpec("list_candidates", ..., write_scope=None, ...),
}
```

**중요한 제약**: `20_Knowledge/`, `30_Projects/`, `40_AgentMemory/`로 직접 쓰는 tool은 등록하지 않는다. run-goal이 만들 수 있는 결과물은 항상 `50_Outputs/*`(바로 쓰는 결과물, 기존 Generate 단계와 동일한 성격) 또는 `60_Candidates/*`(사람이 `promote-candidate`/`apply-memory-patch`로 승격해야 하는 후보)뿐이다. CLAUDE.md의 후보 흐름 규칙과 완전히 일치시키는 게 목적이라 이 부분은 예외를 두지 않는다.

### 3b. `planner.py` — recipe 우선, LLM은 나중

```python
GOAL_RECIPES: dict[str, list[str]] = {
    "portfolio": ["build_context", "portfolio_draft", "suggest_career_bullets", "interview_questions", "update_open_loops"],
}

def plan(goal: str) -> Plan:
    intent = _match_recipe(goal)   # 키워드 매칭: "포트폴리오" in goal → "portfolio"
    if intent:
        return Plan(goal=goal, steps=[Step(tool=t, args=_extract_args(goal)) for t in GOAL_RECIPES[intent]])
    # recipe가 없으면 LLM planner로 fallback (2단계에서 추가, 1단계는 미지원 goal로 안내만)
    raise UnsupportedGoalError(goal)
```

`_extract_args`가 goal 문자열에서 프로젝트명을 뽑아야 하는데, 이건 `Assistant.interpret()`가 이미 하는 일(LLM으로 `arg` 추출)과 동일한 문제다. 새로 만들지 말고 `render_prompt("intent_route", ...)` 대신 별도의 짧은 프롬프트(`run_goal_extract_args.md`) 하나만 추가해서 `complete_json`으로 처리한다.

1단계에서는 recipe 1개(포트폴리오 정리)만 지원하고, 매칭 안 되는 goal은 "아직 지원하지 않는 목표입니다. 지원 목표: 포트폴리오 정리"로 안내한다. LLM 자유 planner는 recipe가 2~3개로 늘어나 패턴이 보일 때 추가한다(과설계 방지).

### 3c. `executor.py`

```python
def execute(plan: Plan) -> list[ToolResult]:
    results = []
    for step in plan.steps:
        spec = TOOL_REGISTRY[step.tool]
        try:
            output = spec.call(**step.args)
            results.append(ToolResult(tool=step.tool, ok=True, output=output))
        except Exception as e:
            results.append(ToolResult(tool=step.tool, ok=False, error=str(e)))
            break  # 이후 단계는 앞 단계 결과에 의존하므로 중단
    return results
```

### 3d. `verifier.py` — 규칙 체크 + LLM self-check

규칙 체크(코드로, LLM 불필요):
- 각 `ToolResult.output`이 가진 `path`/`rel_path`가 해당 tool의 `write_scope` 접두사로 시작하는가
- 실패한 step이 있는가 (있으면 self-check에 "미완료"로 명시)

LLM self-check(1회 호출, `run_goal_selfcheck.md` 프롬프트, 기존 `career_bullets.md` 등과 같은 형식):
- source_refs에 없는 수치·성과가 본문에 등장하는가
- 목표(goal)와 관련 없는 내용이 섞였는가

출력은 체크리스트 문자열 그대로 AgentRun에 포함한다(사람이 검토할 근거).

### 3e. `state.py` — AgentRun 저장

경로: `50_Outputs/AgentRuns/{YYYYMMDD-HHMMSS}-{slug}.md` (slug는 `ProjectAgent._save`의 `project.lower().replace(" ", "-")`와 동일한 방식)

```markdown
---
type: AgentRun
status: completed | failed | partial
goal: XCoreChat 포트폴리오 정리
created: 2026-07-01T21:40:00
tools_used: [build_context, portfolio_draft, suggest_career_bullets, interview_questions, update_open_loops]
outputs:
  - 50_Outputs/Portfolio/20260701-portfolio-xcorechat.md
  - 60_Candidates/CareerBullets/xcorechat-rag-검색-구조.md
---

# Agent Run: XCoreChat 포트폴리오 정리

## Plan
1. build_context(XCoreChat)
2. portfolio_draft(XCoreChat)
3. suggest_career_bullets(XCoreChat)
4. interview_questions(XCoreChat)
5. update_open_loops()

## Execution Log
- build_context ✅
- portfolio_draft ✅ → 50_Outputs/Portfolio/20260701-portfolio-xcorechat.md
- suggest_career_bullets ✅ → 60_Candidates/CareerBullets/xcorechat-rag-검색-구조.md (1건)
- interview_questions ✅ → 50_Outputs/Interview/20260701-interview-xcorechat.md
- update_open_loops ✅ → 후보 없음(추가할 이슈 없음)

## Self Check
- [x] source 기반 작성 확인 (source_refs 5건)
- [x] write_scope 위반 없음
- [ ] 실제 운영 화면 캡처는 컨텍스트에 없어 반영되지 않음 — 사람 확인 필요

## Next Actions
- 60_Candidates/CareerBullets/ 검토 후 promote-candidate 실행
- 운영 화면 캡처 추가 후 portfolio_draft 재실행 검토
```

`wiki_service.append_vault_log("run-goal", goal, outputs)`도 기존 관례대로 호출해서 `log.md`에 흔적을 남긴다.

---

## 4. CLI 추가 (`app/cli.py`)

기존 명령 스타일(`@app.command("build-context")` 등)과 동일하게:

```python
@app.command("run-goal")
def run_goal(
    goal: str = typer.Argument(..., help="달성하려는 목표, 예: 'XCoreChat 포트폴리오 정리해줘'"),
    approve: bool = typer.Option(False, "--approve", help="계획을 실제로 실행. 없으면 계획만 출력"),
) -> None:
    ...
```

동작:
- `--approve` 없음: `planner.plan(goal)` 결과만 사람이 읽을 수 있게 출력 (tool 이름 + 설명 + write_scope), 파일 생성 없음
- `--approve` 있음: `executor.execute()` → `verifier.check()` → AgentRun 저장 → 저장 경로와 self-check 요약 출력

Telegram `/goal` 노출은 1단계에서는 하지 않는다(8장 참고 — 이건 사람이 정할 결정 항목).

---

## 5. 첫 번째 지원 Goal — "프로젝트 포트폴리오 정리"

이 goal을 1차로 고른 이유: 필요한 모든 tool(`ProjectAgent`, `CareerBulletAgent`, `OpenLoopsAgent`)이 이미 구현돼 있고 테스트도 있다(`test_project_agent.py`, `test_career_bullet_agent.py`, `test_open_loops_agent.py`). 즉 이 goal은 **새 Agent 로직을 하나도 추가하지 않고** 오케스트레이션만으로 동작 검증이 가능하다.

```bash
work-agent run-goal "XCoreChat 포트폴리오 정리해줘"            # 계획 미리보기
work-agent run-goal "XCoreChat 포트폴리오 정리해줘" --approve  # 실행
```

recipe: `["build_context", "portfolio_draft", "suggest_career_bullets", "interview_questions", "update_open_loops"]`

---

## 6. 안전 정책 (기존 정책 상속, 신규 규칙 최소화)

1. `TOOL_REGISTRY`에 `20_Knowledge/`, `30_Projects/`, `40_AgentMemory/` 쓰기 tool을 등록하지 않는다 — 코드 리뷰 시 이 한 줄만 확인하면 됨.
2. 모든 write는 반드시 `write_scope`가 선언된 tool을 통해서만 일어난다. `verifier.py`가 선언된 scope와 실제 결과 경로를 대조한다.
3. 삭제 동작을 하는 tool은 등록하지 않는다(`CuratorAgent.delete_candidate` 등은 registry에서 제외).
4. `capture_session` 같은 외부 전송성(텔레그램 알림 등) tool은 이번 1차 registry에는 넣지 않는다 — 필요해지면 별도 승인 규칙과 함께 추가.
5. `--approve` 없는 기본 실행은 파일을 전혀 만들지 않는다(순수 조회 + LLM 계획 생성만).

---

## 7. 구현 순서

| Phase | 내용 | 완료 기준 |
|---|---|---|
| 1 | `app/agent_runtime/registry.py` — 읽기 전용 tool 2개(`build_context`, `list_candidates`)만 등록, 단위 테스트 | `pytest tests/test_agent_runtime_registry.py` 통과 |
| 2 | `planner.py` — `portfolio` recipe 1개, 인자 추출 프롬프트 추가 | goal 문자열 → Plan 변환 테스트 |
| 3 | `executor.py` + `verifier.py` — 나머지 4개 tool 등록, self-check 규칙 | mock Agent로 실행 흐름 테스트 |
| 4 | `state.py` + `loop.py` — AgentRun 저장, `run-goal` CLI 연결 | `work-agent run-goal "..." --approve` 실제 vault(테스트용 tmp_path)로 e2e |
| 5 | `docs/feature-reference.md`/`docs/implementation-status.md` 갱신 | 문서에 `run-goal` 반영 |

각 Phase는 독립적으로 머지 가능하다. Phase 1~2만으로도 "계획 미리보기"는 동작하므로, 실행(Act)까지 가기 전에 먼저 사람이 계획 출력 형식을 검토할 수 있다.

브랜치: CLAUDE.md 규칙상 새 Agent/CLI 커맨드이므로 `feat/run-goal-agent` 브랜치에서 작업.

---

## 8. 사람이 결정해야 할 것 (AI가 대신 정하지 않음)

- **Planner 시작점**: recipe 고정 매핑으로 시작(이 문서의 제안) vs 처음부터 LLM 자유 planner. 후자는 유연하지만 "계획에 없던 tool을 호출"하는 리스크를 1단계부터 안게 됨.
- **plan 미리보기 노출 범위**: CLI에만 둘지, Telegram `/goal`에도 붙일지. 봇에 붙이면 모바일에서 승인까지 가능해지지만 승인 UX(버튼? 텍스트 재입력?)를 새로 설계해야 함.
- **`--approve` 기본값**: 항상 명시적으로 켜야 하는 현재 설계 유지 vs 특정 저위험 goal(읽기만 하는 것)은 자동 승인. 후자는 편하지만 "AI가 뭘 했는지 항상 기록으로 확인 가능해야 한다"는 원래 취지와 충돌할 수 있음.
- **2번째 지원 goal**: "이번 주 작업 정리해서 포트폴리오 반영"(`CareerBulletAgent` + 날짜 필터 조합)과 "발표 준비"(`ProjectAgent` + 신규 프롬프트) 중 어느 쪽을 recipe 2번으로 만들지는 실제 사용 빈도를 보고 정하는 게 나음 — 지금은 근거 데이터가 없음.

---

## 9. 관련 파일

- [app/memory/context_pack_builder.py](../app/memory/context_pack_builder.py) — Observe에 재사용
- [app/services/candidate_writer.py](../app/services/candidate_writer.py) — 60_Candidates 쓰기 경계, 신규 gateway 대신 재사용
- [app/agents/curator_agent.py](../app/agents/curator_agent.py) — 20_Knowledge/30_Projects/40_AgentMemory 반영의 유일한 경로
- [app/agents/project_agent.py](../app/agents/project_agent.py) — portfolio_draft/interview_questions/summarize_project tool
- [app/agents/career_bullet_agent.py](../app/agents/career_bullet_agent.py) — suggest_career_bullets tool
- [app/agents/open_loops_agent.py](../app/agents/open_loops_agent.py) — update_open_loops tool
- [app/assistant/assistant.py](../app/assistant/assistant.py) — 인자 추출 패턴(`complete_json` + intent) 참고
- [app/cli.py](../app/cli.py) — `run-goal` 명령 등록 위치
- [docs/implementation-status.md](./implementation-status.md) — 완료 후 반영
- [docs/vault-ai-integration.md](./vault-ai-integration.md) — 별개 작업(브리핑 파일)이지만 같은 `40_AgentMemory` 경로 이슈를 다룸
