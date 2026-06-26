# CLAUDE.md

이 프로젝트(work-agent)에서 Claude Code가 따라야 하는 규칙.

## capture-session rule

`work-agent capture-session --from-agent` 명령을 실행할 때:

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 아래 항목을 포함하는 세션 요약 Markdown을 **충분히 자세하게** 작성한다.

### 작성 기준

**오늘 작업한 내용**
- 무엇을 왜 했는지 서술한다. "X를 구현했다"가 아니라 "X가 없어서 Y 문제가 생겼고, Z 방식으로 해결했다" 수준으로.
- 작업 흐름(어떤 순서로 진행됐는지)도 포함한다.

**변경/추가/삭제된 파일 또는 모듈**
- 파일 경로와 함께 변경 이유를 한 줄씩 기록한다.
- 예: `app/config.py` — Notion/workspace dead 필드 제거 (NotionSource가 존재하지 않아 참조 없음)

**해결한 문제나 버그**
- 증상, 원인, 해결 방법을 모두 기록한다. "버그 수정"이 아니라 "어떤 상황에서 왜 발생했고 어떻게 고쳤는지".

**설계 결정과 그 이유**
- 여러 선택지 중 왜 이 방향을 택했는지 근거를 남긴다.
- 나중에 다시 봤을 때 "왜 이렇게 했지?"가 나오지 않을 수준으로.

**남은 문제 및 다음 할 일**
- 미완성 항목, 알려진 이슈, 다음 세션에서 이어갈 것.

**블로그/포트폴리오 소재**
- 이번 작업 중 기술적으로 흥미롭거나 공유 가치가 있는 것. 제목 수준으로라도 남긴다.

3. 요약을 임시 파일로 저장한 뒤 `--summary-file` 옵션으로 전달한다.
4. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 권장 패턴
work-agent capture-session --project <프로젝트명> --from-repo --from-agent --summary-file ./session-summary.md
```

## Vault 구조 (작업 전 참조)

Obsidian Vault는 모든 Agent가 공유하는 메모리 버스다. 작업 시작 전 아래 파일을 먼저 확인한다:
- `{VAULT}/40_AgentMemory/Core/` — 프로젝트별 핵심 컨텍스트 (가장 먼저 읽을 것)
- `{VAULT}/40_AgentMemory/05_OpenLoops.md` — 미해결 이슈 목록

### 폴더별 역할과 AI 권한

| 폴더 | 역할 | AI 권한 |
|------|------|---------|
| `00_Inbox/URLs/` | URL 캡처 노트 | 읽기 전용 |
| `00_Inbox/Memos/` | 텍스트·음성·이미지 캡처 노트 | 읽기 전용 |
| `00_Inbox/Raw/` | 첨부 바이너리 파일 | 읽기 전용 |
| `10_Worklog/Sessions/` | capture-session 출력 (AI 세션 요약) | 읽기 전용 |
| `10_Worklog/Daily/` | daily-log 파일 (사람이 직접 채우는 일지) | 읽기 전용 |
| `10_Worklog/GitSummaries/` | 커밋별 git 요약 | 읽기 전용 |
| `20_Knowledge/` | 승격된 공식 지식 노트 | **직접 수정 금지** — `promote-candidate` 경유 |
| `30_Projects/` | 프로젝트별 컨텍스트 | **직접 수정 금지** |
| `40_AgentMemory/` | AI 공용 메모리 (Core/, OpenLoops 등) | `Core/` 직접 수정 금지 — `apply-memory-patch` 경유 |
| `50_Outputs/Digest/` | daily digest (nightly 자동 생성) | 읽기 전용 |
| `50_Outputs/WeeklyReview/` | weekly 회고 (weekly 자동 생성) | 읽기 전용 |
| `50_Outputs/Blog/` | 블로그 초안·발행본 | 읽기 전용 |
| `60_Candidates/Knowledge/` | 지식 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/Decisions/` | 결정 기록 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/MemoryPatches/` | OpenLoops 패치 후보 | AI가 생성, `apply-memory-patch`로 반영 |
| `60_Candidates/BlogIdeas/` | 블로그 아이디어 후보 | AI가 생성, 사람이 검토 후 promote |
| `60_Candidates/CareerBullets/` | 이력서/포트폴리오 후보 | AI가 생성, 사람이 검토 후 promote |

### 후보 흐름
모든 AI 출력(지식 정리, 결정, 블로그 아이디어, 메모리 패치)은 반드시 `60_Candidates/`를 거친다.
사람이 `list-candidates` → `promote-candidate` / `apply-memory-patch`로 검토 후 공식 영역에 반영한다.

## 브랜치 & PR 규칙

- 새 Agent / CLI 커맨드 / 계층 구조 변경은 반드시 `feat/` 또는 `refactor/` 브랜치에서 작업한다.
- 문서(md 파일)만 수정할 때는 main에서 직접 커밋해도 된다.
- GitHub API는 curl + `GITHUB_TOKEN`으로 호출한다 (`gh` CLI 사용 안 함).
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를 넣지 않는다.
- squash merge 기본 사용.
