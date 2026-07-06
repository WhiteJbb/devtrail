# Vault MCP 수정안 — feat/vault-mcp 코드 리뷰 반영

`feat/vault-mcp` 브랜치(main 대비 26개 파일)에 대한 멀티에이전트 코드 리뷰에서 확인된
버그 14건 + 문서 불일치 1건 + 구조 개선 항목의 수정 지시서다. 각 항목은 검증 에이전트가
CONFIRMED(트리거 입력과 잘못된 출력을 코드로 확인) 또는 PLAUSIBLE(메커니즘은 실재,
트리거는 환경 의존)로 판정된 것만 담았다.

## 작업 지침 (공통)

- 브랜치: `feat/vault-mcp`에서 계속 작업한다 (기능 브랜치 규칙).
- 테스트 실행: `py -3.11 -m pytest -q` (셸 기본 `python`은 msys64라 pytest가 없다).
- **main에서도 실패하던 기존 실패 15개는 건드리지 않는다** (test_wiki_core,
  test_capture_agent, test_telegram_media, test_assistant_bot 등 — 이번 작업과 무관).
  수정 전후로 실패 목록이 15개 그대로인지 확인한다.
- 각 수정에는 해당 버그를 재현하는 테스트를 먼저/함께 추가한다 (아래 항목별 테스트 지침 참고).
- 커밋 메시지에 AI 작성 표시(Co-Authored-By 등)를 넣지 않는다 (CLAUDE.md 규칙).
- P1 → P2 → P3 → P4 → P5 순서로 진행한다. P1~P3은 서로 독립적이므로 항목 단위 커밋 권장.

---

## P1 — 데이터 유실/정합성 (가장 먼저)

### 1.1 memory_patch dedup이 두 번째 세션부터 Agent Execution Notes를 버림 [CONFIRMED]

- **위치**: `app/vault_tools.py:604` (write_session_process의 memory_patch 생성),
  `app/services/candidate_writer.py:64-95` (find_duplicate)
- **증상**: memory_patch 후보 제목이 `f"{project} — Agent Execution Notes — {date}"`
  고정 형식이라, 날짜만 다른 이전 세션 제목과 유사도 ~0.97(같은 날이면 1.0)로
  `_DEDUP_THRESHOLD=0.85`를 넘어 `find_duplicate`가 기존 파일을 반환한다.
  `write()`는 **새 본문을 어디에도 쓰지 않고** 기존 파일 경로만 돌려주므로, 14일 안에
  같은 프로젝트로 두 번째 세션이 돌면 그 세션의 실수/개선 노트가 조용히 유실된다.
- **수정**: `write_session_process`에서 memory_patch를 쓸 때 dedup을 끈다.

  ```python
  # vault_tools.py write_session_process 내부
  memory_patch_result = writer.write(
      CandidateSpec(kind="memory_patch", ...),
      dedup=False,
  )
  ```

  `record_note`/`record_agent_improvement`의 dedup은 그대로 둔다(같은 이슈 반복 기록은
  진짜 중복이므로 의도된 동작).
- **테스트**: `tests/test_vault_tools.py`에 "같은 프로젝트로 write_session_process를
  이틀 연속 2회 호출하면 MemoryPatches/ 파일이 2개이고 두 번째 본문이 실제로 존재한다"
  를 추가. (현재 코드로는 실패해야 정상.)

### 1.2 final_judge 누락 시 미해결 결정이 Decision 후보로 유출 [CONFIRMED]

- **위치**: `app/vault_tools.py:577-578`
- **증상**: `final_judge = str(decisions.get("final_judge", "")).strip().lower()` 후
  `if decision_text and final_judge != "unresolved":` — 키를 아예 안 넘기면 `""`이
  가드를 통과해 Decision 후보가 생성된다. 반면 `_render_process_body`(477행)는 같은
  누락을 `'unresolved'`로 렌더링한다. 본문에는 "unresolved"라 적히는데 후보는 생성되는 모순.
- **수정**: 가드를 `if decision_text and final_judge not in ("", "unresolved"):`로 변경.
- **테스트**: `test_vault_tools.py`에 final_judge 키를 생략한 호출에서
  `result.decision is None`을 검증하는 케이스 추가 (기존
  `test_write_session_process_no_decision_when_unresolved`는 명시적 "unresolved"만 커버).

### 1.3 MCP 이중 기록이 needs_distill=True라 nightly distill이 재추출·중복 생성 [CONFIRMED]

- **위치**: `app/vault_tools.py:567-573` → `app/agents/capture_agent.py:184`,
  소비처 `app/agents/distill_agent.py:104-107` (`_RAW_PREFIXES = ("00_Inbox/", "10_Worklog/")`)
- **증상**: write_session_process가 남기는 10_Worklog/Sessions/ 노트가
  `needs_distill: True`로 저장돼, 그날 밤 distill이 이미 구조화된 Process를 다시 LLM에
  넣어 방금 분리 생성한 Decision/MemoryPatch와 중복 후보(제목이 달라 0.85 dedup을
  빠져나감)를 만든다.
