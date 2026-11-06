# 새 검색의 stdio 왕복과 모아 연결 확인

2026-11-06 UTC, 기준 소스 `fa991fd`. 임시 Vault에서 실제 CLI 서버와의 왕복은 통과했다.
**모아/PM 운영 연결은 확인하지 못했다.** 이 대화에는 Devtrail MCP 도구가 없어서
`structured` 호출을 운영 연결로 실행할 수 없다. 사용자 Vault, Hermes 프로필·설정·프로세스는 건드리지 않았다.
서버 결함은 발견하지 않아 제품 코드나 검색 정책을 바꾸지 않았다.

## 재현과 증거

```sh
venv/bin/python -m pytest -q -s tests/test_mcp_stdio.py
```

네이티브 CPython 3.11.2, Linux aarch64/glibc 2.36, MCP SDK 1.30.0,
AnyIO 4.16.0, pytest 9.2.0, Typer 0.28.0에서 실행했다.
프로젝트 선언 버전은 `0.1.0`이다. 이 환경은 editable 설치 메타데이터와
`venv/bin/devtrail` 실행 파일이 없어 다음과 같이 **동일한 Typer CLI 진입점**을 실행한다.

```sh
/work/repo/venv/bin/python -m app.cli mcp-serve
```

클라이언트는 `mcp.client.stdio.stdio_client`와 `ClientSession`이다.
별도 OS 프로세스를 생성하고 `initialize` → `tools/list` → `tools/call` 7회를
같은 연결에서 수행한다. 서비스 직접 호출·내부 `call_tool`·가짜 transport는 사용하지 않는다.
자식 cwd·HOME·Vault·마커는 `TemporaryDirectory` 안에 두며, 모든 Settings 필드를
기본값 환경변수로 덮어서 저장소 `.env`나 부모의 키·토큰·Vault 설정을 사용하지 않는다.
SDK 종료 컨텍스트 뒤 PID 소멸과 임시 디렉터리 제거도 검사한다. 쓰기 도구는 호출하지 않는다.

`-s` 출력에는 initialize 응답, 두 도구의 전체 inputSchema, 각 요청과 응답,
`child_reaped=true`, `temporary_vault_removed=true`가 남는다.
이번 실행의 원본 로그는 작업 산출물 `mcp-stdio.txt`로 별도 보관한다.

initialize 관측값:

```json
{"protocolVersion":"2025-11-25","serverInfo":{"name":"devtrail-vault","version":"1.30.0"},"capabilities":{"tools":{"listChanged":false}}}
```

여기서 `serverInfo.version=1.30.0`은 FastMCP가 제공하는 SDK 버전이다.
Devtrail 소스 revision이나 설치 경로를 식별하는 값으로 쓰면 안 된다.

실제 `tools/list`에서 받은 스키마(유일한 필수 인자는 각각 `query`, `rel_path`):

| 도구 | properties 이름 전체 |
|---|---|
| search_vault | query, limit, structured, project, include_common, include_unattributed, include_history, kinds, cursor, max_chars |
| read_note | rel_path, structured, start_line, max_lines, max_chars, expected_version |

`structured` 기본값은 false, `project`·`cursor`·`expected_version`은 빈 문자열,
`include_*`는 false다. 줄 수·문자 예산과 legacy 기본값은 [기존 계약](./evidence-search.md)을 따른다.

합성 Vault는 Alpha/Beta 프로젝트, 공통 메모리, 소속 불명 산출물, 금지된 Inbox로 구성한다.

| 왕복 | 확인 결과 |
|---|---|
| `search_vault(query="왕복토큰", structured=true, project="Alpha")` | Alpha 결정 1건. 타 프로젝트 2문서, 공통 1문서, 소속 불명 1문서 제외 |
| 검색 발췌 | `30_Projects/Alpha/Decisions/search.md`, 5–5줄, `왕복토큰 알파 원문`, `sha256:029dc605a77cf99e` |
| 위 경로·start_line=5·max_lines=1·expected_version을 넘긴 structured 읽기 | 성공. content가 검색 발췌 및 fixture 원문 줄과 일치. 파일 바이트 SHA-256 앞 16자리도 독립 비교 |
| 같은 검색에 `include_common=true` | Alpha 결정 + 공통 메모리 2건만 반환 |
| legacy 검색(query/limit), 읽기(rel_path) | 기존 키 5개를 가진 리스트 4건, 전문 문자열 반환 |
| fixture 파일 수정 뒤 같은 expected_version으로 읽기 | `ok=false`, `error.code=version_mismatch`, content 없음 |
| structured Inbox 읽기 | `error.code=scope_violation` |

