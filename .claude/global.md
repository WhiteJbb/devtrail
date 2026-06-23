# Global Claude Code Rules
# 새 컴퓨터 설정 시 이 파일 내용을 ~/.claude/CLAUDE.md에 복사한다.

## capture-session rule

`capture-session --from-agent` 플래그가 포함된 명령을 실행할 때:

1. 현재 작업 세션에서 실제로 수행한 일을 되돌아본다.
2. 아래 항목을 포함하는 세션 요약 Markdown 파일을 작성한다.
   - 오늘 작업한 내용
   - 변경/추가/삭제된 파일 또는 모듈
   - 해결한 문제나 버그
   - 설계 결정과 그 이유
   - 남은 문제 및 다음 할 일
   - 블로그/포트폴리오 소재가 될 만한 것
3. 요약을 임시 파일로 저장한 뒤 `--summary-file` 옵션으로 전달한다.
4. 실제로 하지 않은 일은 절대 작성하지 않는다. 불확실하면 `확실하지 않음`으로 표시한다.

```bash
# 실행 패턴
work-agent capture-session --project <프로젝트명> --from-repo --from-agent --summary-file ./session-summary.md
```
