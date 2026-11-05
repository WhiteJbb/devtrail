# 프로젝트 근거 검색과 원문 구간 읽기 (structured 모드)

`search_vault`와 `read_note`에 `structured=True` 선택지를 더했다. 기존 호출은 그대로 동작한다.
목적은 "이 프로젝트에서 이 일을 언제 왜 했나"를 **적은 조회로, 정확한 원문 줄까지** 확인하는 것이다.

- 구현: `app/services/evidence_search.py`(검색), `app/services/source_reader.py`(구간 읽기),
  `app/services/project_identity.py`(프로젝트 식별), `app/services/vault_source.py`(경로 검증·줄 기준·버전)
- 진입점: MCP `search_vault` / `read_note`, Python `vault_tools.search_evidence` / `vault_tools.read_source`
- 테스트: `tests/test_evidence_search.py`, `tests/test_source_reader.py`, `tests/test_project_identity.py`,
  `tests/test_mcp_server.py`(실제 `call_tool` 경로), `tests/test_evidence_eval.py`(평가 Vault 비교)

## 호환 정책

| 항목 | 유지되는 것 |
|---|---|
| 도구 이름 | `search_vault`, `read_note` 그대로. 새 도구 없음 |
| 기본 호출 | `search_vault(query, limit=10)` → `[{path,title,status,score,summary}]` 리스트, `read_note(rel_path)` → 전문 문자열 |
| legacy 순위 | WikiService 점수, stable → candidate → raw 정렬, raw 예약(최대 3자리, limit의 1/3) 변경 없음 |
| 모순된 인자 | `structured=False`인데 `project`·`kinds`·`cursor`·`include_*`·`max_chars`(검색), `start_line`·`max_lines`·`max_chars`·`expected_version`(읽기)를 주면 **오류**다. 조용히 무시하면 범위를 줬다고 믿고 전체 결과를 읽게 된다 |
| 바뀐 것 | 심볼릭 링크로 금지 prefix(00_Inbox 등)나 vault 밖을 가리키는 파일은 legacy `read_note`도 거부하고 legacy `search_vault` 결과에서도 빠진다. 허용 prefix 안(숨김 폴더 포함)을 가리키는 링크는 전처럼 검색·읽기된다. 정상 파일의 순위는 그대로다 |

MCP 반환 스키마는 `list[dict] | dict`(검색), `str | dict`(읽기)로 넓어졌다. 기존 인자로 부르면 값의 형태는 이전과 같다.

## structured 검색

```text
search_vault(query, structured=True,
             project="",                # 프로젝트명·별칭·owner/repo·repo 디렉터리 경로. 비면 vault 전체
             include_common=False,      # 공통(전역) 문서·블록도 합친다
             include_unattributed=False,# 소속 불명·이 프로젝트가 걸린 소속 충돌도 합친다
             include_history=False,     # superseded/archived·_Archive 문서도 본다
             kinds=None,                # ["decision","problem","session_handoff",...]
             limit=None,                # 기본 5, 최대 20
             cursor="",                 # 이전 응답의 next_cursor
             max_chars=None)            # 응답 전체 JSON 문자 수. 기본·최대 12000, 최소 3000 (응답 고정부 + 압축형 결과 1건)
```

`kinds` 값: `context decision problem plan design conversation prompt_log project_doc knowledge agent_memory
memory_patch blog_idea career_bullet session_handoff session_log worklog output task other` (경로로 정한다).

### 분량 상한

| 항목 | 값 | 근거 |
|---|---|---|
| 결과 수 | 기본 5, 최대 20 | 설계 확정값 |
| 문서당 발췌 | 최대 2개, 각 800자 | 설계 확정값 |
| 응답 전체 | 기본·최대 12000자 (JSON 직렬화 길이, `budget.used_chars`가 실제 길이) | 설계 확정값 — 줄일 수만 있다 |
| 근거 창 | 연속 5줄 | 구현 상수 `_WINDOW_LINES` |
| 반복 인정 | 토큰당 3회 | 구현 상수 `_FREQ_CAP` |
| 질의 | 300자·단어 32개 이하 (`query`·`project` 모두) | 응답에 되돌려 싣는 값이라 길이를 묶어야 응답 상한을 보장할 수 있다 |
| 결과 안 메타데이터 | 제목 200자, `attribution.blocks` 10개, `duplicates` 10개, 문서 경고 5개, 근거 문자열 160자 | 초과분은 `blocks_omitted`(개수·첫 줄·끝 줄), `duplicates_omitted`, `warnings_omitted`로 남긴다 |

**성공 응답은 언제나 `max_chars` 이하다.** 예산을 넘기면 그 결과의 발췌를 1개로 줄여 보고, 그래도 넘치면 그 앞에서
멈춘다(`budget.stopped_by="budget"`, `has_more=true`, `next_cursor`로 이어 받는다). 첫 결과가 발췌 1개로도 넘치면
줄여서라도 1건은 낸다 — 0건 페이지가 무한 이어받기를 만들지 않게 한다:

