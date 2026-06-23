# LLM Router — 미완료 항목

`feat/llm-router-fallback` (2026-06-23) 코드 리뷰에서 범위 초과로 스킵한 기술 부채.

---

## 1. `LONG_WRITER_PROVIDER` / `POLISH_PROVIDER` 환경변수 미연결

**파일:** `app/config.py:40-41`, `app/llm/router.py:29-35`

`.env`에 `LONG_WRITER_PROVIDER=gemini`를 설정해도 라우터가 `TASK_CHAINS` 상수만 읽어 무시된다.

**수정 방향:** `get_provider_for_task()`에서 `settings.long_writer_provider` / `settings.polish_provider` 값이 있으면 해당 task chain의 첫 번째 provider를 override하도록 `_build_chain()` 수정.

---

## 2. `_FallbackProvider` vs `FallbackChain` 중복

**파일:** `app/llm/factory.py:12-25`, `app/llm/fallback.py`

2-provider 체인인 `_FallbackProvider`는 N-provider `FallbackChain`의 special case다. `get_local_llm_provider()`만 `_FallbackProvider`를 생성한다.

**수정 방향:**
1. `get_local_llm_provider()`를 `FallbackChain([primary, gemini])`으로 교체
2. `_FallbackProvider` 삭제
3. `tests/test_llm_router.py:89`의 `isinstance(provider, _FallbackProvider)` 단언을 duck-type 검사로 교체

---

## 3. `complete_with_json_retry` vs `json_utils.complete_json` 중복

**파일:** `app/llm/fallback.py:52`, `app/services/json_utils.py`

둘 다 "provider 호출 → JSON 파싱 실패 시 재시도" 패턴을 구현한다. `complete_json`은 코드펜스 제거·부분 JSON 추출 기능이 추가로 있어 `complete_with_json_retry`보다 기능이 강하다. 현재 에이전트들은 모두 `complete_json`을 사용하고 `complete_with_json_retry`는 테스트에서만 호출된다.

**수정 방향:** `complete_with_json_retry` 내부를 `extract_json_object()`를 사용하도록 개선하거나, 에이전트들이 `complete_json(FallbackChain, ...)` 형태로 호출하도록 통일 후 `complete_with_json_retry` 제거.

---

## 4. 기존 에이전트들이 새 FallbackChain 라우터를 사용하지 않음

**파일:** `worklog_agent`, `wiki_blog_agent`, `resume_agent`, `portfolio_agent`, `project_agent` 등

해당 에이전트들은 `get_writer_llm_provider()`(구 경로)를 호출한다. Gemini 실패 시 GPT-4o mini / Kimi로 fallback되지 않는다.

**수정 방향:** 에이전트별로 `get_task_llm_provider("writer", settings)` 또는 `get_task_llm_provider("long_writer", settings)`로 교체. `get_writer_llm_provider()` / `get_local_llm_provider()`는 deprecated 처리.
