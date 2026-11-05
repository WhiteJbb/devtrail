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
| 이번 작업 끝 | 662 passed | 6 |

실패 6건은 세 시점 모두 같은 목록이다(새 실패 0건) — 프로세스 생성 5건과 대소문자 구분 파일시스템에서 실패하는 기존
`test_get_recent_sessions_groups_plan_and_process` 1건. 목록은 `evidence-search.md` "테스트 결과".

### 회귀 테스트가 결함을 실제로 잡는지

수정 전 코드에 새 테스트만 얹어 돌렸다(`git archive <rev>` 사본 + 현재 테스트 파일).

| 수정 전 코드 | 새 테스트 중 실패 | 내용 |
|---|---|---|
| `a297825`(긴 줄·cursor·중복 수정 전) | 17건 | 긴 줄 `line_too_long`(읽기 5·발췌 2·MCP 1), `char_offset` 제거, 완전한 줄 성질, cursor(스캔 집합·소속·partial 회복) 3, 중복(다른 결정·프로젝트 경계·사본 근거) 3, 손상 marker 집계 1 |
| `e857ab8`(1차 리뷰 반영 전) | 8건 | 해석 못 한 frontmatter 2, 별칭 소속, 등록부 1회, 숨김 폴더 경고, 경로 문자열 오류 코드, Context project 비문자열, NotFound 타입 |
| `58fe4cc`(2차 리뷰 반영 전) | 4건 | 폴더명≠선언명 프로젝트의 자기 문서 유실, 별칭 소속 기대값, 주석·`{}` frontmatter 오판 2 |
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
| 최종 리뷰 차단 문제 해결·검사 근거 | 이 문서 | 1차 정확성 지적 5건·2차 2건·병합 차단 2건 반영, 정리 지적 3건은 사유와 함께 보류 |
| 평가 Vault 실측·문서·범위 밖 무변경 | `evidence-search.md` 평가 표, `git diff --stat` | 사용자 vault·운영 설정·브리핑·쓰기 코드 변경 없음 |