1. 최소형: 발췌·중복 목록·문서 경고를 개수로만 남기고 블록은 1개만(`blocks_omitted`)
2. 압축형(`compacted: true`): 경로·제목 80자·종류·등급·상태 class·소속·관련도 그룹·`excerpt_lines`(발췌했을 줄 범위)·버전만
3. 응답 공통부의 뒤 경고부터 `warnings_omitted`로 바꾼다

그래도 넘치면(아주 긴 경로 등) 성공으로 내지 않고 `ok=false`, `error.code="budget_too_small"`(`needed_chars` 포함)를 돌려준다.
1·2단계에 들어가면 `budget_exceeded` 경고가 붙는다.

### 응답

```json
{
  "ok": true,
  "query": "Context 상한 5000자", "tokens": ["context", "상한", "5000자"],
  "scope": {"project": "Devtrail", "project_resolution": {"status": "resolved", "method": "canonical", "evidence": ["context:30_Projects/Devtrail/Context.md"], "...": "..."},
            "include_common": false, "include_unattributed": false, "include_history": false, "kinds": [],
            "read_prefixes": ["20_Knowledge/", "..."]},
  "filtered": {"documents": {"other_project": 12, "common": 7, "unknown": 30, "history": 1}, "blocks": {"other_project": 4}},
  "offset": 0, "returned": 5, "total_matches": 9, "has_more": true, "next_cursor": "eyJ2Ijo…",
  "partial": false, "warnings": [], "warnings_omitted": 0,
  "budget": {"max_chars": 12000, "used_chars": 6234, "stopped_by": "limit", "excerpt_max_chars": 800, "excerpts_per_doc": 2},
  "results": [{
    "rank": 1,
    "path": "60_Candidates/SessionHandoffs/Devtrail/2026-10-27 Process.md",
    "title": "Process — briefing 상한",
    "kind": "session_handoff", "kind_source": "path", "declared_type": "candidate",
    "record_tier": "candidate",
    "status": {"declared": "candidate", "class": "known", "reason": "meta:status=candidate"},
    "attribution": {"scope": "project", "project": "Devtrail",
                    "evidence": ["path:60_Candidates/SessionHandoffs/Devtrail/", "meta:project=Devtrail"]},
    "time": {"value": "2026-10-27T10:00:00", "source": "meta:created_at"},
    "relevance": {"token_coverage": "3/3", "window_coverage": "3/3", "phrase": false, "group": [3, 3, 0]},
    "matched_terms": ["context", "상한", "5000자"],
    "matched_fields": {"context": ["body"], "상한": ["title", "body"], "5000자": ["body"]},
    "excerpts": [{"start_line": 128, "end_line": 129, "text": "- 막힌 점: Context 상한이 …", "matched_terms": ["context", "상한", "5000자"], "truncated": false}],
    "source_version": "sha256:1f0c…",
    "total_lines": 132,
    "duplicates": [{"path": "10_Worklog/Sessions/2026-10-27-devtrail.md", "reason": "same_session_id", "source_version": "sha256:…"}]
  }],
  "elapsed_ms": 7
}
```

- `total_matches`: 범위 안 일치 문서 수(중복 출처를 묶은 뒤). **스캔이 불완전하면(`partial=true`) `null`** — 모르는 수를 만들지 않는다.
- `filtered`: 점수화 전에 범위 밖이라 뺀 문서·블록 수(이유별). 0건일 때 범위를 넓힐지는 이 값을 보고 호출자가 정한다.
- `excerpts[].text`는 언제나 **완전한 원문 줄**이다(줄 중간을 자르지 않는다). 800자에 맞추려고 뒷줄을 덜었으면
  `truncated: true`와 `omitted_lines`가 붙는다.
- 첫 줄 하나가 800자보다 길면 그 발췌는 `text: null`, `line_too_long: {line, line_chars}`다 — 줄 일부를 근거처럼 내지 않는다.
  그 줄은 `read_note(structured=True, start_line=line, max_lines=1, max_chars>=line_chars)`로 통째로 읽는다(16000자 이하일 때).
  같은 근거 창의 뒷줄은 `omitted_lines`로 남고, 발췌 겹침은 실제로 낸 줄 범위로 판정하므로 그 뒷줄 근거는 두 번째 발췌로 나온다
  (발췌 자리가 남아 있으면).
- `duplicates`: 명시적 동일 출처만 묶는다.
  ① `same_content` — 본문 바이트·**파일명**·파일 소속이 모두 같다(curator 승격과 `_Archive` 보관은 파일명을 유지한다).
  파일명이 다르면 본문이 같아도(빈 템플릿 결정 등) 서로 다른 문서로 보고, 소속이 다르면 다른 프로젝트 문서로 본다.
  ② `same_session_id` — 같은 프로젝트·같은 `session_id`의 `10_Worklog/Sessions` 세션 원문과 SessionHandoff Process.
  Plan·결정 후보는 내용이 달라 묶지 않는다. 대표는 순위가 높은 쪽이다.
