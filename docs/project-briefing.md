# 구분된 프로젝트 briefing — `get_project_briefing(structured=True)`

기본 briefing은 Context·메모리·최근 결정·최근 세션 발췌를 한 덩어리 markdown으로 준다. 무엇이 지켜야 할
제약이고 무엇이 지난 세션이 남긴 할 일인지, 어느 파일 몇 번째 줄인지, 어디가 잘렸는지는 읽는 쪽이 추측해야 했다.
특히 Context는 로더가 5000자에서 미리 잘라, 긴 Context 후반의 제약 절은 briefing에 아예 도달하지 못했다.

`structured=True`는 같은 기록을 다섯 갈래로 나누고, 모든 발췌에 원문 위치·내용 버전을 달고, 못 넣은 구간을
정확한 줄 범위와 이어읽기 인자로 남긴다. 기본 호출은 바뀌지 않는다.

## 호출

```text
get_project_briefing(project_or_repo)                   # 기본 — project/matched/candidates/text/source_refs (변경 없음)
get_project_briefing(project_or_repo, structured=True)  # 새 응답
```

- SessionStart 훅(`scripts/hooks/session-start-briefing.py`)과 `devtrail project-briefing` CLI는 기본 호출을 그대로 쓴다.
  자동으로 structured로 바꾸지 않는다.
- 구현: `app/services/project_briefing.py`(조립), `app/vault_tools.get_structured_project_briefing`(기본 briefing의
  결정·세션 목록 함수를 넘겨 같은 창·순서를 쓴다), `app/mcp_server.get_project_briefing`(`structured` 인자).
- LLM·새 DB·인덱스·벡터 검색·외부 Task/운영 상태 동기화는 쓰지 않는다. 매 호출 vault 파일을 읽어 조립한다.

## 응답

| 필드 | 뜻 |
|------|----|
| `schema_version` | `"1"` |
| `generated_at` | 응답을 만든 시각(ISO 8601, 시간대 포함). 발췌의 기록 시각과 다르다 |
| `project`, `matched` | 확정된 프로젝트 표기, 확정 여부(`matching.status == "resolved"`) |
| `candidates`, `source_refs` | 기본 호출과 같은 키. `candidates`는 확정하지 못했을 때 고를 프로젝트 이름(확정이면 `[]`), `source_refs`는 소속 검증을 통과해 실제로 쓴 문서 경로(읽은 순서 — `sources`에서 `excluded` 아닌 것과 같다) |
| `matching` | 식별 결과 — `input, status, project, method, evidence, candidates, hint, basis` (+ 확정 못 했을 때 `registered_projects`) |
| `sections` | 표시 순서대로 5개: `constraints`, `context`, `recent`, `follow_ups`, `gaps` |
| `omissions` | 본문에 못 넣은 구간(한 항목에 여러 건일 수 있다 — 건너뛴 긴 줄마다 한 건 + 예산·상한으로 못 넣은 나머지 구간 한 건. 나머지 구간은 보통 뒤쪽, append형 Lessons·공통 OpenLoops는 앞쪽) — `item, section, kind, path, lines:[시작,끝], reason, critical, read, read_continues, first_read_end_line, structured_readable` (+ `line_chars`). `read`는 MCP `read_note` 인자 그대로다(아래) |
| `critical_omission` | 제약이 일부라도 본문에 없거나, 제약 출처(Context.md)를 확인하지 못했다 |
| `requires_read` | 먼저 읽어야 할 것 — `{path, lines, reason: critical_omission, item, read}`(빠진 제약 구간) 또는 `{path, reason: context_unreadable·context_unverifiable, read: {rel_path}, unverified?}`. `read`는 그대로 `read_note(**read)` |
| `partial` | 일부 기록을 읽지 못했다(읽기 실패·frontmatter 해석 실패로 기본 목록에서 빠진 파일·등록부 미확인) |
| `warnings` | `{code, message, path?}` — `read_failed`, `registry_unreadable`, `frontmatter_unparsed`, `link_skipped`, `document`, `response_large` …. 공유 후보 결정 폴더(`60_Candidates/Decisions`)에서 빠진 파일은 소속을 확인할 수 없어 파일명 없이 사유별로 묶는다: `{code, message, path: "60_Candidates/Decisions/", count, attribution: "unverified"}` |
| `sources` | 사용한 문서마다 `path, title, kind, record_tier, status, time, attribution, source_version, total_lines, frontmatter_lines`. 소속 검증에 실패한 문서는 `{path, excluded}`만 |
| `text` | 사람·에이전트가 읽는 본문. **20000자 이하**, 완전한 줄만 |
| `budget` | `text_max_chars, text_chars, response_chars, sources_meta_chars, sections_meta_chars, display_order, budget_order, group_caps, item_caps` |
| `elapsed_ms` | 조립 시간 |

### 항목(sections[].items)

```json
{"id": "c3", "kind": "constraint", "label": "제약 / 원칙", "path": "30_Projects/Devtrail/Context.md",
 "span": [20, 24], "shown": "full|partial|omitted", "contiguous": false,
 "segments": [{"start_line": 20, "end_line": 20, "text": "## 제약 / 원칙"},
              {"start_line": 22, "end_line": 23, "text": "- …\n- …"}],
 "cleaned": [{"lines": [21, 21], "reason": "empty_scaffolding"}],
 "scope": "project|common", "project": "Devtrail", "record_tier": "stable|candidate|raw",
 "source_version": "sha256:…", "omission": {"lines": [24, 24], "reason": "budget"}}
```

- `segments[].text`는 원문 `start_line`~`end_line` 줄을 `\n`으로 이은 것과 **정확히 같다**. 줄 번호는 frontmatter를 포함한
  파일 전체 기준, 1부터(`read_note(structured=True)`·`search_vault(structured=True)`와 같은 기준 — `app/services/vault_source.py`).
- 정리로 빠진 줄이 있으면 구간이 여러 개(`contiguous: false`)가 되고, 본문에도 구간마다 `@L시작-L끝` 줄이 따로 붙는다.
  빠진 줄은 `cleaned`에 이유와 함께 남는다.
