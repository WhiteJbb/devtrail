# Work Agent — Obsidian LLM Wiki Core

Obsidian Vault를 단일 지식 저장소로 삼아, 작업 흔적을 자동으로 캡처하고 정제해 블로그·포트폴리오·이력서 초안을 만드는 개인 생산성 CLI/봇.

**파이프라인: Capture → Distill → Promote**

```text
커밋 / 메모 / 세션          정제·분류               확정·출력
  capture                  distill-today           promote-candidate
  capture-commit   →       suggest-*        →      write-blog
  capture-session          build-context           portfolio-draft
  daily-log                list-candidates         resume / worklog / todo
```

LLM은 창작자가 아닌 **작업 기록 정리자**다. 존재하지 않는 사실·수치를 만들지 않고, source에 있는 내용만 정리한다.

---

## 설치

요구사항: Python 3.11+

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env   # 필요한 값만 채우면 됨
```

---

## `.env` 핵심 설정

```env
# [필수] Obsidian 볼트 절대경로
OBSIDIAN_VAULT_PATH=D:/personal-vault

# [LLM] 분류·라우팅용 로컬 모델 (ollama 권장)
LOCAL_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# [LLM] 글쓰기 모델 (Gemini REST — google-generativeai 패키지 불필요)
WRITER_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_FLASH_MODEL=gemini-2.5-flash

