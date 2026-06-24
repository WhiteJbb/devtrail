# work-agent 구현 현황 보고

> 기준일: 2026-06-24

---

## 전체 파이프라인 상태

```
[ Capture ] → [ Distill ] → [ Curate ] → [ Generate ] → [ Deliver ]
   ✅ 완료       ✅ 완료       ✅ 완료       ✅ 완료        ✅ 완료
```

---

## 기능별 현황

### Capture (원본 기록)

| 기능 | 상태 | 비고 |
|------|------|------|
| `capture` 텍스트 메모 | ✅ | `00_Inbox/Captures/` |
| `capture-commit` git hook 자동 실행 | ✅ | post-commit hook, LLM 요약 포함 |
| `capture-session` AI 세션 요약 | ✅ | `--from-agent`, `--summary-file` |
| `daily-log` 데일리 로그 | ✅ | `--from-agent` 컨텍스트 자동 채움 |
| Telegram 음성/이미지/URL 캡처 | ✅ | 미디어 핸들러, STT |

### Distill (LLM 후보 생성)

| 기능 | 상태 | 비고 |
|------|------|------|
| `distill-today` 오늘 전체 후보 생성 | ✅ | Knowledge / Decisions / MemPatches / BlogIdeas |
| `suggest-knowledge` | ✅ | |
| `suggest-blog-topics` | ✅ | 선별 기준 강화 (독자 중심) |
| `suggest-career-bullets` | ✅ | |
| `suggest-memory-patch` / `update-open-loops` | ✅ | |
| `build-context` ContextPack 구성 | ✅ | AgentMemory + Projects + 관련 노트 |
| wikilink 자동 주입 (`_inject_related_links`) | ✅ | related 없어도 placeholder 교체 |
| task_type 적정성 | ⚠️ | distill이 `light` 사용 중 — `writer`로 변경 검토 필요 |

### Curate (후보 관리)

| 기능 | 상태 | 비고 |
|------|------|------|
| `list-candidates` (stale 표시) | ✅ | 3일 이상 경과 시 stale 마킹 |
| `promote-candidate` | ✅ | `20_Knowledge/`, `30_Projects/`, etc. |
| `promote-all [--kind]` | ✅ | 타입별 일괄 승격 |
| `apply-memory-patch` | ✅ | `40_AgentMemory/` 반영 |
| `preview-candidate` | ✅ | |
| 중복 후보 dedup | ✅ | 14일 내 유사도 0.85 이상 병합 |

### Generate (결과물 생성)

| 기능 | 상태 | 비고 |
|------|------|------|
| `write-blog` | ✅ | ContextPack 기반, wikilink 포함 |
| `revise-blog` | ✅ | polish chain |
| `publish-ready` / `publish-done` | ✅ | 상태 관리 |
| `export-tistory` | ✅ | HTML/MD 변환 |
| `worklog` | ✅ | |
| `todo` | ✅ | |
| `portfolio` / `portfolio-draft` | ✅ | |
| `resume` | ✅ | |
| `summarize-project` / `interview-questions` | ✅ | |

### Deliver (자동화·전송)

| 기능 | 상태 | 비고 |
|------|------|------|
| `nightly-distill` (23:30 자동) | ✅ | distill + career-bullets + digest + Telegram |
| `weekly-distill` (일요일 00:00) | ⚠️ | E2E 테스트 미완 — smoke test만 |
| `push-digest` Telegram 수동 전송 | ✅ | |
| `serve-bot` Telegram 봇 | ✅ | 자연어 의도 분류, 확인 후 실행 |
| `ask` 자연어 CLI | ✅ | |
| 봇 도움말 2단계 구성 | ✅ | 매일/가끔 빈도별 분리 |

### 자동화 스크립트

| 스크립트 | 상태 | 비고 |
|----------|------|------|
| `sync-vault.ps1` vault git 동기화 | ✅ | AI 폴더 + log.md 추적 |
| `update-work-agent.ps1` 자동 업데이트 | ✅ | bot 먼저 종료 후 pip install |
| `run-nightly-safe.ps1` | ✅ | lock 파일, Telegram 오류 알림 |
| `run-weekly-safe.ps1` | ✅ | |
| `run-bot-service.ps1` | ✅ | SYSTEM 계정, 로그인 불필요 |
| `register-schedules.ps1` | ✅ | Task Scheduler 자동 등록 |

---

## LLM 지원 현황

| Provider | task_type | 상태 |
|----------|-----------|------|
| Gemini Flash-Lite | light | ✅ |
| Gemini Flash | writer | ✅ |
| Kimi (Moonshot) | long_writer | ✅ |
| OpenAI / GPT-4o mini | polish, fallback | ✅ |
| Ollama (local) | local | ✅ |
| Fallback chain 자동 전환 | 전체 | ✅ |

---

## 알려진 이슈 & 다음 할 일

| 항목 | 우선순위 | 설명 |
|------|----------|------|
| `distill_agent` task_type 변경 | 중 | `light` → `writer` (Gemini Flash) — 품질 향상, 쿼터 소진 tradeoff |
| `weekly-distill` E2E 테스트 | 중 | 실 데이터로 출력 품질 확인 필요 |
| Worklog raw 파일 보존 정책 | 낮 | distilled 마킹 + 30일 후 cleanup-worklogs 커맨드 (설계 합의, 미구현) |
| Vault 서버-로컬 동시 push 충돌 | 낮 | sync-vault rebase 충돌 시 재시도 로직 없음 |
| `40_AgentMemory/Core/` 비어있음 | 높 | AI 맥락 없이 동작 중 — Context.md 수동 작성 필요 |
| Notion 마이그레이션 | 낮 | 파일명 정리 스크립트 + frontmatter 추가 |

---

## 테스트 현황

- 단위 테스트: 모든 외부 의존성 mock (LLM, Vault, Telegram)
- API 키·vault 없이 실행 가능
- E2E (실제 vault + LLM): 수동 검증 단계
