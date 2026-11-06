# 근거 검색·원문 구간 읽기 — 검증 기록 (2026-11-05)

[`evidence-search.md`](./evidence-search.md)의 structured 모드를 마무리하면서 돌린 검사, 리뷰 근거, 수용 기준별 결과를 남긴다.
작업 보고가 길이 제한으로 잘려도 근거가 사라지지 않도록 여기에 둔다.

## 검증 환경 — 무엇으로 돌렸고 무엇을 못 돌렸나

| 항목 | 내용 |
|---|---|
| 실행 환경 | 작업 컨테이너(Linux). 네이티브 Python 없음, PyPI 차단 |
| Python | 공식 Pyodide 0.27.7(CPython 3.12.7 wasm, GitHub 릴리스) on Node 26 |
| 패키지 | Pyodide 동봉: pytest 8.1.1, anyio 4.9.0, httpx 0.28.1, pyyaml 6.0.2, jsonschema 4.21.1 등. GitHub 소스: mcp 1.30.0, pydantic 2.12.5, pydantic-settings 2.12.0, starlette 0.49.1, sse-starlette 3.0.2, python-frontmatter 1.1.0, typer 0.17.4, Markdown 3.9 등. pydantic_core 2.41.5 emscripten 휠 |
| 대체 | Pyodide에 없는 `fcntl`을 아무것도 안 하는 모듈로 대체(단일 프로세스라 잠금 의미 없음). textual·uvicorn은 테스트가 import하지 않아 넣지 않았다 |
| 못 돌린 것 | 네이티브 CPython(macOS 개발 트리) 실행, 프로세스를 띄우는 테스트 5건, stdio로 띄운 실제 MCP 서버 프로세스와 클라이언트 왕복(도구 호출은 FastMCP `call_tool` 경로로 검증), 실제 사용자 vault 측정 |

## 테스트 결과

| 시점 | 전체 | 실패 |
|---|---|---|
| 기능 이전 `5d2f4be`(= main) | 511 passed | 6 |
| 앞선 작업 끝 `a297825` | 624 passed | 6 |
| 이번 작업 끝 | 670 passed | 6 |

실패 6건은 세 시점 모두 같은 목록이다(새 실패 0건) — 프로세스 생성 5건과 대소문자 구분 파일시스템에서 실패하는 기존
`test_get_recent_sessions_groups_plan_and_process` 1건. 목록은 `evidence-search.md` "테스트 결과".

### 회귀 테스트가 결함을 실제로 잡는지

수정 전 코드에 새 테스트만 얹어 돌렸다(`git archive <rev>` 사본 + 현재 테스트 파일).

| 수정 전 코드 | 새 테스트 중 실패 | 내용 |
|---|---|---|
| `a297825`(긴 줄·cursor·중복 수정 전) | 17건 | 긴 줄 `line_too_long`(읽기 5·발췌 2·MCP 1), `char_offset` 제거, 완전한 줄 성질, cursor(스캔 집합·소속·partial 회복) 3, 중복(다른 결정·프로젝트 경계·사본 근거) 3, 손상 marker 집계 1 |
| `e857ab8`(1차 리뷰 반영 전) | 8건 | 해석 못 한 frontmatter 2, 별칭 소속, 등록부 1회, 숨김 폴더 경고, 경로 문자열 오류 코드, Context project 비문자열, NotFound 타입 |
| `58fe4cc`(2차 리뷰 반영 전) | 4건 | 폴더명≠선언명 프로젝트의 자기 문서 유실, 별칭 소속 기대값, 주석·`{}` frontmatter 오판 2 |
| `3722f62`(2번째 병합 차단 리뷰 반영 전) | 6건 | 숫자·날짜·실수 Context project의 식별↔소속 불일치 3, 숫자 project만 있는 문서 1, 숫자 `.claude/vault.json` 1, 공용 규칙 함수 1 |
| `4b1dfde`(병합 차단 리뷰 반영 전) | 5건 | 모호한 이름의 소속 충돌 보존 1, 같은 파일명·본문의 다른 결정 1, 같은 영역 동일 파일 1, 제목이 다른 후보·정본 1, 같은 영역 200개 예산 1 |

