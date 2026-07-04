# work-agent — Feature Reference

작업 흔적을 자동으로 수집하고, 후보로 정제하고, 검토 후 공식 지식으로 승격한다.

```
Git commit → Vault 저장 → LLM 증류 → 블로그 · 이력서 · 포트폴리오
```

---

## 파이프라인 개요

```
[ 01 Capture ] ──→ [ 02 Distill ] ──→ [ 03 Curate ] ──→ [ 04 Generate ] ──→ [ 05 Deliver ]
  00_Inbox            60_Candidates      검토 → 승격        50_Outputs          Telegram · Blog
  10_Worklog
```

---

## Vault 폴더 구조

| 폴더 | 역할 | 쓰기 규칙 |
|------|------|-----------|
| `00_Inbox/` | raw 캡처 (메모, URL, 음성) | CLI/봇 자동 |
| `10_Worklog/` | 커밋·세션·일지·요약 | CLI/봇 자동 |
| `20_Knowledge/` | 공식 지식 노트 | promote-candidate 경유 |
| `30_Projects/` | 프로젝트 컨텍스트 | 직접 수정 금지 |
| `40_AgentMemory/` | AI 공유 메모리·OpenLoops | apply-memory-patch 경유 |
| `50_Outputs/` | 블로그·이력서·포트폴리오 | Generate 커맨드 |
| `60_Candidates/` | AI 생성 후보 (검토 대기) | AI 생성, 사람이 승격 |

---

## 01 — Capture

작업 흔적을 raw 상태로 Vault에 빠르게 받아놓는다. 가공 없이 저장이 우선.

| 커맨드 | 설명 | LLM |
|--------|------|-----|
| `capture <text> [-p project]` | 즉시 메모 저장 → `00_Inbox/Captures/` | — |
| `capture-commit [-r repo] [--ref]` | Git 커밋을 구조화 노트로 변환 → `10_Worklog/GitSummaries/` | opt |
| `capture-session [-p project] [--from-repo]` | 현재 작업 세션 요약 저장 → `10_Worklog/Daily/` | opt |
| `daily-log [-p project]` | 오늘 일지 파일 생성 → `10_Worklog/Daily/` | opt |

**`--from-agent` 플래그**: capture-commit은 커밋 의도·결정을 LLM으로 요약. daily-log는 오늘 캡처·커밋·OpenLoops를 읽어 내용 미리 채움.

**자동화**: `install-hooks <repo>`로 git post-commit hook 설치 시 매 커밋마다 `capture-commit` 자동 실행.

---

## 02 — Distill

raw 기록을 LLM이 읽고 후보 노트를 생성한다. 모두 `60_Candidates/`에 쌓이며, 사람이 검토하기 전까지 공식 영역에 반영되지 않는다.

| 커맨드 | 설명 |
|--------|------|
| `distill-today` | 오늘 raw 기록 전체 분석 → Knowledge·Decision·Blog·Memory 후보 일괄 생성 |
| `suggest-knowledge` | 지식 노드 후보 → `60_Candidates/Knowledge/` |
| `suggest-blog-topics` | 블로그 아이디어 후보 → `60_Candidates/BlogIdeas/` |
| `suggest-memory-patch` | AgentMemory 패치 후보 → `60_Candidates/MemoryPatches/` |
| `suggest-career-bullets` | 이력서·포트폴리오 bullet 후보 → `60_Candidates/CareerBullets/` |
| `update-open-loops` | 미해결 이슈 분석 → OpenLoops 패치 후보 → `60_Candidates/MemoryPatches/` |

모든 커맨드에 LLM 필수.

---

## 03 — Curate

`60_Candidates/` 후보를 검토하고 공식 Vault 영역으로 승격한다. AI 출력의 gate 역할.

| 커맨드 | 설명 |
|--------|------|
| `list-candidates` | 후보 목록 전체 조회. 14일 이상 오래된 항목은 stale 표시 |
| `preview-candidate <path>` | 선택한 후보 내용 미리보기 |
| `promote-candidate <path>` | 후보를 종류에 따라 공식 영역으로 이동 |
| `promote-all [--kind]` | 타입별 일괄 승격. `--kind`: knowledge · decision · blog_idea |
| `apply-memory-patch [path] [-i]` | MemoryPatch 후보를 `40_AgentMemory/` 파일에 append |

**승격 규칙**:
- Knowledge → `20_Knowledge/`
- Decision → `30_Projects/*/Decisions/`
- BlogIdea → `50_Outputs/Blog/Ideas/`
- MemoryPatch → `40_AgentMemory/`

---

## 04 — Generate

Vault 전체를 context로 삼아 LLM이 결과물을 생성한다.

