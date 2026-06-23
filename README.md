# Work Agent — Obsidian LLM Knowledge Core

Obsidian Vault를 단일 지식 저장소로 삼아 작업 흔적을 자동으로 캡처·정제하고, 블로그·포트폴리오·이력서 초안을 만드는 개인 생산성 CLI/봇.

**파이프라인: Capture → Distill → Promote**

```
커밋/메모/세션          정제·분류                 확정
  capture             distill-today            promote-candidate
  capture-session  →  nightly-distill      →   apply-memory-patch
  capture-commit      list-candidates          write-blog / resume / portfolio
```

LLM은 창작자가 아닌 **작업 기록 정리자**다. source에 없는 사실·수치를 만들지 않는다.

---

## 설치

Python 3.11+ 필요.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

---

## AI 설정

work-agent는 작업 성격에 따라 LLM을 자동 선택하고, 실패 시 다음 provider로 자동 폴백합니다.

### task_type별 라우팅

| task_type | 용도 | 기본 chain |
|-----------|------|-----------|
| **light** | 분류·태깅·짧은 요약 (`distill-today`, `suggest-*`, `capture`) | Gemini Flash-Lite → GPT-4o mini → Ollama |
| **writer** | 블로그·이력서·포트폴리오 초안 (`write-blog`, `resume`, `worklog`) | Gemini Flash → GPT-4o mini → Kimi |
| **long_writer** | 긴 ContextPack 기반 글쓰기 (`weekly-distill`, `summarize-project`) | Kimi → Gemini Flash → GPT-4o mini |
| **polish** | 최종 문장 다듬기 (`revise-blog`) | GPT-4o mini → Gemini Flash |
| **local** | 인터넷 전체 장애 시 최소 동작 | Ollama |

각 chain에서 API 키가 없는 provider는 자동으로 제외됩니다. Gemini만 설정해도 동작합니다.

### HTTP 오류별 처리

- **503 / 429 / timeout / connection error** → 즉시 다음 provider로 fallback
- **JSON 파싱 실패** → 같은 provider 1회 재시도 → 실패 시 다음 provider
- **모든 provider 실패** → 명확한 오류 메시지 반환

### Gemini (추천 — 인터넷 연결만 있으면 됨)