- 묶인 사본도 자기 근거를 남긴다: `{path, reason, source_version, record_tier, status{declared,class},
  attribution{scope,project}, excerpt_lines}` — `excerpt_lines`는 그 사본 파일에서 근거가 있는 줄 범위다(frontmatter 길이가
  달라 대표와 줄 번호가 다를 수 있다).

### 범위: 파일 소속과 블록 소속

소속은 **파일 단위**와 **블록 단위**를 따로 판정한다. 프로젝트명이 본문에 나온다는 사실은 근거가 아니다.

| 근거 | 판정 |
|---|---|
| `30_Projects/<dir>/…` | `<dir>`의 Context.md가 선언한 프로젝트 (없으면 폴더명) |
| `60_Candidates/SessionHandoffs/<P>/…` (`_Archive` 아래 포함) | `<P>` |
| `20_Knowledge/<P>/…` | `<P>`가 등록 프로젝트(Context.md 또는 SessionHandoffs 폴더 — 프로젝트 식별과 같은 기준)일 때만 (curator가 프로젝트 knowledge를 두는 곳). `20_Knowledge/AI/` 같은 주제 폴더는 근거가 아니다 |
| frontmatter `project:` | 그 프로젝트. 값은 식별과 **같은 근거·같은 순서로만** 정규화한다 — 등록 표기 → SessionHandoffs 폴더 → 매핑 별칭(가리키는 프로젝트가 하나일 때만). 식별이 인정하지 않는 이름(예: 선언명과 다른 30_Projects 폴더명)은 바꾸지 않는다 — 식별로 확정한 프로젝트가 자기 문서를 다른 프로젝트로 판정하지 않게. 정규화했으면 evidence가 `meta:project=dt→Devtrail` 꼴이다. marker의 `project`도 같다 |
| 경로와 frontmatter가 다르다 | `conflict` (`conflict_with`에 둘 다) |
| frontmatter `scope: global` | 공통 (memory_patch가 쓰는 값. 출신 프로젝트는 evidence에 남긴다) |
| `40_AgentMemory/…` (위 근거 없음) | 공통 — AGENTS.md가 "전역 AI 메모리"로 정의한 경로 규칙 |
| 아무 근거 없음 (`50_Outputs` digest, `70_Tasks` 등) | `unknown`. 메타데이터가 없다고 공통으로 보지 않는다 |

marker 문서에서는 제목(본문 `# ` 줄에서 얻은 경우)과 인라인 `#태그`도 범위 안 블록에서 온 것만 쓴다 — 범위 밖 블록의
제목 줄이면 응답 제목은 파일명이다.

블록: `40_AgentMemory/` 문서는 `<!-- devtrail-memory-patch: {...} -->` marker로 나눈다(agent_memory_loader·curator·
update_open_loops가 쓰는 형식). marker 앞은 파일 소속(보통 공통), `{"scope":"project","project":P}` 블록은 P,
`{"scope":"global"}` 블록은 공통, JSON이 깨졌거나 scope/project를 해석할 수 없으면 `unknown` + 경고 +
`invalid_marker: true`. 손상 marker 블록은 필터 집계에서 "근거 없음(`unknown`)"과 구분해 `filtered.blocks.invalid_marker`로 센다.
블록 경계는 `<!-- devtrail-memory-patch:` 접두로 감지한다 — 닫는 `-->`가 빠진 marker도 경계로 보고 그 블록을 `unknown`으로 둔다
(경계로 안 보면 그 아래 블록이 앞 블록 소속에 흡수된다). 이 처리는 검색에만 적용된다 — briefing 로더(`agent_memory_loader`)는 바꾸지 않았다.

`project`를 주면:

- 기본: 그 프로젝트 소속 파일·블록만. 공통·타 프로젝트·unknown·conflict 제외.
- `include_common=True`: 공통을 더한다. 타 프로젝트는 여전히 제외.
- `include_unattributed=True`: unknown과 **그 프로젝트가 한쪽인** conflict를 더한다.
- 제외된 블록은 점수·발췌 계산에 들어가지 않는다(같은 파일의 다른 블록만 본다). `attribution.blocks`는 포함된
  블록만, `blocks_excluded`는 뺀 블록 수.
- 0건이어도 범위를 자동으로 넓히지 않는다(`no_match_in_scope` 경고).

`project`를 안 주면 vault 전체를 보고 각 결과에 소속을 표시한다(`include_common`/`include_unattributed`를 주면 인자 오류).

소속 필터는 **접근 권한이 아니다.** 읽기 권한 경계는 기존 read_scope(아래 "경로 보안") 하나뿐이고, 같은
read_scope 안이면 `read_note`로 어느 프로젝트 문서든 읽을 수 있다.

### 순위