| 커맨드 | 설명 | 출력 위치 |
|--------|------|-----------|
| `worklog` | 최근 raw 기록 → 작업 회고 요약 | `10_Worklog/Summaries/` |
| `todo` | 최근 raw 기록 분석 → 다음 할 일 제안 | `50_Outputs/Todo/` |
| `write-blog <topic> [-p project]` | ContextPack 조합 → 블로그 초안 | `50_Outputs/Blog/Drafts/` |
| `revise-blog <path>` | 기존 초안 문장·구조 다듬기, status → review | — |
| `portfolio` | 전체 프로젝트 + AgentMemory → 포트폴리오 소개 | `50_Outputs/Portfolio/` |
| `resume` | CareerContext + 전체 프로젝트 → 이력서·자소서 초안 | `50_Outputs/Resume/` |
| `summarize-project <name>` | 프로젝트 요약 (800자) | `50_Outputs/Portfolio/` |
| `portfolio-draft <name>` | 단일 프로젝트 포트폴리오 서술 | `50_Outputs/Portfolio/` |
| `interview-questions <name>` | 프로젝트 기반 면접 Q&A 생성 | `50_Outputs/Interview/` |

모든 커맨드에 LLM 필수.

> **참고**: `todo`는 현재 "분석 후 제안"만 가능. 직접 할 일 추가 기능 없음. 임시 방편: `capture "해야할 일: ..."` 또는 `40_AgentMemory/05_OpenLoops.md` 직접 편집.

---

## 05 — Deliver

결과물을 외부로 내보내거나 야간 자동화 파이프라인을 설정한다.

| 커맨드 | 설명 | LLM |
|--------|------|-----|
| `export-tistory [target]` | 초안 → Tistory 붙여넣기용 HTML / Markdown 변환 | — |
| `publish-ready <path>` | 초안 status → review (발행 준비 완료 표시) | — |
| `publish-done <path> [--url]` | status → published + Tistory URL 기록 | — |
| `nightly-distill` | distill-today + career-bullets + 일간 digest + Telegram 자동 발송 | ✓ |
| `weekly-distill` | 7일치 distill + career-bullets + 주간 digest + Telegram 발송 | ✓ |
| `push-digest [--daily\|--weekly\|--worklog]` | 후보 요약을 Telegram으로 수동 전송 | — |
| `print-schedule [--windows\|--cron]` | OS 스케줄러 등록 명령 출력 (Windows / cron) | — |

---

## Utilities

| 커맨드 | 설명 | LLM |
|--------|------|-----|
| `search <query> [-n N]` | Vault 전체 키워드 검색, 점수순 정렬 | — |
| `related <path> [-n N]` | 태그·wikilink 기반 연관 노트 탐색 | — |
| `build-context <topic>` | AgentMemory + Project + 관련 노트 → ContextPack 조합 | — |
| `ask <text> [-y]` | 자연어 → 명령 매핑 후 실행. `-y`: 확인 없이 바로 실행 | ✓ |
| `serve-bot` | Telegram 봇 long-polling 시작 (명령·자연어·미디어 캡처) | — |
| `init-vault` | Vault 초기 폴더 구조 및 index 파일 생성 | — |
| `install-hooks <repo> [-p name]` | target repo에 git post-commit hook 설치 | — |
| `index-vault` | Vault 전체 index.md 재생성 | — |

---

## Telegram Bot Commands

URL을 그냥 보내면 자동으로 URL 캡처 + LLM 요약 실행됨. 음성·이미지도 자동 처리 (STT / caption 설정 시).

| 커맨드 | 설명 | LLM |
|--------|------|-----|
| `/capture <메모>` | 빠른 메모 저장 | — |
| `/distill` | 오늘 기록 → 후보 생성 | ✓ |
| `/candidates` | 후보 목록 (최대 10건) | — |
| `/promote <path>` | 후보 승격 | — |
| `/search <검색어>` | Vault 검색 (5건) | — |
| `/context <topic>` | ContextPack 미리보기 | — |
| `/write <주제>` | 블로그 초안 생성 | ✓ |
| `/revise [path]` | 초안 다듬기 | ✓ |
| `/preview [path]` | 초안 미리보기 | — |
| `/export [path]` | Tistory HTML 변환 | — |
| `/publish <url>` | 발행 완료 기록 | — |
| `/worklog` | 작업 회고 생성 | ✓ |
| `/todo` | 할 일 제안 | ✓ |
| `/portfolio` | 포트폴리오 초안 | ✓ |
| `/resume` | 이력서 초안 | ✓ |
| `/list` | 블로그 초안 목록 | — |
