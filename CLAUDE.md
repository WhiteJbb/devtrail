# CLAUDE.md

Claude Code / Codex가 이 저장소에서 작업할 때 따라야 하는 규칙.

## capture-session rule

`work-agent capture-session --from-agent` 명령을 실행할 때:

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 변경 파일, 설계 결정, 해결한 문제, 남은 일을 정리한다.
3. 아래 항목을 포함하는 세션 요약 Markdown을 작성한다.
   - 오늘 작업한 내용
   - 변경/추가/삭제된 파일 또는 모듈
   - 해결한 문제나 버그
   - 설계 결정과 그 이유
   - 남은 문제 및 다음 할 일
   - 블로그/포트폴리오 소재가 될 만한 것
4. `--summary-file <임시파일.md>`로 요약 파일을 먼저 작성한 뒤 CLI에 전달하는 것을 권장한다.
5. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 권장 패턴
work-agent capture-session --project WorkAgent --from-repo --from-agent --summary-file ./session-summary.md
```

## 브랜치 & PR 규칙

- 새 Agent / CLI 커맨드 / 계층 구조 변경은 반드시 `feat/` 또는 `refactor/` 브랜치에서 작업한다.
- 문서(md 파일)만 수정할 때는 main에서 직접 커밋해도 된다.
- GitHub API는 curl + `GITHUB_TOKEN`으로 호출한다 (`gh` CLI 사용 안 함).
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를 넣지 않는다.
- squash merge 기본 사용.
