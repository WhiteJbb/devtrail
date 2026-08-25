# Activity Collector 설계 (Phase 4)

> 작성: 2026-08-25. `docs/devtrail-improvement-roadmap.md` Phase 4의 상세 설계.
> Phase 1~3 머지·e2e 검증 완료 후 착수. 사용자 결정 3건 반영(§7).

## 1. 목표 / 비목표

**목표**: 커밋 없는 작업(SSH·Docker·systemd 조작, 홈랩 운영)을 셸에서 자동
수집해 세션 노트로 만든다. 만들어진 노트는 **기존 파이프라인(distill →
context question → thread → blog)을 그대로 탄다** — 이 설계의 신규 범위는
"셸 이벤트 → 세션 노트"까지다.

**비목표 (1차)**:
- 홈랩 원격 노드(rpi4 등) 수집 — 2차 (§8). 1차는 로컬 PowerShell + WSL/git-bash.
- 브라우저·에디터·앱 사용 추적. 셸만.
- command 단위 Markdown 노트 생성 — 절대 안 함. 의미 있는 세션 단위만 Vault로.

## 2. 아키텍처

```
PowerShell prompt 훅 ─┐
bash PROMPT_COMMAND ──┤→ ~/.devtrail/activity/YYYY-MM-DD.jsonl  (append-only)
                      │         ↓
                      │   Sessionizer (nightly 앞단, fail-open)
                      │         ↓  간격≤30분 + 같은 host/shell로 묶고 잡음 필터
                      │         ↓  실질 명령 5개 미만이면 버림
                      │   LLM light 1회 — 제목·요약 생성
                      │         ↓
                      └─  {VAULT}/10_Worklog/Sessions/…-activity-session-….md
                                ↓
                          기존 distill / context question / thread 파이프라인
```

### 저장소: SQLite가 아니라 JSONL (로드맵 초안에서 변경)

로드맵은 SQLite를 그렸지만 1차는 **일자별 JSONL**로 간다:
- 훅은 셸 내장 명령(Add-Content / `>>`)으로 한 줄 append만 한다 — 프롬프트마다
  Python 기동·DB 락이 없어 체감 지연 0에 가깝고 의존성도 없다.
- 읽는 쪽(sessionizer)은 하루 1회 배치라 인덱스가 필요 없다.
- 보존·정리도 파일 삭제로 끝난다.
- 쿼리가 필요해지는 시점(멀티노드 통합, 통계)에 SQLite 도입을 재검토한다.

## 3. 이벤트 스키마 (JSONL 한 줄)

```json
{"ts": "2026-08-25T16:03:12", "host": "DESKTOP-XXX", "shell": "pwsh",
 "cwd": "C:/Users/admin/Desktop/devtrail", "cmd": "docker compose up -d", "exit": 0}
```

- `ts` 초 단위면 충분. `shell`: `pwsh` | `bash`.
- `exit`: PowerShell은 `$LASTEXITCODE`/`$?` 조합, bash는 `$?`.
- git HEAD·소요 시간은 1차 제외 — 훅을 무겁게 만들 가치가 아직 없다.
  (sessionizer가 cwd로 repo를 알 수 있으니 필요하면 배치 쪽에서 보강)

### 마스킹 — 훅에서, 디스크에 닿기 전에

명령 **전문을 저장**하되(사용자 결정), 비밀값 패턴은 훅 안에서 치환 후 기록한다
— 원문이 디스크에 아예 남지 않게:

```
(ghp_|github_pat_|sk-|AIza|xoxb-|Bearer\s+)\S+            → ***
(?i)(token|secret|password|passwd|api_?key)\s*[=:]\s*\S+  → $1=***
```

JSONL은 로컬(`~/.devtrail/`) 전용이고 Vault에는 세션 요약만 올라간다.
세션 노트에 대표 명령을 인용할 때도 마스킹된 값을 쓴다.

## 4. 셸 훅

### PowerShell (`$PROFILE`)

`prompt` 함수를 래핑해 직전 명령(`Get-History -Count 1`)의 시각·명령·exit를
JSONL로 append. devtrail 마커 블록(`# >>> devtrail activity >>>` … `# <<<`)으로
감싸 idempotent 설치/제거.

### bash — WSL + git-bash (`~/.bashrc`)

`PROMPT_COMMAND`에 함수 추가 — `history 1` 파싱 + `$?`. 같은 마커 블록 방식.
히스토리 파일 파싱(폴링)은 타임스탬프·cwd·exit가 없어서 탈락 — 훅이 정답.

### 설치 CLI

```
devtrail activity install [--shell pwsh|bash|all]   # 프로필에 마커 블록 append
devtrail activity uninstall                          # 마커 블록 제거
devtrail activity status                             # 오늘 이벤트 수·마지막 이벤트·훅 설치 여부
devtrail activity sessionize [--date YYYY-MM-DD]     # 수동 실행 (디버그용)
```