- 세션 항목은 `session_rank, session_id, handoff_type, recorded_at{value, source}, host, agent`, 결정 항목은
  `decision_status(candidate|promoted), recorded_at`, 메모리 블록은 `block_evidence`(marker 근거)를 더 단다.
- 다시 읽기: `read_note(path, structured=True, start_line, max_lines, expected_version=source_version)`. 그 사이 파일이
  바뀌었으면 `version_mismatch`로 거절된다.

### 이어읽기 인자 `read`

`omissions[].read`와 `requires_read[].read`는 MCP `read_note`의 인자 이름 그대로이고 다른 필드를 섞지 않는다 — 변환 없이
`read_note(**read)`로 넘긴다(stdio 왕복 테스트가 그대로 넘겨 확인한다).

```json
{"rel_path": "30_Projects/Devtrail/Context.md", "structured": true, "start_line": 192, "max_lines": 70,
 "expected_version": "sha256:…"}
```

- 구간 끝·안내 정보는 생략 항목 쪽에 따로 있다: `lines`(정확한 [시작, 끝]), `first_read_end_line`(`read` 한 번의 마지막 줄),
  `read_continues`(400줄 또는 16000자 상한 때문에 한 번에 끝까지 못 읽어 응답의 `next`로 이어 읽어야 함), `structured_readable`.
- 16000자를 넘는 줄이 구간에 있으면 structured로 그 줄을 받을 수 없어 `structured_readable=false`, `read = {"rel_path": …}`
  (전문 읽기, 버전 확인 없음)다.

## 다섯 갈래 — 분류 근거는 제목과 메타데이터뿐

| 갈래 | 들어가는 것 | 근거 |
|------|-------------|------|
| 제약 `constraints` | Context.md의 제약 제목 절과 그 하위 절 (제목 단계 무관 — `#### 금지`도 따로 떼어 제약으로 둔다. 범위는 아래 계층 규칙). CurrentFocus·Lessons의 이 프로젝트 블록·공통 블록 안에 있는 같은 규칙 제목 절(**기억의 적용 규칙**, `memory_rule: true`, `scope: project|common` 유지) | 제목에 `제약·원칙·규칙·금지·불변식·constraint(s)·principle(s)·rule(s)·guardrail(s)·invariant(s)` |
| 프로젝트 맥락 `context` | Context.md의 나머지 절(모르는 제목 포함), CurrentFocus·Lessons의 이 프로젝트 블록과 공통 블록 중 규칙 절이 아닌 부분, OpenLoops의 공통 블록 | 경로·marker 귀속 |
| 기록된 최근 결과·결정 `recent` | 최근 결정 최대 5건의 `## 결정` 절(없으면 한 줄짜리 frontmatter `summary:` 줄), 최근 3세션의 Process `## What Changed`, Plan `## Goal` | 제목·frontmatter |
| 명시적 후속 항목 `follow_ups` | 최근 3세션 Process의 `## Next Session`, OpenLoops의 이 프로젝트 marker 블록 | 제목·marker |
| 정보 부족·경고·근거 `gaps` | 아래 gaps 코드 목록. 본문에는 그 아래 `### 경고`(`warnings`의 **코드별 건수만** — 메시지·경로는 JSON에만)와 `### 근거 출처`(경로·source_version·줄 수)가 이어진다 | — |

- 기억의 적용 규칙은 Context 제약과 같은 예산(제약 단계)·생략 처리를 받는다 — 잘리면 `critical_omission`·`requires_read`. 공통 규칙과
  프로젝트 규칙, Context 제약이 서로 충돌해도 어느 쪽을 우선하거나 합치지 않고 출처(`scope`·경로)를 단 채 모두 싣는다.
  다른 프로젝트·소속 불명 블록의 규칙은 넣지 않는다. 블록 안 규칙이 아닌 이웃 구간은 하나의 맥락 항목으로 남는다.
  코드 펜스는 블록 단위로 본다 — 블록 안에서 닫히지 않은 펜스 뒤 제목은 제목으로 보지 않고, Context.md와 같이
  `unclosed_code_fence` gap으로 알린다(판정은 하지 않는다).
- 제목에 위 단어가 없는 절의 제약성 문장("반드시 dev 브랜치에서")은 맥락으로 남긴다. 내용을 읽어 제약으로 올리지 않는다.
- **제약 범위는 모든 제목의 계층으로 정한다.** 제목 하나는 자기 제목에 제약 단어가 있거나 상위 제목(자기보다 얕은 단계의 가장
  가까운 앞 제목들) 중 하나가 제약이면 제약이다. 같거나 얕은 단계의 제목이 나오면 그 범위가 끝난다. 항목은 1~3단계 제목과,
  제약 여부가 바뀌는 제목에서 끊는다 — 한 항목 안의 줄은 모두 같은 분류다. 예: `#### 제약` → `##### 금지` → `##### 세부 설명` →
  `#### 결과`에서 앞의 셋은 제약, `#### 결과`(와 그 아래)는 맥락이다.
- **Plan Goal은 후속 항목이 아니다** — 그 세션이 기록 당시 하려던 일이다. 완료 여부를 판정하지 않는다.
- 공통(전역) OpenLoops는 이 프로젝트의 후속 항목으로 보지 않고 맥락에 `scope: common`으로 둔다.
- 창과 순서는 기본 briefing과 같다: 결정은 `_list_decisions` 순서(후보+승격, superseded 제외) 앞 5건, 세션은
  `_recent_session_groups`(session_id로 묶어 최신 시각 순) 3개. 결정·세션의 소속 근거(`load_doc`)가 이 프로젝트로
  확정되지 않으면 넣지 않고 `attribution_mismatch`로 알린다.
- 과거 실패, 이후의 성공 기록, 같은 이름의 작업은 날짜·유사성으로 합치지 않는다. 각 세션의 Next Session은 그 세션 항목으로
  따로 남고, 나중 세션이 "성공"을 적었어도 이전 후속 항목을 지우거나 `resolved`를 붙이지 않는다.

