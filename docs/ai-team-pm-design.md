# AI 개발팀 PM 설계 검토 — Devtrail을 Shared Project Memory로

> 작성: 2026-08-25. `dev` 브랜치 코드(`app/vault_tools.py`, `app/mcp_server.py`,
> `app/services/candidate_writer.py`, `app/llm/router.py`, `app/assistant/` 등)를
> 실제로 읽고 검증한 설계 검토다. 목표는 기능 추가가 아니라 **"프로젝트에 대해
> 계속 대화하며 생각을 바꿔도, AI 팀이 결정의 이유를 기억하고 다음 작업을
> 이어가는 경험"**을 가장 단순한 구조로 만드는 것.

## 0. 핵심 결론

1. Devtrail은 Shared Project Memory 역할에 **이미 거의 맞다**. 새 메모리
   시스템은 만들지 않는다.
2. 단, "read broadly, write narrowly" 중 read 쪽이 현재 코드와 불일치 —
   read scope가 `20_Knowledge/30_Projects/40_AgentMemory/60_Candidates`로
   좁아서 `10_Worklog/`(세션 원문)·`50_Outputs/`를 못 본다. **이것이 devtrail
   쪽 유일한 필수 변경이다.**
3. PM은 새 앱으로 만들지 않는다. **Claude Code 세션 자체를 PM으로** 쓰고,
   PM repo는 규약(CLAUDE.md) + MCP 연결 + 위임 스킬만 담는 얇은 repo로 시작한다.
4. OmniRoute·HTTP adapter·multi-agent 협업·성능 학습은 MVP에서 제외한다.

## 1. 현재 코드 진단

### 이미 구현된 것 (전면 재사용)

- **MCP 7 tools** (`app/mcp_server.py`, `app/vault_tools.py`):
  `get_project_briefing` / `search_vault` / `read_note` / `record_note` /
  `record_agent_improvement` / `write_work_plan` / `write_session_process`.
  PM에게 필요한 기억 인터페이스가 이미 전부 있다.
- **briefing이 "다음 세션 recall" 문제를 이미 푼다**: Context 요약(600자 +
  read_note 안내), Recent Decisions(검토 대기 후보 + 승격 정본 병합), 최근
  handoff 3건 발췌(Next Session 우선), OpenLoops/Lessons tail 주입, Context·
  Memory 신선도 경고, 미짝 Plan 경고, orphan plan 재귀속(`vault_tools.py:316`).
- **Candidate/Promote 흐름**: `CandidateWriter`(유사도 dedup, thread merge) +
  CLI `list-candidates`/`promote-candidate`/`apply-memory-patch`. "AI는 후보만
  만들고 사람이 승격"이라는 불변식이 코드로 강제된다.
- **checkpoint 기록에 최적화된 semantics**: `write_work_plan`/`write_session_process`를
  같은 세션이 재호출하면 새 파일 없이 기존 handoff를 갱신한다
  (`vault_tools.py:714-718`, `858-867`). 대화 중 여러 번 기록해도 파일이 안 쌓인다.
- **Decision 자동 분리**: process의 `project_decisions.final_judge`가 확정이면
  Decision candidate가 자동 생성된다(`vault_tools.py:885-903`). "고려한 대안"
  필드가 있어 버린 대안·이유를 남기는 자리도 이미 있다.
- **멀티 프로젝트 매칭**: `get_project_briefing`은 repo 경로(`.claude/vault.json`)
  뿐 아니라 프로젝트명 직접 전달도 매칭한다 — PM이 pm-repo cwd에서 여러
  프로젝트의 briefing을 이름으로 호출할 수 있다.

### 현재 설계와 충돌하는 것

1. **read scope가 좁다**: `_ALLOWED_READ_PREFIXES`(`vault_tools.py:40-42`)가
   `20/30/40/60`만 허용. PM이 "지난주에 뭐 했지"를 물으면 briefing의 handoff
   발췌 3건 이상을 볼 수 없다. `search_vault`도 같은 prefix로 필터링된다.
