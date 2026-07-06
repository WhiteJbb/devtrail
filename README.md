# devtrail — Personal Knowledge OS

Obsidian Vault를 단일 지식 저장소로 삼아 작업 흔적을 자동으로 캡처·정제하고, 블로그·포트폴리오·이력서 초안을 만드는 개인 생산성 CLI/봇.

```
[ Capture ] ──→ [ Distill ] ──→ [ Curate ] ──→ [ Generate ] ──→ [ Deliver ]
  00_Inbox        60_Candidates    검토 → 승격     50_Outputs       Telegram · Blog
  10_Worklog
```

LLM은 창작자가 아닌 **작업 기록 정리자**다. source에 없는 사실·수치를 만들지 않는다.

→ 전체 기능 레퍼런스(archived, 최신 명령 목록은 아래 참고): [docs/old/feature-reference.md](docs/old/feature-reference.md)  
→ 구현 현황 보고(archived): [docs/old/implementation-status.md](docs/old/implementation-status.md)  
→ MCP(Agent Session Lifecycle) 구현 요약: [docs/vault-mcp-implementation-summary.md](docs/vault-mcp-implementation-summary.md)

---

## 설치

Python 3.10 이상 필요. PowerShell에서 실행:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

5단계 자동 처리: Python 버전 감지 → `.venv` 생성 → 패키지 설치 → PATH 등록 → `.env` 초기화.

