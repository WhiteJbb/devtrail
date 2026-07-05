계획을 처음부터 끝까지 읽고, 문서가 전제하는 코드 구조와 관련 문서들을 실제 리포와 대조해서 검토했습니다. 결론부터 말하면 방향과 진단은 정확하고 실행 가능한 계획이지만, 이미 끝난 작업이 P0로 남아 있고, 세션 종료 시 산출물 중복 문제와 CandidateWriter 변경 규모 과소평가라는 설계 구멍이 있습니다.

진단의 정확성 — 코드와 대조해 확인함
계획의 "이미 강한 영역"에 나열된 커맨드(capture-session, distill-today, promote-candidate, nightly-distill, push-digest, serve-bot 등)는 app/cli.py에 전부 실재하고, vault_tools.py와 mcp_server.py는 아직 없어서 P2·P3가 진짜 신규 작업이라는 점도 맞습니다. "병목은 기록이 아니라 소비"라는 §1 진단은 코드 현실과 일치합니다. CLI/MCP 역할 분리 기준(§2), Project Decisions와 Agent Execution Notes의 분리 + evidence/confidence/requires_user_review 필드(§3d), "당장 만들지 않을 것"(§5)의 절제는 이 문서의 강점입니다.

발견한 문제들 (심각도 순)
1. P0는 이미 해소된 것으로 보이고, 관련 문서 링크가 전부 깨져 있음

P0가 고치라는 vault-consumption-plan.md의 read_scope 충돌은 확인 결과 07-02 개정으로 이미 정리되어 있습니다 — vault-consumption-plan.md:60-94에서 60_Candidates/는 candidate 라벨로 포함, 00_Inbox/·10_Worklog/만 제외로 일관됩니다. 게다가 어제 커밋(d9c199a)으로 그 문서가 docs/old/로 이동해서, 이 계획 상단의 관련 문서 링크 3개가 모두 깨졌습니다. 더 근본적인 질문: P1~P3의 상세 스펙(read_scope 코드, 경로 탈출 방지 등)이 가장 자세히 적힌 문서를 archive에 두는 게 맞는지 결정이 필요합니다. P0는 "충돌 수정"이 아니라 "P0 완료 확인 + 링크 정리 + old 이동 여부 재검토"로 바꾸는 게 정확합니다.

2. write_session_process와 capture-session의 중복 — 소유권이 미정의

세션 종료 시점에 에이전트가 거의 같은 내용을 두 번 쓰게 됩니다. CLAUDE.md의 capture-session 규칙(변경 파일, 설계 결정, 남은 문제, 다음 할 일)과 §3d의 Process 스키마(Files Touched, Project Decisions, Next Session)가 대부분 겹치고, Learning Recovery는 P4가 capture-session에, §3d가 Process에 각각 넣어서 양쪽에 존재합니다. 계획은 "원본 세션 기록은 기존 capture-session 흐름을 사용한다"(§3d)고만 말하는데, 이러면 P5의 복습 질문을 10_Worklog/Sessions/에서 뽑는지 SessionHandoffs/에서 뽑는지도 모호해집니다. 둘의 관계(대체인지 보완인지, 하나가 다른 하나에서 파생되는지)를 P1에서 먼저 확정해야 합니다. 개인적으로는 Process를 단일 소스로 쓰고 capture-session이 그것을 참조/파생하는 쪽이 이중 작성 부담을 없앱니다.

3. CandidateWriter 변경 규모를 과소평가 — dedup이 handoff를 조용히 삼킬 위험

계획은 "_CANDIDATE_DIRS와 kind normalization에 session_handoff 추가"(§P2)면 된다고 하는데, 실제 candidate_writer.py를 보면 그것만으로는 안 됩니다:

_unique_rel_path(candidate_writer.py:142)는 kind별 평면 폴더만 지원 — SessionHandoffs/<Project>/ 하위 경로 라우팅은 구조 변경이 필요합니다.
가장 위험한 것: find_duplicate(candidate_writer.py:55)가 14일 내 제목 유사도 0.85로 dedup하고, 중복이면 쓰지 않고 기존 경로를 반환합니다. "Plan — vault-mcp 작업" 같은 제목이 세션마다 반복되면 새 handoff가 조용히 유실됩니다. 시계열 데이터인 session_handoff는 dedup=False 또는 날짜 포함 제목 규칙이 필수인데 계획에 언급이 없습니다.
CandidateSpec에 handoff_type, evidence, confidence 같은 임의 frontmatter 필드를 넣을 자리가 없어 스키마 확장이 필요합니다.
list-candidates → promote 검토 큐에 promote 대상이 아닌 handoff가 매 세션 2개씩 쌓이므로, list-candidates에서 session_handoff 필터링도 P2 완료 기준에 넣어야 합니다.
4. 라이프사이클 준수를 "지침"에만 의존 — 강제 수단이 있는데 안 씀