### 후속 항목 상태

`sections[follow_ups]`의 `state`:

| state | 뜻 |
|-------|----|
| `has_items` | 기록에 명시된 후속 항목이 있다(기록 당시). `complete=false`면 확인하지 못한 출처가 있거나 후속 기록 일부가 본문에서 생략됐다 — 메시지에 "후속 작업 유무를 확인하지 못한 기록 있음"이 붙는다 |
| `none_in_scope` | 메시지 "**이 브리핑에 포함된 기록에는 명시된 후속 작업 없음**" — 대상 읽기가 완전하고, 최근 세션의 Next Session과 프로젝트 OpenLoops 블록이 모두 명시적 "없음"이거나 OpenLoops 블록이 없거나 비었고, 그 후속 기록이 본문에서 생략되지 않았다. 명시적 없음은 그 기록에만 해당하고, 범위 밖·현재 상태는 판정하지 않았다 |
| `unknown` | 메시지 "**후속 작업 유무를 확인하지 못한 기록 있음**" — 읽기 실패·생략(`unreadable`·`attribution_mismatch`·`unattributed`·`link_skipped`·partial)이거나, 데이터 부족(세션 기록 없음, Next Session 절 없음 `missing`, 빈 틀 `empty`, Plan만 `no_process`)이거나, 후속 기록(명시적 "없음" 포함)이 예산 때문에 본문에서 생략됐다. 없다고 말할 수 없다 |
| `not_evaluated` | 프로젝트를 확정하지 못해 보지 않았다 |

이유는 `unknown_reasons`로 구분한다: `{read_failed_or_skipped, partial, data_insufficient, no_sessions, omitted_from_text?}`.
`omitted_from_text`는 예산 배정 **뒤**에 센다 — 후속 항목 판단은 배정 결과까지 반영해 최종 확정한다(고정부 크기는 생략이 가장 많을 때의
메시지로 미리 잡아 상한을 넘지 않는다). 데이터 부족은 gaps에도
`follow_up_section_missing`·`follow_up_section_empty`(OpenLoops 빈 틀 블록 포함)·`orphan_plan`·`no_sessions`로 남는다 — 읽기 실패와 섞지 않고,
그 세션에 후속 작업이 있었는지 판정하지 않는다.

`sources_checked`에 출처마다 `items | explicit_none | empty | missing | no_process | unreadable | unattributed | block_empty | no_block`.
`unattributed`는 OpenLoops의 소속 unknown/conflict 블록이다 — 이 프로젝트 것일 수 있어 확인 불가로 센다.
OpenLoops 프로젝트 블록이 빈 틀("- ")뿐이면 `empty`(확인 불가), 제목만 남았으면(항목을 다 지운 상태) `block_empty`(없음).
명시적 없음은 내용이 `없음·없다·해당 없음·none·n/a` 한 줄일 때만이다 — "없음 — 단 실측은 남음"은 항목으로 본다.
Next Session과 프로젝트 OpenLoops 블록에 같은 규칙을 쓴다(`follow_up_state: explicit_none`, 원문 발췌는 남는다). 명시적 없음은 그 기록에만
해당한다 — 다른 세션·블록의 후속 항목을 지우거나 해결 처리하지 않는다.
빈 틀("- ")은 없음이 아니라 확인 불가다.

### 제약 상태

`sections[constraints].state`(Context.md 기준)와 `memory_rule_items`(기억의 적용 규칙 항목 수). state: `items`, `heading_empty`(제약 제목만 있고 빈 틀), `none_found`(제약 제목 절 없음 —
다른 제목 아래 제약성 문장은 판정 안 함), `no_context`(Context.md 없음), `unknown`(Context.md 또는 그 폴더를 읽지 못함 →
`critical_omission`), `not_evaluated`.

### gaps 코드

`no_context`, `context_unreadable`, `context_unverifiable`, `no_constraint_heading`, `constraint_section_empty`,
`context_stale`·`memory_stale`(30일, 기본 briefing과 같은 기준), `no_decisions`, `no_sessions`, `orphan_plan`,
`decisions_unverifiable`·`sessions_unverifiable`(읽은 기록은 없지만 읽지 못한 파일·폴더가 있다), `unclosed_code_fence`,
`attribution_mismatch`, `unattributed_block_excluded`(marker 소속이 unknown/conflict), `unregistered`, `vault_empty`,
`project_<status>`(식별 실패), `follow_up_section_missing`·`follow_up_section_empty`(후속 항목 데이터 부족).

## 정리 — 알려진 것만, 줄 번호는 그대로

정리는 줄을 **빼기만** 하고 줄 내용·번호를 바꾸지 않는다. 대상:

- `memory_marker`: `<!-- devtrail-memory-patch: … -->` 줄 (귀속 근거는 `block_evidence`로 남는다)
- `empty_scaffolding`: init-project/init-vault 템플릿 안내 줄(정확히 같은 문자열), 빈 불릿(`-`, `*`, `1.`)
- `repeated_title`: 이미 항목 이름으로 드러난 제목 — 문서 H1(`# Process`, `# Plan`, `# OpenLoops`, Context 제목),
  `## Next Session`·`## What Changed`·`## Goal`·`## 결정`, OpenLoops의 `## <프로젝트>`
- `empty_section`: 위를 빼고 나니 내용 없이 제목만 남은 절

코드 블록 안 줄은 건드리지 않고 제목으로도 보지 않는다. 코드 블록 판정은 CommonMark 펜스 규칙을 따른다 — 여는 펜스는
들여쓰기 0~3칸의 ` 또는 ~ 3개 이상, 닫는 펜스는 **같은 문자·여는 길이 이상**이고 뒤에 공백 말고는 없어야 한다
(`~~~markdown` 블록 안의 단독 ``` 줄은 블록을 닫지 않는다). 제목 탐지·정리·`unclosed_code_fence` 판정이 같은 규칙을 쓴다. 템플릿과 비슷하게 생긴 사용자 문장(`_(직접 쓴 메모)_`), 모르는 제목과 그 내용은 남는다.
빈 틀뿐인 Context 절은 항목을 만들지 않고 `sections[context].cleaned_sections`에 남긴다.

