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
| **writer** | 블로그·이력서·포트폴리오 초안 (`blog write`, `resume`, `suggest-career-bullets`) | Gemini Flash → GPT-4.1-mini → Kimi |
| **long_writer** | 긴 ContextPack 기반 글쓰기 (`weekly-distill`, `summarize-project`) | Kimi → Gemini Flash → GPT-4.1-mini |
| **polish** | 최종 문장 다듬기 (`blog revise`) | GPT-4.1-mini → Gemini Flash |
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
│  └─ URLs/          # URL 북마크 (사람이 넣음, 읽기 전용)
├─ 10_Worklog/
│  └─ Sessions/      # write_session_process / capture-session 출력 (AI 세션 요약)
├─ 20_Knowledge/     # 확정된 지식 ← nightly 자동 승격 목적지 (프로젝트별 하위 폴더)
├─ 30_Projects/      # 프로젝트 정본 문서 — Context.md · Decisions/ · Plans/ · Design/ · Conversations/
├─ 40_AgentMemory/   # 전역 AI 메모리 (00_Profile.md ~ 06_Lessons.md)
├─ 50_Outputs/
│  ├─ Digest/        # daily digest (nightly 자동 생성)
│  ├─ WeeklyReview/  # 주간 회고 (weekly 자동 생성)
│  ├─ Blog/          # 블로그 초안·발행본 (Ideas / Drafts / Export)
│  ├─ Career/        # 승격된 이력서·포폴 불릿 (career_bullet promote 시 생성)
│  ├─ Portfolio/
│  ├─ Resume/
│  ├─ Interview/
│  └─ Todo/
├─ 60_Candidates/    # distill 후보 — 사람 검토 전 임시 영역
│  ├─ Knowledge/
│  ├─ Decisions/
│  ├─ MemoryPatches/
│  ├─ BlogIdeas/
│  ├─ CareerBullets/
│  ├─ Problems/      # record_problem — 증상·원인·시도·해결·예방 + component/cause_class
│  └─ SessionHandoffs/  # 세션 Plan/Process — promote 대상 아님, 다음 세션 briefing이 소비
├─ 70_Tasks/         # Telegram /task 할 일 (Active.md + Done/)
├─ index.md
└─ log.md
```

**AI 쓰기 가능**: `00_Inbox/`, `10_Worklog/`, `50_Outputs/`, `60_Candidates/`, `70_Tasks/`(task 커맨드 경유)  
**직접 수정 금지** (candidate/patch 경유): `20_Knowledge/`, `40_AgentMemory/`, `30_Projects/*/Context.md`, `30_Projects/*/Decisions/`

Obsidian 템플릿은 [docs/vault-templates/](docs/vault-templates/)을 Vault의 `90_Templates/`에 복사해서 사용 (외부 AI 프롬프트 가이드 포함).

---

## 명령 목록

### Vault 초기화

```bash
devtrail doctor [--fix] [--project <이름>]       # 머신별 설치·연동 상태 진단·수리
devtrail init-vault                             # 볼트 폴더 구조 생성
devtrail index-vault                            # index.md 갱신
```

### Capture — 세션 기록 (MCP 미연결 시 fallback)

```bash
devtrail capture-session [-p project] [--from-repo]            # → 10_Worklog/Sessions/
devtrail capture-session [-p project] --from-agent             # AI 세션 요약 포함
devtrail capture-session [-p project] --summary-file <md>      # AI 요약 파일 삽입
```

1차 경로는 MCP `write_session_process`다. 메모·커밋·데일리 로그 캡처(`capture`,
`capture-commit`, `daily-log`)와 git post-commit hook은 입력이 없어 2026-10-19에 제거했다.

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

### Candidates

사람 검토 CLI(`list-candidates` · `review` · `promote-*` · `apply-memory-patch`)는 2026-10-19에
제거했다. 후보는 nightly가 자동 반영·승격한다(memory_patch 매일, knowledge/decision/problem은
2일 조용하면). 상태는 digest와 `60_Candidates/`를 Obsidian에서 본다.

### 탐색

```bash
devtrail search "RAG"             # 키워드 볼트 검색
devtrail related <path>           # 관련 노트 탐색 (태그·wikilink 기반)
```

### Generate — 결과물 생성 (LLM 필요)

```bash
# 할 일
devtrail todo                                # 다음 할 일 분석 → 50_Outputs/Todo/