"발췌는 완전한 원문 줄" 성질 테스트는 처음에 수정 전 코드에서도 통과했다. 입력에 긴 줄이 발췌로 뽑히는 경우가 없었기 때문이라,
긴 줄이 반드시 발췌되도록 입력을 바꾼 뒤 수정 전 코드에서 실패하는 것을 확인했다.

### legacy 동작 A/B

평가 Vault(합성 문서 48개)에서 기능 이전 `5d2f4be`와 이번 작업 끝 코드로 legacy `search_vault`를 질의 10개 × limit 3/5/10/20으로,
`read_note`를 1회 불러 JSON을 비교했다. 결과 132건과 전문이 **바이트 단위로 같았다**. (링크로 범위 밖을 가리키는 파일이 결과에서 빠지는 것만
의도된 차이이며, 이 Vault에는 그런 링크가 없다 — 그 경우는 `test_legacy_search_and_read_reject_symlink_bypass` 등이 따로 검증한다.)

### 비밀값 검사

`git diff 5d2f4be..HEAD`의 추가 줄에서 API 키·토큰 패턴(`sk-`, `ghp_`, `github_pat_`, `xox?-`, `AKIA…`, 개인키 헤더,
`api_key=`/`token=`/`password=` 리터럴, Telegram 봇 토큰 꼴)을 찾았다 — 0건. `.env`·키 파일 등 민감 파일명 변경 0건.

## 이번에 고친 차단 사유

| 차단 사유 | 수정 |
|---|---|
| 긴 줄을 `char_offset`으로 줄 중간부터 이어 읽고, 발췌는 줄 일부(`line_clip`)를 냈다 — 승인된 설계는 완전한 줄 단위 | 읽기 `content`는 완전한 줄만. 페이지 중간의 긴 줄 앞에서 멈추고(`truncation_reason=line_too_long`, `long_line`), 첫 줄이 길면 내용 없는 `line_too_long` 결과(`error.next`는 다음 줄). 발췌는 `text: null` + `line_too_long`. `char_offset` 인자 제거 |
| cursor가 일치 문서·버전만 묶어 소속(등록부) 변화, 상태 class 변화, partial 회복, 범위 안 비일치 문서 변화를 놓쳤다 | 범위 필터를 통과한 모든 문서의 경로·버전·상태 class·파일/블록 소속 + 읽기 실패 목록·partial로 지문. cursor 형식 v2 |
| 본문만 같으면 묶어 템플릿 본문이 같은 서로 다른 결정·다른 프로젝트 문서를 숨길 수 있었고, 사본의 근거가 경로·버전뿐이었다 | `same_content`는 본문·파일명·소속이 모두 같을 때만, `same_session_id`는 같은 프로젝트일 때만. 사본마다 등급·상태·소속·발췌 줄을 남긴다 |
| 손상 marker 블록이 "근거 없음"과 같은 `unknown`으로 집계됐다 | `invalid_marker` 표시와 `filtered.blocks.invalid_marker`로 구분 |
| `20_Knowledge/<P>` 소속이 Context.md 프로젝트만 등록으로 봐 식별 기준(SessionHandoffs 폴더 포함)과 달랐다 | 같은 기준(`is_known`) |

## 최종 리뷰

### 1차 — 브랜치 전체(`main...HEAD`), 정확성·정리 관점