1. 토큰 충족도 — 질의 토큰 중 문서(제목·경로·태그·summary·범위 안 본문)에 나온 수
2. 같은 근거 창 충족도 — 연속 5줄 안에 함께 나온 토큰 수의 최댓값
3. 구절 일치 — 질의 전체(공백 정규화)가 한 줄 또는 제목에 그대로 있다 (토큰 1개면 그룹을 가르지 않는다)
4. (같은 그룹 안) 이력(superseded/archived) 문서는 뒤
5. (같은 그룹 안) 정본 우대 — stable → candidate → raw
6. 반복 점수(토큰당 3회 상한) → 경로

토큰 규칙은 legacy와 같다(`[0-9A-Za-z가-힣_+-]+`, 2글자 이상, 소문자, 부분 문자열 일치). 그래서 한 글자 낱말(예: "핀")은
검색어에서 빠진다. structured에는 종류별 고정 자리(raw 예약)가 없다 — 정확한 세션 근거는 관련도로 앞에 온다.

### 상태(status)와 기록 등급(record_tier)

`record_tier`는 경로가 정한다(stable=20/30/40, candidate=60, raw=10/50/70). `status`는 frontmatter 선언 값을
그대로 돌려주고 분류만 한다. **현재 유효한지 판정하지 않는다.**

| class | 뜻 | 기본 검색 |
|---|---|---|
| `known` | 아래 조사 목록에 있는 값 | 포함 |
| `unknown` | 목록에 없는 값 또는 문자열이 아닌 값 — 문서에 경고 "유효성 미인증" | 포함 |
| `absent` | status 없음 | 포함 |
| `history` | `superseded`/`archived` 선언, 또는 `60_Candidates/_Archive/` 위치 | 제외 (`include_history=True`로 조회) |

상태 값 근거 (2026-11-05 코드 조사):

| 값 | 쓰는 곳 |
|---|---|
| `candidate` | `app/services/candidate_writer.py` (모든 후보) |
| `accepted` / `stable` | `app/agents/curator_agent.py` promote (decision / 그 외) |
| `applied` | curator `apply_memory_patch` 뒤 후보 |
| `promoted` | `app/services/retention.py`가 읽는 승격 표시 |
| `raw` | `app/agents/capture_agent.py` 세션 원문 |
| `generated` | weekly_review_agent, nightly_distill_agent digest |
| `draft` / `review` / `published` | `app/agents/wiki_blog_agent.py` |
| `active` | Context.md·AgentMemory 기본 템플릿 (`wiki_service`) |
| `superseded` | `vault_tools._list_decisions`가 이력으로 숨긴다 |
| `archived` | 코드에서 쓰는 곳 없음. 보관을 선언하는 값이라 이력으로 본다 |

frontmatter: 첫 줄과 닫는 줄이 `---`여도 그 사이가 YAML **매핑**으로 해석되지 않으면(문법 오류, 문자열 한 줄, 목록 등. 비었거나 주석뿐이면 정상) 메타데이터 없이
파일 전체를 본문으로 본다(경고 "frontmatter를 해석하지 못해…"). 수평선으로 시작하는 노트의 앞줄이 검색에서 사라지지 않게 하려는 것이다.

특수 문서 구조: SessionHandoffs의 `handoff_type`(plan/process)·`session_id`, AgentMemory marker 블록,
OpenLoops `## <project>` 블록(marker로 감싸짐). 지원하지 않는 형식은 결과의 `warnings`로 드러난다 —
닫히지 않은 frontmatter, 해석 실패한 frontmatter, 문자열이 아닌 `project`/`status`, 깨진 marker, UTF-8이 아닌 파일.

`time.source`는 `meta:updated_at` → `meta:created_at` → `meta:date` → `meta:promoted_at` → `file_mtime` 순으로 처음 있는 것.

### cursor

`next_cursor`는 (검색 조건 지문, 스캔 상태 지문, 다음 offset)을 담는다. 스캔 상태 지문은 **범위 필터를 통과한 모든 문서**
(일치 여부와 무관 — 묶인 중복 사본 포함)의 경로·`source_version`·상태 class·파일/블록 소속과, 읽기 실패 경로 목록·`partial`로 만든다.

| 상황 | 결과 |
|---|---|
| 같은 조건으로 넘김 (`limit`·`max_chars`는 바꿔도 된다) | 다음 페이지 |
| query·project·include_*·kinds가 다르다 | `cursor_mismatch` |
| 범위 안 문서가 늘거나 줄거나 내용(버전)이 바뀌었다 — 일치하지 않는 문서여도 | `cursor_stale` |
| 내용은 그대로인데 소속(등록부·매핑 변화)이나 상태 class가 바뀌었다 | `cursor_stale` |
| 앞 페이지는 `partial`(읽기 실패)이었는데 지금은 읽힌다, 또는 반대 | `cursor_stale` |
| 범위 밖 문서(다른 프로젝트, 금지 prefix)만 바뀌었다 | 그대로 이어진다 |
| 해석 불가·이전 형식(v1) cursor | `cursor_invalid` |

