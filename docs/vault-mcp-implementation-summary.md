# Vault MCP 구현 요약 — docs/service-improvement-plan.md 반영

브랜치: `feat/vault-mcp`
대상 설계서: [service-improvement-plan.md](./service-improvement-plan.md)

---

## 1. 구현 범위

설계서 P0~P8 중 **P1~P7을 코드로 구현했고, P8(포지셔닝/README 재작성)은 의도적으로 제외**했다.
설계서 자체가 P8을 "MCP와 Learning Recovery가 실제로 돌기 시작한 뒤"로 못박아뒀는데, 이번
작업은 그 전 단계(구현 자체)이므로 지금 서사를 다시 쓰면 검증되지 않은 기능을 이미 검증된 것처럼
포장하게 된다. P0(문서 링크 정리)는 이미 완료 상태였다.

| 단계 | 내용 | 상태 |
|---|---|---|
| P0 | 문서 정합성 확인 | 기존에 완료됨(변경 없음) |
| P1 | MCP tool 정본 목록 | `app/vault_tools.py`의 공개 함수 시그니처로 구현 |
| P2 | Vault tool 레이어 | `app/vault_tools.py`, CandidateWriter 확장, CaptureAgent 확장 |
| P3 | MCP 연결 | `app/mcp_server.py`, `mcp-serve`, Tier 1 훅 스크립트(미등록) |
| P4 | 보존 정책 | `vault-cleanup` CLI |
| P5 | Learning Recovery 스키마 | Process 템플릿 + capture-session 폴백 템플릿 |
| P6 | 복습 질문 소비 루프 | `push-digest --daily`에 1줄 추가 |
| P7 | Telegram/assistant Vault Q&A | `/briefing`, `ask-vault` |
| P8 | 포지셔닝/README 재작성 | **제외** — 실사용 검증 이후로 보류 |

---

## 2. 파일별 변경 요약

### 신규 파일

| 파일 | 역할 |
|---|---|
| `app/vault_tools.py` | CLI/MCP/Telegram이 공유하는 서비스 레이어. P1 정본 7개 + `get_briefing`/`build_context` |
| `app/mcp_server.py` | `FastMCP("work-agent-vault")`로 7개 tool을 stdio 노출, session_id 자동 생성·주입 |
| `app/services/retention.py` | `10_Worklog/Sessions/`·`60_Candidates/SessionHandoffs/` 보존 정책 |
| `app/services/review_question.py` | 최근 세션의 Learning Recovery에서 복습 질문 1개 추출 |
| `scripts/hooks/print_briefing.py` | SessionStart 훅이 호출하는 briefing 출력 스크립트 |
| `scripts/hooks/session-start-briefing.ps1` | Claude Code SessionStart 훅 (참고용, 미등록) |
| `scripts/hooks/stop-process-check.ps1` | Claude Code Stop/PreCompact 훅 (참고용, 미등록) |
| `docs/vault-mcp-implementation-summary.md` | 본 문서 |
| `tests/test_vault_tools.py`, `test_candidate_writer.py`, `test_mcp_server.py`, `test_retention.py`, `test_review_question.py` | 신규 기능 테스트 |

### 수정 파일

| 파일 | 변경 이유 |
|---|---|
| `app/services/candidate_writer.py` | `session_handoff` kind 추가(SessionHandoffs/<Project>/ 라우팅, dedup 비활성화), `memory_patch`에 `evidence/scope/confidence/requires_user_review` 필드 추가, `write_many`의 dedup 인자 누락 버그 수정, `_slug`를 `slug_component`로 공용화 |
| `app/agents/curator_agent.py` | `list_candidates(include_session_handoffs=False)`로 기본 출력에서 handoff 제외, `promote_candidate`가 `session_handoff` 승격을 거부 |
| `app/agents/capture_agent.py` | `capture_session()`에 `summary_text`/`session_id` 파라미터 추가(summary_text가 summary_file보다 우선), 폴백 템플릿에 "Learning Recovery" 섹션 추가 |
| `app/cli.py` | `list-candidates --include-handoffs`, `mcp-serve`, `vault-cleanup` 명령 추가, `push-digest --daily`에 복습 질문 삽입 |
| `app/assistant/assistant.py` | `ask-vault` intent 처리 추가 |
| `app/messaging/router.py` | `/briefing` 슬래시 명령 추가 |
| `app/prompts/intent_route.md` | `ask-vault` 명령과 라우팅 힌트 추가 |
| `pyproject.toml` | `mcp>=1.2`(공식 Python SDK) 의존성 추가 |
| `CLAUDE.md` | MCP 연결 시 `write_session_process`가 1차 경로이고 `capture-session`은 fallback임을 명시, Learning Recovery 작성 기준 추가, SessionHandoffs 폴더 설명 추가 |