| # | 지적 | 판단 | 조치 |
|---|---|---|---|
| 1 | `---` 사이가 YAML 매핑이 아니면(문법 오류·문자열) 그 줄이 본문에서 빠져 검색되지 않는다 | 확인함 — python-frontmatter는 스칼라 YAML이면 조용히 빈 dict를 준다 | 매핑으로 해석되지 않으면 파일 전체를 본문으로, 경고 |
| 2 | 문서의 `project:`·marker의 별칭/폴더명이 식별처럼 정규화되지 않아 `project: dt` 문서가 Devtrail 검색에서 빠진다 | 별칭은 확인함. 폴더명 쪽은 식별도 인정하지 않는 규칙이었다(2차 리뷰 1) | `attribution_name` — 식별과 같은 순서(등록 표기 → handoff 폴더 → 단일 대상 별칭). 근거 문자열에 `→정규화명` |
| 3 | 등록부를 검색 한 번에 두 번 읽어 식별과 소속이 다른 상태를 볼 수 있다 | 확인함 | 한 번 읽어 `resolve_project(registry=…)`로 넘김 |
| 4 | 읽기 오류 코드를 메시지 문자열("찾지 못했습니다")로 판별 — 경로 이름이 코드를 바꾼다 | 확인함 | `VaultNotFoundError`(VaultScopeError 하위) 타입으로 판별 |
| 5 | legacy `read_note`가 `resolve_scoped_file`과 같은 검증을 따로 갖고 있어 갈라질 수 있다 | 타당 | **보류** — legacy 읽기 구현을 바꾸면 기존 동작 보존 범위를 넘는다. 두 경로 모두 같은 `real_scoped_rel`을 쓰고 테스트가 같은 링크 사례를 덮는다 |
| 6 | `resolve_project_identity`에 호출처·테스트가 없다 | 타당 | 테스트 추가. 호출처 연결(briefing)은 브리핑 재설계라 범위 밖 |
| 7 | `.claude/vault.json` 판독이 세 곳에 있다 | 타당 | **보류** — 기존 briefing·doctor 판독기를 바꾸는 정리라 범위 밖 |
| 8 | 숨김 폴더의 Context.md가 "링크라 뺐다"는 잘못된 경고를 낸다 | 확인함 | 숨김 폴더는 등록부에서 조용히 건너뜀 |
| 9 | 구간 읽기가 페이지마다 파일 전체를 읽고 해시한다 | 타당(성능) | **보류** — 버전 확인 계약 때문. 한계에 기록 |
| 10 | 바뀐 모듈의 테스트 파일 규칙(`tests/test_<모듈>.py`) | 타당 | `tests/test_vault_source.py` 신설, `test_wiki_core.py`에 `path_filter` 테스트 |

추가로 Context.md의 `project`가 문자열이 아니면(목록 등) `str()`로 바꿔 이상한 이름을 등록하던 것을 폴더명 + 경고로 고쳤다.

### 2차 — 이번 작업 변경분(`a297825..HEAD`) 독립 리뷰

결론을 주지 않은 별도 리뷰어가 변경분만 보고, 의심 사례를 스크립트로 돌려 확인했다.

| # | 지적 | 판단 | 조치 |
|---|---|---|---|
| 1 | (회귀) 1차 반영에서 소속 정규화에 "30_Projects 폴더명 → 그 Context.md 선언명" 단계를 handoff 폴더보다 앞에 넣었다. 식별은 이 규칙을 쓰지 않아, `30_Projects/Alpha/Context.md`가 `project: Beta`를 선언하고 `SessionHandoffs/Alpha/`가 있으면 `project=Alpha`가 식별은 되는데 자기 handoff가 conflict, 세션 원문이 Beta가 되어 결과 0건 | 확인함(리뷰어 재현 스크립트, 수정 후 재실행해 handoff=Alpha·세션 원문은 사본으로 묶임 확인) | 그 단계를 빼고 식별과 같은 순서로 맞춤. 회귀 테스트 추가 |
| 2 | 주석뿐이거나 `{}`인 정상 frontmatter를 해석 실패로 오판해 주석이 제목·본문이 된다 | 확인함 | YAML 값으로 판정(None·매핑 = 정상). 해석은 python-frontmatter와 같은 로더로 **한 번만** — 처음 고친 버전은 YAML을 두 번 해석해 1000문서 규모에서 307→458ms로 느려졌고, 한 번으로 줄여 301ms로 돌아왔다 |

리뷰어가 문제없다고 본 것: 읽기의 완전한 줄·`line_too_long`·`next` 종료, 발췌의 긴 줄 처리와 뒷줄 보존, 응답 예산(자리표시자로 미리 잰다),
cursor 지문의 입력 범위(다른 프로젝트 파일의 읽기 실패도 stale로 만드는 정도의 과잉 보수는 계약상 허용), 중복 키와 사본 근거,
비문자열 YAML 값(`title: 123`, `status: [a]`, `project: {a: 1}`, 숫자 marker project)에서 예외 없음, `VaultNotFoundError`의 하위 호환.

### 3차 — 병합 차단 리뷰(BLOCK) 반영