`project` 없이 vault 전체를 검색하면 모든 허용 prefix 문서가 범위 안이라, 어느 문서가 바뀌어도 `cursor_stale`이다.
이어 받기가 끊기면 cursor 없이 처음부터 다시 검색한다 — 순위가 바뀌었을 수 있는 페이지를 이어 붙이지 않는 쪽을 택했다.

## structured 원문 구간 읽기

```text
read_note(rel_path, structured=True,
          start_line=None,        # 기본 1
          max_lines=None,         # 기본 120, 최대 400
          max_chars=None,         # content 기본·최대 16000, 최소 200
          expected_version="")    # 이전 페이지의 source_version
```

```json
{"ok": true, "path": "10_Worklog/Sessions/x.md", "record_tier": "raw", "source_version": "sha256:…",
 "total_lines": 132, "line_ending": "lf", "frontmatter_lines": [1, 9], "line_basis": "frontmatter 포함 파일 전체, 1부터",
 "start_line": 121, "end_line": 132, "returned_lines": 12, "content": "…",
 "truncated": false, "truncation_reason": null, "long_line": null, "eof": true, "next": null, "warnings": []}
```

- frontmatter 경계는 python-frontmatter와 같다: 첫 줄과 닫는 줄이 `-{3,}`(뒤 공백 허용).
- 줄 기준: frontmatter를 포함한 파일 전체, 1부터. 줄 끝은 `\r\n`·`\n`만 인정한다(`\x0b`·`\u2028` 등은 줄 끝이 아니다).
  파일 끝 줄바꿈 뒤 빈 문자열은 줄이 아니다. 검색 발췌의 `start_line`/`end_line`과 같은 기준이다.
- `content`의 줄 구분은 항상 `\n`이다(원래 줄 끝은 `line_ending`: lf/crlf/mixed/none). UTF-8 BOM은 content에서 빼고 경고한다.
- `content`는 **완전한 줄만** 담는다. 줄 중간에서 자르거나 줄 안 문자 위치로 이어 읽는 방식(char_offset)은 쓰지 않는다.
- `truncation_reason`: `max_lines`, `max_chars`(다음 줄이 남은 자리에 안 들어간다), `line_too_long`(다음 줄 하나가 max_chars보다
  길다 — 그 앞에서 멈추고 `long_line: {line, line_chars}`로 알린다).
- `next`가 있으면 `{start_line, expected_version}`를 그대로 넘긴다. `next=null`이면 EOF다.
- 요청한 첫 줄이 max_chars보다 길면 내용 없이 `ok=false`, `error.code="line_too_long"`이다. `error`에 `line`·`line_chars`·`max_chars`·
  `readable_with_max_chars`(16000자 이하라 max_chars를 올리면 통째로 읽힌다)·`next`가 있다. **`error.next`는 그 다음 줄**이라
  같은 줄을 다시 가리키지 않는다(마지막 줄이면 `null`). 16000자보다 긴 줄은 structured로 읽을 수 없고, 전문은 기존
  `read_note(structured=False)`로 읽는다.
- 끝남 보장: 성공 페이지는 최소 한 줄을 소비하고(`next.start_line = end_line + 1`), `line_too_long` 결과는 그 줄을 건너뛴다.
  그래서 `next`/`error.next`를 따라가면 반드시 끝난다 — 무한 이어읽기가 없다.
- 빈 파일: `ok=true`, `total_lines=0`, `content=""`, `eof=true`, 경고 "빈 파일". 

오류(`ok=false`, `error.code`):

| code | 뜻 |
|---|---|
| `invalid_argument` | 범위를 벗어난 인자 |
| `scope_violation` | read_scope 밖, 절대경로, `..`, 실제 경로가 범위 밖인 심볼릭 링크 |
| `not_found` | 파일 없음 |
| `out_of_range` | `start_line`이 전체 줄 수를 넘음 (빈 성공으로 위장하지 않는다) |
| `line_too_long` | 요청한 첫 줄이 max_chars보다 길다 — 줄을 잘라 주지 않는다. `error.next`로 다음 줄부터 이어 간다 |
| `version_mismatch` | `expected_version`과 현재 버전이 다르다 — 내용 없이 돌려준다. 처음부터 다시 읽는다 |
| `read_failed` | 파일 읽기 실패 |

검색 오류 코드: `invalid_argument`, `project_unresolved` / `project_ambiguous` / `project_conflict` /
`project_unregistered` / `project_invalid`(식별 실패 — 검색하지 않는다), `cursor_invalid` / `cursor_mismatch` / `cursor_stale`.
검색 중 파일 읽기 실패는 오류가 아니라 `partial=true` + `read_failed` 경고다.

## 경로 보안

