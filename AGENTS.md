# AGENTS.md

이 저장소의 중심은 BlogAgent가 아니라 Obsidian 기반 LLM Wiki Core다.

```text
Obsidian Vault = 공용 메모리 버스
LLM Wiki Core = 지식 순환 엔진
BlogAgent = Wiki Core를 사용하는 Output Agent
```

기존 BlogAgent, Worklog/Todo/Portfolio/Resume Agent, Notion, Telegram, Tistory export 구현은 삭제하지 않는다. 새 구조는 기존 기능 위에 병존시키고, 이후 단계에서 내부 흐름을 Wiki Core 중심으로 옮긴다.

## 설계 원칙

- CLI, Telegram, 자연어 `ask`는 얇은 입구로 유지한다.
- 비즈니스 로직은 agents/services/content_sources/repositories/storage 계층에 둔다.
- LLM 호출과 파일 시스템/비즈니스 로직을 분리한다.
- LLM 미설정 상태에서 가짜 결과를 만들지 않는다.
- Notion은 legacy optional로 유지한다.
- source_refs 없는 블로그 초안 생성을 피한다.
- `20_Knowledge/`, `40_AgentMemory/Core/`, `30_Projects/*/Context.md`는 직접 덮어쓰지 않고 candidate/patch 흐름을 거친다.

## Phase 1-4 범위

- `README.md`, `.env.example`, 프로젝트 메타데이터는 Obsidian LLM Wiki Core 중심으로 유지한다.
- `work-agent init-vault`는 vault 기본 구조, `index.md`, `log.md`, vault용 `AGENTS.md`, AgentMemory 기본 파일, 템플릿을 만든다.
- `work-agent index-vault`는 Markdown, YAML frontmatter, wiki link, tag를 읽어 root `index.md`를 갱신한다.
- `work-agent search`는 LLM 없이 동작하는 keyword search를 제공한다.
- `work-agent capture`, `capture-chat`, `capture-commit`, `daily-log`는 원본 기록을 `00_Inbox/` 또는 `10_Worklog/` 아래에 저장하고 root `log.md`에 append한다.

## 테스트

외부 LLM/Notion/Telegram 네트워크 호출은 단위 테스트에서 실제로 나가지 않게 한다.

```bash
.venv\Scripts\python.exe -m pytest -q
```

Windows에서 기본 temp 권한 문제가 있으면 workspace 아래 임시 디렉터리를 `TMP`/`TEMP`로 지정하고 실행한다.