# [메신저 선택] 텔레그램 봇
MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_CHAT_ID=
```

전부 비워도 실행됩니다 (LLM은 안내 메시지만 출력).  
자세한 항목은 `.env.example` 참고.

---

## 명령 목록

### Vault 초기화

| 명령 | 설명 |
| --- | --- |
| `init-vault` | 볼트 기본 폴더 구조 생성 |
| `install-hooks --repo <path>` | git 레포에 post-commit hook 설치 (커밋 → 자동 캡처) |
| `index-vault` | 볼트 Markdown을 읽어 `index.md` 갱신 |

### 탐색

| 명령 | 설명 |
| --- | --- |
| `search "RAG"` | 키워드로 볼트 노트 검색 |
| `related <path>` | 특정 노트와 관련된 노트를 태그·위키링크 기반으로 탐색 |

### Capture — 원시 기록 저장

| 명령 | 설명 |
| --- | --- |
| `capture "메모"` | `00_Inbox/Captures/`에 raw 메모 저장 |
| `capture-commit --repo <path>` | git commit을 `10_Worklog/GitSummaries/`에 저장 |
| `capture-chat --file chat.md` | 대화 파일을 `00_Inbox/Chats/`에 저장 |
| `capture-session --project <name>` | 작업 세션 요약 노트를 `10_Worklog/Daily/`에 저장 |
| `daily-log` | 오늘 날짜 데일리 로그 노트 생성 |

post-commit hook을 설치하면 커밋할 때마다 `capture-commit`이 자동 실행됩니다.

`capture-session` 옵션:
```bash
--from-repo            # git 스냅샷(브랜치/커밋/변경 파일) 포함
--from-agent           # Claude Code가 세션 요약을 작성해야 한다는 신호
--summary-file <path>  # AI 요약 파일을 노트 본문에 삽입
```

### Distill — 정제 후보 생성 (LLM 필요)

| 명령 | 설명 |
| --- | --- |
| `distill-today` | 오늘 Inbox 기록을 읽어 `60_Candidates/`에 정제 후보 생성 |
| `suggest-knowledge` | 후보 중 지식 노트로 승격할 항목 제안 |
| `suggest-blog-topics` | 후보 중 블로그 주제 제안 |
| `suggest-memory-patch` | `40_AgentMemory` 갱신 제안 |
| `build-context "주제"` | 주제별 ContextPack 구성 (디버그·확인용) |

### Candidates 관리

| 명령 | 설명 |
| --- | --- |
| `list-candidates` | `60_Candidates/` 목록 출력 |
| `preview-candidate <path>` | 후보 내용 미리보기 |
| `promote-candidate <path>` | 후보를 `20_Knowledge/`에 확정 |
| `apply-memory-patch <path>` | 후보를 `40_AgentMemory/`에 반영 |

### Wiki (LLM 필요)

| 명령 | 설명 |
| --- | --- |
| `wiki-ingest` | 볼트 소스를 읽어 `60_Wiki/` 페이지 생성·갱신 |
| `wiki-query "질문"` | Wiki 탐색 후 답변 생성 |
| `wiki-lint` | Wiki 건강 상태 점검 |

### 출력 — 블로그 (LLM 필요, Vault 기반)

| 명령 | 설명 |
| --- | --- |
| `write-blog "주제"` | ContextPack → `50_Outputs/Blog/Drafts/`에 초안 저장 |
| `revise-blog <path>` | 기존 블로그 초안 다듬기 |
| `publish-ready <path>` | 초안 상태를 review로 변경 |
| `suggest-topics` | 블로그 주제 추천 |
| `write-draft "주제"` | 초안 생성 (Vault 저장) |
| `list` | 저장된 블로그 초안 목록 |
| `preview [slug]` | 초안 미리보기 |
| `export-tistory [slug]` | 티스토리 포맷으로 변환 |
| `publish-done <url>` | 게시 완료 기록 |

### 출력 — 개인 문서 (LLM 필요, Vault 기반)

| 명령 | 설명 |
| --- | --- |
| `worklog` | `00_Inbox + 10_Worklog`를 읽어 작업 회고 → `10_Worklog/Summaries/` |
| `todo` | 위와 같은 소스로 다음 할 일 제안 → `50_Outputs/Todo/` |
| `resume` | `40_AgentMemory + 30_Projects`를 읽어 이력서 초안 → `50_Outputs/Resume/` |
| `portfolio` | 위와 같은 소스로 포트폴리오 초안 → `50_Outputs/Portfolio/` |
| `summarize-project <name>` | 특정 프로젝트 요약 생성 |
| `portfolio-draft <name>` | 프로젝트별 포트폴리오 초안 |
| `interview-questions <name>` | 프로젝트 기록 기반 예상 면접 질문 생성 |

### 자동화 · 봇

| 명령 | 설명 |
| --- | --- |
| `serve-bot` | 텔레그램 봇 실행 (자연어/명령 양방향) |
| `push-digest` | 주제 추천+회고를 메신저로 푸시 |
| `ask "..."` | 자연어 문장을 해석해 알맞은 명령 실행 |

---

## Obsidian 볼트 구조

`init-vault`가 만드는 기본 구조입니다.

```text
<vault>/
├─ 00_Inbox/         # capture로 쌓이는 원시 기록 (에이전트 쓰기 가능)
│  ├─ Captures/      #   capture 메모
│  └─ Chats/         #   capture-chat 대화 파일
├─ 10_Worklog/       # 작업 흔적 정리
│  ├─ Daily/         #   capture-session, daily-log
│  ├─ GitSummaries/  #   capture-commit (hook 자동)
│  └─ Summaries/     #   worklog 출력
├─ 20_Knowledge/     # 정제·확정된 지식 (promote-candidate 목적지)
├─ 30_Projects/      # 프로젝트별 Context.md + 노트
├─ 40_AgentMemory/   # CareerContext, Profile, ProjectMap 등 에이전트 메모리
├─ 50_Outputs/       # 최종 출력물
│  ├─ Blog/          #   write-blog 결과
│  ├─ Portfolio/
│  ├─ Resume/
│  ├─ Todo/
│  └─ Interview/
├─ 60_Candidates/    # distill 후보 — 검토 전 임시 영역
├─ 60_Wiki/          # wiki-ingest 결과
├─ 90_Templates/     # 노트 템플릿
├─ index.md          # index-vault가 자동 갱신
└─ log.md            # 에이전트 작업 로그
```

**쓰기 가능 영역**: `00_Inbox/`, `10_Worklog/`, `50_Outputs/`, `60_Candidates/`  
**보호 영역** (Candidates·패치 경유): `20_Knowledge/`, `40_AgentMemory/Core/`, `30_Projects/*/Context.md`

---

## LLM 라우팅

두 종류의 LLM을 용도별로 분리합니다.

| 역할 | 설정 | 기본값 |
| --- | --- | --- |
| 분류·라우팅 (빠른 로컬) | `LOCAL_LLM_PROVIDER=ollama` + `OLLAMA_MODEL` | qwen3:8b |
| 글쓰기 (품질 우선) | `WRITER_PROVIDER=gemini` + `GEMINI_API_KEY` | gemini-2.5-flash |

로컬 LLM 미사용 시 `GEMINI_LITE_MODEL`(gemini-2.5-flash-lite)로 자동 폴백합니다.  
Gemini는 `google-generativeai` 패키지 없이 httpx REST로 호출합니다.

---

## 텔레그램 봇

```env
MESSENGER_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<BotFather에서 발급>
TELEGRAM_ALLOWED_CHAT_IDS=<본인 chat id>
TELEGRAM_CHAT_ID=<알림 받을 chat id>
```

```bash
work-agent serve-bot
```

슬래시 명령과 자유 문장 양방향 지원 (LLM 설정 시 자연어, 미설정 시 슬래시만).

```
/capture <메모>    /search <검색어>    /distill
/draft <주제>      /candidates         /context <주제>
/session <프로젝트>  /worklog           /todo
```

---

## 프로젝트 구조

```text
app/
├─ cli.py              # 진입점 (얇게)
├─ config.py           # .env 설정
├─ agents/             # CaptureAgent, DistillAgent, WikiAgent, WikiBlogAgent
│                      # CuratorAgent, ProjectAgent
│                      # WorklogAgent, TodoAgent, PortfolioAgent, ResumeAgent
├─ memory/             # AgentMemoryLoader, ProjectMemoryLoader, ContextPackBuilder
├─ services/           # WikiService, CandidateWriter, RepoSnapshot ...
├─ llm/                # factory(라우팅), GeminiProvider, ollama, openai_compatible
├─ content_sources/    # obsidian / git / local_doc + collector
├─ messaging/          # telegram, router, bot
├─ assistant/          # 자연어 의도 라우팅
├─ models/             # ContextPack, SourceChunk
└─ prompts/*.md        # LLM 프롬프트 (코드 분리)

scripts/hooks/post-commit   # git hook 템플릿
start.py / start.ps1        # 볼트 상태 대시보드 + 환경 시작
```

---

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Vault/LLM/메신저 모두 fake/mock으로 분리되어 키 없이 실행됩니다.
