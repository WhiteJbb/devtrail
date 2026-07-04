# Vault 소비(Consumption) 계획 — AI가 vault를 실제로 활용하게 만들기

작성일: 2026-07-01 · 개정: 2026-07-02
관련: [vault-ai-integration.md](./vault-ai-integration.md)(브리핑 파일 원안), [goal-agent-plan.md](./goal-agent-plan.md)(run-goal tool 레이어)

> **2026-07-02 개정 요지 (실사용 재검토 반영)**: "개발하면서 자동으로 읽고·기록되고·활용되는 루프"가 실제로 도는지 재검토한 결과 3개 구멍을 메웠다 —
> ① 세션 시작 자동 브리핑 강제(자동 읽기), ② MCP에 60_Candidates 한정 **쓰기 도구** 추가(자동 기록), ③ **read_scope에 60_Candidates 포함 + status 라벨**로 기록→활용 루프의 promote 병목 제거. promote는 "가시성 게이트"에서 "신뢰 신호"로 역할이 바뀐다. 아래 본문에 [개정]으로 표시.

---

## 0. 문제 한 줄 정의

capture→distill→promote 파이프라인은 vault에 **넣는 것**만 완성돼 있고, **읽는 주체가 work-agent 자기 명령뿐**이다. 실제로 대화하는 AI(Claude Code, ChatGPT, 봇)는 vault 접근 경로가 없어서, vault가 아무리 채워져도 대화에 반영되지 않는다. → vault가 **쓰기 전용 메모리** 상태다.

기존에 있는 `search`/`ask`/`related`/`build-context`는 전부 **사람이 CLI에 직접 치는** 명령이라, 대화 중 AI가 스스로 호출할 수 없다. 그리고 `WikiService.search`는 **keyword 토큰 매칭**이다(임베딩 없음).

---

## 1. 확정된 결정 (2026-07-01)

| 항목 | 결정 | 함의 |
|---|---|---|
| 주력 클라이언트 | Claude Code/Desktop + Telegram(모바일) | **MCP 서버**가 메인 산출물, **봇 메모리/조회 개선**이 보조 |
| MCP 전송 방식 | **로컬 stdio 전용** | 포트 안 엶. Claude Code·Claude Desktop이 `work-agent mcp-serve`를 자식 프로세스로 그때그때 기동/종료 — 상시 데몬 불필요. **서버 한 벌로 두 클라이언트 공용** |
| 웹 클라이언트(claude.ai/ChatGPT) | 로컬 MCP로는 **연결 불가** | 웹은 내 PC 프로세스를 못 봄 → 원격 MCP(인터넷 노출+인증) 필요. 빈도 낮으므로 보류(Phase 5 조건부). 당장은 브리핑 파일 복붙 |
| 노출 범위 **[개정 07-02]** | `20_Knowledge/` + `30_Projects/` + `40_AgentMemory/` + **`60_Candidates/`(라벨 포함)** | 07-01엔 "정제 영역만"으로 60_Candidates를 뺐으나, 그러면 갓 기록한 후보가 승격 전까지 검색에 안 잡혀 **기록→활용 루프가 promote에서 끊김**(구멍 3). 후보를 포함하되 `status`(stable/candidate)로 구분하고 stable을 상위 랭킹. `00_Inbox/`(원시)·`10_Worklog/`는 여전히 제외(노이즈, recall 부족 시 재검토) |
| 쓰기 경로 **[개정 07-02]** | AI는 `60_Candidates/`에만 기록 가능 | MCP/봇/run-goal 모두 `CandidateWriter` 경유. 공식 영역(20/30/40) 직접 쓰기 없음. 개발 중 "이거 기록해둬"가 세션 안에서 완결 |
| promote 역할 **[개정 07-02]** | 가시성 게이트 → **신뢰 신호** | promote 안 해도 검색 루프는 돎(후보도 잡힘). promote는 "공식/검증으로 졸업"시켜 랭킹·신뢰를 올리는 선택적 액션. 관문 적체 압박 제거 |
| 검색 품질 | keyword로 시작 | 임베딩은 recall 병목이 실제로 확인되면 Phase 4에서 추가 |
| ChatGPT/Gemini 웹 | 이번 범위 밖(보조) | 브리핑 파일 복붙으로만 대응 — 이미 `vault-ai-integration.md`에 설계됨 |