## 표시 순서와 예산 — text 20000자

- 상한은 `text` 본문 길이(문자 수)다. JSON 전체 크기나 토큰 수 상한이 아니다. JSON 전체는 `budget.response_chars`로
  재고, 60000자를 넘으면 `response_large` 경고를 붙인다(줄이거나 숨기지 않는다).
- **표시 순서**(`DISPLAY_ORDER`, 본문 `## 1.`~`## 5.`·`sections` 순서): 제약과 원칙 → 프로젝트 맥락 → 기록된 최근 결과와 결정 →
  명시된 후속 항목 → 정보 부족·경고·근거.
- **예산 배정 순서**(`BUDGET_ORDER`, 응답 `budget.budget_order`): 제약 → 프로젝트 맥락 → 명시된 후속 항목 → 최근 결과·결정.
  묶음으로는 `constraint` → `context_section`(Context 나머지)·`current_focus`·`lessons`·`common_open_loops` →
  `next_session`·`project_open_loops` → `decision`·`session_result`(What Changed)·`plan_goal`. 설계가 정하지 않은 단계 안
  하위 순서는 기존 구현 순서를 유지했다. 후속 항목은 맥락 **뒤에 표시**되지만 최근 결과·결정보다 **먼저 예산을 받는다** —
  표시 순서와 예산 순서는 다르다. 예산이 모자라면 최근 결과·결정 발췌부터 줄어든다(아래 고정 평가의 "본문 예산 초과" 사례).
- 고정부(머리말·상태 줄·세션/결정 목록 줄·후속 기록 위치 목록·gaps·경고·출처 목록)는 text 20000자 **안에** 들어가고 발췌보다 먼저 자리를 잡는다.
  고정부는 발췌의 배정 순서를 바꾸지 않는다.
- 항목·묶음 상한(발췌 줄 글자 수): Next Session 1500/항목, 결정 600/항목, What Changed 1200/항목, Plan Goal 400/항목,
  프로젝트 OpenLoops 6000, Context 나머지 6000, CurrentFocus 2000, Lessons 6000(뒤부터), 공통 OpenLoops 2000(뒤부터).
  제약은 전체 예산만 적용한다. 값은 기본 briefing의 상한에서 가져왔다.
- **발췌 자리를 미리 잡지 않는다.** 발췌 본문은 예산 순서 그대로 앞 묶음부터 남은 예산을 쓴다 — 고정부 뒤 남은 예산에 제약이
  다 들어가면 제약은 전부 실린다(뒤 묶음의 안내 줄·발췌 예약이 제약을 밀어내지 않는다). 예산이 바닥난 뒤의 작은 자투리에는
  뒤 항목의 짧은 줄이 들어갈 수 있다(제약의 다음 줄이 들어가지 않는 크기일 때만).
- 후속 기록의 위치는 **고정부**가 맡는다: 후속 항목 갈래에 `후속 기록 위치` 목록(항목 id·세션 순위·종류·경로·`L시작-L끝`, 20줄까지,
  넘으면 건수)을 항상 싣는다. 그래서 제약이 예산을 다 써도 후속 기록이 어디 있는지는 본문에 남는다. 결정·세션도 고정부 목록 줄이
  있다. 발췌가 다 빠진 항목은 남은 예산이 있으면 한 줄 안내(`본문 생략 L…-L… → read_note(…)`)를, 없으면 본문의 "안내도 못 낸
  생략 N건"과 JSON `omissions`로 드러난다.
- 본문의 경고는 코드별 건수 한 줄이다. 경고 수가 늘어도 고정부가 제약 발췌를 밀어내지 않고, 공유 후보 폴더의 다른 프로젝트 파일
  경로(파일명이 제목 구실을 한다)가 본문에 실리지 않는다. 메시지·경로는 JSON `warnings`에 있다 — 단 공유 후보 결정 폴더에서 빠진 파일은
  소속을 확인할 수 없어 JSON에도 파일명 없이 폴더 경로·사유·건수(`count`)로만 남는다. 이 프로젝트 것일 수도 있어 `partial`은 켠다.
  폴더 자체를 못 읽은 경우는 파일명이 없으므로 `read_failed`(폴더 경로·사유) 경고를 그대로 남긴다.
- 항목은 앞에서부터 **완전한 줄**만 넣는다. 못 넣은 꼬리는 하나의 구간으로 `omissions`에 남고 본문에
  `⋯ 생략 L시작-L끝 (이유) → read_note(…)` 줄이 붙는다. 이유: `budget`, `item_cap`, `group_cap`, `line_too_long`.
  append형인 Lessons·공통 OpenLoops는 반대로 블록도, 블록 안 줄도 **뒤(최신)부터** 넣고 앞 구간을 생략으로 남긴다
  (생략 줄이 발췌 앞에 붙는다).
- 고정부의 문서 유래 문자열(결정 제목·session_id·host 등)은 200자로 자르고, 목록(gaps·확인 못 한 출처·세션 파일 안내·출처)은
  20줄까지 낸다. 고정부만으로 상한을 넘으면 목록을 5줄, 0줄로 줄이고 개수만 적는다 — 어떤 vault에서도 text는 20000자를 넘지 않는다.
- 한 줄이 상한보다 길면 자르지 않는다(`line_too_long`, `line_chars`). **16000자(`read_note` structured의 줄 상한)를 넘는 줄은
  예산이 남아도 발췌하지 않는다** — 근거 위치·버전으로 회수할 수 없는 줄을 정상 발췌처럼 주지 않기 위해서다. 그 줄 **하나만**
  건너뛰고(본문에 `⋯ 생략 L n-L n (line_too_long) → read_note("경로")` 한 줄) 뒤의 읽을 수 있는 줄은 계속 배정한다 — 긴 줄 하나
  때문에 뒤 제약이 사라지거나 그 구간까지 전문 읽기로 뭉개지지 않는다. 건너뛴 줄마다 `omissions`에 따로 한 건
  (`lines:[n,n]`, `structured_readable=false`, `read`는 전문 읽기 인자 — 버전 확인 없음, `line_chars`)이 남고, 항목에는
  `unreadable_lines`, `line_exceeds_read_limit` gap이 붙는다. 제약 줄이면 `critical_omission`·`requires_read`다. 본문의 모든 발췌
  줄은 structured `read_note`(이어읽기 포함)로 회수된다.