| # | 지적 | 판단 | 조치 |
|---|---|---|---|
| 1 | `attribution_name`은 canonical 이름이 있으면 별칭을 보지 않는다. Beta의 별칭이 Alpha이면 식별(`_resolve_name("Alpha")`)은 후보 둘인데 소속은 Alpha로 확정해, repo 매핑으로 Alpha를 검색하면 모호한 `project: Alpha` 문서·블록이 섞인다 | 확인함(재현 테스트가 수정 전 코드에서 실패) | 소속 판정이 식별의 `_resolve_name`을 그대로 쓴다(`attribution_targets`). frontmatter·marker의 `project`, SessionHandoffs·20_Knowledge 폴더명 모두 후보가 둘 이상이면 `conflict`(후보 보존, `(모호: …)` 근거). 경로와 선언이 함께 있으면 공통 후보가 정확히 하나일 때만 확정 — `30_Projects/Alpha/` 안의 `project: Alpha`는 경로가 좁혀 Alpha로 남는다(그러지 않으면 Alpha 폴더 문서 전부가 conflict가 된다). 처음 고친 버전은 합집합으로 판정해 Alpha의 Context.md까지 conflict가 됐고, 테스트에서 잡아 교집합 규칙으로 바꿨다 |
| 2 | 중복 키가 제목 등 frontmatter를 빼서, 같은 프로젝트 `Decisions/backend/decision.md`(캐시 도입)와 `Decisions/frontend/decision.md`(캐시 제거)가 템플릿 본문이 같으면 한 결정이 사본으로 축약된다 | 확인함 | curator는 사본 관계를 메타데이터로 남기지 않아(승격 후 후보 삭제), 사본 판정 근거를 좁혔다: 승격·보관이 바꾸는 값만 뺀 frontmatter가 같고, **서로 다른 영역**(후보·정본·보관 중 영역당 하나)일 때만 묶는다. 같은 영역의 같은 본문 파일은 묶지 않는다. 승격·보관 흐름의 사본(후보+정본+보관)은 계속 한 건으로 묶이고 각자 상태·근거 줄을 남긴다(회귀 테스트) |

같은 Vault에서 legacy A/B를 다시 돌려 결과가 기능 이전과 바이트 단위로 같음을 확인했고, 평가·규모 측정도 다시 했다(`evidence-search.md` 표).

### 4차 — 2번째 병합 차단 리뷰(BLOCK) 반영

| # | 지적 | 판단 | 조치 |
|---|---|---|---|
| 1 | Context.md 등록부는 `project: 123`을 버리고 폴더명 Alpha로 등록하는데, 검색 소속 판정(`_str_meta`)은 숫자를 `"123"`으로 바꿔 경로(Alpha)와 충돌시킨다. `project="Alpha"` 검색에서 자기 Context.md가 빠진다. 날짜 값도 같다 | 확인함(재현 테스트가 수정 전 코드에서 숫자·날짜·실수 3건 모두 실패) | `project` 값을 읽는 규칙을 `project_identity.project_field` 하나로 합쳤다 — 문자열만 이름, 그 밖의 타입은 근거에서 빼고 경고. Context.md 등록부·`.claude/vault.json`·문서 frontmatter·marker가 모두 이 함수를 쓴다. 숫자·날짜·목록·불리언·실수 Context에 대해 식별(`resolve_project_identity`) → 검색(`project="Alpha"`) → 소속(`path:30_Projects/Alpha/`)까지 확인하는 회귀 테스트를 더했다. 경로 근거 없이 숫자 project만 있는 문서는 `"123"` 프로젝트로 귀속하지 않고 `unknown`이다 |

목록·불리언 값은 수정 전에도 양쪽이 버려서 일관됐다(테스트가 수정 전 코드에서도 통과). 이번에는 같은 규칙을 지키는지 보는 보호 테스트로 남긴다.
쓰기 흐름(`candidate_writer`)의 `str(project)` 비교는 쓰기 동작 개편이 범위 밖이라 그대로 두었다 — 검색·식별에는 영향이 없다.

## 수용 기준별 결과