---

## 2. 핵심 설계 — tool 레이어 하나를 세 곳에 노출

세 소비 경로(MCP·봇·run-goal)가 필요로 하는 기능은 결국 같다: **vault를 읽고/검색/기록하는 순수 함수**. 이걸 각자 구현하면 3중 중복이 되므로, **tool 레이어를 한 번 만들고 세 군데에서 재사용**한다. 읽기(read_scope)와 쓰기(write_scope) 경계를 이 레이어 한 곳에서 강제한다.

```
                    app/vault_tools.py  (신규, 순수 함수 + read/write 경계)
                    ── 읽기 ──────────────────────────────────
                    ├─ search_vault(query, limit)   ← 결과에 status 라벨, scope로 거름
                    ├─ read_note(rel_path)          ← scope 밖이면 거부
                    ├─ get_briefing()               ← AgentMemoryLoader.load().render()
                    ├─ build_context(topic)         ← ContextPackBuilder 재사용
                    ├─ list_notes(prefix)
                    ── 쓰기 [개정 07-02] ─────────────────────
                    └─ record_note(kind, title, body)  ← CandidateWriter 경유, 60_Candidates 한정
                          │
        ┌─────────────────┼──────────────────────┐
        ▼                 ▼                       ▼
  app/mcp_server.py   Telegram 봇            goal-agent registry
  (Claude Code/       (ask-vault intent,     (run-goal의 tool도
   Desktop, stdio)     /briefing)             동일 함수 참조)
```

`goal-agent-plan.md`의 `registry.py`가 참조할 tool 함수와 **여기서 만드는 함수가 동일하다.** 즉 이 문서와 goal-agent-plan은 tool 레이어를 공유한다 — 어느 쪽을 먼저 하든 `app/vault_tools.py`를 먼저 만들면 양쪽에 재사용된다.

### 2a. read_scope 경계 + status 라벨 **[개정 07-02]**

노출 범위를 코드 한 곳에서 강제한다. **핵심 개정**: 60_Candidates를 scope에 포함하되, 검색 결과에 `status`를 실어 검증 여부를 구분한다. "검색에 잡히는 것(findability)"과 "검증된 것(verification)"을 분리하는 것이 목적 — 갓 기록한 후보도 즉시 찾을 수 있어야 기록→활용 루프가 닫힌다.

```python
# stable = 공식/검증 영역, candidate = 미검토 후보
ALLOWED_READ_PREFIXES = {
    "20_Knowledge/": "stable",
    "30_Projects/": "stable",
    "40_AgentMemory/": "stable",
    "60_Candidates/": "candidate",   # [개정] 포함 — 단 candidate로 라벨
}
# 00_Inbox/(원시), 10_Worklog/는 여전히 제외

def _status_of(rel_path: str) -> str | None:
    for prefix, status in ALLOWED_READ_PREFIXES.items():
        if rel_path.startswith(prefix):
            return status
    return None   # scope 밖

def read_note(rel_path: str) -> str:
    if _status_of(rel_path) is None:
        raise PermissionError(f"scope 밖 경로 접근 거부: {rel_path}")
    ...

def search_vault(query: str, limit: int = 10) -> list[dict]:
    results = WikiService(vault_dir).search(query, limit=limit * 4)
    scoped = [(r, _status_of(r.note.path)) for r in results]
    scoped = [(r, s) for r, s in scoped if s is not None]
    # stable을 candidate보다 위로 (동점이면 검색 점수 순)
    scoped.sort(key=lambda x: (0 if x[1] == "stable" else 1, -x[0].score))
    return [_to_dict(r, status=s) for r, s in scoped][:limit]  # 각 결과에 status 포함
```

- 결과 dict에 `status` 필드가 실린다. **MCP 툴 설명/시스템 프롬프트에 명시**: "`candidate`는 미검토 초안이니 '확정'이 아니라 '초안에 따르면 ~'으로 인용하라." → 미검토 노이즈를 확정처럼 말하는 걸 방지.
- `40_AgentMemory/` 루트의 `00_Profile`~`05_OpenLoops`는 stable → 브리핑/조회 허용.
- `00_Inbox/`(원시 캡처), `10_Worklog/`는 scope 밖 → AI에 노출 안 됨.
- **경로 정규화 주의**: `..`나 절대경로가 들어와도 vault 밖을 못 읽게, `rel_path`를 vault_dir 기준으로 resolve한 뒤 vault_dir 하위인지 재확인한다(디렉터리 탈출 방지).