- 예산 판정은 줄을 넣은 뒤 남는 구간의 **실제** 생략 줄 길이(그 자리에서 멈출 때의 이유·`read` 인자 그대로)로 한다. 최악 길이로
  잡아 들어갈 줄을 자르지 않는다. 남는 보수 오차는 구간 표시 줄(`@L…`)을 최대 자릿수로 잡은 몇 자뿐이다.
- 이어읽기 정보는 실제 `read_note` 페이지 규칙(400줄, 16000자 — 줄 사이 개행 포함, 16000자 넘는 줄 앞에서 멈춤)을 그대로 계산한다.
  `first_read_end_line`은 `read` 한 번이 돌려주는 마지막 줄, `read_continues: true`면 그 줄이 구간 끝보다 앞이다 — 응답의
  `next`(start_line·expected_version)로 이어 읽는다.
- 제약이 일부라도 빠지면 `critical: true` 생략이 되고 `critical_omission=true`, `requires_read`에 그 구간과 `read` 인자가 들어간다.
  본문 머리에도 경고 줄이 붙는다.
- 원문은 로더가 아니라 `evidence_search.load_doc`으로 직접 읽는다. 기본 briefing의 Context 5000자 사전 잘림이 후반 제약을
  숨기지 않는다. 로더(`ProjectMemoryLoader`·`AgentMemoryLoader`)는 바꾸지 않았다.

## 식별과 귀속

- 프로젝트는 `resolve_project`(명시적 근거: 등록 표기·SessionHandoffs 폴더·별칭·`.claude/vault.json`·owner/repo 매핑)로만
  확정한다. **repo 디렉터리 이름만으로는 확정하지 않는다** — 기본 briefing은 디렉터리 이름으로 매칭하므로 같은 입력에서
  결과가 다를 수 있다(`matching.hint`에 안내). 별칭 매핑 체계는 바꾸지 않았다.
- `unresolved / ambiguous / conflict / invalid`면 어떤 프로젝트 기록도 넣지 않는다. 후보는 `matching.candidates`.
- `unregistered`(매핑은 있지만 vault에 Context.md·SessionHandoffs가 없음)면 공통 메모리와 그 이름이 marker로 명시된 블록만 넣는다.
- 40_AgentMemory는 marker 블록 단위로 귀속한다(검색과 같은 규칙 — `evidence_search._marker_units`). 다른 프로젝트 블록은
  세기만 하고(`sections[context].excluded`), 소속 unknown/conflict 블록은 넣지 않고 `unattributed_block_excluded`로 알린다.
- 문서 제목도 블록으로 거른다. 본문 `# ` 제목 줄이 이 프로젝트·공통 블록 밖(다른 프로젝트·소속 불명 블록)에 있으면 항목 이름·
  `sources[].title`·신선도 경고에 그 제목 대신 파일명을 쓴다(근거 검색 `evidence_search._score`와 같은 규칙). frontmatter
  `title`은 파일 단위 값이라 그대로 쓴다.
- 등록부가 30_Projects 아래 폴더를 읽지 못하면, 그 폴더가 이 프로젝트의 Context.md일 수 있어 "Context 없음"으로 보고하지
  않고 `context_unverifiable`(critical)로 둔다. `requires_read`에는 그 폴더의 `Context.md` 경로가 `unverified: true`로 들어간다.
- 승격 결정은 Context.md가 있는 실제 폴더(`30_Projects/<폴더>/Decisions`)에서 읽는다 — 선언 이름과 폴더명이 다른 프로젝트도
  빠지지 않는다. 이를 위해 `_list_decisions`에 선택 인자 `project_dir`를 더했다(기본값이면 기존과 같다).
- 기본 목록 함수는 읽기·해석에 실패한 파일을 조용히 건너뛰고, Python 3.11 `glob`은 목록을 못 읽는 폴더를 빈 결과로 넘긴다.
  structured는 결정·세션 폴더를 직접 열어 보고 빠진 파일을 다시 세어 `read_failed`·`frontmatter_unparsed`·partial로 드러낸다.
- **읽기 경계**: structured는 결정·세션 목록 단계에서도 파일을 **열기 전에** 근거 검색 스캔(`evidence_search.scan_vault`)과 같은
  경계로 거른다 — 링크 파일과 실제 경로가 요청 경로와 다른 파일은 열지 않고 `link_skipped` 경고(경로만)로 알린다. 그래서
  vault 밖을 가리키는 링크의 제목·날짜도 응답에 들어오지 않는다. 이를 위해 `_list_decisions`·`_list_session_handoffs`에 선택
  인자 `path_filter`를 더했다(기본값이면 링크도 따라 읽는 기존 동작 그대로). 건너뛴 세션 링크가 있으면 후속 항목은 `unknown`이다.
- 소속 검증에 실패한 결정·세션 문서(`attribution_mismatch`)는 경로와 상태만 남긴다. 제목·날짜·session_id·host·agent·귀속 근거·
  문서 경고처럼 내용에서 온 값은 응답 어디에도(`sections`·`sources`·`warnings`·`text`) 싣지 않는다. 세션의 session_id·host·
  agent·유형도 목록 함수가 읽은 값이 아니라 검증을 통과한 문서에서 다시 꺼낸다.

## 검증

