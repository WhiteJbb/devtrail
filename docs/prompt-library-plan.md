# Prompt Library — BP 프롬프트 저장소 설계

서브에이전트 생성, 리뷰, 리서치 등에서 잘 동작한 프롬프트(Best Practice)를 vault에
자산으로 축적하고, 다음 세션에서 불러와 재사용할 수 있게 한다.

**핵심 설계 결정 2가지:**

1. **저장은 기존 후보 흐름을 그대로 탄다** — AI가 `60_Candidates/Prompts/`에 후보로
   기록하고, 사람이 `promote-candidate`로 검토 후 `20_Knowledge/Prompts/`로 승격한다.
   새 권한 모델이 필요 없고 "AI가 쓰고 사람이 승인"이라는 vault 원칙과 일치한다.
2. **소비는 MCP prompts 프리미티브로 노출한다** — MCP에는 tool과 별개로 prompts
   프리미티브가 있고(FastMCP 지원), Claude Code는 MCP 서버의 prompt를
   슬래시 명령(`/devtrail-vault:<이름>` 형태)으로 자동 노출한다. 승격된 프롬프트가
   곧바로 슬래시 명령이 된다.

`.claude/agents/`·`.claude/commands/` 같은 Claude Code 네이티브 방식은 **레포 단위**라
"모든 프로젝트·모든 Agent가 공유하는 메모리 버스"라는 vault 철학과 어긋나므로 쓰지
않는다. vault가 원본, MCP가 배포 채널이다.

## 진행 조건

- fix-plan P1~P5 완료 후(완료됨), `feat/prompt-library` 브랜치에서 작업한다.
- rename(docs/rename-to-devtrail.md)과 순서 무관 — 겹치는 파일이 mcp_server.py 정도이고
  서버명 문자열만 다르다. 둘 다 진행한다면 rename을 먼저 끝내는 쪽이 diff가 깨끗하다.
- 테스트: `py -3.11 -m pytest -q`, 기존 실패 15개 외 추가 실패 금지 (fix-plan과 동일).

## 1. 프롬프트 노트 형식

`60_Candidates/Prompts/` 및 승격 후 `20_Knowledge/Prompts/`의 노트:

```markdown
---
type: candidate            # 승격 후에는 promote 흐름이 status를 바꾼다
candidate_type: prompt
title: 코드리뷰 서브에이전트 파인더
status: candidate
created_at: 2026-07-06T14:30:00
project: ""                # 특정 프로젝트 전용이면 지정, 범용이면 빈 값
task_type: subagent        # subagent | review | research | writing | etc (자유 문자열)
variables: ["TARGET_DIR", "FOCUS"]
tags: [prompt]
source_refs: []            # 이 프롬프트가 잘 동작했던 세션/노트 경로
---

# 코드리뷰 서브에이전트 파인더

## Prompt

(프롬프트 원문. {TARGET_DIR}, {FOCUS} 같은 {변수} 자리표시자 사용 가능)

## Notes

- 언제/왜 잘 동작했는지, 주의점.
```

- 본문에서 `## Prompt` 섹션이 실제 주입될 내용이고, `## Notes`는 사람/AI용 메모다.
  `## Prompt` 섹션이 없으면 본문 전체를 프롬프트로 취급한다(단순 노트 호환).
- `variables`는 `{이름}` 자리표시자 목록. MCP prompt의 arguments로 노출된다.

## 2. 기록 경로 (AI → 후보)

### 2.1 CandidateWriter에 `prompt` kind 추가

- `app/services/candidate_writer.py`:
  - `_CANDIDATE_DIRS`에 `"prompt": "60_Candidates/Prompts"` 추가.
  - `CandidateSpec`에 `task_type: str = ""`, `variables: list[str] = field(default_factory=list)`
    추가. `write()`의 kind별 metadata 블록에 `if kind == "prompt":` 분기로 두 필드 기록
    (memory_patch 분기와 같은 패턴 — kind별 분기가 3개째이므로, 여력이 있으면 fix-plan
    리뷰에서 지적된 kind-registry로 묶는 리팩터링을 함께 해도 되지만 필수는 아니다).
  - `_normalize_kind` aliases에 `"prompts": "prompt"` 추가.
  - dedup: 기본 유지(같은 제목의 프롬프트 후보 반복 기록은 진짜 중복).

### 2.2 MCP tool: `record_prompt`

- `app/vault_tools.py`에 추가:

  ```python
  def record_prompt(title, prompt_body, description="", task_type="",
                    variables=None, project="", settings=None) -> CandidateWriteResult
  ```

  body는 `## Prompt\n\n{prompt_body}\n\n## Notes\n\n{description}` 형태로 조립.
  `record_note`의 허용 kind에는 **추가하지 않는다** — variables/task_type 구조가 필요해
  전용 함수가 맞다.