다른 프로젝트 레포에 git hook을 설치하려면:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Repo C:\path\to\repo -Project myproject
```

> **참고**: post-commit hook은 현재 비활성화 상태입니다(`exit 0` 처리). 커밋마다 LLM 호출로 커밋 속도가 저하되고 diff가 800자로 잘려 실질적 가치가 낮았기 때문입니다. `capture-commit` 명령 자체는 보존돼 있어 수동 실행은 가능합니다. 재활성화하려면 `scripts/hooks/post-commit`에서 `exit 0` 줄을 제거하세요.

---

## 대시보드 실행

```bash
launch.bat          # 새 터미널 창으로 대시보드 열기
python start.py     # 현재 터미널에서 직접 실행
```

환경 점검 후 Textual TUI 대시보드로 진입합니다.

---

## AI 설정

작업 성격에 따라 LLM을 자동 선택하고, 실패 시 다음 provider로 폴백합니다.

### task_type별 라우팅

| task_type | 용도 | 기본 chain |
|-----------|------|-----------|
| **light** | 분류·태깅·짧은 요약 (`distill-today`, `suggest-*`, `capture`) | Gemini Flash-Lite → GPT-4.1-mini → Ollama |
| **writer** | 블로그·이력서·포트폴리오 초안 (`write-blog`, `resume`, `worklog`) | Gemini Flash → GPT-4.1-mini → Kimi |
| **long_writer** | 긴 ContextPack 기반 글쓰기 (`weekly-distill`, `summarize-project`) | Kimi → Gemini Flash → GPT-4.1-mini |
| **polish** | 최종 문장 다듬기 (`revise-blog`) | GPT-4.1-mini → Gemini Flash |
| **local** | 인터넷 장애 시 최소 동작 | Ollama |

API 키가 없는 provider는 chain에서 자동 제외됩니다. Gemini만 설정해도 동작합니다.

### Gemini (추천)

[Google AI Studio](https://aistudio.google.com/apikey)에서 API 키 발급 (무료 티어 있음).

```env
GEMINI_API_KEY=AIza...
GEMINI_FLASH_MODEL=gemini-2.5-flash
GEMINI_LITE_MODEL=gemini-2.5-flash-lite
```

### OpenAI / GPT-4.1-mini

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

### Kimi (Moonshot AI) — long_writer 특화

```env
KIMI_API_KEY=...
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2
```

### Ollama (로컬, 인터넷 불필요)

```bash
ollama pull qwen3:8b
```

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

### vLLM (자체 GPU 서버)

```env
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=dummy
OPENAI_MODEL=Qwen/Qwen2.5-14B-Instruct
```

---

## Vault 구조

`init-vault`가 생성하는 기본 구조.

```
<vault>/
├─ 00_Inbox/
│  ├─ URLs/          # URL 캡처 (Telegram URL 전송, capture-url)
│  ├─ Memos/         # 텍스트·음성·이미지 캡처
│  └─ Raw/           # 첨부 바이너리 파일
├─ 10_Worklog/
│  ├─ Sessions/      # capture-session 출력 (AI 세션 요약)
│  ├─ Daily/         # daily-log (사람이 채우는 일지)
│  └─ Summaries/     # worklog 출력
├─ 20_Knowledge/     # 확정된 지식 ← promote-candidate 목적지
├─ 30_Projects/      # 프로젝트별 Context.md
├─ 40_AgentMemory/   # AI 공용 메모리 (Core/, OpenLoops 등)
├─ 50_Outputs/
│  ├─ Digest/        # daily digest (nightly 자동 생성)
│  ├─ WeeklyReview/  # 주간 회고 (weekly 자동 생성)
│  ├─ Blog/          # 블로그 초안·발행본
│  ├─ Portfolio/
│  ├─ Resume/
│  └─ Todo/
├─ 60_Candidates/    # distill 후보 — 사람 검토 전 임시 영역
│  ├─ Knowledge/
│  ├─ Decisions/
│  ├─ MemoryPatches/
│  ├─ BlogIdeas/
│  └─ CareerBullets/
├─ index.md
└─ log.md
```

**AI 쓰기 가능**: `00_Inbox/`, `10_Worklog/`, `50_Outputs/`, `60_Candidates/`  
**직접 수정 금지** (candidate/patch 경유): `20_Knowledge/`, `40_AgentMemory/Core/`, `30_Projects/*/Context.md`

Obsidian 템플릿은 [docs/vault-templates/](docs/vault-templates/)을 Vault의 `90_Templates/`에 복사해서 사용 (외부 AI 프롬프트 가이드 포함).

---

## 명령 목록

### Vault 초기화

```bash
devtrail init-vault                             # 볼트 폴더 구조 생성
devtrail install-hooks <repo> [-p project]      # git post-commit hook 설치
devtrail index-vault                            # index.md 갱신
```

### Capture — raw 기록 저장

```bash
devtrail capture "메모"                                         # → 00_Inbox/Memos/
devtrail capture-commit --repo <path> [--from-agent]           # → 10_Worklog/GitSummaries/ (수동 실행, hook은 기본 비활성)
devtrail capture-session [-p project] [--from-repo]            # → 10_Worklog/Sessions/
devtrail capture-session [-p project] --from-agent             # AI 세션 요약 포함
devtrail capture-session [-p project] --summary-file <md>      # AI 요약 파일 삽입
devtrail daily-log [-p project]                                # 오늘 데일리 로그 → 10_Worklog/Daily/
devtrail daily-log [-p project] --from-agent                   # LLM이 오늘 컨텍스트 미리 채움
```

`--from-agent` 플래그: daily-log는 오늘 캡처·OpenLoops를 읽어 Done/Next 등 미리 채움.

> **참고**: post-commit hook은 기본적으로 비활성화(`exit 0`) 상태로 설치됩니다. 커밋마다 LLM 호출로 커밋 속도가 저하되고 diff가 800자로 잘려 실질적 가치가 낮았기 때문입니다. `capture-commit` 명령 자체는 남아 있어 수동 실행은 가능하며, `nightly-distill`이 세션 노트 기반으로 하루치를 종합 처리하는 것으로 대체됐습니다.

### Distill — 정제 후보 생성 (LLM 필요)

```bash
devtrail distill-today               # 오늘 Inbox → 60_Candidates/ 후보 일괄 생성
devtrail suggest-knowledge           # Knowledge 후보 제안
devtrail suggest-blog-topics         # BlogIdea 후보 제안
devtrail suggest-memory-patch        # AgentMemory 패치 제안
devtrail suggest-career-bullets      # 이력서·포폴 bullet 후보
devtrail update-open-loops           # OpenLoops 패치 후보
devtrail build-context "주제"        # ContextPack 구성
```

### Candidates 관리

```bash
devtrail list-candidates                      # 60_Candidates/ 목록 (stale 표시 포함)
devtrail preview-candidate <path>             # 후보 미리보기
devtrail promote-candidate <path>             # 공식 영역으로 승격
devtrail promote-all [--kind knowledge|decision|blog_idea]   # 타입별 일괄 승격
devtrail apply-memory-patch [path] [-i]       # → 40_AgentMemory/ 반영
```

### 탐색

```bash
devtrail search "RAG"             # 키워드 볼트 검색
devtrail related <path>           # 관련 노트 탐색 (태그·wikilink 기반)
```

### Generate — 결과물 생성 (LLM 필요)

```bash
# 작업 회고 / 할 일
devtrail worklog                             # 작업 회고 → 10_Worklog/Summaries/
devtrail todo                                # 다음 할 일 분석 → 50_Outputs/Todo/

# 블로그
devtrail write-blog "주제" [-p project]      # ContextPack → 50_Outputs/Blog/Drafts/
devtrail revise-blog <path>                  # 기존 초안 다듬기
devtrail publish-ready <path>                # status → review
devtrail export-tistory [target]             # 티스토리 포맷 변환
devtrail publish-done <path> [--url <url>]   # 게시 완료 기록
devtrail list                                # 초안 목록
devtrail preview [target]                    # 초안 미리보기

# 개인 문서
devtrail portfolio                           # 포트폴리오 소개 → 50_Outputs/Portfolio/
devtrail resume                              # 이력서·자소서 초안 → 50_Outputs/Resume/
devtrail summarize-project <name>            # 프로젝트 요약 (800자)
devtrail portfolio-draft <name>              # 프로젝트별 포폴 초안
devtrail interview-questions <name>          # 예상 면접 질문
```

### Deliver — 자동화 · 전송

```bash
devtrail nightly-distill                     # 하루 종합 정제 + daily digest + Telegram 전송
devtrail weekly-distill                      # 7일치 daily digest 종합 + weekly 회고 + Telegram 전송
devtrail push-digest [--daily|--weekly|--worklog]   # 후보 요약 Telegram 수동 전송
devtrail notify morning|evening              # 아침/저녁 알림 Telegram 전송 (OS 스케줄러가 호출)
devtrail print-schedule [--windows|--cron]   # OS 스케줄러 등록 명령 출력 (최소 구성)
devtrail ask "자연어"                        # 의도 분류 후 커맨드 실행
devtrail serve-bot                           # Telegram 봇 실행
```

전체 자동화(봇 상시 실행 · 코드/Vault 자동 동기화 · nightly · weekly · 아침/저녁 알림)를 한 번에 등록하려면
아래 [야간 자동화](#야간-자동화) 섹션의 `register-schedules` 스크립트를 사용하세요.

### 유지보수 (사람 전용, MCP 미노출)

```bash
devtrail vault-cleanup [--dry-run] [--keep N] [--worklog-days N] [--handoff-days N]
# 오래된 10_Worklog/Sessions/, 60_Candidates/SessionHandoffs/ 정리 (destructive)
```

### MCP — Claude Code / Desktop 연동

```bash
devtrail mcp-serve            # Vault tool 레이어를 MCP(stdio)로 노출
devtrail project-briefing     # get_project_briefing() 결과를 stdout에 출력 (SessionStart 훅용)
```

자세한 내용은 아래 [MCP 연동](#mcp-연동-claude-code-session-lifecycle) 섹션 참고.

---

## MCP 연동 (Claude Code Session Lifecycle)

`devtrail mcp-serve`는 Vault를 **Agent Session Lifecycle 공용 메모리 버스**로 노출하는
MCP(stdio) 서버입니다. MCP가 연결돼 있으면 세션 시작/종료 기록은 아래 7개 tool이
1차 경로이고, `capture-session` CLI는 MCP 미연결 시의 fallback입니다.

등록 (Claude Code):

```bash
claude mcp add devtrail-vault -- devtrail mcp-serve
```

| Tool | 역할 |
|------|------|
| `get_project_briefing` | 세션 시작 시 프로젝트 컨텍스트 · 최근 handoff · decision · Open Loops 반환 |
| `search_vault` | read_scope 안 노트 검색 (status=stable/candidate 포함) |
| `read_note` | scope 안 노트 전문 읽기 |
| `record_note` | 결정/지식/아이디어를 `60_Candidates/`에 후보로 기록 (knowledge/decision/blog_idea/career_bullet) |
| `record_agent_improvement` | 반복 실수 · 개선할 작업 방식 · 프로젝트 주의사항을 MemoryPatch 후보로 기록 |
| `write_work_plan` | 작업 시작 전, 실제 수정 전에 Plan 기록 |
| `write_session_process` | 세션 종료/컴팩팅 전 Process 기록 → `SessionHandoffs` candidate + `10_Worklog/Sessions/` 세션 기록 동시 생성 |

세션 시작 시 `get_project_briefing`을 먼저 호출하고, 세션 종료/컴팩팅 직전에는
`write_session_process`로 기록합니다. `session_id`는 MCP 서버 프로세스 시작 시
1회 생성돼 모든 write 계열 tool에 자동 주입되므로 에이전트가 직접 들고 다닐 필요가
없습니다(컴팩팅 중 분실 방지).

---

## AI Agent 연동 (MCP 미지원 도구 — Cursor 등, 또는 fallback)

### 1단계 — CLAUDE.md / AGENTS.md 설정

프로젝트 루트에 추가:

```markdown
## Vault 경로
OBSIDIAN_VAULT_PATH: D:/personal-vault

## 작업 시작 전 필독 파일
- {VAULT}/40_AgentMemory/Core/<프로젝트명>.md — 핵심 컨텍스트
- {VAULT}/40_AgentMemory/05_OpenLoops.md    — 미해결 이슈 목록

## Vault 수정 규칙
- 20_Knowledge/, 30_Projects/, 40_AgentMemory/Core/ 는 직접 수정하지 않는다.
- 모든 제안·초안은 60_Candidates/ 에 파일로 생성하고 사람이 검토 후 promote 한다.
```

### 2단계 — 세션 시작 시 컨텍스트 로딩

```bash
devtrail build-context "XCoreChat RAG"   # → 50_Outputs/Context/ 에 파일 생성
devtrail search "RAG 검색"               # 관련 노트 확인
```

생성된 파일을 AI 세션에 추가합니다 (Claude Code: `/add 파일명`, Cursor: `@파일명`).

### 3단계 — 세션 종료 시 Vault에 저장

```
capture-session 실행해줘
```

CLAUDE.md/AGENTS.md의 규칙에 따라 요약을 작성하고 실행:

```bash
devtrail capture-session --project <name> --from-repo --from-agent --summary-file ./session-summary.md
```

### 전체 흐름

```
[세션 시작]  MCP: get_project_briefing (fallback: build-context → AI에 파일 추가) → 작업
[세션 종료]  MCP: write_session_process (fallback: capture-session --from-agent) → 10_Worklog/Sessions/ 저장
[야간]       nightly-distill → 60_Candidates/ 후보 생성
[매주 일요일] weekly-distill → 50_Outputs/WeeklyReview/ 주간 회고
[다음 날]    list-candidates → promote-candidate → 20_Knowledge/ 누적
```

---

## 야간 자동화

```
[시작 시]        devtrail-bot          → Telegram 봇 상시 실행 (SYSTEM, 로그인 없이 동작)
[10분마다]        devtrail-update       → 코드 업데이트 (git pull)
[10분마다]        devtrail-vault-sync   → Vault git 동기화
[08:00]          notify morning        → Telegram 아침 알림 (할 일 + 후보 개수)
[23:30]          nightly-distill
  ├─ DistillAgent       → 60_Candidates/ (Knowledge / Decisions / MemPatches / BlogIdeas)
  ├─ CareerBulletAgent  → 60_Candidates/CareerBullets/
  ├─ 50_Outputs/Digest/{date}-daily-digest.md 저장
  └─ Telegram 설정 시 digest 자동 전송
[21:30]          notify evening        → Telegram 저녁 알림
[일요일 18:00]     weekly-distill
  └─ WeeklyReviewAgent  → 50_Outputs/WeeklyReview/{date}-weekly-review.md + Telegram
```

전체 스케줄을 한 번에 등록하는 OS별 스크립트가 `scripts/windows/`, `scripts/mac/`에
분리되어 있습니다.

```powershell
# Windows (관리자 권한 PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\windows\register-schedules.ps1
```

```bash
# macOS (launchd)
bash scripts/mac/register-schedules.sh
```

Mac을 처음 설정한다면 터미널 기초부터 다루는 [docs/mac-automation-setup.md](docs/mac-automation-setup.md)를 참고하세요.

수동으로 스케줄러 등록 명령만 확인하고 싶다면(nightly-distill / push-digest 최소 구성):

```bash
devtrail print-schedule --windows   # Windows schtasks 등록 명령 출력
devtrail print-schedule --cron      # Linux / Mac crontab 등록 명령 출력
```

---

## Telegram 봇

```env
MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<BotFather에서 발급>
TELEGRAM_ALLOWED_CHAT_IDS=<본인 chat id>
TELEGRAM_CHAT_ID=<알림 받을 chat id>
```

```bash
devtrail serve-bot
```

### 할 일 관리

```
/task <내용>              할 일 추가  (예: /task 코드리뷰 내일까지)
/tasks                    목록 보기 + 완료·삭제 인라인 버튼  (별칭: /할일, /할_일)
/done <번호>              완료 처리
/del <번호>               삭제  (별칭: /delete, /rm)
/edit <번호> <새내용>     내용·날짜·섹션 수정
```

날짜 키워드 자동 인식: `오늘` · `내일` · `이번 주` · `월~일요일` · `2026-07-01`  
날짜 기준으로 섹션(오늘 / 이번 주 / 언제든지) 자동 배정.

`/tasks` 응답에는 태스크마다 **완료(✅)·삭제(🗑) 버튼**이 붙습니다. 버튼은 내부적으로 안정 ID(`^hex6`)를 사용해 목록이 바뀐 뒤에도 오동작하지 않습니다.

태스크는 Obsidian Vault `70_Tasks/Active.md`에 저장되며, 완료 시 `70_Tasks/Done/<날짜>.md`에 기록됩니다.

### 기록 → 지식화

```
/capture <메모>     /distill           /candidates
/search <검색어>    /context <주제>    /promote <path>
/worklog            /todo              /briefing
/sync
```

`/briefing`은 `40_AgentMemory/`를 요약해 보여줍니다. `/sync`는 Vault git 동기화를 수동 트리거합니다 (Windows 서버 전용, `scripts/windows/sync-vault.ps1` 실행).

**`/review`** — 후보를 한 건씩 인라인 버튼 카드로 검토합니다.

```
/review          검토 시작 (60_Candidates/ 전체를 큐에 담아 첫 카드 전송)
✅ 승격 / ⏭ 건너뛰기 / 🗑 삭제 / ⛔ 종료   ← 버튼 탭으로 진행
```

### 블로그

```
/write <주제>       /list              /preview [경로]
/revise [경로]      /export [경로]     /publish <URL>
```

`/preview`, `/revise`, `/export`는 인자를 생략하면 최신 초안(latest)을 대상으로 합니다.

### 개인 문서 · 기타

```
/portfolio          /resume            /restart
```

`/restart`는 봇 프로세스를 재시작합니다(코드 배포 후 반영용).

URL 전송 시 자동으로 캡처 + LLM 요약 실행. 음성·이미지도 자동 처리.

전체 명령 목록은 봇에게 `/help`(또는 빈 메시지)를 보내면 확인할 수 있습니다.

---

## 프로젝트 구조

```
app/
├─ cli.py              # 진입점
├─ config.py           # .env 설정
├─ mcp_server.py       # MCP(stdio) 서버 — Agent Session Lifecycle 7개 tool 노출
├─ vault_tools.py      # MCP tool이 호출하는 상태 없는 Vault 함수 모음
├─ agents/             # CaptureAgent, DistillAgent, WikiBlogAgent
│                      # CuratorAgent, NightlyDistillAgent, WeeklyReviewAgent
│                      # CareerBulletAgent, OpenLoopsAgent
│                      # WorklogAgent, TodoAgent, PortfolioAgent
│                      # ResumeAgent, ProjectAgent
│                      # TaskAgent  ← 할 일 관리 (Telegram 봇 전용)
├─ services/           # WikiService, CandidateWriter, RepoSnapshot, retention(vault-cleanup)
│                      # TaskService  ← Active.md CRUD + 안정 ID
├─ memory/             # AgentMemoryLoader, ProjectMemoryLoader, ContextPackBuilder
├─ llm/                # router(task_type→chain), FallbackChain
│                      # GeminiProvider, KimiProvider, OllamaProvider, OpenAICompatibleProvider
├─ content_sources/    # ObsidianSource, GitSource
├─ messaging/          # Telegram provider, router, media_handler, bot
├─ assistant/          # 자연어 의도 라우팅
├─ models/             # ContextPack, SourceChunk
└─ prompts/*.md        # LLM 프롬프트 (코드와 분리)

start.py               # 환경 점검 + 대시보드 진입
dashboard.py           # Textual TUI 대시보드
launch.bat             # 새 터미널 창으로 대시보드 실행 (Windows)
install.ps1            # 최초 설치 스크립트 (Python + venv + PATH + hook, Windows)

scripts/
├─ hooks/post-commit       # git post-commit hook 스크립트 (기본 비활성)
├─ windows/                # Task Scheduler 등록/실행 스크립트 (register-schedules.ps1 등)
└─ mac/                    # launchd 등록/실행 스크립트 (register-schedules.sh 등)

docs/
├─ mac-automation-setup.md            # Mac 자동화 설정 가이드 (터미널 기초부터)
├─ vault-mcp-implementation-summary.md # MCP(Agent Session Lifecycle) 구현 요약
├─ vault-templates/                   # Obsidian 노트 템플릿 (외부 AI 프롬프트 가이드 포함)
└─ old/                               # 과거 기획·설계 문서 아카이브 (feature-reference, architecture 등)
```

---

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Vault / LLM / 메신저 모두 fake/mock으로 분리되어 API 키 없이 실행됩니다.