### 2b. write_scope 경계 + promote 재정의 **[개정 07-02]**

AI가 개발 중 "이거 기록해둬"를 세션 안에서 끝내려면 쓰기가 필요하다. 단 **60_Candidates에만** 쓰게 하고, 기존 `CandidateWriter`(이미 60_Candidates 밖 쓰기를 생성자 수준에서 차단)를 그대로 경유한다 — 새 경계를 만들지 않는다.

```python
def record_note(kind: str, title: str, body: str, project: str = "") -> str:
    """AI가 개발 중 남긴 결정/지식을 60_Candidates에 후보로 기록. 공식 영역엔 못 쓴다."""
    spec = CandidateSpec(kind=kind, title=title, body=body, project=project,
                         source_refs=["(agent session)"])
    return CandidateWriter(vault_dir).write(spec).rel_path
```

- 공식 영역(20/30/40)·삭제 tool은 **등록하지 않는다.** run-goal의 write_scope 규칙과 동일한 안전 모델.
- **promote 역할 변경**: 이제 promote는 "검색에 넣기 위한 관문"이 아니다(후보도 이미 검색됨). "이 후보를 공식/검증으로 졸업"시켜 stable 랭킹·신뢰를 부여하는 **선택적** 액션이다. 사람이 promote를 미뤄도 기록→활용 루프는 계속 돈다 → 관문 적체가 루프를 막지 않는다.

### 2c. 루프가 닫히는 그림 **[개정 07-02]**

```
개발 중 (Claude Code/Desktop 세션)
  │ AI가 결정/지식을 record_note → 60_Candidates 기록
  ▼
다음 조회 시 search_vault가 그 후보를 status=candidate로 즉시 반환
  │ ("초안에 따르면 ~"으로 인용)
  ▼
사람이 여유될 때 promote → status=stable 로 졸업 (안 해도 루프는 돎)
```
수동 단계 없이 **기록→활용이 자동으로 이어진다.** 이것이 "죽은 인프라"를 막는 핵심.

---

## 3. MCP 서버 (Claude Code / Desktop) — 메인 산출물

### 3a. 이게 왜 최고 레버리지인가

- **대화 중 실시간 조회**: "내가 RAG 청킹에 대해 뭐라고 결정했지?" → AI가 `search_vault` 툴을 스스로 호출 → 답변에 반영. 복붙 불필요.
- **vault 경로 문제 자동 해결**: MCP 서버는 **vault가 있는 그 머신에서** `.env`의 `OBSIDIAN_VAULT_PATH`를 읽어 돈다(work-agent와 동일). Claude Code에는 `work-agent mcp-serve` 명령만 등록하면 되고, 머신별 절대경로를 하드코딩할 필요가 없다 → `vault-ai-integration.md` 1a 문제가 여기서 해소된다.
- **#1(부트스트랩)과 #2(온디맨드 조회)를 한 번에**: `get_briefing` 툴 = 세션 시작 시 프로필, `search_vault`/`read_note` = 대화 중 조회.

### 3b. 구현

```
app/mcp_server.py   # 신규 — MCP SDK(FastMCP)로 vault_tools를 툴로 노출
app/cli.py          # "mcp-serve" 명령 추가 → stdio로 MCP 서버 기동
```

```python
# app/mcp_server.py (스케치)
from mcp.server.fastmcp import FastMCP
from app import vault_tools

mcp = FastMCP("work-agent-vault")

@mcp.tool()
def search_vault(query: str, limit: int = 10) -> list[dict]:
    """정제된 vault 영역(Knowledge/Projects/AgentMemory)에서 노트를 keyword 검색한다."""
    return vault_tools.search_vault(query, limit)

@mcp.tool()
def read_note(rel_path: str) -> str:
    """vault 노트 전문을 읽는다. 정제 영역 밖은 거부된다."""
    return vault_tools.read_note(rel_path)

@mcp.tool()
def get_briefing() -> str:
    """현재 프로필·포커스·프로젝트맵·OpenLoops 요약(40_AgentMemory)을 반환한다."""
    return vault_tools.get_briefing()

@mcp.tool()  # [개정 07-02] 쓰기 도구 — 개발 중 기록을 세션 안에서 완결
def record_note(kind: str, title: str, body: str, project: str = "") -> str:
    """개발 중 남길 결정/지식을 60_Candidates에 후보로 기록한다. 공식 영역엔 쓰지 못한다.
    kind: knowledge | decision | blog_idea | career_bullet | memory_patch"""
    return vault_tools.record_note(kind, title, body, project)

def main() -> None:
    mcp.run()   # stdio transport
```