- `app/mcp_server.py`에 `@mcp.tool() record_prompt(...)` 래퍼 추가. docstring에
  "재사용 가치가 있는 프롬프트를 발견하면 기록하라. variables는 {이름} 자리표시자 목록"
  명시 (fix-plan P7.2와 같은 원칙 — docstring이 곧 지침).

### 2.3 승격 경로

- `app/agents/curator_agent.py`:
  - `_normalize_kind` aliases에 prompt 계열 추가.
  - `_promoted_path`의 kind→대상 폴더 매핑에 `"prompt": "20_Knowledge/Prompts"` 추가.
  - promote 시 frontmatter의 task_type/variables가 보존되는지 확인 (기존 promote가
    metadata를 통째로 옮기면 추가 작업 없음 — 코드 확인 후 판단).

## 3. 소비 경로 (vault → 세션)

### 3.1 MCP prompts 등록

- `app/mcp_server.py` `main()`에서 서버 시작 시 `20_Knowledge/Prompts/*.md`를 스캔해
  각 노트를 MCP prompt로 등록한다.
  - 설치된 `mcp` SDK(1.28.x)의 FastMCP prompt 등록 API를 확인할 것 —
    `@mcp.prompt()` 데코레이터가 기본이고, 동적 등록은 `mcp.add_prompt(...)`
    (`mcp.server.fastmcp.prompts` 모듈) 사용. 시그니처가 다르면 SDK 소스에 맞춘다.
  - prompt name: 파일명 slug (예: `코드리뷰-서브에이전트-파인더`),
    description: frontmatter title + Notes 첫 줄,
    arguments: frontmatter `variables` (모두 optional로).
  - 렌더링: `## Prompt` 섹션 추출 → `{변수}`를 인자 값으로 치환(제공 안 된 변수는
    자리표시자 그대로 둠 — 에이전트가 채우도록).
  - **candidate(60_Candidates/Prompts/)는 등록하지 않는다** — 승격된 것만 슬래시 명령이
    된다. 검토 전 후보가 명령으로 노출되면 promote 흐름이 무의미해진다.
- **알려진 한계(문서화만)**: 시작 시 1회 스캔이라 세션 중 승격된 프롬프트는 MCP 서버
  재시작 후 보인다. list 호출마다 재스캔하는 최적화는 하지 않는다(과설계).

### 3.2 검색/열람 폴백

- 추가 작업 없음 — `20_Knowledge/`와 `60_Candidates/`는 이미 `search_vault` read_scope
  안이므로 "리뷰용 프롬프트 있었나?" 같은 자연어 검색과 `read_note` 전문 열람이
  그대로 동작한다. `record_prompt` docstring에 이 사실을 한 줄 언급.

## 4. 문서/규칙 갱신

- `CLAUDE.md` 폴더 표에 행 추가:
  `| 60_Candidates/Prompts/ | 재사용 프롬프트 후보 | AI가 생성, 사람이 검토 후 promote |`
  (20_Knowledge/는 기존 행이 커버). 후보 흐름 문단의 kind 나열에도 prompt 추가.
- `docs/vault-mcp-implementation-summary.md`는 과거 스냅샷이므로 갱신하지 않는다.

## 5. 테스트

- `test_candidate_writer.py`: prompt kind 라우팅(60_Candidates/Prompts/), task_type/
  variables frontmatter 기록, dedup 동작.
- `test_vault_tools.py`: record_prompt가 `## Prompt` 섹션 포함 본문을 만드는지.
- `test_curator_agent.py`: prompt 후보 promote → 20_Knowledge/Prompts/ 이동, metadata 보존.
- `test_mcp_server.py`: 승격된 노트가 prompt로 등록되는지, 변수 치환, candidate 미등록,
  `## Prompt` 섹션 없는 노트의 본문 전체 폴백.

## 6. 수동 검증

1. MCP 등록 상태에서 `record_prompt` 호출 → `60_Candidates/Prompts/`에 파일 확인.
2. `work-agent list-candidates`에 prompt 후보가 보이는지 → `promote-candidate`로 승격.
3. MCP 서버 재시작 후 Claude Code에서 `/` 입력 → `devtrail-vault(현재는 work-agent-vault)`
   프롬프트가 목록에 뜨고, 선택 시 변수 입력과 본문 주입이 되는지.
4. "저장된 리뷰 프롬프트 찾아줘" 자연어로 ask-vault/search_vault가 찾는지.

## 범위 제외

- 프롬프트 버전 관리/효과 측정(A-B) — 노트의 Notes 섹션과 git 이력으로 충분.
- 후보 프롬프트의 자동 승격 — promote는 항상 사람이 한다.
- `.claude/agents/`·`.claude/commands/` 동기화 — vault→MCP 단일 채널을 유지한다.