2. **세션 = 코딩 세션 전제**: Process 필드가 what_changed/files_touched 중심이라
   논의만 한 PM 세션엔 어색하다. 치명적이진 않음 — 자유 텍스트 필드라 논의
   요약으로 유연하게 채울 수 있다.
3. **session_id = MCP 서버 프로세스 수명**(`mcp_server.py:26`): PM이 한 Claude
   Code 세션을 며칠 쓰면 handoff 하나에 계속 덮어쓴다. "새 대화 스레드 = 새
   Claude Code 세션" 운영 습관으로 흡수한다.

### 변경이 필요한 최소 영역

- `_ALLOWED_READ_PREFIXES`에 `10_Worklog/`·`50_Outputs/` 추가
  (+ `_status_of`에 라벨, 테스트). write scope는 손대지 않는다.
  `00_Inbox/`는 캡처 노이즈라 우선 제외, `70_Tasks/`는 필요 확인 후.
- (조건부, 후순위) discussion형 handoff 필드 — Process 필드 유용(流用)이
  실사용에서 어색하다고 확인된 뒤에만 tool 추가를 검토한다.

## 2. 최종 책임 분리

| 구성요소 | 책임 | 하지 않는 것 |
|---|---|---|
| **Devtrail** | 무엇을 아는가 — Vault 스키마, MCP tools, candidate/promote, distill 파이프라인 | orchestration, agent 라우팅, PM 대화 저장 |
| **PM** (= Claude Code 세션 + PM 규약) | 사용자 대화 창구. briefing 조회, 대안 정리, 결정·미결 체크포인트 기록, task brief 작성, 위임, 결과 설명 | 코드 직접 수정(원칙), vault 파일 직접 접근(MCP만 사용) |
| **Claude Code (실행)** | 프로젝트 repo에서 설계·구현·리뷰. 자체적으로 briefing 조회, plan/process 기록(훅이 강제) | — |
| **Codex** | PM 판단으로 위임받는 구현·진단 (기존 codex plugin/CLI 경유) | vault 직접 쓰기 (필요 시 결과를 PM이 기록) |
| **OmniRoute류** | **MVP 제외.** agent CLI들이 자체 구독·인증·도구 실행 환경을 갖고 있어 API 라우터를 끼우면 하네스를 재구현해야 한다. devtrail 내부 LLM은 이미 FallbackChain 보유 | — |
| **GitHub** | 정본 코드·PR·리뷰 기록. 실행 에이전트가 AGENTS.md 규칙대로 직접 조작 | — |
| **CI/Test** | 실행 에이전트 책임(`python -m pytest` 통과 후 보고). PM은 결과 수신·요약만 | — |

## 3. 최소 아키텍처

PM 앱을 만들지 않는다. Claude Code가 이미 PM 하네스다 — MCP 클라이언트
(devtrail 연결), 서브에이전트 호출, Codex 위임(설치된 codex plugin), 대화
transcript 자동 보존, 스킬 시스템. 부족한 것은 코드가 아니라 **역할 규약**뿐이다.

```
pm-repo/  (신규, 아주 얇게)
├── CLAUDE.md        ← PM 행동 규약 (체크포인트 규칙, brief 양식)
├── .mcp.json        ← devtrail-vault (devtrail mcp-serve)
└── skills/          ← 선택: delegate-task (brief 작성 → claude -p / codex exec)
```

- 사용자는 pm-repo에서 Claude Code를 연다 = PM과 대화.
- PM은 세션 시작 시 논의 대상 프로젝트명으로 `get_project_briefing`을 호출한다.
- 위임은 headless CLI subprocess: `claude -p "<brief>"`(프로젝트 repo cwd) 또는
  codex. 실행 에이전트는 그 repo의 AGENTS.md + 자기 MCP 세션으로 움직이므로
  PM이 컨텍스트를 싸들고 갈 필요가 없다. **brief에는 결정·제약·수용기준만 담는다.**