읽기 4개 + 쓰기 1개. 쓰기는 60_Candidates로 제한돼 있어 안전하고, search_vault가 후보도 반환하므로 방금 쓴 게 바로 다음 조회에 잡힌다.

> ⚠️ 확인 필요(구현 시점): MCP Python SDK 패키지명/버전(`pip install "mcp[cli]"` 계열), Claude Code 등록 방식(`claude mcp add work-agent-vault -- work-agent mcp-serve` 또는 프로젝트 `.mcp.json`), Claude Desktop `claude_desktop_config.json` 형식. MCP 스펙은 변화가 잦으므로 착수 직전 현행 공식 문서로 교차 확인한다. 이 문서에서 확정하는 건 **노출할 tool 목록과 scope**이고, 프로토콜 배선은 구현 시 검증한다.

### 3c. 등록 (예상, 검증 대상)

- **Claude Code**: `claude mcp add work-agent-vault -- work-agent mcp-serve` (사용자 또는 프로젝트 스코프)
- **Claude Desktop**: 설정 파일 `claude_desktop_config.json`의 `mcpServers`에 `command: work-agent`, `args: ["mcp-serve"]`
  - 주의: 등록하는 명령(`work-agent`)이 그 PC에서 실제로 resolve돼야 함. PATH에 없으면 전체 경로(예: `.venv/Scripts/work-agent`)를 적는다.
- 둘 다 **같은 서버·같은 코드**를 각자 설정에 등록만 하는 것. 서버를 두 벌 만들지 않는다.

### 3d. 세션 시작 자동 브리핑 — "자동 읽기" 강제 **[개정 07-02]**

MCP가 도구를 쥐여줘도 모델이 안 부르면 vault를 무시한다("자동 읽기"가 가능성일 뿐 보장이 아님, 재검토 구멍 1). 게다가 **현재 CLAUDE.md의 읽기 지침이 깨져 있다**:
```
- `{VAULT}/40_AgentMemory/Core/` — ... (가장 먼저 읽을 것)   # {VAULT} 미치환, Core/ 미존재
```
그래서 "세션 시작 시 컨텍스트를 읽는다"가 명령 수준에서 이미 죽어 있다. 두 가지로 강제한다:

1. **CLAUDE.md 지침 수리**: 위 깨진 줄을 → "세션 시작 시 `get_briefing` MCP 툴을 호출해 현재 컨텍스트를 먼저 읽는다. 미연결 시 `work-agent briefing` 출력을 참고한다"로 교체.
2. **(선택) 세션 시작 hook**: `vault-ai-integration.md`가 제안한 `.claude/settings.json` hook으로 브리핑을 자동 갱신. hook 없이도 CLAUDE.md 지침만으로 1차 효과.

> 이 수리는 MCP와 독립적으로도 값어치가 있다(브리핑 파일 경로 통일). Phase 2에 묶어 함께 처리한다.

### 3e. 로컬 stdio vs 원격 — 프라이버시 경계 (왜 로컬로 정했나)

| | 로컬 stdio (이 계획) | 원격 MCP (웹 지원 시, Phase 5) |
|---|---|---|
| 네트워크 포트 | **안 엶** | 인터넷에 엶 |
| 남(제3자)의 접근 | 불가 | 인증 뚫리면 가능 — vault가 네트워크 접근 가능한 엔드포인트가 됨 |
| 상시 실행 | 클라이언트가 자동 관리 | 직접 상시 호스팅/터널 |
| 세팅 | 명령 한 줄 등록 | 호스팅 + OAuth/토큰 인증 구축 |

