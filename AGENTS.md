# AGENTS.md

이 저장소의 중심은 Obsidian 기반 LLM Wiki Core다.

```text
Obsidian Vault  = 공용 메모리 버스
LLM Wiki Core   = 지식 순환 엔진
WikiBlogAgent   = Wiki Core를 사용하는 Output Agent
```

Phase 1-9 구현 완료. Worklog/Todo/Portfolio/Resume Agent, Telegram, Tistory export 포함.

## 설계 원칙

- CLI, Telegram, 자연어 `ask`는 얇은 입구로 유지한다.
- 비즈니스 로직은 agents / services / content_sources / repositories / storage 계층에 둔다.
- LLM 호출과 파일 시스템/비즈니스 로직을 분리한다.
- LLM 미설정 상태에서 가짜 결과를 만들지 않는다.
- Notion은 legacy optional로 유지한다.
- `source_refs` 없는 블로그 초안 생성을 피한다.
- `20_Knowledge/`, `40_AgentMemory/Core/`, `30_Projects/*/Context.md`는 직접 덮어쓰지 않고 candidate/patch 흐름을 거친다.

## 계층 구조

```
CLI / Telegram / ask (자연어)
        │
   Agent 계층          — 사용자 요청 단위 오케스트레이터
        │
   Service 계층        — WikiService, CandidateWriter, DraftGenerator, ...
        │
Content Source 계층    — ObsidianSource, GitSource, NotionSource, LocalDocSource
        │
  LLM Provider         — Local(Ollama/OpenAI) 분류 · Gemini Flash/Pro 글쓰기
        │
   Obsidian Vault      — 메모리 버스 (모든 Agent가 같은 Vault 참조)
```

## Agent 목록

| Agent | 역할 | 입력 | 출력 경로 |
|---|---|---|---|
| `CaptureAgent` | 메모/대화/커밋/미디어/URL → Vault raw 저장 | 텍스트/파일/git repo/voice/image | `00_Inbox/`, `10_Worklog/` |
| `DistillAgent` | raw 기록 → 정제 후보 생성 (LLM) | `00_Inbox/` + `10_Worklog/` | `60_Candidates/` |
| `NightlyDistillAgent` | 하루 전체 정제 + career bullet + digest 생성 | 모든 당일 raw 기록 | `60_Candidates/` + `50_Outputs/Digest/` |
| `CareerBulletAgent` | 이력서/포트폴리오 bullet 후보 추출 | `10_Worklog/` + `00_Inbox/` | `60_Candidates/CareerBullets/` |
| `OpenLoopsAgent` | 미해결 이슈 분석 → Open Loops 패치 후보 | `10_Worklog/` + `00_Inbox/` + `40_AgentMemory/05_OpenLoops.md` | `60_Candidates/MemoryPatches/` |
| `CuratorAgent` | 후보 관리 (조회/승격/패치) | `60_Candidates/` | `20_Knowledge/`, `40_AgentMemory/` |
| `WikiAgent` | Wiki ingest / query / lint | Vault + prompts | `60_Wiki/` |
| `WikiBlogAgent` | ContextPack → 블로그 초안 | ContextPack | `50_Outputs/Blog/Drafts/` |
| `WorklogAgent` | 작업 회고 생성 | `00_Inbox/` + `10_Worklog/` | `10_Worklog/Summaries/` |
| `TodoAgent` | 다음 할 일 제안 | 최근 raw 기록 | `50_Outputs/Todo/` |
| `PortfolioAgent` | 포트폴리오 초안 | AgentMemory + Projects | `50_Outputs/Portfolio/` |
| `ResumeAgent` | 이력서/자기소개서 초안 | AgentMemory + Projects | `50_Outputs/Resume/` |
| `ProjectAgent` | 프로젝트 요약 / 포폴 / 면접 질문 | Context + Project | `50_Outputs/` |

## CLI 커맨드

### Vault 관리
```bash
work-agent init-vault              # Vault 기본 구조 + index.md + log.md 생성
work-agent index-vault             # Markdown 읽어 root index.md 갱신
work-agent install-hooks <repo>    # git post-commit hook 설치
work-agent search "검색어"         # 키워드 검색 (LLM 불필요)
work-agent related <path>          # 태그/wikilink 기반 관련 노트 탐색
```