실제 경로(`os.path.realpath`)를 푼 뒤 vault 안인지, 허용 prefix
(`20_Knowledge/ 30_Projects/ 40_AgentMemory/ 60_Candidates/ 10_Worklog/ 50_Outputs/ 70_Tasks/`) 안인지를 **파일을 열기 전에** 본다.

| 경로 | 검사 |
|---|---|
| structured 검색 | 링크된 디렉터리는 따라가지 않고(`symlink_dir_skipped`), 링크 파일은 읽지 않는다(`outside_scope_link` / `symlink_file_skipped` — 대상이 범위 안이면 대상 경로로 검색된다). 숨김 폴더도 보지 않는다 |
| legacy 검색 | `WikiService.search(path_filter=…)`로 파일을 열기 전에 거른다. 금지 prefix·vault 밖 대상은 읽지도 않고, 허용 prefix 안 대상(숨김 폴더 포함)은 전처럼 검색된다. 읽을 수 없는 파일(깨진 링크 등)은 건너뛴다 — 전에는 검색 전체가 예외로 멈췄다 |
| 프로젝트 등록부 | Context.md·SessionHandoffs 폴더가 링크면 읽지 않고 경고만 남긴다 |
| structured·legacy 읽기 | 범위 밖 실제 경로는 거부. 기존 `read_note`처럼 숨김 폴더 안 파일은 읽는다 |

## 프로젝트 식별

명시적 근거로만 확정한다. repo 디렉터리 basename이 프로젝트명과 같다는 사실은 근거가 아니다(`hint`로만 알린다) —
fork나 동명 개인 repo를 그 프로젝트로 확정하면 다른 프로젝트 근거가 섞인다. (`get_project_briefing`의 기존 basename
매칭은 이번 범위가 아니라 그대로다.)

| method | 근거 |
|---|---|
| `canonical` | `30_Projects/<dir>/Context.md`의 frontmatter `project`(없으면 폴더명)와 대소문자 무시 일치 |
| `handoff_folder` | `60_Candidates/SessionHandoffs/<P>/` 폴더명과 일치 (Context.md 없이 세션 기록만 있는 프로젝트) |
| `alias` | 식별 매핑 파일의 `aliases` (가리키는 프로젝트가 vault에 없으면 `unregistered`) |
| `local_mapping` | repo 디렉터리의 `.claude/vault.json` `{"project": …}`. 경로는 절대·`~`·`./`·`../` 형태만 경로로 본다 — 맨 이름은 서버 cwd의 같은 이름 디렉터리가 있어도 프로젝트 이름으로 판정한다 |
| `repo_mapping` | `owner/repo`(직접 입력, https/ssh URL, 또는 repo의 `.git/config` remote) → 매핑 파일의 `repos` |

| status | 뜻 | 검색 |
|---|---|---|
| `resolved` | 근거 하나로 확정 | 진행 |
| `unresolved` | 근거 없음 (`candidates`에 등록 프로젝트) | 거부 |
| `ambiguous` | 같은 이름을 선언한 Context.md가 둘 이상, 별칭이 다른 canonical과 겹침. 별칭·owner/repo·`.claude/vault.json`·remote 경로로 그 이름을 가리켜도 같다 | 거부 |
| `conflict` | `.claude/vault.json`과 remote 매핑이 다른 프로젝트, 한 repo가 두 프로젝트에 매핑 | 거부 |
| `unregistered` | 매핑은 있지만 vault에 Context.md·SessionHandoffs가 없다 | 거부 |

식별 매핑 파일은 선택이다. `.env`에 경로를 준다:

```bash
DEVTRAIL_PROJECT_MAP=/path/to/project-map.json
```

형식(`docs/examples/project-map.example.json`):

```json
{
  "version": 1,
  "projects": {
    "Devtrail": {"aliases": ["devtrail-cli", "dt"], "repos": ["WhiteJbb/devtrail"]}
  }
}
```

식별 전용이다 — 프로젝트 상태·설명·목록을 여기에 복제하지 않고, 외부와 동기화하지 않는다. 파일이 없거나 깨지면
경고만 남기고 canonical 식별은 계속된다.

## 평가 (고정 평가 Vault, 이전/새 방식 비교)

`python -m tests.evidence_eval [결과.json] [추가 문서 수]`로 다시 잴 수 있다. 평가 Vault(`tests/evidence_eval.py`)는
실제 vault 구조(SessionHandoffs Process, Decisions, AgentMemory marker, Digest, 두 프로젝트)를 본뜬 합성 문서 19개이고,
사례마다 정답 문서와 줄 범위를 고정했다. legacy는 `search_vault(limit=5)` 후 summary에 근거가 없으면 `read_note` 전문,
structured는 `search_vault(structured=True, project=…)` 후 발췌가 정답 줄을 덮지 않으면 그 구간만 읽는다고 보고 셌다.

2026-11-05 재측정 — 긴 줄·cursor·중복·리뷰 반영 뒤 (Pyodide 0.27.7 / CPython 3.12.7 wasm, Node 26 — 아래 "한계" 참고):