| 기준 | 확인 방법 | 결과 |
|---|---|---|
| 기존 호출 호환·structured 계약·모순 인자 거부 | `test_mcp_server.py` 10건(FastMCP `call_tool` 경로), legacy A/B 132건 동일 | 통과. stdio 서버 프로세스 왕복은 미실행 |
| 명시적 식별·미등록/충돌/동명 안전 실패·basename 미사용 | `test_project_identity.py`, `test_evidence_search.py`(별칭 소속·basename·모호한 이름의 소속 conflict 보존) | 통과 |
| 프로젝트/공통/unknown/conflict/손상 marker 필터가 점수·발췌 전, 자동 확대 없음 | `test_evidence_search.py` 범위 절 + `invalid_marker` 집계 | 통과 |
| 관련도 우선·정본 우대·raw 잠식 방지·이력 기본 제외·미지 상태·중복 근거 보존 | 순위·상태·중복 테스트(다른 결정·같은 영역 파일 미병합, 승격·보관 사본 병합), 평가 Vault | 통과 |
| 응답 범위·반환 수·cursor·partial·귀속·발췌·버전·예산·후반 근거, 모르는 total 없음 | 응답 필드·예산·partial 테스트, 평가 "late" 사례 | 통과 |
| 원문 구간·줄 기준·버전·이어읽기, 한글·CRLF·frontmatter·빈 파일·EOF·긴 줄·버전 불일치 | `test_source_reader.py`(임의 줄 길이 성질 테스트 포함), `test_vault_source.py` | 통과. 16000자 초과 줄은 structured로 읽을 수 없음(설계상) |
| 페이지 일관성·partial·경로 탈출·금지 prefix·링크 | cursor 테스트 6종, 링크 테스트(검색·읽기·등록부) | 통과 |
| 최종 리뷰 차단 문제 해결·검사 근거 | 이 문서 | 1차 정확성 지적 5건·2차 2건·병합 차단 2건·2번째 병합 차단 1건 반영, 정리 지적 3건은 사유와 함께 보류 |
| 평가 Vault 실측·문서·범위 밖 무변경 | `evidence-search.md` 평가 표, `git diff --stat` | 사용자 vault·운영 설정·브리핑·쓰기 코드 변경 없음 |

---

# 2026-11-06 — 권한·매핑 인코딩·손상 marker로 검색 전체가 멈추던 문제, 예산 테스트 경로

[`evidence-search.md`](./evidence-search.md) "권한 오류·손상 입력"의 검증 기록. 이번에는 Pyodide가 아니라 **네이티브 CPython**으로 돌렸다.

## 검증 환경

| 항목 | 내용 |
|---|---|
| Python | CPython 3.11.2 (GCC 12.2.0), 프로젝트 venv(`venv/bin/python`) |
| 플랫폼 | `Linux-7.0.14-orbstack-00380-ga7e0a2dc9535-aarch64-with-glibc2.36` (컨테이너), 실행 사용자 uid 501(비 root) |
| 대체 | 없음 — Pyodide·`fcntl` 대체·프로세스 생성 대체를 쓰지 않았다 |
| 못 돌린 것 | **macOS(개발 트리) 실행**. macOS의 실제 권한 의미·경로 한도(PATH_MAX 1024바이트)에서 통과하는지는 확인하지 않았다 |

## 수정 전 재현 (`88288b4`, 같은 venv)

| 결함 | 재현 | 수정 전 결과 |
|---|---|---|
| SessionHandoffs 폴더 모드 000 | 실제 chmod | `load_registry`의 `iterdir()`에서 `PermissionError` — 검색 전체 예외 |
| SessionHandoffs 폴더 모드 r--(실행 권한 없음) | 실제 chmod | 하위 폴더 `is_dir()`에서 `PermissionError` |
| `30_Projects/Secret` 모드 r-- | 실제 chmod | 등록부 glob은 경고 없이 Secret을 뺐고, 스캔의 `is_symlink()`가 `PermissionError` |
| `30_Projects/Secret` 모드 000 | 실제 chmod | 예외는 없지만 등록부가 경고 없이 Secret을 뺐다(불완전성이 응답에 안 보임) |
| cp949 매핑 파일 | 실제 파일 | `UnicodeDecodeError` 전파 (MCP `call_tool`에서는 `ToolError`) |
| marker `{"scope":"project","project":"\ud800"}` | 실제 파일 | `project` 없는 검색에서 `_digest`(cursor 지문)가 `UnicodeEncodeError` |
| 예산 테스트 | 코드 확인 | 상대 경로만 2천 자 — macOS PATH_MAX(1024바이트)를 넘어 파일 생성 단계에서 실패하는 구조(Linux는 4096이라 통과) |

