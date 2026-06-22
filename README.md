# Work Agent — Blog Agent MVP

내 실제 작업 흔적(로컬 문서·Git 로그·Notion 메모)을 읽어 기술 블로그 **초안**을 빠르게 만들어 주는 CLI 도구입니다. "완성형 자동 발행기"가 아니라, 70~80점짜리 초안을 만들어 5~10분 다듬어 게시할 수 있게 하는 것이 목표입니다.

> 이 README는 스캐폴드 단계의 초안이며, 전체 사용법/Notion 설정은 이후 단계에서 채워집니다.

## 설치

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
cp .env.example .env   # 필요한 값 채우기 (LLM/Notion 미설정이어도 동작)
```

## CLI (구현 진행 중)

```bash
work-agent suggest-topics
work-agent write-draft "주제"
work-agent preview latest
work-agent sync-notion
```

## 구조

`app/` 아래 계층 분리: `cli` → `agents` → `services` → (`content_sources` / `llm` / `repositories` / `storage` / `notion`). 자세한 내용은 [AGENTS.md](AGENTS.md) 참고.