훅은 수집만, 판단 없음("멍청한 훅"). 필터·묶기 로직은 전부 sessionizer에 —
훅을 고칠 일이 없어야 여러 셸·나중의 원격 노드에 안전하게 뿌릴 수 있다.

## 5. Sessionizer (`app/services/activity_sessionizer.py`)

nightly daily 실행 시 어제~오늘 JSONL을 읽어(fail-open, 기존
`_generate_context_questions` 패턴):

1. **묶기 (결정적)**: 같은 `host`+`shell`에서 이벤트 간격 ≤ 30분이면 같은 세션.
2. **잡음 필터**: `ls/cd/pwd/clear/exit/history` 등 단독 탐색 명령은 실질 명령
   수에서 제외 (기록은 유지 — 흐름 맥락으로는 씀).
3. **의미 판정**: 실질 명령 5개 미만인 묶음은 노트를 만들지 않는다.
4. **project 추정**: cwd 최빈값 → `.claude/vault.json` 매핑이 있으면 그 프로젝트,
   없으면 폴더명. ssh 명령이 지배적이면 대상 호스트명을 제목에 반영.
5. **노트 생성**: LLM light 1회 — 입력은 카테고리 통계(docker N회, git N회…)
   + 대표 명령 최대 20개(시간순). 출력은 제목·요약(goal/what/problems 추정)·
   불확실 표시. LLM 실패 시 명령 목록만 담은 노트로 폴백(제목은 "activity —
   host — 시간대").

노트 frontmatter:

```yaml
type: session
source: activity
project: <추정>
created_at: <세션 시작>
session_id: activity-<date>-<host>-<n>
needs_distill: true
```

파일명에 `session`을 포함해(`…-activity-session-….md`) 기존 세션 필터에 걸리게
한다. 이후 distill·context question·thread는 손댈 것 없이 이 노트를 소비한다.

### MCP 세션과의 겹침

Claude Code 작업 중의 셸 이벤트는 MCP `write_session_process` 노트와 시간대가
겹칠 수 있다. **1차는 그대로 둘 다 생성한다** — 겹침 판정·병합은 실사용에서
겹침이 실제로 거슬리는지 본 뒤 결정한다. (예상 개선: 같은 project·겹치는
시간대의 MCP 세션이 있으면 activity 노트를 만들지 않고 스킵)

## 6. 보존

`~/.devtrail/activity/*.jsonl`은 90일 지나면 삭제 — 기존
`retention.py`에 정리 항목 하나 추가. Vault로 승격된 세션 노트는 기존 세션
보존 정책을 그대로 따른다.

## 7. 확정된 사용자 결정 (2026-08-25)

| 결정 | 선택 |
|------|------|
| 명령 저장 수준 | **전문 저장 + 훅 단계 마스킹** (JSONL은 로컬 전용, Vault엔 요약만) |
| 1차 수집 범위 | **로컬 PowerShell + WSL/git-bash** |
| sessionize 시점 | **nightly 통합** (fail-open, 수동 명령은 디버그용으로 병행) |

## 8. 2차 — 홈랩 멀티 노드 (설계 방향만)

- bash 훅을 그대로 rpi4 등에 설치 (`devtrail activity install --shell bash`는
  노드에 devtrail 전체 설치 없이 훅 스크립트 단독 배포 가능하게 분리).
- 각 노드는 로컬 JSONL에만 쓰고, 중앙 PC가 Tailscale 경유로 pull(rsync/scp,
  cron) → `~/.devtrail/activity/remote/<host>/`에 모음. sessionizer는 host
  필드로 이미 노드를 구분하므로 추가 변경 최소.
- push가 아니라 pull인 이유: 노드에 Vault 경로·자격증명을 두지 않는다.

## 9. PR 분할

| PR | 내용 | 비고 |
|----|------|------|
| A | 훅 스크립트(pwsh/bash) + `activity install/uninstall/status` | LLM 무관, 셸별 수동 검증 |
| B | sessionizer + 노트 생성 + 테스트 | JSONL fixture 기반, LLM은 fake |
| C | nightly 통합(fail-open) + retention + `sessionize --date` | e2e는 testvault 재사용 |

각 PR은 `feat/activity-*` 브랜치 → dev PR squash merge. A 머지 후 훅을 실제로
며칠 켜두고 쌓인 JSONL을 B의 fixture 소재로 쓴다.

## 10. 리스크

- **PowerShell prompt 훅 지연**: Add-Content 한 줄이지만 느린 디스크에서 체감되면
  버퍼링 도입. 훅에 try/catch — 수집 실패가 셸을 깨면 안 된다 (최우선 불변식).
- **Get-History 중복**: 같은 명령이 프롬프트마다 재기록되지 않게 HistoryId 추적.
- **bash 히스토리 멀티라인 명령**: `history 1` 파싱 한계 — 1차는 첫 줄만 기록.
- **LLM 요약 품질**: 명령만으로 goal 추정은 한계 — Context Gap 질문(Phase 2)이
  이 빈칸을 채우는 구조라 과하게 추정하지 말고 "불확실"을 남기는 쪽으로 프롬프트.
