# CLAUDE.md

이 프로젝트(work-agent)에서 Claude Code가 따라야 하는 규칙.

## capture-session rule

`work-agent capture-session --from-agent` 명령을 실행할 때:

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 아래 항목을 포함하는 세션 요약 Markdown을 **충분히 자세하게** 작성한다.

### 작성 기준

**오늘 작업한 내용**
- 무엇을 왜 했는지 서술한다. "X를 구현했다"가 아니라 "X가 없어서 Y 문제가 생겼고, Z 방식으로 해결했다" 수준으로.
- 작업 흐름(어떤 순서로 진행됐는지)도 포함한다.

**변경/추가/삭제된 파일 또는 모듈**
- 파일 경로와 함께 변경 이유를 한 줄씩 기록한다.
- 예: `app/config.py` — Notion/workspace dead 필드 제거 (NotionSource가 존재하지 않아 참조 없음)

**해결한 문제나 버그**
- 증상, 원인, 해결 방법을 모두 기록한다. "버그 수정"이 아니라 "어떤 상황에서 왜 발생했고 어떻게 고쳤는지".

**설계 결정과 그 이유**
- 여러 선택지 중 왜 이 방향을 택했는지 근거를 남긴다.
- 나중에 다시 봤을 때 "왜 이렇게 했지?"가 나오지 않을 수준으로.

**남은 문제 및 다음 할 일**
- 미완성 항목, 알려진 이슈, 다음 세션에서 이어갈 것.

**블로그/포트폴리오 소재**
- 이번 작업 중 기술적으로 흥미롭거나 공유 가치가 있는 것. 제목 수준으로라도 남긴다.

3. 요약을 임시 파일로 저장한 뒤 `--summary-file` 옵션으로 전달한다.
4. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 권장 패턴
work-agent capture-session --project <프로젝트명> --from-repo --from-agent --summary-file ./session-summary.md
```

## 브랜치 & PR 규칙

- 새 Agent / CLI 커맨드 / 계층 구조 변경은 반드시 `feat/` 또는 `refactor/` 브랜치에서 작업한다.
- 문서(md 파일)만 수정할 때는 main에서 직접 커밋해도 된다.
- GitHub API는 curl + `GITHUB_TOKEN`으로 호출한다 (`gh` CLI 사용 안 함).
- 커밋 메시지와 PR 본문에 AI 작성 표시(`Co-Authored-By`, `Generated with` 등)를 넣지 않는다.
- squash merge 기본 사용.