### Capture — raw 기록 저장
```bash
work-agent capture "메모"                                   # → 00_Inbox/Captures/
work-agent capture-commit --repo <path>                    # → 10_Worklog/GitSummaries/
work-agent daily-log                                       # → 10_Worklog/Daily/
work-agent capture-session --project WorkAgent             # → 10_Worklog/Daily/ (세션 단위)
work-agent capture-session --project WorkAgent --from-repo                # git 스냅샷 포함
work-agent capture-session --project WorkAgent --from-repo --from-agent  # AI 세션 요약 신호
work-agent capture-session --project WorkAgent --summary-file ./s.md     # AI 요약 파일 삽입
```

### Distill — 정제 후보 생성 (LLM 필요)
```bash
work-agent distill-today           # Inbox → 60_Candidates/ 일괄 생성
work-agent suggest-knowledge       # Knowledge 후보 제안
work-agent suggest-blog-topics     # BlogIdea 후보 제안
work-agent suggest-memory-patch    # AgentMemory 패치 제안
work-agent build-context "주제"    # 주제별 ContextPack 생성
```

### Candidate 관리
```bash
work-agent list-candidates              # 60_Candidates/ 목록
work-agent preview-candidate <path>     # 후보 미리보기
work-agent promote-candidate <path>     # → 20_Knowledge/ 승격
work-agent apply-memory-patch <path>    # → 40_AgentMemory/ 반영
```

### Wiki
```bash
work-agent wiki-ingest [--folder <path>]    # Vault 소스 읽어 wiki 페이지 생성
work-agent wiki-query "질문" [--save path]  # Wiki 탐색 후 답변
work-agent wiki-lint                        # Wiki 건강 상태 점검
```

### 블로그 (Vault 기반)
```bash
work-agent write-blog "주제"        # ContextPack → 초안 → 50_Outputs/Blog/Drafts/
work-agent revise-blog <vault_path> # Vault 블로그 초안 다듬기
work-agent publish-ready <path>     # 초안 상태 → review
work-agent suggest-topics           # 주제 추천
```

### 개인 문서
```bash
work-agent worklog                         # 작업 회고
work-agent todo                            # 다음 할 일 제안
work-agent resume                          # 이력서/자기소개서
work-agent portfolio                       # 포트폴리오
work-agent summarize-project <project>     # 프로젝트 요약
work-agent portfolio-draft <project>       # 프로젝트별 포폴 초안
work-agent interview-questions <project>   # 면접 질문 초안
```

### 자동화 & 봇
```bash
work-agent serve-bot               # Telegram 봇 실행 (voice/image/URL 캡처 포함)
work-agent push-digest             # BlogIdea 목록 메신저 전송
work-agent push-digest --daily     # 오늘 전 카테고리 요약 전송
work-agent push-digest --weekly    # 최근 7일 요약 전송
work-agent push-digest --worklog   # 작업 회고도 함께 전송
work-agent ask "자연어"            # 의도 분류 후 커맨드 실행
```

### Phase 2 자동화
```bash
work-agent nightly-distill                        # 하루 raw 기록 종합 정제 + daily digest 생성
work-agent suggest-career-bullets                 # 이력서/포트폴리오 bullet 후보 생성
work-agent suggest-career-bullets --project WorkAgent   # 특정 프로젝트 필터
work-agent update-open-loops                      # Open Loops MemoryPatch 후보 생성
work-agent print-schedule --windows              # Windows schtasks 등록 명령 출력
work-agent print-schedule --cron                 # Linux/Mac crontab 등록 명령 출력
```

**자동화 루프 예시:**
```
[OS 스케줄러 23:30]
  └─ nightly-distill
       ├─ DistillAgent → 60_Candidates/ (Knowledge / Decision / MemPatch / BlogIdea)
       ├─ CareerBulletAgent → 60_Candidates/CareerBullets/
       ├─ 50_Outputs/Digest/{date}-daily-digest.md 저장
       └─ MESSENGER_PROVIDER=telegram이면 digest 자동 전송

[OS 스케줄러 08:30]
  └─ push-digest --daily  (아침에 어제 digest 확인)
```

## 지식 순환 파이프라인

```
Capture → Distill → Promote
```