원칙 9는 "세션 시작/종료는 프로토콜"이라 했지만, 실행 수단은 P3의 "agent instruction 문서에 지침 추가"뿐입니다. 지침만으로는 에이전트가 write_work_plan·write_session_process 호출을 빼먹는 게 현실적으로 가장 흔한 실패 모드가 될 겁니다. Claude Code에는 SessionStart hook(브리핑 자동 주입), PreCompact/Stop hook(Process 작성 강제/리마인드) 이 있어서 이 프로토콜을 기계적으로 보장할 수 있는데 계획에 등장하지 않습니다. P3에 "Claude Code는 hook 기반 강제를 레퍼런스 구현으로 한다"를 추가하는 걸 권합니다. 성공 기준(§6)도 전부 "호출된다"인데 호출 여부를 어떻게 확인할지 측정 방법이 없습니다.

5. 도구 목록이 섹션마다 다름

§2 역할 분리 표는 10개(list_open_loops, suggest_next_actions 포함), P1은 7개, P2/P3는 9개(get_briefing, build_context 추가, list_open_loops 없음)입니다. P1의 완료 기준이 "tool 목록 확정"이므로 문서 안에 정본 목록 하나를 두고 나머지는 참조해야 합니다. 겸사겸사 get_briefing vs get_project_briefing, build_context vs search_vault의 역할 중복도 정리 대상입니다 — 원칙 7("표면을 늘리지 않는다")과의 긴장이 있습니다.

6. 프로젝트 매칭 메커니즘이 미정의

get_project_briefing(project_or_repo)가 repo 이름으로 프로젝트를 "추론"한다는데, repo 폴더명과 30_Projects/<Project> 이름의 매핑 규칙이 없습니다. 잘못 매칭되면 다른 프로젝트의 컨텍스트가 조용히 주입되는데, 이건 컨텍스트가 없는 것보다 나쁩니다. 명시적 매핑(예: repo의 .claude/ 설정 또는 Vault 쪽 매핑 파일)과 "매칭 실패 시 후보 목록 반환" 동작을 스펙에 넣어야 합니다.

7. SessionHandoffs 무한 증가 — 보존 정책이 P-item에 없음

세션마다 Plan+Process 2개 파일이 쌓이고 60_Candidates/는 검색 범위에 포함되므로, 한 달이면 검색 노이즈가 실질적으로 늘어납니다. §3f가 "digest/cleanup 정책으로 관리"라고 한 줄 언급하지만 실행 항목이 없습니다. 이전에 합의된 worklog 보존 정책(distilled 마킹 + 30일 cleanup)도 아직 미구현 상태라, cleanup을 SessionHandoffs까지 포함해 P-item으로 승격하거나, SessionHandoffs를 search_vault에서는 빼고 briefing만 소비하게 하는 결정이 필요합니다.

8. 멀티에이전트 동시 쓰기 문제가 사라짐

포지셔닝이 "여러 에이전트가 함께 쓰는 버스"인데, 구 문서의 open question에 있던 vault git sync/동시 쓰기 충돌 항목이 이 계획에서는 빠졌습니다. 단일 사용자면 당장 위험은 낮지만, 포지셔닝이 그 시나리오를 전면에 내세우는 만큼 최소한 open question으로는 남겨야 합니다.

검토할 만한 설계 대안 하나
세션당 Plan과 Process를 별도 파일 2개로 남기는 대신, 세션 노트 1개(시작 시 Plan 섹션 작성, 종료 시 Process 섹션 추가)로 합치는 옵션이 있습니다. 파일 수가 절반이 되고, 다음 에이전트가 "계획 대비 실제"를 한 파일에서 읽을 수 있으며, briefing에서 Plan/Process를 짝지을 필요가 없어집니다. 대가는 CandidateWriter가 write-once라서 update 시맨틱이 필요해진다는 점입니다. 어느 쪽이든 P1에서 명시적으로 결정하고 넘어가는 게 좋습니다.

우선순위 조정 제안
P0: "충돌 수정" → "완료 확인 + 깨진 링크 정리 + old/ 이동 재검토"로 재정의
P1: 도구 정본 목록 확정에 더해 ① capture-session vs Process 소유권, ② Plan/Process 파일 분리 vs 단일 노트, ③ 프로젝트 매핑 방식 — 이 세 가지 결정을 완료 기준에 추가 (셋 다 사용자 판단이 필요한 항목)
P2: 완료 기준에 session_handoff dedup 비활성화, list-candidates 필터링, CandidateSpec 스키마 확장 추가
P3: hook 기반 강제(SessionStart/PreCompact)를 Claude Code 레퍼런스 구현으로 추가
P4: 독립적이고 저렴하므로 순서는 유지하되, 2번 소유권 결정에 종속됨을 명시
전체적으로 §8의 한 줄 판단("Agent Session Lifecycle + vault_tools.py + MCP + Learning Recovery")은 옳은 다음 수라고 봅니다. 위 항목들은 방향 수정이 아니라 실행 중 좌초를 막는 보강입니다. 원하시면 이 검토 내용을 반영해 계획 문서를 직접 수정해 드릴 수 있습니다.