**공통 사항(로컬이라고 아무것도 안 나가는 건 아님)**: AI가 툴로 *실제 조회한 노트 내용*은 그 대화의 프롬프트로 모델(Anthropic)에 전송된다 — 파일 열기·복붙과 동일. 단 **전체 vault가 아니라 조회된 것만**, 그리고 **read_scope 밖(00_Inbox/10_Worklog)은 원천 차단. 60_Candidates는 candidate status로 노출하되, 확정 정보가 아니라 초안으로 인용한다.** 완전 무전송을 원하면 조회·요약을 로컬 LLM(Ollama)로 태우는 별도 선택지가 있다.

---

## 4. Telegram 봇 (모바일) — 보조

현재 봇은 **의도 분류 → 명령 실행**만 한다. "vault에 질문하고 답을 받는" 흐름이 없다. tool 레이어가 생기면 두 가지를 얹는다:

### 4a. `/briefing` 명령 (#1 부트스트랩, 저비용)
`get_briefing()` 결과를 메시지로 전송. 모바일에서 현재 컨텍스트 확인. — `vault-ai-integration.md` 5b에 이미 설계됨, tool 레이어로 1줄.

### 4b. `ask-vault` 인텐트 (#2 온디맨드 조회)
`Assistant.interpret()`에 새 command `ask-vault` 추가:
```
사용자: "RAG 청킹 관련해서 내가 정리해둔 거 있어?"
→ intent: ask-vault
→ search_vault("RAG 청킹") → 상위 노트 3개를 컨텍스트로 LLM 요약 답변(+ 출처 rel_path)
```
`intent_route.md` 프롬프트에 분기 하나, `Assistant.execute()`에 `ask-vault` 핸들러 하나 추가하면 된다. 봇/`ask` CLI 양쪽에서 동작.

---

## 5. ChatGPT / Gemini 웹 (범위 밖, 기록만)

MCP·파일 접근 모두 불가. `work-agent briefing`으로 `.claude/briefing.md` 생성 → 복붙이 유일한 현실적 방법. `vault-ai-integration.md`에 이미 설계돼 있으므로 이 문서에서 새로 만들지 않는다. (API+커스텀 GPT Action은 고비용이라 지금은 비권장.)

---

## 6. 구현 순서

| Phase | 내용 | 완료 기준 | 서비스되는 소비 경로 |
|---|---|---|---|
| 1 | `app/vault_tools.py` — 읽기(`search_vault`+status라벨/`read_note`/`get_briefing`/`build_context`) + **쓰기(`record_note`, 60_Candidates 한정)** + read/write 경계 + 단위 테스트(디렉터리 탈출·scope 거부·후보 검색 포함·후보 기록) | `pytest tests/test_vault_tools.py` 통과 | (공통 기반) |
| 2 | `app/mcp_server.py`(읽기4+쓰기1) + `mcp-serve` CLI + **CLAUDE.md 읽기 지침 수리(3d)**. Claude Code에 등록해 조회·기록 왕복 확인 | Claude Code에서 `record_note`→`search_vault`로 방금 기록이 잡힘 | **Claude Code/Desktop** |
| 3 | 봇 `/briefing` + `ask-vault` 인텐트(후보 포함 검색) | 봇에 질문 → vault 출처 포함 답변 | **Telegram** |
| 4 (조건부) | 임베딩 검색 — Phase 2~3 써보고 keyword recall이 부족하면 착수 | semantic 검색이 keyword보다 관련 노트를 더 잘 찾음 | 전체 |
| 5 (조건부) | 원격 MCP — 웹 claude.ai/ChatGPT 지원. HTTP 전송 전환 + 호스팅/터널 + **인증(OAuth/토큰) 필수** | 웹에서 vault 상시 조회가 실제로 필요하다고 확인됐을 때만 | claude.ai / ChatGPT 웹 |

Phase 1은 goal-agent-plan의 registry와 공유되므로, run-goal을 먼저 하든 이걸 먼저 하든 **Phase 1을 공통 선행 작업**으로 두면 양쪽이 이득이다. 그리고 재검토 결론상 **일상 개발 루프엔 이 문서(vault-consumption)가 run-goal보다 우선**이다 — run-goal은 "포트폴리오 정리" 같은 가끔 하는 배치 작업용이라 성격이 다르다.