## 테스트 결과

실행 명령(전체): `venv/bin/python -m pytest -q -p no:cacheprovider -rfEs`
등록 검사: 위 명령 + `--deselect tests/test_session_markers.py::test_ancestor_pids_starts_with_self_and_includes_parent --deselect tests/test_session_markers.py::test_marker_for_current_session_picks_own_among_concurrent --deselect tests/test_vault_tools.py::test_get_recent_sessions_groups_plan_and_process`

| 시점 | 전체 | 등록 검사 |
|---|---|---|
| 수정 전 baseline (`88288b4`) | 673 passed, 3 failed, 0 skipped | 673 passed, 3 deselected |
| 수정 후 | 698 passed, 3 failed, 0 skipped | 698 passed, 3 deselected |

실패 3건은 두 시점이 같다(새 실패 0건): `test_ancestor_pids_starts_with_self_and_includes_parent`,
`test_marker_for_current_session_picks_own_among_concurrent`, `test_get_recent_sessions_groups_plan_and_process` — 이 컨테이너 환경
실패로 등록 검사에서 deselect한 목록과 같다. 늘어난 25건은 아래 새 테스트다. 실제 chmod 테스트는 root에서만 skip되며 이번에는 실행됐다(skip 0).

### 회귀 테스트가 결함을 실제로 잡는지

수정 전 코드(`git archive 88288b4`)에 현재 테스트를 얹어 돌렸다: **새 테스트 25건 모두 실패**, 기존 테스트는 모두 통과.
(아래 표의 20건 + 리뷰 반영 5건. 그중 `test_context_path_that_is_not_readable_as_file_keeps_folder_fallback`은 수정 전과 같은 동작을 지키는
보호 테스트라 새 속성 `unreadable`이 없어서만 실패한다.)

| 테스트 | 수정 전 실패 내용 |
|---|---|
| `test_registry_folder_permission_error_does_not_abort_search` ×4 (SessionHandoffs 000·r--, 프로젝트 폴더 000·r--) | `PermissionError` 3건, 등록부 경고 없음 1건 (000 프로젝트 폴더) |
| `test_docs_under_unconfirmed_registry_folder_are_not_attributed` | `PermissionError` |
| `test_cursor_stale_when_registry_folder_recovers` | `PermissionError` |
| `test_real_chmod_registry_folders_do_not_abort_search` (실제 chmod) | `PermissionError` |
| `test_non_utf8_project_map_is_ignored_and_search_continues` | `UnicodeDecodeError` |
| `test_marker_with_lone_surrogate_is_a_corrupt_marker` ×4 | `UnicodeEncodeError` 3건, `scope=global`+손상 project가 손상 marker로 안 잡힘 1건 |
| `test_frontmatter_project_with_lone_surrogate_is_not_evidence` | `UnicodeEncodeError` |
| `test_project_identity.py` 새 6건 | `UnicodeDecodeError` 2건(매핑·`.claude/vault.json`), `PermissionError` 1건, 손상 project가 이름으로 쓰임 1건, 새 API(`project_field_issue`·`unreadable`) 없음 2건 |
| `test_mcp_server.py::test_search_vault_structured_survives_corrupt_marker_and_non_utf8_map` | `ToolError`(UnicodeDecodeError) |

`test_budget_never_returns_oversized_success`는 고쳐 쓴 테스트라 수정 전 코드에서도 통과한다(코드 결함이 아니라 테스트 이식성 문제였다).

### 권한 재현 방식

- 결정적 재현: `tests/conftest.py`의 `DenyAccess`가 `os.scandir`·`os.listdir`·`os.stat`·`os.lstat`에서 POSIX 의미대로 EACCES를 낸다
  (000 폴더는 목록·하위 stat 거부, r-- 폴더는 하위 stat·목록 거부). root·플랫폼과 무관하고, 구현이 glob·iterdir·walk 중 무엇을 쓰든 이 호출을
  거친다. 각 테스트는 `deny_access.hits`로 거부가 실제로 일어났는지 확인한다.