MCP SDK 응답에서는 값이 `structuredContent.result`에 감싸진다. `isError=false`여도
structured 값의 `ok`와 `error.code`를 확인해야 한다(version_mismatch 등이 그 예다).

## 구형 노출의 경계를 분리하기

| 경계 | 현재 근거와 상태 | 다음 확인 |
|---|---|---|
| PM에 보이는 모델 입력 | 사용자 제공 관측: 검색 query/limit, 읽기 rel_path뿐. 이 환경에서 원본 PM tools/list는 접근 불가 | PM이 받은 두 inputSchema와 실제 도구 이름을 비밀값 없이 확보 |
| 현재 저장소/신규 서버 | 위 실제 stdio 왕복에서 새 스키마 확인 | 운영 대상과 소스 revision·모듈 경로 비교 |
| 운영 서버 실행 대상 | command·args·cwd·Python·import 경로·PID·기동 시각 확인 불가 | 모아를 제공하는 프로필/게이트웨이가 실제로 띄운 자식 기준으로 확인 |
| Hermes 설치 버전과 필터/변환 | 이 컨테이너에 `hermes` 실행 파일이 없음. 운영 프로필·allowlist·adapter 정의 접근 불가 | 설치 버전·소스 revision, 선택한 프로필, mcp_servers 해당 항목과 래퍼의 인자 스키마 확인 |
| 서버/클라이언트 재발견 | 테스트 서버는 tools.listChanged=false. 운영 서버와 Hermes 동작은 확인 불가 | 신규 연결의 raw tools/list와 최종 모델 도구 정의를 각각 비교 |

따라서 캐시·오설치 어느 쪽도 원인으로 확정하지 않는다. 다른 소스를 가리키는 실행 경로,
기동 후 소스만 갱신된 서버, 클라이언트가 보존한 정의, 별도 래퍼가 고정한 입력은 모두 미확인 가설이다.
새로 띄운 운영 대상 서버의 raw 스키마가 구형이면 실행/설치 경계를, raw는 신형인데 모델 입력만
구형이면 클라이언트 discovery·adapter 경계를 먼저 조사한다. 도구 이름 allowlist를 넓힐 이유는 없다.

[Hermes 공식 MCP 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)에는
시작 시 discovery, 설정 변경 후 `/reload-mcp`, 서버 알림에 따른 tool 목록 갱신이 설명되어 있다
(2026-11-06 열람). 이는 최신 문서의 기능 설명이며 설치된 운영 버전의 지원 증거가 아니다.
운영 버전의 도움말·소스와 대상 프로필에서 지원 여부를 먼저 확인한다.
이 Devtrail 서버는 목록 변경 알림을 제공한다고 선언하지 않으므로 자동 갱신을 기대하지 않는다.

## PM 후속 작업: 최소 변경과 확인 순서

아래는 **별도 운영 설정/배포 작업**이다. 이 저장소 작업에서는 실행하지 않았다.

1. 모아를 제공하는 정확한 Hermes 설치·프로필·게이트웨이/세션과 Devtrail 서버 항목을 식별한다.
   기본 프로필이라고 가정하지 않는다. 설정 전체·환경변수 전체를 출력하지 말고 command/args/cwd,
   선택된 프로필, 기존 읽기 도구 이름 필터, 경로·버전 정보만 기록한다. 실제 PID·기동 시각과
   해당 실행 파일의 Python·Devtrail import 경로를 대조한다. 설정의 토큰은 기록하지 않는다.
2. 해당 **Python과 같은 cwd**에서 다음 읽기 전용 진단으로 경로/함수 시그니처를 확인한다.
   import는 실제 서버 재기동이나 tools/list를 대신하지 못한다.

   ```sh
   <대상-python> -c 'import sys, inspect, importlib.metadata as m; from app import mcp_server; print(sys.executable); print(mcp_server.__file__); print(m.version("mcp")); print(inspect.signature(mcp_server.search_vault)); print(inspect.signature(mcp_server.read_note))'
   ```