---

## 3. 설계서가 비워둔 부분 — 이번에 내린 결정

설계서에 명시되지 않았거나, 실제로는 존재하지 않는 전제(예: "기존 github.json 로드 패턴")를
참조한 부분을 구현하며 아래와 같이 결정했다.

1. **프로젝트 매핑 설정 파일은 `.claude/vault.json`(신규)** — `{"project": "Devtrail"}` 형태.
   설계서는 "기존 github.json 로드 패턴과 동일"하게 만들라고 했지만, 코드 전체를 확인한 결과
   그런 로더는 이 저장소에 존재하지 않는다(`.claude/github.example.json`은 어디서도
   `open()`되지 않는 템플릿일 뿐). 같은 단순 JSON 로드 관례로 새로 만들었다.
2. **`session_id`는 MCP 서버 프로세스가 소유** — 시작 시 1회 `uuid4()`로 생성해
   `write_work_plan`/`write_session_process` 호출에 자동 주입한다. `vault_tools`의 함수들은
   `session_id`를 인자로만 받는 상태 없는 함수로 유지했다(서버가 상태를 들고 tool은 순수 함수).
3. **Process의 Decisions/MemoryPatch 분리는 명시적 dict 파라미터로 구조화** — "필요하면 분리
   생성"이라는 서술을 그대로 두지 않고, `write_session_process`가 `project_decisions`/
   `agent_execution_notes`에 실질 내용이 있으면(placeholder가 아니면) 자동으로 각각
   `decision`/`memory_patch` candidate를 분리 생성하도록 구현했다.
4. **`record_agent_improvement`의 `scope`/`confidence` 기본값** — P1 시그니처
   (`record_agent_improvement(project, issue, improvement, evidence="")`)에는 없지만 P2 완료
   기준은 결과에 `scope`/`confidence`가 포함되길 요구한다. 함수 내부 기본값
   (`scope="project"`, `confidence="unspecified"`, `requires_user_review=True`)으로 채우고
   keyword-only로 override 가능하게 했다.
5. **`ask-vault`는 추가 LLM 합성 없는 MVP** — `search_vault` 상위 결과를 상태 라벨(초안에
   따르면/확정 지식)과 경로만 붙여 그대로 반환한다. 별도 답변 합성 프롬프트를 새로 만들지
   않아 범위를 최소로 유지했다.
6. **Retention 기본값** — SessionHandoffs는 프로젝트당 최신 3개를 무조건 보존, 그 밖은 30일
   초과 시 삭제(Plan/Process 구분 없이 같은 규칙 — 짝 없는 오래된 Plan도 자연히 포함됨).
   Worklog Sessions는 `needs_distill=False`이고 30일 초과 시 삭제. 모두 CLI 옵션으로 조정 가능.

---

## 4. Tier 1 훅에 대한 중요한 안내 — 미등록 상태

`scripts/hooks/session-start-briefing.ps1`(SessionStart)과
`scripts/hooks/stop-process-check.ps1`(Stop/PreCompact)을 작성했지만, **이 저장소의
`.claude/settings.json`에는 의도적으로 등록하지 않았다.** 이 구현 작업 자체가 devtrail
저장소에서 도는 Claude Code 세션이라, 지금 등록하면 검증되지 않은 차단 훅이 곧바로 스스로에게
적용되는 위험이 있어 사용자와 상의 후 보류하기로 했다.

PowerShell로 직접 실행해 다음은 확인했다:
- SessionStart 훅: `get_project_briefing()` 결과를 `hookSpecificOutput.additionalContext` JSON
  으로 조립하는 부분
- Stop 훅: git dirty 여부 + `.claude/.vault-mcp/current_session.json`의 `process_written`
  플래그를 읽어 차단/통과를 가르는 로직

**하지만 Claude Code의 실제 훅 프로토콜(정확한 stdin JSON 필드, exit code 의미, 차단 응답
포맷)에 대한 실제 세션 검증은 하지 않았다.** 등록 전 반드시 별도 세션에서 검증할 것 — §6의
"수동 검증 절차" 참고.

---

## 5. 자동 테스트

```bash
# Python 3.11 인터프리터 사용 (레포에 pytest 9가 설치돼 있음)
python -m pytest -q
```