- 터미널이 불편해지는 시점(모바일 등)에 얇은 채널(Telegram assistant 확장 등)을
  검토한다 — 지금은 아니다.

## 4. 사용자 Workflow

```
[아이디어] pm-repo에서 Claude Code 열기
→ PM: get_project_briefing("<프로젝트>") — 과거 결정·open loops·최근 handoff 주입
→ 대화: 대안 비교·방향 수정 (필요 시 search_vault / read_note로 과거 근거 조회)
→ 결정 확정 순간: PM이 "결정으로 기록한다" 확인 후 record_note(kind=decision)
→ 미결정 질문: record_agent_improvement (→ MemoryPatches → apply 시 OpenLoops)
→ 논의 일단락: write_session_process (논의 요약·버린 대안·Next Session)
→ "구현해": PM이 task brief 확정 (결정·범위·수용기준·비범위)
→ claude -p / codex exec (프로젝트 repo cwd)
   — 실행 에이전트가 자체 briefing → plan → 구현 → test → PR
→ PM이 결과(PR 링크·테스트 결과) 수신, 사용자에게 설명
→ PM write_session_process 재호출 (같은 파일 갱신) — 위임 결과·후속 open loop 반영
→ [사람] list-candidates → promote-candidate / apply-memory-patch
→ 다음 세션: briefing이 전부 다시 주입
```

버린 대안과 이유는 decision candidate의 "고려한 대안" 필드에 남긴다 —
새 스키마가 필요 없다.

ChatGPT는 Thinking Space로 유지한다. 프로젝트로 발전시킬 내용이 생기면 짧은
handoff 텍스트를 PM 대화에 붙여넣는 것으로 시작하고, 자동 수집 시스템은
만들지 않는다.

## 5. Memory Lifecycle

```
Conversation      = Claude Code transcript (pm-repo 로컬) — Vault에 넣지 않음
Working Context   = PM 세션 컨텍스트 + get_project_briefing 주입분
Decision          = 확정 순간 record_note(decision) → 60_Candidates/Decisions/
Open Loop         = record_agent_improvement → 60_Candidates/MemoryPatches/
Session Handoff   = write_session_process (checkpoint마다 갱신) → SessionHandoffs/<P>/
Candidate → 정본  = 사람이 promote-candidate / apply-memory-patch (기존 그대로)
다음 세션 Recall  = get_project_briefing
                    (Recent Decisions는 후보+정본 병합이라 promote 전에도 보임)
```

전 단계가 기존 코드다. 새로 만드는 것은 **PM이 체크포인트를 지키게 하는
프롬프트 규칙**뿐이다.

원문 대화를 Vault에 넣지 않는 이유: Vault는 curated memory bus다 — raw chat은
크고 반복적이라 distill·search 노이즈만 키운다. 발췌가 필요하면
`30_Projects/<P>/Conversations/`에 사람 요청 시 수동 기록(기존 규칙 그대로).

기록 시점(distill vs checkpoint): 매 턴 distill은 비용·노이즈·중복 후보만
늘린다. **이벤트 기반 checkpoint**로 간다 —
(a) 결정 확정 즉시, (b) 미결 질문 발생 시, (c) 논의 일단락·주제 전환 시,
(d) "구현해" 직전(plan), (e) 위임 완료 시(process 갱신).

## 6. MVP

### 필수 (이것만)

1. **devtrail PR 1개**: read scope에 `10_Worklog/`·`50_Outputs/` 추가 (소, 테스트 포함).
2. **pm-repo 생성**: CLAUDE.md(PM 규약 — briefing 먼저, 결정 즉시 기록,
   checkpoint 규칙, brief 양식) + `.mcp.json`.
3. **위임은 수동으로 시작**: PM이 brief를 만들면 사용자가 실행을 승인하고
   PM이 `claude -p`/codex를 호출한다. 스킬화는 2~3회 반복 후.

