# work-agent — Personal Knowledge OS

Obsidian Vault를 단일 지식 저장소로 삼아 작업 흔적을 자동으로 캡처·정제하고, 블로그·포트폴리오·이력서 초안을 만드는 개인 생산성 CLI/봇.

```
[ Capture ] ──→ [ Distill ] ──→ [ Curate ] ──→ [ Generate ] ──→ [ Deliver ]
  00_Inbox        60_Candidates    검토 → 승격     50_Outputs       Telegram · Blog
  10_Worklog
```

LLM은 창작자가 아닌 **작업 기록 정리자**다. source에 없는 사실·수치를 만들지 않는다.

→ 전체 기능 레퍼런스: [docs/feature-reference.md](docs/feature-reference.md)  
→ 구현 현황 보고: [docs/implementation-status.md](docs/implementation-status.md)

---

## 설치

Python 3.10 이상 필요. PowerShell에서 실행:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

5단계 자동 처리: Python 버전 감지 → `.venv` 생성 → 패키지 설치 → PATH 등록 → `.env` 초기화.

다른 프로젝트 레포에 git hook도 같이 설치하려면:

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
├─ 00_Inbox/         # capture로 쌓이는 raw 메모
│  └─ Captures/
├─ 10_Worklog/       # 작업 흔적
│  ├─ Daily/         #   capture-session, daily-log
│  ├─ GitSummaries/  #   capture-commit (git hook 자동)
│  └─ Summaries/     #   worklog 출력
├─ 20_Knowledge/     # 확정된 지식 ← promote-candidate 목적지
├─ 30_Projects/      # 프로젝트별 Context.md
├─ 40_AgentMemory/   # AI 공용 메모리 (Core/, OpenLoops 등)
├─ 50_Outputs/       # 최종 출력물 (Blog, Portfolio, Resume, Digest, Todo)
├─ 60_Candidates/    # distill 후보 — 사람 검토 전 임시 영역
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
work-agent init-vault                             # 볼트 폴더 구조 생성
work-agent install-hooks <repo> [-p project]      # git post-commit hook 설치
work-agent index-vault                            # index.md 갱신
```

### Capture — raw 기록 저장

```bash
work-agent capture "메모"                                         # → 00_Inbox/Captures/
work-agent capture-commit [-r repo] [--from-agent]               # → 10_Worklog/GitSummaries/
work-agent capture-session [-p project] [--from-repo]            # → 10_Worklog/Daily/
work-agent capture-session [-p project] --from-agent             # AI 세션 요약 포함
work-agent capture-session [-p project] --summary-file <md>      # AI 요약 파일 삽입
work-agent daily-log [-p project]                                # 오늘 데일리 로그 생성
work-agent daily-log [-p project] --from-agent                   # LLM이 오늘 컨텍스트 미리 채움
```

`--from-agent` 플래그: capture-commit은 커밋 의도를 LLM으로 요약. daily-log는 오늘 캡처·커밋·OpenLoops를 읽어 Done/Next 등 미리 채움.

post-commit hook 설치 시 커밋마다 `capture-commit` 자동 실행.

### Distill — 정제 후보 생성 (LLM 필요)

```bash
work-agent distill-today               # 오늘 Inbox → 60_Candidates/ 후보 일괄 생성
work-agent suggest-knowledge           # Knowledge 후보 제안
work-agent suggest-blog-topics         # BlogIdea 후보 제안
work-agent suggest-memory-patch        # AgentMemory 패치 제안
work-agent suggest-career-bullets      # 이력서·포폴 bullet 후보
work-agent update-open-loops           # OpenLoops 패치 후보
work-agent build-context "주제"        # ContextPack 구성
```

### Candidates 관리

```bash
work-agent list-candidates                      # 60_Candidates/ 목록 (stale 표시 포함)
work-agent preview-candidate <path>             # 후보 미리보기
work-agent promote-candidate <path>             # 공식 영역으로 승격
work-agent promote-all [--kind knowledge|decision|blog_idea]   # 타입별 일괄 승격
work-agent apply-memory-patch [path] [-i]       # → 40_AgentMemory/ 반영
```

### 탐색

```bash
work-agent search "RAG"             # 키워드 볼트 검색
work-agent related <path>           # 관련 노트 탐색 (태그·wikilink 기반)
```

### Generate — 결과물 생성 (LLM 필요)

```bash
# 작업 회고 / 할 일
work-agent worklog                             # 작업 회고 → 10_Worklog/Summaries/
work-agent todo                                # 다음 할 일 분석 → 50_Outputs/Todo/

# 블로그
work-agent write-blog "주제" [-p project]      # ContextPack → 50_Outputs/Blog/Drafts/
work-agent revise-blog <path>                  # 기존 초안 다듬기
work-agent publish-ready <path>                # status → review
work-agent export-tistory [target]             # 티스토리 포맷 변환
work-agent publish-done <path> [--url <url>]   # 게시 완료 기록
work-agent list                                # 초안 목록
work-agent preview [target]                    # 초안 미리보기

