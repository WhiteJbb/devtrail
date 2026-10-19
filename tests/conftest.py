"""테스트 공용 fixture/헬퍼."""

from app.models import SourceChunk


class FakeLLM:
    """고정 응답을 돌려주는 LLM provider 대역."""

    name = "fake"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.last_prompt = ""
        self.last_system = ""
        self.prompts: list[str] = []  # 호출 순서대로 누적 (critic 등 다단계 검증용)

    def complete(self, prompt: str, system: str = "") -> str:
        self.last_prompt = prompt
        self.last_system = system
        self.prompts.append(prompt)
        return self.response


class FakeSource:
    name = "fake"

    def __init__(self, chunks):
        self._chunks = chunks

    def fetch(self):
        return self._chunks


def sample_chunks():
    return [
        SourceChunk(source_type="worklog", ref="w", title="worklog", text="환경 분리 작업"),
        SourceChunk(source_type="git", ref="abc123", title="commit", text="분리 커밋"),
    ]


class MemoCapture:
    """옛 `CaptureAgent.capture`(00_Inbox/Memos 메모) 대역 — 기능은 2026-10-19 제거됐지만
    distill 테스트는 '오늘 raw 노트 하나'가 필요하다."""

    def __init__(self, settings, now=None):
        from pathlib import Path

        self.vault_dir = Path(settings.obsidian_vault_root)
        self.now = now

    def capture(self, text: str, project: str = "", source: str = "manual"):
        from datetime import datetime

        import frontmatter

        from app.agents.capture_agent import CaptureResult

        now = self.now or datetime.now()
        rel_path = f"00_Inbox/Memos/{now.strftime('%Y%m%d-%H%M%S')}-{project or 'memo'}.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            f"# Capture - {project}\n\n{text.strip()}\n",
            type="capture", date=now.strftime("%Y-%m-%d"), project=project, source=source, status="raw", tags=[],
        )
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return CaptureResult(path=path, rel_path=rel_path, created=True, kind="capture")