| 확인 | 위치 | 결과 |
|------|------|------|
| 기본 호출 키·본문 불변, structured 스키마 | `tests/test_project_briefing.py::test_default_briefing_keys_and_text_unchanged_by_structured_option` | 통과 |
| 갈래 구분·Plan Goal≠후속·정리·모르는 제목 보존·코드 블록 | `test_sections_*`, `test_known_scaffolding_*`, `test_cleanup_*` | 통과 |
| 결정 5건·세션 3개 창과 순서가 기본과 같음, 후보/정본·기록 시각 근거 | `test_recent_windows_and_order_match_default_briefing` | 통과 |
| 다른 프로젝트·소속 불명 블록 미주입, 식별 실패·동명 모호 | `test_other_project_*`, `test_unresolved_*`, `test_ambiguous_*` | 통과 |
| 후속: 실패/성공/동명 미병합, 명시적 없음·빈 틀·절 없음·Plan만·읽기 실패 | `test_follow_ups_*`, `test_explicit_none_*`, `test_missing_*`, `test_partial_*` | 통과 |
| 모든 발췌 = 원문 줄, 버전 일치, `read_source`로 회수, 비연속 구간, 원문 변경 시 `version_mismatch`, CRLF·BOM | `test_every_segment_*`, `test_crlf_*` | 통과 |
| 20000자·완전한 줄·제약 우선·정확한 생략 위치, 긴 Context 후반 제약, 제약 초과 critical, 과도한 한 줄, Context 읽기 실패, 빈 vault·미등록, 응답 크기 측정 | `test_late_constraint_*`, `test_constraints_over_budget_*`, `test_overlong_*`, `test_unreadable_context_*`, `test_empty_vault_*`, `test_response_*`, `test_large_response_*`, `test_many_unreadable_*`, `test_follow_ups_keep_a_location_line_*` | 통과 |
| 실제 stdio MCP 왕복: 도구 발견 → structured briefing → 근거 구간 읽기 → 원문 변경 후 버전 불일치 | `tests/test_mcp_stdio.py::test_cli_stdio_structured_briefing_then_evidence_read` (임시 vault, `python -m app.cli mcp-serve` 자식 프로세스) | 통과 |
| 독립 리뷰가 재현한 결함 7건의 회귀 — 소속 불명 OpenLoops 블록, 고정부 길이 폭주, 목록 못 읽는 폴더, 4단계 제약 제목·닫히지 않은 코드 블록, 폴더명≠선언명 결정, 빈 틀 OpenLoops 블록, append형 파일 최신 줄 | `test_unattributed_open_loops_*`, `test_long_fixed_parts_*`, `test_unlistable_*`, `test_deep_constraint_*`, `test_promoted_decisions_*`, `test_scaffold_only_open_loops_*`, `test_append_files_*`, `test_permission_denied_memory_dir_*` | 통과 |
| 병합 리뷰 지적 3건의 회귀 — 읽기 경계 밖 링크를 열지도 싣지도 않음(열린 파일 기록으로 확인), 소속 실패 문서는 경로·상태만, 펜스 종류·길이·정보 문자열·들여쓰기 규칙, 반환된 `read`를 MCP `read_note`에 그대로 전달 | `test_links_outside_read_boundary_*`, `test_attribution_failures_expose_only_*`, `test_fence_rules_*`, `test_late_constraint_after_mixed_fence_*`, `test_constraints_over_budget_*`·`test_overlong_*`(tool 함수에 `**read`), stdio 테스트(`read_note(**om["read"])`, `requires_read[].read`, 변경 후 같은 인자로 `version_mismatch`) | 통과 |
| 병합 리뷰 2차 지적 2건의 회귀 — 다른 프로젝트 블록 안 `# ` 제목이 항목 이름·`sources`·신선도 경고에 섞이지 않음(공통·자기 블록 제목은 유지), 중첩된 깊은 제약 절 뒤 같은 단계 제목부터는 맥락 | `test_title_line_inside_other_project_block_*`, `test_title_line_in_common_or_own_block_*`, `test_nested_deep_constraint_*`, `test_constraint_inheritance_uses_all_headings_*`, `test_context_blocks_unit` (고치기 전 코드에서 5건 실패 확인) | 통과 |
| 확정 설계 #7 순서 — 표시 순서(본문 `## 1.`~`## 5.`, 최근 결과·결정 발췌가 후속 항목보다 앞, 5번째 갈래에 gaps→경고→근거 출처), 예산 순서(제약→맥락→후속→최근 결과·결정: 예산이 최근 결과에서 바닥나고 맥락·후속은 예산으로 잘리지 않음, 이전 순서면 맥락이 잘림), structured에도 기본 키(`candidates`·`source_refs`) | `test_display_and_budget_orders_follow_design_7`, `test_budget_runs_out_in_recent_stage_not_in_context`, `test_display_order_in_text_puts_follow_ups_after_recent_and_gaps_warnings_sources_last`, `test_default_briefing_keys_and_text_unchanged_by_structured_option`, `tests/test_briefing_eval.py::test_budget_order_keeps_context_and_follow_ups_before_recent` (고치기 전 코드에서 5건 실패 확인) | 통과 |
| 독립 리뷰 3차 지적 3건의 회귀 — 많은 맥락 절의 위치 안내 예약이 제약을 밀어냄, 본문 경고 목록이 제약을 밀어냄, 다른 프로젝트 파일 경로가 경고로 본문에 실림. 후속 항목 문구를 설계 문구 그대로·읽기 실패와 데이터 부족 구분 | `test_many_context_sections_do_not_crowd_out_*`, `test_many_warnings_do_not_push_*`, `test_other_project_file_paths_in_warnings_*` (고치기 전 코드에서 3건 실패 확인), `test_explicit_none_*`, `test_missing_*`, `test_partial_*` | 통과 |
| 독립 리뷰 4차 지적 — Next Session 절 120개·OpenLoops 블록 120개일 때 미리 잡은 안내 줄이 제약을 밀어냄 (그때는 예약 수 상한으로 고쳤고, 지금은 예약 자체를 없앴다) | `test_many_follow_up_items_do_not_displace_constraints[*]` | 통과 |
| 독립 리뷰 5차 지적 — 작은 후속 항목(두 줄)이 위치 안내 줄을 잃음 (지금은 위치를 고정부 `후속 기록 위치` 목록이 맡는다) | `test_small_follow_up_keeps_location_without_taking_constraint_budget[*]` | 통과 |
| 병합 리뷰 BLOCK 지적 4건의 회귀 — 기억의 명시적 규칙 절을 제약으로(공통/프로젝트 귀속 유지, 잘리면 critical), 공유 후보 폴더의 귀속 불명 파일명을 JSON에서도 감춤(집계 경고), 프로젝트 OpenLoops의 명시적 없음, 예산 배정 뒤 후속 기록 생략을 최종 판단에 반영 | `test_memory_rule_headings_are_constraints_with_scope_kept`, `test_cut_memory_rule_raises_critical_omission_and_requires_read`, `test_other_project_file_paths_in_warnings_stay_out_of_text`, `test_links_outside_read_boundary_*`, `test_project_open_loops_explicit_none_is_scoped_like_next_session`, `test_follow_up_items_cut_from_text_mark_state_incomplete`, `test_explicit_none_records_cut_from_text_are_not_reported_as_none` (고치기 전 코드에서 8건 실패 확인) | 통과 |
| 병합 리뷰 4차(BLOCK) 지적 3건의 회귀 — 위치 안내·발췌 예약이 제약 예산을 먼저 가져감(예약 제거, 후속 위치는 고정부 목록), 16000자 넘는 줄을 회수 불가 발췌로 반환, 이어읽기 정보가 16000자 상한을 무시 | `test_constraint_that_fits_is_never_cut_for_later_stages`(고정부 뒤 남은 예산 = 제약 전체 비용으로 직접 재현), `test_line_over_read_limit_is_never_excerpted[16001/17000/19000]`(모든 발췌를 structured `read_note`로 회수), `test_read_continues_matches_actual_read_note_paging[*]`(실제 `read_note`의 end_line·next와 비교), `test_small_follow_up_keeps_location_*`, `test_follow_ups_keep_a_location_line_*` (고치기 전 코드에서 12건 실패 확인). 퍼즈 200 시드 — 모든 발췌가 structured 읽기(페이지 이어읽기)로 원문과 일치, 생략 440건의 `first_read_end_line`·`read_continues`가 실제 읽기와 일치 | 통과 |
| 독립 리뷰 6차 지적 2건의 회귀 — 16000자 넘는 줄 하나가 뒤 제약 줄까지 숨기고 그 구간을 전문 읽기로 뭉갬, 최악 길이 생략 줄 예약 때문에 들어갈 제약 줄이 잘림 | `test_over_limit_line_does_not_hide_later_constraints_or_widen_their_read`, `test_line_over_read_limit_is_never_excerpted[*]`(뒤 제약 표시·비연속 구간), `test_budget_cut_uses_exact_omission_note_length`(경계 900자를 1자 단위로 훑음) (고치기 전 코드에서 5건 실패 확인). 리뷰어 퍼즈 220 시드 — 예산 순서 위반·긴 줄 뒤 누락·발췌 회수 실패·이어읽기 불일치·상한 초과 0건 | 통과 |
| 기존 소비자 회귀(MCP·CLI·훅·식별·인계 정렬·메모리 격리) | 등록 전체 검사 | 797 통과. 지정 제외 3개(`test_session_markers` 2·`test_get_recent_sessions_groups_plan_and_process`)는 이 브랜치와 `main`에서 똑같이 실패한다 — 이번 변경과 무관 |