### 명시적 후순위

- discussion형 handoff 필드 — Process 필드 유용이 어색하다고 실제로 느낀 뒤에.
- briefing handoff 창(3건)에 discussion/impl 세션이 섞여 밀리는 문제 —
  실사용에서 확인된 뒤 조정.
- OmniRoute, HTTP API, PM 전용 UI, ChatGPT 대화 자동 수집, 복잡한 multi-agent
  협업, agent 성능 학습, 자동 모델 벤치마킹, Knowledge Graph, 새 Vector DB,
  Browser Extension, 범용 Task Manager, 새 Memory DB — 전부 제외.

## 7. Repo 전략

- **devtrail (dev)**: read scope PR만. orchestration·PM 관련 코드는 넣지
  않는다 — 로드맵 Track B-2(Devtrail Core OSS)의 정체성과 일치. PM은 "MCP를
  소비하는 첫 외부 고객"이 되어 MCP API 품질을 dogfooding으로 검증한다.
- **pm-repo (신규)**: 규약·스킬·brief 템플릿. 코드 최소.
- **interface = MCP 7 tools 단 하나.** PM은 vault 파일시스템을 직접 만지지
  않는다. vault 스키마가 부족하면 devtrail 쪽 PR로 풀고, PM이 우회 접근하지
  않는다. 이 경계가 개인용 편의와 OSS 정체성을 동시에 지킨다.

## 8. 13개 질문 평결

1. **현재 구조의 적합성**: 높음 — briefing/handoff/candidate가 핵심 문제를
   이미 푼다. 결함은 read scope 하나.
2. **기존 Vault/MCP/Candidate 재사용 가능?**: 예, 전면 재사용. 신규 메모리
   시스템 0.
3. **read 확대·write 제한 적절한가**: 적절. `10_Worklog/`·`50_Outputs/` 추가,
   write는 현행 유지.
4. **MCP vs HTTP adapter**: MCP 그대로. PM이 Claude Code(또는 이후 Agent SDK)면
   네이티브 지원. HTTP는 표면적·인증·운영 부담만 추가.
5. **PM 대화 저장 위치**: 원문은 로컬 transcript, Vault엔 증류물만.
6. **기록 시점**: 결정 확정 즉시(decision) / 미결 발생 시(open loop) /
   논의 일단락·위임 완료 시(process 갱신) / "구현해" 직전(plan).
7. **매턴 distill vs checkpoint**: checkpoint. `write_session_process`의
   갱신 semantics가 이미 이를 위해 설계돼 있다.
8. **역할 고정 vs 동적**: config 수준의 기본 매핑(Claude=설계·리뷰·복잡 구현,
   Codex=병렬·기계적 작업) + PM 재량. 학습형 라우팅은 만들지 않는다.
9. **subprocess vs OmniRoute/ACP**: headless CLI subprocess. OmniRoute는
   agent 하네스를 대체하지 못한다 — MVP 제외.
10. **GitHub/Worktree/Test/Review/PR 자동화 범위**: 실행 에이전트 책임.
    PM은 지시·수신·요약(+ 가벼운 Issue 생성 정도).
11. **"구현해" workflow**: brief 한 장 → headless 실행 → 실행 측이 자체
    briefing/plan/process. §4 참조.
12. **별도 PM repo?**: 예. 단, 앱이 아니라 규약 repo로.
13. **OSS 경계**: MCP-only 접근 + devtrail에 orchestration 코드 금지.

## 9. 다음 행동

1. read scope PR 범위 확정 — `10_Worklog/`·`50_Outputs/` 우선,
   `00_Inbox/`(노이즈)·`70_Tasks/`는 포함 여부만 결정.
2. pm-repo CLAUDE.md 초안 작성 (PM 규약 + checkpoint 규칙 + brief 양식).
3. 실사용 1~2주 후 후순위 항목(discussion handoff, briefing 창 조정) 재평가.