- 실제 권한: `test_real_chmod_registry_folders_do_not_abort_search`가 실제 chmod(000, 0o444)로 같은 결과를 확인한다. root에서는 skip.

### 예산 테스트 이식성

경로 길이 대신 응답 고정부를 문서화된 입력 상한(project 선언명 300자, 질의 단어 32개)으로 채웠다. 상대 경로 426자로 `budget_too_small`
(`needed_chars` 3266 > 3000)이 나고, 짧은 경로 대조군은 압축형으로 성공(2875자 ≤ 3000)한다 — 경계 양쪽에서 성공 응답이 상한을 넘지 않는다.
여유 있는 예산 사례(30건·`limit=20`)는 그대로 두고 `stopped_by="budget"` 확인을 더했다. 파일을 만들기 전에 절대 경로 < 1024바이트,
경로 각 부분 ≤ 255바이트를 테스트 안에서 단언한다 — 이 컨테이너의 tmp_path로 확인했고 macOS tmp_path(`/private/var/folders/…`, 보통 100자 안팎)
에서도 여유가 있을 것으로 보지만 **macOS에서 실행하지는 않았다**.

### 호환성

- 평가 Vault(`python -m tests.evidence_eval`)를 네이티브로 다시 돌렸다: 7개 사례의 순위·근거 적중·호출 수·응답 문자 수·타 프로젝트 수가
  2026-11-05 표와 같다(ms만 다르다 — 측정 환경이 wasm에서 네이티브로 바뀌었다).
- 기존 검색·읽기·식별·MCP 테스트(범위 필터·상태·예산·cursor·링크·legacy A/B 포함)는 수정 없이 모두 통과한다. 기존 테스트에서 바꾼 것은
  예산 테스트 하나다(위).
- 응답 형태: 새 경고 코드 `registry_unreadable`(`path` 포함, 경고 목록 맨 앞)과 새 소속 evidence `registry_unreadable:<경로>`가 생겼다.
  필드 추가·삭제는 없다. `partial`은 등록부 미확인일 때도 켜진다.
- 의미가 바뀐 기존 동작 하나: Context.md를 **권한 등 OSError로 읽지 못하면** 전에는 폴더명으로 등록했고 지금은 등록하지 않는다.
  선언명이 폴더명과 다를 수 있어 권한 오류로 소속을 잘못 확정하지 않으려는 것이다. 형식 오류(YAML)는 전처럼 폴더명으로 식별한다.

### 비밀값 검사

`git diff`에 API 키·토큰·비밀번호 패턴(`api_key`, `sk-…`, `ghp_…`, `xox?-`, `AKIA…`, private key 헤더 등) 검색 — 일치 없음.
테스트 fixture는 합성 문자열뿐이고 `.env`는 저장소에 없다.

### 리뷰 반영 테스트 (수정 전 코드에서 실패)

| 테스트 | 수정 전 실패 내용 |
|---|---|
| `test_knowledge_folder_hidden_by_unreadable_registry_is_not_attributed` ×2 | `PermissionError` |
| `test_real_chmod_unreadable_context_file_does_not_attribute` (실제 chmod) | Context.md 000이면 폴더명 Secret으로 등록돼 `project="Secret"`이 확정됐다 |
| `test_map_with_lone_surrogates_is_ignored_without_encode_error` | `UnicodeEncodeError` |
| `test_context_path_that_is_not_readable_as_file_keeps_folder_fallback` | 보호 테스트(위 설명) |

## 최종 리뷰 (독립 리뷰, 이번 변경분 `88288b4..작업 트리`)

변경 내용을 모르는 리뷰어에게 diff만 주고 정확성·예외 누출·범위 확대·surrogate 경로·테스트 약화를 보게 했다. 리뷰어가 수정 전 코드와
같은 스크립트로 비교해 재현했고, 새 테스트 20건이 수정 전 코드에서 모두 실패함과 기존 단언이 약해지지 않았음을 따로 확인했다.