| 사례 | 종류 | 정답 | legacy 순위 | 새 순위 | legacy 응답에 근거 | 새 응답에 근거 | 호출 legacy→새 | 문자 legacy→새 | ms legacy→새 | 타 프로젝트(상위5) legacy→새 | superseded(상위5) legacy→새 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mcp 개명 문제 | regression | `30_Projects/Devtrail/Problems/mcp 2.x 개명.md:16-16` | 2 | 1 | 아니오 | 예 | 2→1 | 595→1913 | 13.1→8.7 | 0→0 | 0→0 |
| Stop 훅 결정 | regression | `30_Projects/Devtrail/Decisions/2026-10-19 Stop 훅 parent_pid.md:12-12` | 1 | 1 | 예 | 예 | 1→1 | 528→3848 | 5.7→6.9 | 0→0 | 0→0 |
| 자동 승격 결정 | history | `30_Projects/Devtrail/Decisions/2026-10-18 검토 게이트 제거.md:12-12` | 2 | 1 | 예 | 예 | 1→1 | 655→1932 | 5.6→6.4 | 0→0 | 1→0 |
| Context 상한 세션 근거 | inversion | `60_Candidates/SessionHandoffs/Devtrail/2026-10-27 Process.md:128-129` | 없음 | 1 | 아니오 | 예 | -→1 | 797→3713 | 5.4→6.6 | 0→0 | 0→0 |
| 조상 pid 매칭 세션 근거 | late | `10_Worklog/Sessions/2026-10-19-stop-hook.md:79-80` | 3 | 1 | 아니오 | 예 | 2→1 | 3061→2936 | 5.6→6.3 | 0→0 | 0→0 |
| 다른 프로젝트 격리 | isolation | `60_Candidates/SessionHandoffs/rpg-game-web/2026-10-20 Process.md:14-14` | 없음 | 1 | 아니오 | 예 | -→1 | 797→2890 | 5.3→5.8 | 2→0 | 0→0 |
| Lessons 프로젝트 블록 | isolation | `40_AgentMemory/06_Lessons.md:12-12` | 1 | 1 | 아니오 | 예 | 2→1 | 473→2048 | 5.9→6.3 | 0→0 | 0→0 |

규모: 같은 Vault에 세션 원문 1000개(각 약 3천 자)를 더했을 때 검색 1회 중앙값 legacy 287.5ms, structured 301.0ms (5회).
legacy는 파일을 열기 전 실제 경로 검사(realpath)를 더해 기능 이전보다 느려졌다 — 같은 조건 A/B(5회 중앙값, 이전 측정)에서 256.4ms → 286.6ms(약 12%).
대신 금지 prefix·vault 밖 링크 대상과 00_Inbox 등 범위 밖 파일은 더 이상 열지 않는다.

이전 측정 대비 바뀐 값: "Context 상한 세션 근거"의 새 응답이 3543자 → 3713자. 묶인 사본(세션 원문)의 근거(등급·상태·소속·발췌 줄)를
함께 싣기 때문이다. 순위·근거 적중·호출 수는 같다.

읽는 법:

- legacy 상위 5에 정답이 있던 5건(regression 2·history·late·Lessons)은 모두 structured 상위 5(실제로는 1위)에 남았다 — `tests/test_evidence_eval.py`가 회귀로 막는다.
- 관련도 역전: legacy는 stable을 무조건 앞에 둬 단어 하나만 맞는 정본 5개가 정확한 세션 근거(후보·원문)를 밀어냈다. structured는 1위.
- 후반 근거: legacy summary는 문서 첫 줄이라 128행·80행 근거가 안 보여 전문 읽기가 한 번 더 필요했다. structured는 발췌가 그 줄이다.
- 격리: legacy는 rpg-game-web 질의 상위 5에 Devtrail 문서 2개가 섞였고 정답은 밖이었다. structured는 0개.
- 문자 수: 짧은 문서에서는 structured 응답이 더 길다(범위·필터·발췌·버전 메타데이터, 1.9~3.9천 자). 긴 원문을 전문으로 읽어야 하던 사례(80행 세션)에서만 줄었다. 상한 12000자 안이다.
- 시간: 같은 환경에서 structured가 사례당 0.7~1.2배(사례별 ms는 1회 측정이라 흔들린다 — 앞선 측정에서는 1.0~1.5배), 1000문서 규모에서 약 1.05배 느리다(파일마다 버전 해시·줄 단위 창 계산).

## 테스트 결과 (2026-11-05)