- **수정**: `capture_session()`에 `needs_distill: bool = True` 파라미터를 추가하고
  frontmatter에 그 값을 쓴다. `write_session_process`는 `needs_distill=False`로 호출한다
  (결정/메모리 분리는 write_session_process가 이미 수행했으므로 재증류 불필요.
  부수 효과로 retention 규칙상 30일 후 삭제 대상이 되는데, 이는 "처리 완료 기록은
  만료된다"는 기존 보존 철학과 일치함).
- **테스트**: `test_capture_session.py`에 needs_distill 파라미터 전달 검증,
  `test_vault_tools.py`에 write_session_process가 만든 worklog 노트의 frontmatter가
  `needs_distill: False`인지 검증.

---

## P2 — "최신" 선택이 시간이 아니라 이름순인 문제군

### 2.1 handoff created_at을 초 단위 timestamp로 [CONFIRMED — 3개 버그의 공통 원인]

- **위치**: `app/services/candidate_writer.py:121`
  (`"created_at": self._now().strftime("%Y-%m-%d")`)
- **증상**: 날짜 단위라 같은 날 handoff가 전부 동점 →
  - `app/vault_tools.py:141` `_list_session_handoffs` 정렬이 stable sort + 파일명
    오름차순(= uuid 앞 8자리 hex 알파벳순)으로 결정돼 briefing의 `handoffs[:3]`,
    `processes[0]`(Suggested Next Actions)이 오전 세션 것을 보여줄 수 있음
  - `_reattach_orphan_plan_if_needed`(180행)와 `max(orphan_plans, ...)`(341행)가 같은 날
    미짝 Plan 중 임의의 것을 선택
- **수정**: created_at을 `self._now().strftime("%Y-%m-%dT%H:%M:%S")`로 변경.
  - 기존 소비처 호환 확인 완료: `find_duplicate`(candidate_writer.py:82)와 retention의
    `_parse_created_at`(retention.py:31)은 `[:10]`만 파싱하므로 안전.
    `_list_session_handoffs`는 `str()` 후 문자열 정렬이라 안전
    (PyYAML이 ISO 문자열을 datetime으로 로드해도 `str()` 결과가 시간순 정렬됨.
    구형 날짜-only 값과 섞여도 `"2026-07-06" < "2026-07-06 09:00:00"` 로 자연스럽게 정렬).
  - retention `_parse_created_at`은 full timestamp가 있으면 활용하도록 개선:
    `datetime.fromisoformat(raw[:19].replace(" ", "T"))` 시도 → 실패 시 기존 `[:10]` 로직.
- **테스트**: 같은 날 시각이 다른 Plan 2개를 만들고(_now 주입은 `CandidateWriter(now=...)`
  이용) briefing의 첫 handoff가 나중 것인지 검증.

### 2.2 pick_review_question이 같은 날 두 번째 세션을 영원히 무시 [CONFIRMED]

- **위치**: `app/services/review_question.py:29`
- **증상**: `sorted(sessions_dir.glob("*.md"), reverse=True)` — CaptureAgent가 같은 날
  충돌을 `-2` 접미사로 푸는데 ASCII상 `'-'(0x2D) < '.'(0x2E)`라
  `...session-2.md`(신규)가 `...session.md`(구)보다 **앞**에 정렬되고 reverse에서 뒤로
  밀린다. 같은 날 다른 프로젝트 간에도 slug 알파벳 역순이 시간을 이긴다.
- **수정**: 파일명 정렬 대신 frontmatter `created_at`(capture_session이 이미 초 단위
  ISO로 기록, capture_agent.py:173)으로 내림차순 정렬. 어차피 각 파일의 frontmatter를
  파싱하고 있으므로 추가 I/O 없음:

  ```python
  entries = []
  for md_path in sessions_dir.glob("*.md"):
      try:
          post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
      except Exception:
          continue
      created = str(post.metadata.get("created_at", "") or "")
      entries.append((created, md_path, post))
  entries.sort(key=lambda e: e[0], reverse=True)
  for created, md_path, post in entries:
      ...  # 기존 본문 파싱 로직
  ```

  (선택) 오래된 세션에 질문이 없으면 전체를 훑는 비효율이 있으므로 최신 10개까지만
  검사하고 None 반환해도 된다 — "오늘의" 복습 질문에 열흘 전 질문은 무의미.
- **테스트**: `test_review_question.py`에 같은 날짜 `...session.md`(질문 A, 이른
  created_at)와 `...session-2.md`(질문 B, 늦은 created_at)를 만들어 B가 선택되는지 검증.

### 2.3 vault-cleanup이 Plan/Process 짝을 무시하고 비결정적으로 삭제 [CONFIRMED]

- **위치**: `app/services/retention.py:82-108`
- **증상**: (a) 파일 단위 삭제라 keep-N 컷이 짝 사이를 가를 수 있음 — 66일 전
  PlanA+ProcA, 최근 PlanB+ProcB, keep=3이면 A짝 중 하나만 `items[3:]`에 들어가
  ProcA만 삭제되고 PlanA가 생존 → 이후 모든 briefing이 거짓 "미짝 Plan 경고"를 내고,
  이후 plan 없는 Process가 그 stale session_id로 재귀속(2.1/P3.2와 연쇄).
  (b) 92행 `project_dir.glob("*.md")`에 `sorted()`가 없고 created_at이 날짜 단위라
  동점 시 파일시스템 열거 순서가 삭제 대상을 결정 — 머신마다 결과가 다름.
- **수정**: session_id 짝을 보존 단위로 묶는다.

  ```python
  # 1) 파일들을 session_id로 그룹핑 (session_id 없으면 파일 단독 그룹)
  # 2) 그룹의 created = 그룹 내 최신 created_at
  # 3) 그룹을 created 내림차순 정렬 (동점 tie-break: 그룹 내 최소 파일명 — 결정적)
  # 4) 최신 keep_per_project개 그룹은 무조건 보존
  # 5) 나머지 그룹은 created가 retention_days 초과면 그룹 전체 삭제
  ```

  glob에 `sorted()`를 추가하고, `_parse_created_at`은 2.1의 full-timestamp 개선을 적용.
  keep_per_project의 의미가 "파일 N개"에서 "세션 N개"로 바뀌므로 docstring과
  `app/cli.py` vault-cleanup의 `--keep` help 텍스트("프로젝트당 보존할 최신 세션(짝) 수")도
  갱신한다.
- **테스트**: `test_retention.py`에 (a) 오래된 짝+최근 짝, keep=1로 오래된 짝이
  **둘 다** 삭제되고 최근 짝이 **둘 다** 생존하는지, (b) 같은 created_at 4파일에서
  결과가 결정적인지(두 번 실행 동일) 검증.

---

## P3 — 입력 방어 / 경계 조건

### 3.1 .claude/vault.json이 dict가 아니면 briefing이 AttributeError [CONFIRMED]

- **위치**: `app/vault_tools.py:239-243` (`_load_project_config`)
- **증상**: `"devtrail"`(스칼라)이나 `["devtrail"]`(배열)은 유효 JSON이라
  JSONDecodeError가 안 나고, try **밖**의 `data.get("project", "")`에서 AttributeError.
  briefing 안내문이 사용자에게 vault.json 작성을 권하므로 실수 가능성이 높은 입력이다.
- **수정**: `json.loads` 직후 `if not isinstance(data, dict): return ""` 추가.
- **테스트**: vault.json에 `"devtrail"`만 쓴 tmp repo로 get_project_briefing이 예외 없이
  matched=False(또는 이름 매칭 폴백)를 반환하는지 검증.

### 3.2 orphan Plan 재귀속에 recency 상한이 없음 [CONFIRMED]

- **위치**: `app/vault_tools.py:163-181` (`_reattach_orphan_plan_if_needed`)
- **증상**: 이번 세션이 write_work_plan을 안 불렀을 뿐인데(서버 재시작이 아니어도 발동)
  몇 주 전 무관한 세션의 미짝 Plan session_id로 오늘의 Process/worklog가 재귀속된다.
  정당한 "미짝 Plan 경고"도 사라지고, 반환 session_id가 서버 `_SESSION_ID`·마커와
  불일치한다.
- **수정**: 재귀속 후보를 **최근 24시간 내 생성된** 미짝 Plan으로 제한한다(설계 의도인
  "같은 세션 중 서버 재시작" 복구에는 충분). 2.1의 full timestamp를 활용:

  ```python
  cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
  orphan_plans = [
      p for p in plans
      if p["session_id"] and p["session_id"] not in paired_ids
      and str(p["created_at"]) >= cutoff
  ]
  ```

  (구형 날짜-only created_at은 `"2026-07-05" < "2026-07-05T14:00:00"` 비교로 자연스럽게
  구제외되는데, 당일 날짜-only 값이 컷오프보다 작게 비교돼 제외될 수 있음 — 신규 파일은
  전부 full timestamp이므로 허용 가능한 마이그레이션 엣지로 docstring에 명시.)
- **테스트**: 25시간 전 created_at의 미짝 Plan이 있어도 새 session_id가 유지되는지,
  1시간 전 Plan이면 재귀속되는지 검증.

### 3.3 search_vault가 scope 필터를 절단 이후에 적용해 빈/불완전 결과 [CONFIRMED]

- **위치**: `app/vault_tools.py:194-206`, `app/services/wiki_service.py:184-200`
- **증상**: `wiki.search(query, limit=max(limit*4, 20))`가 vault **전체**(00_Inbox,
  10_Worklog, 50_Outputs 포함)에서 전역 top-N을 만든 뒤에야 vault_tools가 prefix를
  거른다. 동점 tie-break가 path 오름차순이라 00_/10_ 폴더가 20_/60_보다 우선. 세션
  요약이 쌓이면 프로젝트명 검색에서 worklog가 상위 40개를 채워 MCP `search_vault`와
  Telegram `ask-vault`가 "관련된 노트를 찾지 못했습니다"를 반환한다.
- **수정**: `WikiService.search`에 선택 인자 `prefixes: tuple[str, ...] | None = None`을
  추가해 `scan_notes()` 결과를 **점수화·절단 전에** 필터링한다:

  ```python
  def search(self, query, limit=10, prefixes=None):
      notes = self.scan_notes()
      if prefixes:
          notes = [n for n in notes if n.path.startswith(prefixes)]
      return self._search_notes(notes, query, limit=limit)
  ```

  vault_tools.search_vault는 `wiki.search(query, limit=limit, prefixes=_ALLOWED_READ_PREFIXES)`
  로 호출하고 사후 필터·4배 over-fetch를 제거한다.
- **테스트**: tmp vault에 10_Worklog 노트 25개(키워드 다수)와 20_Knowledge 노트 1개를
  만들고 search_vault가 knowledge 노트를 반환하는지 검증.

### 3.4 read_note: 비 UTF-8 노트와 디렉터리 경로 처리 [CONFIRMED, 낮음]

- **위치**: `app/vault_tools.py:209-219`
- **증상**: (a) `read_text(encoding="utf-8")` strict라 외부 도구가 cp949로 저장한 노트를
  search_vault는 색인하는데(WikiService `_parse_note`는 errors="replace" 폴백) read_note는
  UnicodeDecodeError를 낸다. (b) `"20_Knowledge/AI"` 같은 스코프 내 디렉터리가
  `exists()`를 통과해 read_text에서 PermissionError(Windows)/IsADirectoryError(POSIX).
- **수정**:

  ```python
  if not resolved.exists() or not resolved.is_file():
      raise VaultScopeError(f"노트를 찾지 못했습니다: {rel_path}")
  try:
      return resolved.read_text(encoding="utf-8")
  except UnicodeDecodeError:
      return resolved.read_text(encoding="utf-8", errors="replace")
  ```

- **테스트**: cp949 바이트로 저장한 노트 읽기, 디렉터리 경로에 VaultScopeError 검증.

### 3.5 미등록 프로젝트의 handoff가 briefing에 영원히 안 보임 + 프로젝트명 표기 불일치 [PLAUSIBLE]

- **위치**: `app/vault_tools.py:246-283` (매칭 실패 분기), `write_work_plan`/`write_session_process`
- **증상**: write_work_plan은 아무 project 문자열이나 받아
  `SessionHandoffs/<slug(원본)>/`에 쓰지만, briefing은 30_Projects 등록 또는 vault.json이
  있어야만 그 폴더를 읽는다(테스트 `test_get_project_briefing_cold_start_...`가 현재 동작을
  고정). 또 쓰기는 에이전트가 넘긴 원본 표기, 읽기는 레지스트리 확정 표기를 slug해서
  대소문자/철자가 다르면 폴더가 갈린다(Linux에서 실제 분리).
- **수정** (둘 다 소규모):
  1. `write_work_plan`/`write_session_process` 시작부에서
     `ProjectMemoryLoader(vault_dir).load().find(project)`가 매칭되면 레지스트리 표기로
     project를 치환한 뒤 기록한다 (읽기와 같은 표기 보장).
  2. 매칭 실패 분기에서 `60_Candidates/SessionHandoffs/` 하위 폴더명도 후보 목록에
     추가하고, `probe_name`이 그 폴더명과 대소문자 무시로 일치하면 matched=True로
     처리해 handoff를 노출한다.
- **테스트**: 등록 없는 프로젝트로 write_work_plan → get_project_briefing(같은 이름)이
  handoff를 포함하는지; "devtrail"로 쓰고 "Devtrail"로 조회해도 같은 폴더인지 검증.
  기존 `test_get_project_briefing_cold_start_returns_global_memory_only`는 새 동작에 맞게
  수정한다(핸드오프도 컨텍스트도 전혀 없을 때만 matched=False).

### 3.6 digest의 "미해결 개념: -" 노출 [CONFIRMED, 사소]

- **위치**: `app/services/review_question.py:64-70`
- **증상**: 빈 placeholder `- `가 strip 후 `"-"`가 되어 `startswith("- ")`에 안 걸리고
  그대로 반환 → push-digest가 `미해결 개념: -`를 전송.
- **수정**: 값 정리 후 `if text in ("-", ""): continue` 처리 (질문 쪽 `1.` placeholder는
  이미 빈 문자열로 걸러짐).
- **테스트**: unclear_concepts가 빈 세션에서 `unclear_concept == ""` 검증.

---

## P4 — 훅 스크립트 (미등록 상태지만 등록 전 필수 수정)

`scripts/hooks/`는 아직 `.claude/settings.json`에 등록되지 않았으므로 현재 실동작
버그는 아니지만, 문서(§6.2)가 등록을 안내하므로 등록 전에 반드시 고친다.

### 4.1 세션 마커: import 부작용 제거 + staleness 방어 [CONFIRMED]

- **위치**: `app/mcp_server.py:36, 51`, `scripts/hooks/stop-process-check.ps1:44-57`
- **증상**: (a) `_write_session_marker(False)`가 모듈 import 시점에 실행돼 `import
  app.mcp_server`만으로 cwd에 마커가 생성/리셋됨(REPL, 향후 eager import 시 라이브
  세션의 true 마커를 덮음). (b) 훅이 `process_written`만 읽고 세션 식별·신선도를 안 봐서
  — 이전 세션의 true 잔존 마커가 이후 MCP 없는 dirty 세션을 통과시키고, 같은 repo 동시
  세션이 서로의 상태를 덮어씀. (c) 서버 프로세스 cwd ≠ 훅 payload cwd일 수 있음
  (Claude Desktop 확실, Claude Code 미확인).
- **수정**:
  1. `_write_session_marker(process_written=False)` 호출을 모듈 레벨에서 `main()` 안
     (mcp.run 직전)으로 이동.
  2. 마커 JSON에 `"updated_at": datetime.now().isoformat()` 추가.
  3. stop-process-check.ps1: 마커의 updated_at이 **12시간 이상** 지난 경우 마커 없음으로
     간주(스테일 true 방어). 동시 세션 공유 문제는 단일 파일 설계상 완전 해결이 불가하므로
     스크립트 헤더 주석에 알려진 한계로 명시.
  4. session-start-briefing.ps1 시작부에서 기존 마커 파일을 삭제(세션마다 clean start —
     MCP 서버가 뜨면 main()이 다시 쓴다).
- **테스트**: `tests/test_mcp_server.py`의 `_reload_mcp_server` 픽스처가 import만으로
  마커가 생기던 전제를 쓰고 있다면 main() 호출 기반으로 수정. import 시 마커가 생기지
  **않는지** 테스트 추가.

### 4.2 Stop 훅이 stop_hook_active를 확인 안 함 [CONFIRMED]

- **위치**: `scripts/hooks/stop-process-check.ps1:18-27`
- **증상**: 차단 조건을 해소할 수 없는 상황(MCP 미연결 + dirty)에서 매 Stop마다
  decision:block → Claude Code가 8회 연속 차단 후에야 강제 해제, 그때까지 강제 계속
  실행으로 토큰 낭비. 공식 문서가 stop_hook_active 확인을 요구.
- **수정**: stdin payload 파싱부에서
  `if ($payload -and $payload.stop_hook_active) { exit 0 }` 를 추가.

### 4.3 한글 briefing cp949 mojibake [CONFIRMED]

- **위치**: `scripts/hooks/session-start-briefing.ps1:30-36`
- **증상**: print_briefing.py는 stdout을 UTF-8로 강제하는데 PowerShell은
  `[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 디코딩 → 한글 briefing이
  깨진 채 additionalContext에 주입.
- **수정**: 두 .ps1 모두 stdin 파싱 전에 추가:

  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
  ```

### 4.4 bare `python` 호출 + EAP=Stop 미보호 네이티브 호출 [CONFIRMED]

- **위치**: `scripts/hooks/session-start-briefing.ps1:30`,
  `scripts/hooks/stop-process-check.ps1:32`, `scripts/hooks/print_briefing.py:20-26`
- **증상**: (a) `& python ... 2>$null`이 `$ErrorActionPreference="Stop"` 하에서 try 밖 —
  python 부재 시 CommandNotFoundException으로 훅 전체 사망, PS 5.1/pwsh<7.2에서는 stderr
  한 줄(경고/traceback)만으로 NativeCommandError. (b) PATH python에 devtrail이 없으면
  print_briefing.py의 모듈 레벨 import(20행)와 try 밖 `get_settings()`(26행)가
  "항상 exit 0" 계약을 깨고 traceback으로 종료. (c) stop-process-check.ps1의
  `git status --porcelain 2>$null`은 같은 이유로 PS 5.1에서 git 경고 한 줄에 catch로
  빠져 dirty tree를 clean으로 오판(fail-open).
- **수정**:
  1. `app/cli.py`에 `project-briefing` 커맨드 추가 — print_briefing.py의 main 로직을
     그대로 옮긴 얇은 래퍼(인자: repo 경로, 기본 cwd; 모든 예외를 삼키고 안내문 출력 후
     exit 0). scripts/hooks/print_briefing.py는 삭제하고 session-start-briefing.ps1은
     `devtrail project-briefing $cwd`를 호출한다(설치된 엔트리포인트라 인터프리터
     문제가 사라짐). `devtrail`가 없을 때를 대비해 호출을 try/catch로 감싼다.
  2. 두 .ps1의 네이티브 호출(devtrail, git)을 전부 try/catch로 감싸고, 해당 블록만
     `$ErrorActionPreference = "Continue"`로 낮춘 뒤 호출이 끝나면 복원한다
     (`2>$null`은 제거 — stderr는 버리지 말고 무시되도록 둔다).
  3. print_briefing.py를 남겨두는 선택을 하는 경우엔 최소한 import와 get_settings()를
     try 안으로 옮긴다 — 단, 1안(CLI 커맨드)이 근본 해결이므로 권장.
- **테스트**: `tests/test_cli.py`(또는 신규)에 `project-briefing`이 vault 미설정에서도
  exit code 0인지 CliRunner로 검증.

---

## P5 — 정합성/구조 (기능 버그는 아니지만 이번에 정리)

### 5.1 apply-memory-patch가 session_handoff를 40_AgentMemory에 append 가능 [CONFIRMED]

- **위치**: `app/agents/curator_agent.py` apply_memory_patch (~175행)
- **증상**: promote_candidate는 session_handoff를 거부(122행)하지만 apply_memory_patch는
  kind 검사가 전혀 없어 `devtrail apply-memory-patch "60_Candidates/SessionHandoffs/..."`
  로 Process 본문 전체가 05_OpenLoops.md에 붙는다. (main부터 있던 일반 갭이지만, 이번
  PR이 "절대 승격 금지" kind를 처음 도입하면서 비대칭이 생김.)
- **수정**: apply_memory_patch 초입에서 candidate_type을 읽어
  `kind != "memory_patch"`면 ValueError (`_normalize_kind` 적용 후 비교).
  "memory_patch 후보만 적용할 수 있습니다" 메시지.
- **테스트**: `test_curator_agent.py`에 handoff 경로로 apply 시 ValueError, knowledge
  후보로 apply 시에도 ValueError 검증.

### 5.2 CLAUDE.md 폴더 권한 표 갱신 [CONFIRMED]

- **위치**: `CLAUDE.md` 70행
- **수정**: `| 10_Worklog/Sessions/ | capture-session 출력 (AI 세션 요약) | 읽기 전용 |`
  → 역할을 `capture-session / write_session_process 출력 (AI 세션 요약)`으로 변경.
  권한 셀("읽기 전용")은 "직접 수정 금지, 지정 도구로만 기록" 의미가 유지되므로 그대로.

### 5.3 SessionHandoffs 경로 규칙 단일화

- **위치**: `app/services/candidate_writer.py:162-164`, `app/vault_tools.py:115-121`,
  `app/services/retention.py:85`
- **문제**: `<slug(project) or "_Unassigned">` 규칙이 3곳에 중복 — 한 곳만 바뀌면
  briefing/retention이 조용히 빈 결과를 낸다.
- **수정**: candidate_writer.py에 공개 함수 추가 후 세 곳 모두 이것만 사용:

  ```python
  SESSION_HANDOFF_DIR = "60_Candidates/SessionHandoffs"

  def handoff_project_dir(project: str) -> str:
      sub = slug_component(project) if project.strip() else "_Unassigned"
      return f"{SESSION_HANDOFF_DIR}/{sub}"
  ```

  vault_tools의 `_project_dir_slug` 제거, retention의 하드코딩 경로 치환.

### 5.4 Learning Recovery 헤딩 문자열 상수화

- **위치**: 작성자 `app/agents/capture_agent.py:268-271`·`app/vault_tools.py:498-509`,
  소비자 `app/services/review_question.py:35-39`
- **문제**: 헤딩 문구가 3곳에 하드코딩 — 한 곳만 바꾸면 복습 질문 기능이 무증상으로
  None만 반환.
- **수정**: `app/services/review_question.py`(소비자 쪽)에 상수 정의 후 세 곳이 import:

  ```python
  HEADING_QUESTIONS = "다음에 직접 설명해봐야 할 질문"
  HEADING_UNCLEAR = "내가 아직 완전히 이해하지 못한 개념"
  HEADING_AI_LED = "AI가 주도적으로 처리한 부분"
  HEADING_RELATED = "관련 Vault 후보"
  ```

  (순환 import 없음: capture_agent/vault_tools → review_question 단방향.)

### 5.5 복습 질문 블록을 digest 빌더로 이동

- **위치**: `app/cli.py:923-939` (push_digest 핸들러 안 인라인 조립)
- **문제**: Telegram 전송본에만 붙고 50_Outputs/Digest/에 저장되는 파일에는 없어 두
  산출물이 영구히 달라짐.
- **수정**: 복습 질문 섹션 문자열 조립을 `app/services/review_question.py`의
  `format_review_block(vault_dir) -> str`(없으면 "") 함수로 추출하고, push-digest와
  nightly digest 빌더(`app/agents/nightly_distill_agent.py`의 digest 조립부) 양쪽에서
  호출한다.
- **테스트**: nightly digest 산출물에 "오늘의 학습 회수" 블록 포함 검증.

### 5.6 (선택) 소소한 정리 — 시간 남으면

- `app/mcp_server.py`: 4.1 적용 후 `_write_session_marker` 관련 docstring 갱신.
- `app/vault_tools.py:264-269`: 무의미한 `else: resolved_project = ""` 분기와
  `project_memory.find()` 이중 호출 정리.
- `app/vault_tools.py:348-354`: 원소가 0~1개뿐인 `next_actions` 리스트 기계 제거.
- `app/services/retention.py:24`: 아무도 읽지 않는 `CleanupResult.dry_run` 필드 —
  유지하되 사용하거나 제거.
- 두 .ps1의 동일한 stdin→cwd 파싱 블록을 `scripts/hooks/common.ps1`로 추출해 dot-source.

## P6 — (선택) 성능: 이번 배치에 포함하지 말 것

P1~P5를 전부 끝내고 테스트가 안정된 뒤, **별도 커밋(가능하면 별도 PR)**으로만 진행한다.
버그 픽스와 섞지 않는다. 착수 전 사용자에게 진행 여부를 확인할 것.

### 6.1 vault 노트 인덱스 캐시 (search_vault / ask-vault / briefing 공통)

- **문제**: `WikiService.scan_notes()`가 호출마다 vault 전체 `*.md`를 read+frontmatter
  파싱한다. MCP `search_vault`, Telegram `ask-vault`(메시지당 1회), `get_project_briefing`
  이 전부 이 경로를 타서 노트 수천 개 규모에서 호출당 수천 회 파일 I/O가 반복된다.
- **범위**: WikiService에 `(path, mtime, size)` 키의 인메모리 파스 캐시를 추가 —
  scan_notes가 mtime/size 불변 파일은 캐시된 WikiNote를 재사용하고 변경/신규 파일만
  재파싱한다. MCP 서버·serve-bot 같은 장수 프로세스에서만 효과가 있으면 충분하므로
  디스크 영속화는 하지 않는다(과설계 금지). 무효화 기준은 mtime+size 둘 다.
- **주의**: CLI 단발 실행 경로의 동작이 달라지면 안 됨(캐시 미스 시 결과 동일해야 함).
  테스트: 같은 인스턴스로 2회 검색 시 결과 동일 + 파일 수정 후 재검색 시 반영 검증.

### 6.2 SessionStart 훅 지연 (~1초) 완화

- **문제**: 훅이 콜드 Python 시작 + `app.vault_tools` import(~580ms 실측, pydantic 체인)
  + 전체 vault 스캔을 세션 시작마다 동기 수행한다.
- **범위(순서대로, 앞의 것만으로 충분하면 중단)**:
  1. `app/vault_tools.py`의 top-level import 중 briefing에 불필요한 것(CaptureAgent,
     ContextPackBuilder)을 해당 함수 내부로 지연 — import 비용의 큰 부분 제거.
  2. `get_project_briefing`에서 매칭 실패 시에도 무조건 로드하는 AgentMemoryLoader를
     `resolved_project` 확정 이후로 이동(매칭 실패 경로는 project_memory만 필요).
  3. 그래도 부족하면: briefing 결과를 `.claude/.vault-mcp/briefing_cache.md`에 캐시하고
     훅은 파일만 읽고, 갱신은 MCP 서버가 담당 — 이건 4.1 마커 설계와 얽히므로 반드시
     사용자와 상의 후 진행.

## P7 — (선택) 기록 밀도: AI가 내용을 알차게 채우도록

배관(기록 → 다음 세션 소비 루프)은 P1~P5로 완성됐고, 남은 병목은 기록 **내용의
충실도**다. 에이전트의 작성 품질에 영향을 주는 층위는 세 겹이며, 효과 순서대로:

1. **MCP tool docstring** — 에이전트가 도구를 호출할 때마다 반드시 읽는 유일한 지침.
   Claude Desktop 등 CLAUDE.md가 없는 클라이언트에도 적용되는 유일한 층. 최우선.
2. **CLAUDE.md** — Claude Code 세션 규칙. capture-session rule(fallback)에는 이미 상세한
   작성 기준이 있는데 MCP 경로(write_session_process)에는 대응 기준이 없다 — 이 비대칭을
   메운다.
3. **서버측 검증** — 최후 방어선. 빈 값/placeholder를 조용히 저장하지 않는다.

### 7.1 write_session_process에 git 스냅샷 추가

- **문제**: `vault_tools.write_session_process`가 `capture_session`을 호출할 때
  `from_repo`를 넘기지 않아, CLI capture-session에는 있는 branch/commit/changed_files
  frontmatter가 MCP 세션 기록에는 없다. "Files Touched"가 에이전트의 주장뿐이고
  어느 커밋에서 한 작업인지 객관적 앵커가 없다.
- **수정**: `write_session_process`(vault_tools)와 MCP tool(mcp_server)에
  `repo: str = ""` 파라미터를 추가하고, 값이 있으면 `capture_session(...,
  from_repo=True, repo=repo)`로 전달. MCP 서버는 `str(Path.cwd())`를 기본값으로 주입
  (서버가 프로젝트 디렉터리에서 뜨는 Claude Code 기준; repo가 git이 아니면
  capture_repo_snapshot이 error 스냅샷을 남기므로 안전).
- **테스트**: tmp git repo에서 write_session_process 후 worklog frontmatter에
  branch/commit이 있는지 검증.

### 7.2 MCP tool docstring에 작성 기준 명시

- **문제**: `write_session_process`/`write_work_plan` docstring이 파라미터 나열뿐이라
  `what_changed="작업함"` 수준의 입력도 자연스럽게 통과한다.
- **수정**: `app/mcp_server.py`의 두 tool docstring에 작성 기준을 추가. 예:

  ```
  각 항목 작성 기준 (CLAUDE.md capture-session rule과 동일):
  - what_changed: "X를 구현했다"가 아니라 "X가 없어서 Y 문제가 생겼고 Z로 해결했다"
    수준으로, 작업 흐름 순서 포함. 2문장 이상.
  - files_touched: 파일 경로마다 변경 이유 한 줄씩.
  - project_decisions: 왜 이 방향인지 + 고려한 대안. 나중에 "왜 이렇게 했지?"가
    나오지 않을 수준.
  - next_session: 다음 세션이 이것만 읽고 이어서 시작할 수 있는 구체성.
  - learning_recovery.questions: 실제로 하지 않은 일·과장된 이해도 금지.
  ```

- 함께: `record_note`/`record_agent_improvement` docstring에도 evidence(재현 상황)
  포함 기준 한 줄씩.

### 7.3 CLAUDE.md에 MCP 경로 작성 기준 연결

- **문제**: CLAUDE.md의 상세한 "작성 기준" 절은 capture-session fallback rule 안에
  있어 MCP 1차 경로에는 적용 문구가 없다.
- **수정**: CLAUDE.md의 Session Lifecycle 절에 한 문단 추가 — "write_session_process
  호출 시에도 아래 capture-session rule의 작성 기준(내용 수준·불확실성 표기·실제로
  하지 않은 일 금지)을 동일하게 적용한다."

### 7.4 서버측 최소 검증

- **문제**: 빈 문자열/`- ` placeholder도 조용히 저장된다.
- **수정**: `vault_tools.write_session_process`에서 `what_changed`와 `next_session`이
  비었거나 placeholder(`-`, `- `)면 저장은 하되 반환 dict에
  `"warnings": ["what_changed가 비어 있습니다 — 다음 세션 briefing이 빈약해집니다", ...]`
  를 포함시킨다 (거부하면 컴팩팅 직전 기록 자체가 유실될 수 있으므로 거부는 하지 않는다).
  MCP tool은 warnings를 그대로 반환해 에이전트가 즉시 보완 호출을 하도록 유도.
- **테스트**: 빈 what_changed로 호출 시 warnings 포함 + 파일은 정상 생성 검증.

### 7.5 briefing에 상세 열람 안내 한 줄

- **문제**: briefing은 handoff당 3섹션×400자 발췌만 노출하고, 전문은 `read_note`로
  읽을 수 있다는 사실을 에이전트가 스스로 발견해야 한다.
- **수정**: `get_project_briefing`이 만드는 "Recent Session Handoff" 섹션 끝에
  `"(전문은 read_note로 위 경로를 읽을 것 — Implementation Trace/결정 이유는 발췌에 포함되지 않음)"`
  한 줄을 추가.

### 범위 밖 (백로그로만 기록)

- **시맨틱 검색** — WikiService가 키워드 토큰 매칭이라 표현이 다르면 과거 결정을 못
  찾는다. 임베딩 인덱스는 의존성·저장소 설계가 필요한 별도 프로젝트로, 여기서는
  다루지 않는다.

## 명시적으로 수정하지 않는 것

- **PreCompact + decision:block 무효 주장** — 리뷰 중 제기됐으나 최신 공식 문서 확인
  결과 PreCompact도 decision:block을 지원함이 확인돼 반박됨. 수정 불필요.
- main에서도 실패하던 기존 테스트 15개.

## 완료 기준

1. `py -3.11 -m pytest -q` — 신규 테스트 전부 통과, 기존 실패 15개 외 추가 실패 없음.
2. P1~P4의 각 버그에 대응하는 회귀 테스트가 존재한다.
3. `git diff`에 이 문서에 없는 동작 변경이 섞이지 않았다.