# 블로그 (blog 서브커맨드)
devtrail blog write "주제" [-p project]      # ContextPack → 50_Outputs/Blog/Drafts/
devtrail blog revise <path>                  # 기존 초안 다듬기
devtrail blog publish-ready <path>           # status → review
devtrail blog export-tistory [target]        # 티스토리 포맷 변환
devtrail blog publish-done <path> [--url <url>]  # 게시 완료 기록
devtrail blog list                           # 초안 목록
devtrail blog preview [target]               # 초안 미리보기

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
devtrail push-digest [--daily|--weekly]             # 후보 요약 Telegram 수동 전송
devtrail notify morning|evening              # 아침/저녁 알림 Telegram 전송 (OS 스케줄러가 호출)
devtrail print-schedule [--windows|--cron]   # OS 스케줄러 등록 명령 출력 (최소 구성)
```

전체 자동화(코드/Vault 자동 동기화 · nightly · weekly · 아침/저녁 알림)를 한 번에 등록하려면
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
MCP(stdio) 서버입니다. MCP가 연결돼 있으면 세션 시작/종료 기록은 아래 12개 tool이
1차 경로이고, `capture-session` CLI는 MCP 미연결 시의 fallback입니다.

등록 (Claude Code):

```bash
claude mcp add devtrail-vault -- devtrail mcp-serve
```

`devtrail`이 PATH에 없으면(venv에만 설치한 경우) 연결이 `CONNECTION_CLOSED`로
조용히 실패합니다. 실행 파일의 절대 경로로 등록하세요:

```bash
# Windows
claude mcp add devtrail-vault -- "<repo>\.venv\Scripts\devtrail.exe" mcp-serve
# macOS / Linux
claude mcp add devtrail-vault -- <repo>/.venv/bin/devtrail mcp-serve
```

등록 후 `claude mcp list`로 `✔ Connected`를 확인합니다. 등록 여부 자체는
`devtrail doctor`가 점검합니다.

| Tool | 역할 |
|------|------|
| `get_project_briefing` | 세션 시작 시 프로젝트 컨텍스트 · 최근 handoff · decision · Open Loops 반환 |
| `search_vault` | read_scope 안 노트 검색 (status=stable/candidate 포함) |
| `read_note` | scope 안 노트 전문 읽기 |
| `get_recent_sessions` | 프로젝트의 최근 세션 목록 (세션당 한 항목: goal · what_changed · next_session 발췌) |
| `get_decisions` | 프로젝트의 결정 이력 (승격 전 후보 · 승격 · `include_archived`로 보관분까지) |
| `get_known_problems` | 겪은 문제 조회 — `record_problem` 기록(분류 있음) + 세션 Process의 막힌 점 · 실수. `component`로 필터 |
| `record_note` | 결정/지식/아이디어를 `60_Candidates/`에 후보로 기록 (knowledge/decision/blog_idea/career_bullet) |
| `record_problem` | 겪은 문제와 해결을 problem 후보로 기록 (증상·원인·시도·해결·예방, `component`·`cause_class` 분류) → promote 시 `30_Projects/<P>/Problems/` |
| `record_agent_improvement` | 반복 실수 · 개선할 작업 방식 · 프로젝트 주의사항을 MemoryPatch 후보로 기록 |
| `update_open_loops` | `40_AgentMemory/05_OpenLoops.md`의 프로젝트 블록에 다음 세션에도 남는 할 일을 넣고(add) 끝난 줄을 지운다(resolve) — 40_AgentMemory 중 유일하게 에이전트가 직접 쓰는 파일 |
| `update_project_context` | `30_Projects/<P>/Context.md`의 `## 절` 본문을 교체(없으면 추가)하고 updated_at 갱신 — 신선도 경고를 에이전트가 직접 해소한다. 공식 영역 중 유일한 직접 쓰기 |
| `write_work_plan` | (선택) 긴 작업의 Plan 기록 — 다음 세션 briefing에 Latest Plan으로 보인다. 필수 아님 |
| `write_session_process` | 세션 종료/컴팩팅 전 Process 기록 → `SessionHandoffs` candidate + `10_Worklog/Sessions/` 세션 기록 동시 생성 |

세션 시작 시 `get_project_briefing`을 먼저 호출하고, 세션 종료/컴팩팅 직전에는
`write_session_process`로 기록합니다. `session_id`는 MCP 서버 프로세스 시작 시
1회 생성돼 모든 write 계열 tool에 자동 주입되므로 에이전트가 직접 들고 다닐 필요가
없습니다(컴팩팅 중 분실 방지).

### 새 머신 점검 — `devtrail doctor`

```bash
devtrail doctor          # 진단만
devtrail doctor --fix    # 고칠 수 있는 것만 수리 (기존 파일은 덮어쓰지 않음)
```

`.claude/settings.json`(훅)과 `.claude/vault.json`(프로젝트 매핑)은 gitignore된
**머신 로컬 파일**이라 clone만으로는 생기지 않습니다. 그리고 없어도 아무 경고가
나오지 않습니다 — 훅 없이 몇 주간 작업하고 세션 기록이 0건인 것을 나중에 알게
되는 종류의 실패입니다. `doctor`는 그 조용한 실패를 찾습니다.

점검 항목: vault 경로(`.env`) · `mcp` 패키지 · 훅 설정 파일 · 훅 실행 전제(python) ·
콘솔 스크립트 실행 · 프로젝트 매핑(값이 Vault에 실재하는지까지) · vault 구조 ·
MCP 등록·연결.

**MCP는 등록 여부가 아니라 연결 결과를 봅니다.** 등록돼 있어도 실행 파일이 기동하지
못하면 세션에 tool이 뜨지 않아 증상은 미등록과 같기 때문입니다. 같은 이유로 repo
`.venv`의 `devtrail` 콘솔 스크립트가 실제로 실행되는지도 확인합니다 — repo를 rename
하거나 옮기면 셔뱅이 옛 경로를 가리켜 **오류 메시지 없이 exit 1** 하는데, 이때
`capture-session`도 MCP도 조용히 죽습니다.

