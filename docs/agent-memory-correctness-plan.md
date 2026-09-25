# 공유 에이전트 메모리 정확성 개선 계획

## 목표

후보 저장과 세션 인계가 프로젝트·세션 경계를 지키고, 최근 메모리가 briefing에서 보존되도록 수정한다. 훅 상태 및 후보 쓰기는 같은 머신의 여러 프로세스가 동시에 사용해도 서로의 상태나 파일을 덮어쓰지 않게 한다.

## 범위와 순서

1. CandidateWriter의 중복 탐색·갱신을 프로젝트 범위에 한정하고, 제목 유사도만으로 기존 본문을 교체하지 않도록 한다. exact/thread 병합 경로도 같은 경계를 확인한다.
2. 세션 Process 저장 시 다른 세션의 orphan Plan을 추정해 재귀속하지 않는다. MCP 세션 식별 및 훅 마커를 실제 hook payload가 제공하는 식별 정보와 연결할 수 있는 범위에서 세션별로 분리한다.
3. Lessons 후보의 키를 세션 단위로 만들어 서로 다른 세션의 교훈은 보존하고, 같은 세션 재기록은 멱등하게 유지한다.
4. 장문 메모리 블록 절단 방향을 수정해 최신 끝부분이 briefing에 남도록 하되 기존 ContextPack 예산은 유지한다.
5. 후보 파일 read-modify-write 및 파일명 할당을 같은 머신의 프로세스 간 stdlib 파일 잠금과 원자적 교체로 보호한다. 서로 다른 머신 간 분산 동기화는 범위에서 제외한다.
6. SessionHandoff 최신순 정렬에 updated_at fallback을 적용하고, Suggested Next Actions의 과거 Process는 기록 출처·시각 및 재검증 필요를 표시한다. project-scoped memory가 타 프로젝트에 섞이지 않는지 확인한다.

## 검증

각 회귀 케이스를 테스트로 추가하고, 영향받는 서비스·MCP·훅·briefing 테스트를 `.venv/Scripts/python.exe`로 실행한다. 실제 Vault는 사용하거나 변경하지 않는다.

## 제약

공식 Vault 메모리의 직접 수정, 자동 승격, 외부 의존성 추가, 커밋 및 push는 하지 않는다.

## 결과 (2026-09-24)

- MCP 마커를 서버 프로세스별 파일로 저장하고, 훅은 최근 12시간 안에 갱신된 live 마커가 정확히 하나일 때만 사용한다. marker가 없거나 여러 개이거나 PID를 확인할 수 없으면 enforcement를 건너뛴다.
- Claude hook `session_id`와 MCP 내부 ID를 연결하는 설정 경로가 없어, 같은 repo에서 여러 Claude/MCP 세션이 동시에 live이면 plan/stop 훅은 fail-open 된다. SessionStart는 다른 프로세스의 marker를 삭제하지 않는다. Windows PowerShell 진입점은 공통 Python 훅으로 위임한다.
- 중간 전체 실행은 605 passed, 1 failed였다. 유일한 실패는 기존 유사 제목 dedup 기대였고, 별도 후보 보존 의도에 맞춰 기대를 수정했다.
- 요청된 추가 회귀를 반영한 전체 실행은 613 passed (30.48s)였다. 이후 같은 session_id를 쓰는 서로 다른 프로젝트의 worklog 격리 결함을 수정하고 회귀를 추가했으며, 최종 `tests/test_vault_tools.py` 실행은 85 passed였다.
- 해당 최종 수정 뒤 `git diff --check`도 통과했다. 실제 Vault는 읽거나 수정하지 않았고 MCP 세션 기록, 커밋, push는 하지 않았다.
- 실제 `run-hook.sh`의 plan-check와 stop-process-check, Windows stop wrapper 호출은 exit 0으로 마쳤다. 실제 Vault는 읽거나 수정하지 않았고 MCP 세션 기록도 추가하지 않았다.