- **Capture**: 원본 기록을 `00_Inbox/` 또는 `10_Worklog/`에 raw Markdown으로 저장하고 `log.md`에 append
- **Distill**: raw 기록을 LLM으로 읽어 `60_Candidates/` 아래 후보 노트 생성. 공식 영역을 직접 수정하지 않음
- **Promote**: 사람이 검토 후 `promote-candidate` / `apply-memory-patch`로 공식 Knowledge/AgentMemory에 반영

## LLM 라우팅

| 역할 | Provider | 설정 키 |
|---|---|---|
| 분류 / 라우팅 / 간단한 요약 | 로컬 (Ollama / OpenAI compat) → 실패 시 Gemini 폴백 | `LOCAL_LLM_PROVIDER` |
| 글쓰기 / 초안 / 정제 | Gemini Flash | `WRITER_PROVIDER=gemini` |
| 고급 추론 | Gemini Pro | (자동 선택) |

## 브랜치 & PR 워크플로우

큰 기능 추가나 대규모 작업은 브랜치를 분리해서 진행하고 PR로 합친다.

### 언제 브랜치를 파야 하는가

- 새 Agent / 새 CLI 커맨드 추가
- 기존 계층(agents / services / content_sources / repositories / storage) 구조 변경
- Phase 범위에 영향을 주는 설계 변경
- 단일 커밋으로 설명하기 어려운 연속 작업

문서(md 파일 등)만 수정하는 경우는 브랜치 없이 main에서 직접 작업한다.

### 브랜치 네이밍

```
feat/<short-description>      # 새 기능
refactor/<short-description>  # 리팩터링
fix/<short-description>       # 버그 수정
```

### 작업 절차

```bash
# 1. main 최신화 후 브랜치 생성
git checkout main && git pull
git checkout -b feat/<description>

# 2. 작업 & 커밋 (단위가 작을수록 좋음)
git add <files>
git commit -m "feat: ..."

# 3. 테스트 통과 확인
.venv\Scripts\python.exe -m pytest -q

# 4. PR 생성 (GitHub API 직접 호출)
# GITHUB_TOKEN, GITHUB_REPO는 .claude/settings.json env에 설정
curl -s -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/$GITHUB_REPO/pulls \
  -d '{
    "title": "<제목>",
    "head": "<브랜치명>",
    "base": "main",
    "body": "## 변경 요약\n- 항목 1\n\n## 테스트\n- [ ] pytest 통과\n\n## 관련 설계 원칙\n해당 내용 기입"
  }'

# 5. 머지 (PR 번호 확인 후)
curl -s -X PUT \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/$GITHUB_REPO/pulls/<PR번호>/merge \
  -d '{"merge_method": "squash"}'
```

### PR 본문 규칙

- **변경 요약**: 무엇을, 왜 바꿨는지 bullet로 기술
- **테스트**: pytest 결과와 수동 확인 항목 체크리스트
- **관련 설계 원칙**: 이번 작업이 어떤 원칙을 따랐는지 명시
- squash merge를 기본으로 하여 main 히스토리를 단선으로 유지한다
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를 넣지 않는다

## capture-session rule

`work-agent capture-session --from-agent` 명령을 실행할 때 Claude Code / Codex는 다음을 수행한다.

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 변경 파일, 설계 결정, 해결한 문제, 남은 일을 정리한다.
3. 아래 항목을 포함하는 세션 요약 Markdown을 작성한다.
   - 오늘 작업한 내용
   - 변경/추가/삭제된 파일 또는 모듈
   - 해결한 문제나 버그
   - 설계 결정과 그 이유
   - 남은 문제 및 다음 할 일
   - 블로그/포트폴리오 소재가 될 만한 것
4. `--summary-file <임시파일.md>`로 전달하는 것을 권장한다.
5. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 권장 패턴
work-agent capture-session --project WorkAgent --from-repo --from-agent --summary-file ./session-summary.md
```

## 테스트

외부 LLM/Notion/Telegram 네트워크 호출은 단위 테스트에서 실제로 나가지 않게 한다.

```bash
.venv\Scripts\python.exe -m pytest -q
```

Windows에서 기본 temp 권한 문제가 있으면 workspace 아래 임시 디렉터리를 `TMP`/`TEMP`로 지정하고 실행한다.