`--fix`가 하는 것은 `settings.json` 복사, `vault.json` 생성(Vault 프로젝트 후보가
하나일 때 — 여러 개면 `--project <이름>`), `init-vault` 재실행뿐입니다. `.env` 편집과
`claude mcp add`는 하지 않고 명령만 안내합니다.

### Claude Code 훅 활성화 (선택, 머신별 1회)

`devtrail doctor --fix`가 이 복사를 대신 해줍니다. 직접 하려면:

```bash
cp .claude/settings.example.json .claude/settings.json
```

이 한 번으로 세 가지 훅이 켜집니다 — SessionStart(briefing 자동 주입),
Stop/PreCompact(`write_session_process` 미기록 상태로 세션을 끝내려 하면 차단·리마인드).
훅 명령은 크로스플랫폼입니다: `scripts/hooks/run-hook.sh`(sh 디스패처)가 OS에 맞는
python으로 훅 구현(`scripts/hooks/*.py`)을 실행합니다 — Windows는 Git for Windows의
`sh.exe`, macOS는 `/bin/sh`. `settings.json`은 gitignore된 머신 로컬 파일이므로
머신마다 위 복사를 한 번씩 해줘야 합니다.

---

## AI Agent 연동 (MCP 미지원 도구 — Cursor 등, 또는 fallback)

### 1단계 — AGENTS.md 설정

에이전트 규칙은 **`AGENTS.md` 한 곳**에 둡니다 — Claude Code·Codex·Cursor가
공통으로 읽는 파일입니다. `CLAUDE.md`는 `AGENTS.md`를 가리키기만 하고 규칙을
중복해 적지 않습니다(중복되면 한쪽만 고쳐져 조용히 어긋납니다).

프로젝트 루트 `AGENTS.md`에 추가:

```markdown
## Vault 경로
OBSIDIAN_VAULT_PATH: D:/personal-vault

## 작업 시작 전 필독 파일
- {VAULT}/30_Projects/<프로젝트명>/Context.md — 프로젝트 배경·목표·제약
- {VAULT}/40_AgentMemory/00_Profile.md ~ 06_Lessons.md — 전역 메모리·미해결 이슈

## Vault 수정 규칙
- 20_Knowledge/, 30_Projects/, 40_AgentMemory/ 는 직접 수정하지 않는다.
- 모든 제안·초안은 60_Candidates/ 에 파일로 생성한다. 사람 검토 게이트는 없다 — memory_patch는 nightly가 바로 반영하고, knowledge/decision/problem은 2일 조용하면 자동 승격한다. 사람은 보기만 한다.
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

AGENTS.md의 규칙에 따라 요약을 작성하고 실행:

```bash
devtrail capture-session --project <name> --from-repo --from-agent --summary-file ./session-summary.md
```

### 전체 흐름

```
[세션 시작]  MCP: get_project_briefing (fallback: build-context → AI에 파일 추가) → 작업
[세션 종료]  MCP: write_session_process (fallback: capture-session --from-agent) → 10_Worklog/Sessions/ 저장
[야간]       nightly-distill → 60_Candidates/ 후보 생성
[매주 일요일] weekly-distill → 50_Outputs/WeeklyReview/ 주간 회고
[2일 뒤 야간] nightly-distill이 조용한 후보를 자동 승격 → 20_Knowledge/ · 30_Projects/<P>/Decisions/ 누적
```

---

## 야간 자동화

```
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

## Telegram 전송

```env
MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<BotFather에서 발급>
TELEGRAM_CHAT_ID=<알림 받을 chat id>
```

송신 전용이다 — nightly digest·주간 회고·아침/저녁 알림이 이 채널로 간다. 메시지를 받아
처리하는 봇(`serve-bot`, `/review`·`/task`·메모 캡처)은 2026-10-19에 제거했다: 승격이 자동이
된 뒤 사람이 봇으로 할 일이 없었고, 기록 입력은 전부 Claude Code 세션의 MCP가 담당한다.

---

## 프로젝트 구조

```
app/
├─ cli.py              # 진입점
├─ config.py           # .env 설정
├─ mcp_server.py       # MCP(stdio) 서버 — Agent Session Lifecycle 12개 tool 노출
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
├─ messaging/          # Telegram 송신 provider (digest·알림)
├─ models/             # ContextPack, SourceChunk
└─ prompts/*.md        # LLM 프롬프트 (코드와 분리)

start.py               # 환경 점검 + 대시보드 진입
dashboard.py           # Textual TUI 대시보드
launch.bat             # 새 터미널 창으로 대시보드 실행 (Windows)
install.ps1            # 최초 설치 스크립트 (Python + venv + PATH + hook, Windows)

scripts/
├─ hooks/run-hook.sh       # Claude Code 훅 디스패처 — OS에 맞는 python 선택 (win/mac 공용)
├─ hooks/*.py              # Claude Code 훅 구현 (SessionStart briefing 주입 · Stop 기록 체크)
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