| # | 지적 | 판단 | 조치 |
|---|---|---|---|
| F1 | 등록부가 못 읽은 폴더 때문에 `20_Knowledge/<P>/` 경로 근거가 사라지면, `project: Alpha` 선언만으로 Alpha로 확정된다(정상이면 conflict) | 확인함 — 계약의 "권한 오류로 소속을 잘못 확정하지 않는다"에 어긋난다 | `ProjectRegistry.may_hide` — P가 못 읽은 등록부 경로에 가려졌을 수 있으면 선언이 있는 그 문서를 `unknown`으로 둔다. 회귀 테스트 2건 |
| F2 | 못 읽은 폴더가 같은 이름을 선언했으면 `ambiguous`였을 이름이 `resolved`가 된다 | 확인함 — 수정 전 코드도 같다 | **보류(정책 판단).** 막으려면 등록부 일부만 못 읽어도 모든 이름 식별을 거부해야 해서 "정상 등록부의 검색은 계속"과 부딪친다. `partial`·`registry_unreadable`로 알리고 "알려진 한계"에 남겼다 |
| F3 | UTF-8로 정상인 매핑의 JSON 이스케이프 surrogate(이름·별칭)가 커서 지문에서 `UnicodeEncodeError` | 확인함 — 수정 전 코드도 같다. 손상 문자열이 지문·직렬화를 멈추게 하는 3번 결함과 같은 부류 | 매핑의 손상 이름·목록을 경고 후 무시. 회귀 테스트 |
| F4 | 사용자가 넘긴 repo 경로 자체가 권한 때문에 안 보이면 `PermissionError`가 검색 밖으로 나온다 | 확인함 — 수정 전 코드도 같다. 등록부·스캔이 아니라 입력 경로 | 범위 밖으로 남기고 "알려진 한계"에 적었다 |
| F5 | 인자 `query`/`project`에 surrogate가 있으면 지문에서 멈춘다 | MCP JSON 파서(pydantic_core)가 그런 값을 거부해 MCP로는 들어오지 않는다 | 조치 없음 |
| F6 | Context.md가 폴더 같은 권한 외 OSError도 등록부 미확인이 되어 검색이 계속 `partial`이 된다 | 확인함 — 의도보다 넓다 | 미확인 처리는 `PermissionError`만. 그 밖의 읽기 실패는 전처럼 폴더명 식별. 보호 테스트 |
| 기타 | `DenyAccess.stat` 모드(파일 하나만 stat 실패)는 실제 POSIX에서는 생기지 않는 조합이다 | 맞다 — 등록부 확인과 스캔 읽기 결과가 엇갈리는 경우(경합)를 결정적으로 만드는 용도다 | 현실적인 경우(Context.md 000)는 실제 chmod 테스트를 더해 확인했다 |

## 수용 기준별 결과 (2026-11-06)

| 기준 | 확인 방법 | 결과 |
|---|---|---|
| 등록부 폴더·하위 폴더 순회 PermissionError | `DenyAccess` 결정적 테스트 4종 + 소속 미추측·cursor·20_Knowledge 테스트, 실제 chmod 테스트 2건 | 통과. 검색은 계속, `registry_unreadable`·`partial`, 정상 프로젝트 결과 유지, 못 읽은 프로젝트는 `project_unresolved` |
| UTF-8이 아닌 매핑 | 식별·검색·MCP `call_tool` 테스트 | 통과. 경고 후 무시, canonical 유지, 잘못 읽은 별칭 미사용 |
| marker lone surrogate | marker 4종·frontmatter·`.claude/vault.json`·매핑·MCP 테스트, UTF-8 인코딩 직렬화 확인 | 통과. 손상 marker, 정상 한글 이름 유지, 타 프로젝트 블록 미노출 |
| 예산 테스트 이식성 | 경로 길이 단언 포함 재작성, 짧은 경로 대조군 | 이 컨테이너에서 통과. **macOS에서는 실행하지 않음** |
| 네이티브 Python 전체 실행 | CPython 3.11.2 venv, baseline 비교 | 673 → 698 passed, 실패 3건 동일, skip 0 |
| 호환성·문서·재검사·비밀값·리뷰 | 평가 Vault 재실행, 기존 테스트 무수정 통과, 이 문서 | 순위·근거·분량 동일. 비밀값 일치 없음. 리뷰 F1·F3·F6 반영, F2 정책 보류, F4·F5 범위 밖 |