stdio 왕복은 **제품 왕복 검증**이다. 운영 PM(실사용 Claude 설정·런타임 트리·실제 vault)에는 적용·재연결하지 않았고,
그쪽 연결 확인은 별개다([`docs/mcp-search-connection.md`](mcp-search-connection.md)의 절차).

## 고정 평가 — 기본 vs structured

`python -m tests.briefing_eval` (회귀: `tests/test_briefing_eval.py`). 합성 fixture vault 6개 사례. 측정 정의는 스크립트 머리말.
조건: Python 3.11.2, Linux aarch64 컨테이너(10코어), 같은 프로세스 안 함수 호출(MCP 직렬화·전송 제외), briefing 5회 중앙값.
목표 줄은 사례마다 반드시 전달돼야 하는 원문 줄이고 종류(c 제약 · x 맥락 · f 후속)를 따로 센다.

| 사례 | 목표 줄 | text 문자 기본→새 | 응답 문자 기본→새 | text에 목표 줄 기본→새 | 위치·버전 확보 기본→새 | 확인 호출 기본→새 | 확인 문자 기본→새 | ms 기본→새 | critical_omission | 보존 제약·맥락·후속 기본→새 | 예산으로 준 항목(새) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 일반 | 7 | 5275→8626 | 6295→41594 | 7→7 | 0→7 | 6→1 | 8173→41594 | 1.0→4.1 | False | c2/2 x2/2 f3/3→c2/2 x2/2 f3/3 | - |
| 긴 Context 후반 제약 | 3 | 8993→12386 | 9860→43974 | 2→3 | 0→3 | 3→1 | 32394→43974 | 0.7→3.7 | False | c0/1 x1/1 f1/1→c1/1 x1/1 f1/1 | - |
| 이전 세션의 긴 Next Session | 2 | 5512→8926 | 6327→37245 | 0→2 | 0→2 | 3→1 | 8615→37245 | 0.7→2.8 | False | f0/2→f2/2 | - |
| 제약만 2만 자 초과 | 2 | 6127→19922 | 6702→57074 | 1→1 | 0→1 | 2→2 | 32108→64964 | 0.5→3.4 | True | c1/2→c1/2 | constraints 1, recent 6, follow_ups 3 |
| 본문 예산 초과 — 맥락·후속 vs 최근 결과 | 7 | 12353→19750 | 13221→60456 | 6→7 | 0→7 | 6→1 | 27853→60456 | 0.9→4.3 | False | c1/1 x4/4 f1/2→c1/1 x4/4 f2/2 | recent 2 |
| init-project 템플릿 | 1 | 477→991 | 630→5136 | 1→1 | 0→1 | 2→1 | 969→5136 | 0.2→0.5 | False | c1/1→c1/1 | - |

