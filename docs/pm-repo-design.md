# pm-repo 설계 — AI 개발팀 PM 규약

> 작성: 2026-08-27. `docs/ai-team-pm-design.md`(2026-08-25)의 §6-2를 실제 구현
> 가능한 수준으로 구체화한 문서다. 그 사이 read scope PR(#52)과 검색 랭킹
> PR(#54)이 머지되면서 전제가 바뀌었고, 코드를 다시 읽는 과정에서 이전
> 설계서가 넘어간 충돌 하나(§1)를 발견했다.

## 0. 전제 변화

이전 설계서는 "read scope 하나만 고치면 된다"고 결론냈다. 그것을 #52로 고쳤고,
고치고 나서 두 번째 병목이 드러나 #54로 다시 고쳤다 — 정본·후보가 검색 결과를
다 채우면 세션 원문이 한 건도 안 나왔다. scope만 넓히고 랭킹을 보지 않았으면
pm-repo 첫 세션에서 바로 걸렸을 문제다.

교훈: 설계서의 "이것만 고치면 됨"은 실제로 돌려보기 전까지 가설이다. 이 문서의
설계도 같은 취급을 받아야 한다 (§7).

## 1. 결정 기록 경로가 둘이다 (이전 설계서의 누락)

이전 설계서 §4는 결정 확정 순간 `record_note(kind=decision)`를, 논의 일단락에
`write_session_process`를 호출하라고 썼다. 그런데 `write_session_process`도
Decision 후보를 자동 생성한다:

```python
# app/vault_tools.py:925
if decision_text and final_judge not in ("", "unresolved"):
    decision_result = writer.write(CandidateSpec(
        kind="decision",
        title=f"{project or '미지정'} — {decision_text[:60]}",
        ...))
```

`CandidateWriter`의 dedup은 제목 유사도 0.85 기준인데, 자동 생성 제목에는
`"{project} — "` 접두사가 붙는다. `record_note`로 남긴 제목과 임계값을 넘지
못해 같은 결정이 후보 2건으로 남는다.

제약이 하나 더 있다. `project_decisions`는 dict 하나라 세션당 결정 1건만
담긴다. PM 논의 세션은 보통 결정을 여러 개 만든다.

**규약**: 결정은 `record_note(kind="decision")` 한 경로로만 남긴다.
`write_session_process`의 `project_decisions`에는 사람이 읽을 요약을 채우되
`final_judge`는 비워 둔다 — 위 조건문이 정확히 그 값에서 자동 생성을 건너뛰므로
중복 없이 Process 본문의 가독성만 유지된다.

## 2. 구조

```
pm-repo/
├── CLAUDE.md      ← PM 규약 (§3~§6)
├── .mcp.json      ← devtrail-vault 연결
└── briefs/        ← 실제 보낸 brief 원문 (YYYY-MM-DD-프로젝트-제목.md)
```

코드는 0줄이다. 스킬도 처음에는 만들지 않는다 — 위임을 두세 번 손으로 해보고
반복되는 모양이 확정된 뒤에 만든다.

`briefs/`를 두는 이유는 나중에 스킬화할 때 템플릿 소재가 필요해서다. Vault에
넣지 않는 이유는 brief가 결정의 파생물이기 때문이다 — 결정 자체는 이미 Decision
후보로 남는다.

## 3. 세션 경계

`session_id`는 MCP 서버 프로세스 수명이다(`app/mcp_server.py:26`). PM 세션
하나를 며칠 켜두면 handoff 하나에 계속 덮어쓴다.

**규약**: 주제가 바뀌면 Claude Code 세션을 새로 연다. 이를 지키지 않으면
briefing의 최근 handoff 3건이 전부 같은 세션의 다른 시점으로 채워진다.

세션 마커는 `Path.cwd()/.claude/.vault-mcp/`에 생성되므로, pm-repo에서 열면
대상 프로젝트 repo의 세션과 섞이지 않는다.

## 4. Process 필드 매핑

`write_session_process`는 코딩 세션 모양(what_changed / files_touched 중심)이라
논의 세션에 그대로 쓰면 기록이 망가진다. 필드별 의미를 고정한다.

| 필드 | 논의 세션에서의 의미 |
|------|----------------------|
| `what_changed` | 이번 논의로 확정된 것. 방향 전환 포함. 불릿 |
| `files_touched` | 판단 근거로 실제 조회한 노트 경로 + 위임 결과 PR 링크 |
| `project_decisions` | 대표 결정 1건 요약. `final_judge`는 비운다 (§1) |
| `implementation_trace` | 논의 흐름을 시간순으로 — 아이디어 → 대안 → 반박 → 결론 |
| `agent_execution_notes` | PM 자신의 일하는 방식 교훈. `next_checks`/`better_approach`는 Lessons로 증류되므로 다음 세션에도 통하는 것만 |
| `docs_update_candidates` | Context.md에 반영이 필요한 항목 (사람 관리 영역이라 후보로만) |
| `next_session` | 다음에 이어갈 것 |
| `learning_recovery` | 사용자가 아직 이해하지 못한 개념·질문. 이해도를 과장하지 않는다 |

`files_touched`의 재해석이 이 매핑의 핵심이다. 논의 세션에는 파일 변경이 없지만
어떤 과거 기록을 읽고 판단했는지가 남으면 다음 세션이 같은 근거를 다시 찾을 수
있다. #52에서 넓힌 read scope가 여기서 값을 낸다.

## 5. 체크포인트

| 시점 | 호출 |
|------|------|
| 세션 시작 | `get_project_briefing("<프로젝트명>")` — pm-repo cwd에서도 이름으로 매칭된다 |
| 결정 확정 즉시 | `record_note(kind="decision")` — 사용자 확인 후 |
| 미결 질문 발생 | `record_agent_improvement` → MemoryPatches → apply 시 OpenLoops |
| 논의 일단락·주제 전환 | `write_session_process` (§4 매핑) |
| "구현해" 직전 | `write_work_plan` |
| 위임 완료 | `write_session_process` 재호출 — 같은 파일이 갱신된다 |

매 턴 distill은 하지 않는다. 비용과 중복 후보만 늘고,
`write_session_process`의 갱신 semantics가 이미 체크포인트 방식을 전제로
설계돼 있다.

## 6. brief 양식

```markdown
# <한 줄 목표>
프로젝트: <이름>   repo: <경로>

## 결정 (이미 확정된 것)
## 범위
## 비범위
## 수용 기준
## 참고 근거
```

brief에 컨텍스트를 싸들고 가지 않는다. 실행 에이전트는 대상 repo의 AGENTS.md와
자기 MCP 세션으로 움직이므로 결정·제약·수용기준만 담는다. `비범위`가 없으면
실행 에이전트가 범위를 넓힌다.

## 7. 검증되지 않은 가정

실사용 전에는 알 수 없는 것들이다. 미리 풀면 쓰지 않을 기능을 만든다.

1. **§4 필드 매핑이 자연스러운지**. 어색하다고 확인되면 그때 discussion 전용
   tool 추가를 검토한다.
2. **briefing의 최근 handoff 3건 창**. 논의 세션과 구현 세션이 섞이면 3건이
   금방 밀린다.
3. **결정 경로 단일화가 충분한지**. `final_judge` 비우기가 규약 준수에
   의존한다 — 훅으로 강제할 수단이 현재 없다.

1~2주 사용 후 재평가한다.

## 8. 범위 밖

OmniRoute, HTTP adapter, PM 전용 UI, ChatGPT 대화 자동 수집, 복잡한 multi-agent
협업, agent 성능 학습, Knowledge Graph, 새 Vector DB — 이전 설계서 §6 후순위와
동일하다. 위임도 처음에는 수동이다.