브랜치: 새 CLI 명령·모듈이므로 CLAUDE.md 규칙상 `feat/vault-mcp` 브랜치.

---

## 7. 남은 결정 / 리스크 (사람이 판단)

- **미검토 후보가 검색에 섞이는 노이즈 [개정 07-02]**: 60_Candidates 포함의 대가. status 라벨 + stable 우선 랭킹 + "초안으로 인용" 프롬프트로 완화하지만 0은 아니다. **"루프가 끊긴 것 < 가끔 초안이 섞이는 것"**이라는 판단으로 수용. 실사용에서 후보 노이즈가 심하면 candidate 랭킹을 더 낮추거나 `status=candidate`를 별도 툴(`search_candidates`)로 분리하는 것을 검토.
- **다중 머신 [개정 07-02]**: 로컬 MCP는 "개발 머신 == vault 머신"을 가정한다. 노트북·데스크탑을 오가면 각 머신에 vault가 sync(sync-vault.ps1)돼 있고 MCP 서버가 그 머신에서 따로 떠야 한다. 아니면 그 머신에선 자동 읽기·기록이 안 된다.
- **자동 기록의 척추는 여전히 git 훅 [개정 07-02]**: `record_note`는 AI가 능동적으로 부를 때만 기록한다. "커밋할 때마다 자동"은 기존 `capture-commit`(post-commit 훅)이 담당하며, **레포마다 `install-hooks`를 돌려야** 걸린다(XCoreChat 등 다른 레포 확인 필요). record_note는 훅을 대체하는 게 아니라 세션 내 능동 기록을 보완한다.
- **10_Worklog 노출 여부**: 현재 scope에서 제외했다. AI 세션 요약(Sessions/)은 "내가 언제 뭘 했나" 조회에 유용할 수 있는데, 정제본은 아니다. recall이 아쉬우면 `10_Worklog/Sessions/`만 선택적으로 scope에 추가하는 걸 검토.
- **MCP 서버 상시 실행 vs 온디맨드**: Claude Code는 세션마다 stdio로 서버를 띄우므로 상시 데몬 불필요. 단 Claude Desktop도 같은지, vault git sync와 충돌 없는지(쓰기가 60_Candidates에 생기므로 sync 충돌 가능성 재확인) 확인.
- **keyword 검색의 한계 감수 범위**: "문서 분할"↔"청킹" 같은 동의어를 못 잡는다. 초기엔 AI가 여러 쿼리를 재시도하는 것으로 완화되지만, 자주 헛돌면 Phase 4를 앞당긴다. — 이건 실제 써보고 판단할 문제라 지금 데이터로는 결정 보류.
- **봇 free-form Q&A의 LLM 쿼터**: `ask-vault`가 매 질문마다 LLM을 쓰므로 Gemini 쿼터 소진 주의. 라우팅 task_type을 `light`로.

---

## 8. 관련 파일

- [app/services/wiki_service.py](../app/services/wiki_service.py) — `search`(keyword)/`related_notes`/`scan_notes`, tool 레이어가 감쌀 대상
- [app/memory/agent_memory_loader.py](../app/memory/agent_memory_loader.py) — `get_briefing` 본체
- [app/memory/context_pack_builder.py](../app/memory/context_pack_builder.py) — `build_context` 재사용(이미 60_Candidates 제외)
- [app/services/candidate_writer.py](../app/services/candidate_writer.py) — `record_note`가 실제로 경유하는 쓰기 경계(60_Candidates 한정). read 경계의 대칭
- [app/agents/curator_agent.py](../app/agents/curator_agent.py) — promote/apply-memory-patch. 역할 재정의(가시성→신뢰) 반영 지점
- [app/assistant/assistant.py](../app/assistant/assistant.py) — `ask-vault` 인텐트 추가 지점
- [app/cli.py](../app/cli.py) — `mcp-serve` 명령 등록 지점
- [CLAUDE.md](../CLAUDE.md) — 깨진 vault 읽기 지침(`{VAULT}/40_AgentMemory/Core/`) 수리 대상 (3d)
- [docs/vault-ai-integration.md](./vault-ai-integration.md) — 브리핑 파일(ChatGPT/Gemini 보조 경로) 원안
- [docs/goal-agent-plan.md](./goal-agent-plan.md) — tool 레이어를 공유하는 run-goal 계획