3. 현재 서버가 다른/이전 소스를 가리킨다는 근거가 있을 때만 해당 Devtrail 실행 항목을 고친다.
   예를 들어 검증된 런타임 설치의 **절대 경로** `.../.venv/bin/devtrail`과 `args: ["mcp-serve"]`로
   지정한다. 문서의 Mac 런타임 경로를 PM 머신 경로로 복사하지 않는다.
   모듈 경로의 소스가 오래됐으면 Devtrail 런타임 배포가 먼저 필요하다(이번 범위 밖).
   서버가 맞으면 command/args 변경은 필요 없다.
4. 모델 입력을 고정한 별도 adapter가 발견되면 그 adapter가 속한 저장소/설정의 두 읽기 도구 인자만
   최신 raw inputSchema와 맞춘다. 해당 저장소·파일은 아직 식별되지 않았다. 운영 Hermes의 정확한
   `config.yaml` 위치도 프로필 확인 뒤 정한다. 이번에 다른 저장소나 프로필 파일을 수정하지 않았다.
5. 기존 읽기 전용 `tools.include/exclude` 또는 PM allowlist를 그대로 보존한다. 검색과 읽기는 이름이
   같으므로 새 인자를 위해 쓰기 도구·와일드카드 허용을 추가하지 않는다. Devtrail 원서버에는 쓰기 도구도
   있으므로 필터를 제거한 직접 연결을 모아에게 제공하면 안 된다.
6. 새 코드를 로드하려면 해당 MCP 자식의 재기동이 필요하고, 모델 스키마에는 재발견도 필요하다.
   설치 버전에서 `/reload-mcp`가 서버 재연결과 도구 재등록을 수행함을 확인한 경우에만 대상 세션에서 사용한다.
   미지원이면 해당 프로필을 제공하는 Hermes 세션/게이트웨이의 재시작을 별도 승인 범위로 잡는다.
   다른 프로필이나 기본 프로필 전체를 재시작하지 않는다. 기존 프로세스에 소스 파일만 바꾸는 것으로 끝내지 않는다.
7. 재연결 후 raw tools/list와 모델에 보이는 스키마 양쪽에서 위 properties를 확인한다.
   운영 Vault 대신 격리된 테스트 Vault 연결로 동일 테스트를 먼저 수행하고,
   승인된 운영 확인에서는 읽기 전용 프로젝트 검색 → 반환된 발췌 줄·버전으로 원문 읽기를 실제 모아 대화에서 실행한다.
   사용자 Vault의 변경 감지는 파일을 수정하지 말고 임시 Vault에서만 재현한다.
   쓰기 도구가 계속 차단되는지도 확인한다. 새 대화에서 structured 호출까지 성공하기 전에는 연결 완료로 보고하지 않는다.
8. 변경 전 해당 서버 항목·필터와 실행 revision을 비밀값 노출 없이 안전하게 보존한다.
   스키마가 계속 구형이거나 읽기 실패/쓰기 노출이 생기면 변경한 항목만 이전 값으로 돌리고,
   같은 대상 연결을 재생성해 기존 읽기 동작과 필터를 재확인한다. Vault 복구는 필요 없다(변경하지 않음).

## 검사 결과와 남은 제한

| 검사 | 결과 |
|---|---|
| 수정 전 등록 검사 | 716 passed, 3 deselected |
| 신규 stdio 테스트 단독 | 1 passed, initialize/list + tool 호출 7회, 자식·임시 Vault 정리 확인 |
| 수정 후 등록 검사 | 717 passed, 3 deselected |
| 전체 `venv/bin/python -m pytest -q` | 717 passed, 3 failed. 기존 기록과 같은 실패 목록 |

등록 명령:

```sh
venv/bin/python -m pytest -q --deselect tests/test_session_markers.py::test_ancestor_pids_starts_with_self_and_includes_parent --deselect tests/test_session_markers.py::test_marker_for_current_session_picks_own_among_concurrent --deselect tests/test_vault_tools.py::test_get_recent_sessions_groups_plan_and_process
```

전체 실패는 위 등록 검사에서 제외된 기존 3건이다. 부모 PID 조회 2건과 대소문자 프로젝트 조회 1건으로,
[이전 네이티브 검증](./evidence-search-verification.md)과 동일하며 이번에 수정하거나 검사를 약화하지 않았다.
첫 stdio 테스트 작성 중 source_version을 SHA-256 전체 길이라고 가정해 1회 실패했다.
기존 계약의 앞 16자리와 맞춰 테스트 기대값만 바로잡은 뒤 통과했다.

macOS·실제 Hermes 설치 버전·모아 운영 연결은 미검증이다. 저장소 회귀 검증은 운영 연결 완료를 의미하지 않는다.