환경: 이 작업 컨테이너에는 네이티브 Python과 PyPI 접근이 없어, 공식 Pyodide 0.27.7(CPython 3.12.7 wasm, GitHub 릴리스) +
mcp 1.30.0 + pydantic 2.12.5(소스) + pydantic_core 2.41.5(emscripten 휠) 위에서 `python -m pytest`를 돌렸다. Pyodide에는 `fcntl`이
없어 아무것도 안 하는 대체 모듈을 넣었다(단일 프로세스·단일 스레드라 잠금이 의미가 없다). 프로세스를 띄우는 테스트는 이 환경에서 실패한다.
**네이티브 CPython(macOS 개발 트리)에서는 돌리지 않았다.**

| 시점 | 결과 |
|---|---|
| 기능 이전(baseline, `5d2f4be` = main) | 511 passed, 6 failed |
| 앞선 작업 끝(`a297825`) | 624 passed, 6 failed |
| 이번 작업 끝 | 657 passed, 6 failed — 실패 목록이 세 시점 모두 같다(새 실패 0건) |

같은 실패 6건:

- 환경(프로세스 없음) 5건: `test_candidate_writer.py::test_parallel_process_writes_allocate_distinct_candidate_files`,
  `test_session_markers.py`의 `test_dead_process_marker_is_not_live`·`test_ancestor_pids_starts_with_self_and_includes_parent`·
  `test_marker_for_current_session_picks_own_among_concurrent`, `test_vault_tools.py::test_write_session_process_serializes_multiprocess_appends`
- 기존 실패 1건: `test_vault_tools.py::test_get_recent_sessions_groups_plan_and_process` — `Devtrail`로 쓰고 `"devtrail"`로 조회한다.
  대소문자를 구분하는 파일시스템에서 실패한다(macOS 기본 파일시스템에서는 통과할 것으로 보이나 확인하지 못했다). 이번 변경과 무관하다.

관련 테스트: `test_evidence_search.py`, `test_source_reader.py`, `test_project_identity.py`, `test_vault_source.py`, `test_evidence_eval.py`,
`test_mcp_server.py`(실제 `call_tool` 경로), `test_wiki_core.py`(legacy 검색의 `path_filter`), `test_vault_tools.py`.
상세 검사·리뷰 근거와 수용 기준별 결과는 [`evidence-search-verification.md`](./evidence-search-verification.md)에 있다.

## 알려진 한계

- 평가 Vault는 합성이고 사례 7개다. 실제 사용자 vault에서의 순위·분량·시간은 재지 않았다(이 작업은 사용자 vault를 읽지도 바꾸지도 않는다).
  사례는 legacy가 실패하는 유형을 일부러 담았으므로 "개선 비율"로 일반화하면 안 된다.
- 측정 환경은 Pyodide(wasm) 위 CPython이다 — 이 컨테이너에 네이티브 Python과 PyPI 접근이 없었다. 절대 ms는 네이티브와 다르고, 두 방식의 상대 비교만 의미가 있다.
- 매 호출마다 read_scope 전체를 읽고 해시한다(legacy도 매번 전체를 읽는다). 색인·캐시는 없다. 구간 읽기도 페이지마다 파일 전체를 읽고 해시한다
  (버전 확인 때문). 수십 MB 원문을 페이지로 넘기면 페이지 수 × 파일 크기만큼 든다.
- 16000자보다 긴 한 줄은 structured 읽기로 받을 수 없다(`line_too_long`, `readable_with_max_chars=false`). 줄을 쪼개 주는 방식은
  승인된 설계가 아니라 넣지 않았다. 전문은 기존 `read_note`로 읽는다.
- `project` 없는 vault 전체 검색의 cursor는 허용 prefix 안 어느 문서가 바뀌어도 `cursor_stale`이 된다(스캔 대상 전체를 묶기 때문).
- 토큰은 부분 문자열 일치라 "검색"이 "검색을"에도 맞고, 한 글자 낱말은 버린다(legacy와 같다). 형태소 분석·동의어·벡터 검색은 범위 밖이다.
- 근거 창은 줄 기준이다. 문단 한 줄이 아주 긴 문서에서는 "같은 창"이 넓어지고, 800자보다 긴 일치 줄은 발췌 text 없이 위치만 나온다.
- 소속 근거가 없는 문서(digest, 70_Tasks/Active.md 등)는 `unknown`이라 프로젝트 검색 기본값에서 빠진다. 본문 언급으로 귀속하지 않는 것은 의도다.
- `20_Knowledge/<P>/` 경로 근거는 `<P>`가 등록 프로젝트일 때만 쓴다. 주제 폴더 이름이 우연히 프로젝트명과 같으면 그 프로젝트로 본다.
- 중복 출처는 "본문 바이트·파일명·소속이 같다"와 session_id 규칙만 묶는다. 거의 같은 내용(승격 시 "관련 노트" 절이 붙은 사본 등)이나
  파일명을 바꾼 사본은 따로 나온다 — 서로 다른 결정을 숨기는 것보다 사본이 두 번 나오는 쪽을 택했다.
- `get_project_briefing`, `get_recent_sessions` 등 다른 도구의 프로젝트 판정은 바꾸지 않았다 (briefing은 여전히 basename 매칭을 쓴다).