# 개인 문서
work-agent portfolio                           # 포트폴리오 소개 → 50_Outputs/Portfolio/
work-agent resume                              # 이력서·자소서 초안 → 50_Outputs/Resume/
work-agent summarize-project <name>            # 프로젝트 요약 (800자)
work-agent portfolio-draft <name>              # 프로젝트별 포폴 초안
work-agent interview-questions <name>          # 예상 면접 질문
```

### Deliver — 자동화 · 전송

```bash
work-agent nightly-distill                     # 하루 종합 정제 + daily digest + Telegram 전송
work-agent distill-range --days 7              # N일치 원본 대상 distill (weekly-distill과 동일)
work-agent weekly-distill                      # 7일치 종합 정제 + weekly digest + Telegram 전송
work-agent push-digest [--daily|--weekly|--worklog]   # 후보 요약 Telegram 수동 전송
work-agent print-schedule [--windows|--cron]   # OS 스케줄러 등록 명령 출력
work-agent ask "자연어"                        # 의도 분류 후 커맨드 실행
work-agent serve-bot                           # Telegram 봇 실행
```

---

## AI Agent 연동 (Claude Code / Cursor 등)

### 1단계 — CLAUDE.md 설정

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
work-agent build-context "XCoreChat RAG"   # → 50_Outputs/Context/ 에 파일 생성
work-agent search "RAG 검색"               # 관련 노트 확인
```

생성된 파일을 AI 세션에 추가합니다 (Claude Code: `/add 파일명`, Cursor: `@파일명`).

### 3단계 — 세션 종료 시 Vault에 저장

Claude Code에서:

```
capture-session 실행해줘
```

Claude Code가 `CLAUDE.md`의 규칙에 따라 요약을 작성하고 실행:

```bash
work-agent capture-session --project <name> --from-repo --from-agent --summary-file ./session-summary.md
```

### 전체 흐름

```
[세션 시작]  build-context → AI에 파일 추가 → 작업
[세션 중]    커밋 → post-commit hook → capture-commit (자동)
[세션 종료]  capture-session --from-agent → 10_Worklog/Daily/ 저장
[야간]       nightly-distill → 60_Candidates/ 후보 생성
[다음 날]    list-candidates → promote-candidate → 20_Knowledge/ 누적
```

---

## 야간 자동화

```
[23:30] nightly-distill
  ├─ DistillAgent       → 60_Candidates/ (Knowledge / Decisions / MemPatches / BlogIdeas)
  ├─ CareerBulletAgent  → 60_Candidates/CareerBullets/
  ├─ 50_Outputs/Digest/ 저장
  └─ Telegram 설정 시 digest 자동 전송

[08:30] push-digest --daily   (어제 요약 아침 확인)
```

```bash
work-agent print-schedule --windows   # Windows Task Scheduler 등록 명령
work-agent print-schedule --cron      # Linux / Mac crontab 등록 명령
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
work-agent serve-bot
```

### 할 일 관리

```
/task <내용>              할 일 추가  (예: /task 코드리뷰 내일까지)
/tasks                    목록 보기 + 완료·삭제 인라인 버튼
/done <번호>              완료 처리
/del <번호>               삭제
/edit <번호> <새내용>     내용·날짜·섹션 수정
```

날짜 키워드 자동 인식: `오늘` · `내일` · `이번 주` · `월~일요일` · `2026-07-01`  
날짜 기준으로 섹션(오늘 / 이번 주 / 언제든지) 자동 배정.

`/tasks` 응답에는 태스크마다 **완료(✅)·삭제(🗑) 버튼**이 붙습니다. 버튼은 내부적으로 안정 ID(`^hex6`)를 사용해 목록이 바뀐 뒤에도 오동작하지 않습니다.

태스크는 Obsidian Vault `70_Tasks/Active.md`에 저장되며, 완료 시 `70_Tasks/Done/<날짜>.md`에 기록됩니다.

### 지식 관리 · 기타

```
/capture <메모>     /distill           /candidates
/search <검색어>    /context <주제>    /promote <path>
/write <주제>       /worklog           /todo
/portfolio          /resume            /list
```

URL 전송 시 자동으로 캡처 + LLM 요약 실행. 음성·이미지도 자동 처리.

---

## 프로젝트 구조

```
app/
├─ cli.py              # 진입점
├─ config.py           # .env 설정
├─ agents/             # CaptureAgent, DistillAgent, WikiBlogAgent
│                      # CuratorAgent, NightlyDistillAgent
│                      # CareerBulletAgent, OpenLoopsAgent
│                      # WorklogAgent, TodoAgent, PortfolioAgent
│                      # ResumeAgent, ProjectAgent
│                      # TaskAgent  ← 할 일 관리 (Telegram 봇 전용)
├─ services/           # WikiService, CandidateWriter, RepoSnapshot
│                      # TaskService  ← Active.md CRUD + 안정 ID
├─ memory/             # AgentMemoryLoader, ProjectMemoryLoader, ContextPackBuilder
├─ llm/                # router(task_type→chain), FallbackChain
│                      # GeminiProvider, KimiProvider, OllamaProvider, OpenAICompatibleProvider
├─ content_sources/    # ObsidianSource, GitSource, LocalDocSource
├─ messaging/          # Telegram provider, router, media_handler, bot
├─ assistant/          # 자연어 의도 라우팅
├─ models/             # ContextPack, SourceChunk
└─ prompts/*.md        # LLM 프롬프트 (코드와 분리)

start.py               # 환경 점검 + 대시보드 진입
dashboard.py           # Textual TUI 대시보드
launch.bat             # 새 터미널 창으로 대시보드 실행 (Windows)
install.ps1            # 최초 설치 스크립트 (Python + venv + PATH + hook)

docs/
├─ feature-reference.md    # 전체 기능 레퍼런스
├─ architecture.md         # 아키텍처 설명
└─ vault-templates/        # Obsidian 노트 템플릿 (외부 AI 프롬프트 가이드 포함)
```

---

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Vault / LLM / 메신저 모두 fake/mock으로 분리되어 API 키 없이 실행됩니다.