이번 작업으로 추가/수정된 테스트 파일: `test_candidate_writer.py`(신규),
`test_vault_tools.py`(신규), `test_mcp_server.py`(신규), `test_retention.py`(신규),
`test_review_question.py`(신규), `test_capture_session.py`, `test_curator_agent.py`,
`test_assistant.py`, `test_messaging_router.py`(일부 수정/추가).

결과: 이번 브랜치 작업 시작 전 `main`에서도 이미 실패하던 **15개 테스트는 이번 변경과 무관한
기존 실패**임을 `git stash`로 대조 확인했다(주로 `capture_session`/`capture` 관련 rel_path
어설션이 실제 코드와 어긋난 낡은 테스트, `career_bullet`/`nightly_distill` LLM mock 관련).
그 외 신규/수정 테스트는 전부 통과하며, `main` 대비 63개 테스트가 새로 통과 상태로 추가됐다
(235 → 298 passed, 실패 15개는 동일).

---

## 6. 수동 검증 절차 (코드로 자동화할 수 없는 부분)

### 6.1 MCP 서버 (Claude Desktop/Code)

1. `.env`에 `OBSIDIAN_VAULT_PATH`가 설정돼 있는지 확인한다.
2. Claude Desktop의 `claude_desktop_config.json`에 등록:
   ```json
   {
     "mcpServers": {
       "work-agent-vault": {
         "command": "work-agent",
         "args": ["mcp-serve"]
       }
     }
   }
   ```
   또는 Claude Code에서: `claude mcp add work-agent-vault -- work-agent mcp-serve`
3. 새 세션에서 `get_project_briefing`을 호출해 컨텍스트가 반환되는지 확인한다.
4. `write_work_plan` → `record_note` → `write_session_process`를 순서대로 호출하고,
   `60_Candidates/SessionHandoffs/<Project>/`에 Plan/Process 파일 2개가 생기는지,
   `10_Worklog/Sessions/`에도 세션 기록이 함께 생기는지 확인한다.
5. 다음 세션에서 `get_project_briefing`이 방금 만든 Plan/Process를 최신 handoff로
   포함하는지 확인한다.

### 6.2 Tier 1 훅 (등록 전 반드시 별도 세션에서 검증)

**이 저장소가 아닌 별도의 테스트용 저장소**에서 먼저 검증할 것을 권장한다(자기 자신에게
적용되는 위험 회피).

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/session-start-briefing.ps1" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/stop-process-check.ps1" } ] }
    ]
  }
}
```

확인할 것: SessionStart 시 briefing이 실제로 컨텍스트에 주입되는지, 파일을 수정한 뒤
`write_session_process` 없이 세션을 끝내려 하면 차단되는지, `write_session_process` 호출
후에는 차단되지 않는지, 파일 변경이 없는 세션은 조용히 통과하는지.

### 6.3 push-digest --daily 복습 질문

`10_Worklog/Sessions/`에 Learning Recovery 섹션이 있는 세션 노트를 만든 뒤
`work-agent push-digest --daily`를 실행해 Telegram 메시지 끝에 "오늘의 학습 회수" 블록이
붙는지 확인한다(자동 테스트는 메신저 provider를 fake로 대체해 검증했으므로, 실제 Telegram
전송까지 확인하려면 `MESSENGER_PROVIDER=telegram`과 실제 토큰이 필요하다).

### 6.4 Telegram `/briefing`, 자연어 `ask-vault`

`work-agent serve-bot` 실행 후 실제 Telegram 챗에서 `/briefing`과 "지난번에 뭐라고
결정했었지?" 같은 자연어 질문을 보내 답변과 출처 경로가 오는지 확인한다.

---

## 7. 알려진 한계 / 다음에 할 일

- **P8(포지셔닝/README 재작성)은 하지 않았다** — 설계서 원칙대로 실사용 루프가 검증된 뒤 진행.
- **Tier 1 훅은 미등록·미검증 상태** — §6.2 절차로 별도 세션에서 먼저 검증 필요.
- **Telegram `/briefing`·`ask-vault`, `push-digest --daily`의 실제 전송 경로는 단위 테스트로만
  검증** — 실제 Telegram 봇 연동 확인은 사용자 환경에서 별도로 필요.
- Tier 2(Cursor/OpenClaw 훅 스크립트 자동화)와 Tier 3(지침 전용)는 이번 범위에 포함하지
  않았다 — 설계서 P3에서도 참고 정보로만 다뤄졌다.