읽는 법:

- **더 길고 느리다.** text는 1.4~3.3배, 응답 JSON 전체는 4.5~8.5배, 조립 시간은 약 2.5~6.8배(밀리초 단위)다.
  "본문 예산 초과" 사례는 응답 JSON이 60456자로 `response_large` 경고(60000자) 기준을 넘는다 — 줄이지 않고 경고로 드러낸다.
  MCP 응답은 JSON 전체가 클라이언트 컨텍스트에 들어가므로 이 크기는 실제 비용이다. 성능 개선을 주장하지 않는다.
- "확인 문자"는 새 쪽이 오히려 크다 — 기본 briefing은 목표 줄 파일을 전문으로 더 읽어도 structured 응답 하나보다 작은 경우가
  많다. 새 응답이 줄이는 것은 호출 수와 줄 번호를 직접 세는 수고이고, 글자 수가 아니다.
- **예산 순서 확인**: "본문 예산 초과" 사례에서 예산은 최근 결과·결정 갈래(What Changed 2건)에서 바닥나고, 제약·맥락
  (Context·CurrentFocus·Lessons 앞뒤 블록)·후속(두 세션 Next Session 끝 줄)은 모두 본문에 남는다. 이전 구현 순서(후속·결정·결과
  다음에 맥락)였다면 같은 vault에서 Lessons 블록이 예산 때문에 빠진다(`tests/test_project_briefing.py::test_budget_runs_out_in_recent_stage_not_in_context`
  가 같은 구성으로 두 순서를 비교한다). 기본 briefing은 최신 Process 밖 Next Session을 400자로 잘라 후속 1개를 놓친다.
- "제약만 2만 자 초과" 사례는 제약이 고정부 뒤 예산을 모두 쓰고, 후속·최근 발췌는 예산 때문에 빠진다(예산 순서 그대로). 후속 기록의
  위치는 고정부 `후속 기록 위치` 목록에 남고 후속 판단은 "후속 작업 유무를 확인하지 못한 기록 있음"을 붙인다.
- 빈 틀뿐인 템플릿 Context도 새 응답이 더 길다 — 빈 틀은 지웠지만 매칭·상태·출처 줄이 더 붙는다.
- 보존: 긴 Context 후반 제약과 이전 세션의 긴 Next Session 끝 줄은 기본 briefing text에 없고 새 text에는 있다.
  제약이 2만 자를 넘는 사례는 둘 다 꼬리 제약을 못 싣지만, 새 응답은 `critical_omission`과 정확한 이어읽기 구간을 낸다
  (기본은 `_전문: read_note(...)_` 안내뿐).
- "확인 호출"은 목표 줄을 경로·줄 번호와 함께 확보하는 데 드는 호출 수다. 기본 briefing은 줄 번호·버전을 주지 않아
  파일마다 전문을 읽고 줄을 직접 세야 한다(버전은 얻을 수 없다). 새 응답은 본문에 보이는 목표 줄의 위치·버전을 이미 담는다.
- 합성 vault라 실제 사용자 vault의 문서 길이·세션 수 분포와 다를 수 있다. 실제 vault로는 재지 않았다.

### 응답 크기의 구성 — 무엇이 중복이고 왜 남겼나

"일반" 사례(응답 41594자)의 JSON 직렬화 크기: `sections` 23551 · `text` 8823 · `sources` 7039 · `budget` 906 ·
`source_refs` 665 · `matching` 287. `sections`의 34개 항목 중 발췌 원문(`segments[].text`)은 3168자뿐이고, 나머지는 항목마다
붙는 위치·출처 메타데이터다(`segments` 구간 5131 · `cleaned` 1824 · `path` 1560 · `source_version` 1462 · `recorded_at` 1019 ·
`label` 921 · `block_evidence` 848 …) 그리고 결정·세션·확인한 후속 출처 목록이다.

- 필수 중복으로 남긴 것: 발췌 줄이 `text`와 `segments[].text`에 두 번 들어간다(사람이 읽는 본문과, 줄 번호와 짝지은 기계 검증용).
  항목마다 `path`·`source_version`을 다시 싣는다(`sources`를 찾아보지 않고 바로 `read_note(expected_version=…)`로 넘기게).
  `source_refs`는 기본 호출과 같은 키를 유지하려고 `sources`의 경로를 다시 싣는다.
- 이번에 줄인 것: 예산 단계 표(`budget_stages`)를 응답에 추가하려다 `budget_order`와 같은 정보라 싣지 않았다.
- 줄이지 않은 것: `budget`의 정적 상수(`group_caps`·`item_caps`·순서, 약 900자)와 항목별 메타데이터 키는 문서화된 반환 계약이라
  임의로 빼지 않았다. 더 줄이려면(예: 항목의 `path`·`source_version`을 `sources` 참조 번호로 대체) 계약 변경이므로 따로 결정이 필요하다.

## 한계 · 하지 않은 것

- 기록 당시의 사실만 준다. 현재 작업 상태·외부 Task·운영 상태와 대조하지 않는다. 후속 항목의 완료 여부, 결정의 현재 유효성,
  중요도를 판정하지 않는다.
- 제약 판별은 제목 단어 목록에 의존한다. 목록에 없는 제목(예: "운영 메모") 아래 제약은 맥락으로 간다 — `no_constraint_heading`
  gap이 그 가능성을 알린다.
- 결정 발췌는 `## 결정`/`## Decision` 절 또는 한 줄짜리 `summary:`만 쓴다. 둘 다 없으면 제목·경로만 남긴다(`no_excerpt`).
- 기본 briefing과 식별 규칙이 다르다(디렉터리 이름 매칭 없음). 같은 repo 경로가 기본에서는 매칭되고 structured에서는
  `unresolved`일 수 있다 — `.claude/vault.json`이나 매핑으로 명시한다.
- 응답 JSON 크기에는 상한이 없다(측정·경고만).
- CLI·훅에 structured 옵션을 더하지 않았다.