[Google AI Studio](https://aistudio.google.com/apikey)에서 API 키 발급 (무료 티어 있음).

```env
GEMINI_API_KEY=AIza...
GEMINI_FLASH_MODEL=gemini-2.5-flash        # writer task 1순위
GEMINI_LITE_MODEL=gemini-2.5-flash-lite    # light task 1순위

# 구 경로 호환 (선택)
LLM_PROVIDER=gemini
WRITER_PROVIDER=gemini
```

`google-generativeai` 패키지 없이 httpx REST로 직접 호출합니다.

### OpenAI / GPT-4o mini (fallback chain 포함)

`OPENAI_API_KEY`를 설정하면 각 task chain에 자동으로 포함됩니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

### Kimi (Moonshot AI) — long_writer 특화

긴 ContextPack 기반 글쓰기에서 1순위로 사용됩니다.

```env
KIMI_API_KEY=...
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2
```

### Ollama (로컬, 인터넷 불필요 — light task 최후 폴백)

[ollama.com](https://ollama.com)에서 Ollama 설치 후 모델 Pull.

```bash
ollama pull qwen3:8b
```

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

### vLLM (자체 GPU 서버)

OpenAI 호환 API로 동작합니다. `OPENAI_API_KEY=dummy`로 설정하면 fallback chain에 포함됩니다.

```env
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=dummy
OPENAI_MODEL=Qwen/Qwen2.5-14B-Instruct
OPENAI_MAX_TOKENS=1024
OPENAI_CONTEXT_WINDOW=8192
CONTEXT_CHAR_BUDGET=14000
```

---

## 대시보드 (빠른 시작)

```bash
python start.py
```

환경 점검 후 대화형 대시보드로 진입합니다.

```
╭─────────────────────── work-agent ────────────────────────╮
│  raw  12    후보  3                                        │
│  지식 47    distill  오늘                                  │
│                                                            │
│  최근 지식                                                 │
│  · RAG 검색 전략                                           │
│  · vLLM 컨텍스트 윈도우 처리                               │
│                                                            │
│  오픈 루프                                                 │
│  · XCoreChat DB 마이그레이션                               │
╰────────────────────────────────────────────────────────────╯

  [1] distill-today       [2] nightly-distill
  [3] list-candidates     [4] apply-memory-patch
  [5] push-digest         [6] weekly-distill
  [c] capture 메모        [s] search 키워드
  [q] 종료
```

---

## Vault 구조

`init-vault`가 생성하는 기본 구조.

```
<vault>/
├─ 00_Inbox/         # capture로 쌓이는 raw 메모 (AI 쓰기 가능)
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
├─ 90_Templates/
├─ index.md
└─ log.md
```

**AI 쓰기 가능**: `00_Inbox/`, `10_Worklog/`, `50_Outputs/`, `60_Candidates/`  
**직접 수정 금지** (candidate/patch 경유): `20_Knowledge/`, `40_AgentMemory/Core/`, `30_Projects/*/Context.md`

---

## 명령 목록

### Vault 초기화

```bash
work-agent init-vault                      # 볼트 폴더 구조 생성
work-agent install-hooks --repo <path>     # git post-commit hook 설치
work-agent index-vault                     # index.md 갱신
```

### Capture — raw 기록 저장

```bash
work-agent capture "메모"                                         # → 00_Inbox/Captures/
work-agent capture-commit --repo <path>                          # → 10_Worklog/GitSummaries/
work-agent capture-session --project <name>                      # → 10_Worklog/Daily/
work-agent capture-session --project <name> --from-repo          # git 스냅샷 포함
work-agent capture-session --project <name> --from-agent         # AI 세션 요약 신호
work-agent capture-session --project <name> --summary-file <md>  # AI 요약 파일 삽입
work-agent daily-log                                             # 오늘 데일리 로그 노트
```

post-commit hook 설치 시 커밋마다 `capture-commit` 자동 실행.

### Distill — 정제 후보 생성 (LLM 필요)

```bash
work-agent distill-today           # 오늘 Inbox → 60_Candidates/ 후보 생성
work-agent suggest-knowledge       # Knowledge 후보 제안
work-agent suggest-blog-topics     # BlogIdea 후보 제안
work-agent suggest-memory-patch    # AgentMemory 패치 제안
work-agent build-context "주제"    # ContextPack 구성
```

### Candidates 관리

```bash
work-agent list-candidates              # 60_Candidates/ 목록
work-agent preview-candidate <path>     # 후보 미리보기
work-agent promote-candidate <path>     # → 20_Knowledge/ 승격
work-agent apply-memory-patch <path>    # → 40_AgentMemory/ 반영
work-agent apply-memory-patch -i        # 인터랙티브 선택 모드
```

### 탐색

```bash
work-agent search "RAG"             # 키워드 볼트 검색
work-agent related <path>           # 관련 노트 탐색 (태그·wikilink 기반)
```

### 블로그 출력 (LLM 필요)

```bash
work-agent write-blog "주제"        # ContextPack → 50_Outputs/Blog/Drafts/
work-agent revise-blog <path>       # 기존 초안 다듬기
work-agent suggest-topics           # 블로그 주제 추천
work-agent list                     # 초안 목록
work-agent preview [slug]           # 초안 미리보기
work-agent export-tistory [slug]    # 티스토리 포맷 변환
work-agent publish-done <url>       # 게시 완료 기록
```

### 개인 문서 (LLM 필요)

```bash
work-agent worklog                         # 작업 회고 → 10_Worklog/Summaries/
work-agent todo                            # 다음 할 일 → 50_Outputs/Todo/
work-agent resume                          # 이력서 초안 → 50_Outputs/Resume/
work-agent portfolio                       # 포트폴리오 초안 → 50_Outputs/Portfolio/
work-agent summarize-project <name>        # 프로젝트 요약
work-agent portfolio-draft <name>          # 프로젝트별 포폴 초안
work-agent interview-questions <name>      # 예상 면접 질문
```

### 자동화 · Phase 2

```bash
work-agent nightly-distill                        # 하루 종합 정제 + daily digest
work-agent weekly-distill                         # 7일치 종합 정제 + weekly digest
work-agent suggest-career-bullets                 # 이력서/포폴 bullet 후보
work-agent suggest-career-bullets --project <name>
work-agent update-open-loops                      # Open Loops MemoryPatch 후보
work-agent push-digest --daily                    # 오늘 요약 메신저 전송
work-agent push-digest --weekly                   # 7일 요약 메신저 전송
work-agent push-digest --worklog                  # 회고 포함 전송
work-agent print-schedule --windows               # Windows schtasks 등록 명령 출력
work-agent print-schedule --cron                  # Linux/Mac crontab 등록 명령 출력
work-agent ask "자연어"                            # 의도 분류 후 커맨드 실행
work-agent serve-bot                              # Telegram 봇 실행
```

---

## AI Agent 연동 (Claude Code / Cursor 등)

AI 코딩 어시스턴트가 세션마다 vault에 쌓인 지식을 자동으로 참고하게 만드는 방법입니다.

### 1단계 — CLAUDE.md (또는 .cursorrules) 설정

프로젝트 루트에 아래 내용을 추가합니다. Claude Code는 `CLAUDE.md`를, Cursor는 `.cursorrules`를 자동으로 읽습니다.

```markdown
## Vault 경로
OBSIDIAN_VAULT_PATH: D:/personal-vault   ← 실제 경로로 교체

## 작업 시작 전 필독 파일
- {VAULT}/40_AgentMemory/Core/<프로젝트명>.md — 이 프로젝트 핵심 컨텍스트
- {VAULT}/40_AgentMemory/05_OpenLoops.md    — 미해결 이슈 목록

## Vault 수정 규칙
- 20_Knowledge/, 30_Projects/, 40_AgentMemory/Core/ 는 직접 수정하지 않는다.
- 모든 제안·초안은 60_Candidates/ 에 파일로 생성하고 사람이 검토 후 promote 한다.
```

work-agent 저장소의 `CLAUDE.md`에는 이 내용이 이미 포함되어 있습니다. 다른 프로젝트에서 작업할 때도 같은 내용을 해당 프로젝트의 `CLAUDE.md`에 복사하세요.

---

### 2단계 — 세션 시작 시 컨텍스트 로딩

AI가 지금 작업과 관련된 지식을 갖고 시작하도록 컨텍스트 파일을 생성합니다.

```bash
# 주제/프로젝트 관련 지식을 한 파일로 묶기
work-agent build-context "XCoreChat RAG"
# → 50_Outputs/Context/YYYYMMDD-xcoreChat-rag.md 생성

# 검색으로 관련 노트 확인
work-agent search "RAG 검색"
```

생성된 파일을 AI 세션에 추가합니다.

| AI 도구 | 방법 |
|---------|------|
| **Claude Code** | `/add 50_Outputs/Context/파일명.md` 또는 `@파일명` |
| **Cursor** | `@파일명` |
| **Windsurf / Copilot Chat** | 파일을 열어 두거나 첨부 |

또는 `40_AgentMemory/Core/<프로젝트명>.md`를 직접 참조해도 됩니다 — 프로젝트 컨텍스트, 기술 스택, 설계 결정이 누적된 파일입니다.

---

### 3단계 — 세션 종료 시 vault에 저장

작업이 끝나면 AI에게 세션 요약을 작성하게 하고 vault에 기록합니다.

**Claude Code에서:**
```
capture-session 실행해줘
```

Claude Code가 `CLAUDE.md`의 capture-session 규칙에 따라 요약을 작성하고 아래 명령을 실행합니다.

```bash
work-agent capture-session \
  --project <프로젝트명> \
  --from-repo \
  --from-agent \
  --summary-file ./session-summary.md
```

이후 `nightly-distill`이 이 기록을 읽어 지식 후보를 자동 생성합니다.

---

### 전체 흐름 요약

```
[세션 시작]
  build-context → AI에 파일 추가 → 작업

[세션 중]
  커밋 → post-commit hook → capture-commit (자동)

[세션 종료]
  capture-session --from-agent → 10_Worklog/Daily/ 저장

[야간]
  nightly-distill → 60_Candidates/ 후보 생성

[다음 날]
  list-candidates → promote-candidate → 20_Knowledge/ 누적
```

---

## 야간 자동화

OS 스케줄러로 `nightly-distill`을 매일 자동 실행하면 아침에 결과를 확인하는 루프가 만들어집니다.

```
[23:30] nightly-distill
  ├─ DistillAgent       → 60_Candidates/ (Knowledge / Decisions / MemPatches / BlogIdeas)
  ├─ CareerBulletAgent  → 60_Candidates/CareerBullets/
  ├─ 50_Outputs/Digest/YYYY-MM-DD-daily-digest.md 저장
  └─ Telegram 설정 시 digest 자동 전송

[08:30] push-digest --daily   (어제 요약 아침 확인)
```

스케줄러 등록 명령 출력:

```bash
work-agent print-schedule --windows   # Windows Task Scheduler
work-agent print-schedule --cron      # Linux / Mac crontab
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

슬래시 명령과 자유 문장 양방향 지원.

```
/capture <메모>    /search <검색어>    /distill
/draft <주제>      /candidates         /context <주제>
/session <프로젝트>  /worklog           /todo
```

음성(voice)·이미지(photo)·URL 캡처도 자동 처리합니다 (`OBSIDIAN_VAULT_PATH` 설정 시).

---

## 프로젝트 구조

```
app/
├─ cli.py              # 진입점 (얇게)
├─ config.py           # .env 설정
├─ agents/             # CaptureAgent, DistillAgent, WikiBlogAgent
│                      # CuratorAgent, NightlyDistillAgent
│                      # CareerBulletAgent, OpenLoopsAgent
│                      # WorklogAgent, TodoAgent, PortfolioAgent, ResumeAgent
│                      # ProjectAgent
├─ memory/             # AgentMemoryLoader, ProjectMemoryLoader, ContextPackBuilder
├─ services/           # WikiService, CandidateWriter, RepoSnapshot ...
├─ llm/                # router(task_type→chain), fallback(FallbackChain)
│                      # GeminiProvider, KimiProvider, OllamaProvider, OpenAICompatibleProvider
├─ content_sources/    # ObsidianSource, GitSource, LocalDocSource
├─ messaging/          # Telegram provider, router, bot
├─ assistant/          # 자연어 의도 라우팅
├─ models/             # ContextPack, SourceChunk
└─ prompts/*.md        # LLM 프롬프트 (코드 분리)

start.py               # 대화형 대시보드 (python start.py)
```

---

## 구현 상태

| 영역 | 상태 | 비고 |
|---|---|---|
| Vault 초기화 | ✅ Done | `init-vault` |
| Capture | ✅ Done | `capture`, `capture-commit`, `capture-session` |
| Distill | 🔶 Partial | LLM 품질 검증 필요 |
| Candidate 승격 | ✅ Done | `promote-candidate` / `apply-memory-patch` |
| Blog 작성 | 🔶 Partial | source grounding 검증 필요 |
| Resume / Portfolio | 🔶 Partial | 초안 품질 검증 필요 |
| Telegram Bot | 🔶 Partial | 운영 테스트 필요 |
| Scheduler | ✅ Done | 명령 출력 방식 (`print-schedule`) |
| Natural Language ask | 🔶 Partial | intent routing 개선 필요 |
| LLM 라우터 / Fallback | ✅ Done | task_type별 chain, 503/429/timeout 자동 폴백 |

---

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Vault / LLM / 메신저 모두 fake/mock으로 분리되어 API 키 없이 실행됩니다.
