"""테스트 공용 fixture/헬퍼."""

import errno
import os

import pytest

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


class DenyAccess:
    """POSIX 디렉터리 권한의 의미를 OS 호출 단계(os.scandir·os.listdir·os.stat·os.lstat)에서 재현한다.

    실제 chmod는 root에서 무시되고 플랫폼마다 의미가 달라 테스트가 아무것도 검증하지 않게 될 수 있다. 이 대역은
    실행 사용자·플랫폼과 무관하게 같은 PermissionError(EACCES)를 낸다. 구현이 glob·iterdir·scandir·walk 중 무엇을
    쓰든 결국 이 호출을 거치므로 특정 구현에 묶이지 않는다. 파일 열기(open)는 가로채지 않는다 — 막은 경로는 열기 전에
    stat에서 먼저 실패한다(실제 권한에서도 같다).

    - none(rel): 모드 000 폴더 — 목록과 그 아래 모든 경로의 stat·목록이 거부된다
    - no_exec(rel): 모드 r-- 폴더 — 목록은 되지만 그 아래 경로의 stat·목록이 거부된다
    - stat(rel): 경로 하나의 stat만 거부된다
    """

    def __init__(self, monkeypatch, root):
        self.root = root
        self._none: set[str] = set()
        self._no_exec: set[str] = set()
        self._stat: set[str] = set()
        self.hits: list[tuple[str, str]] = []  # (호출, 경로) — 재현이 실제로 일어났는지 테스트가 확인한다
        real = {name: getattr(os, name) for name in ("scandir", "listdir", "stat", "lstat")}

        def norm(path) -> str | None:
            if isinstance(path, int):
                return None
            return os.path.abspath(os.fsdecode(os.fspath(path)))

        def below(p: str, dirs: set[str]) -> bool:
            return any(p.startswith(d + os.sep) for d in dirs)

        def deny(call: str, p: str):
            self.hits.append((call, p))
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), p)

        def listing(name):
            def fake(path="."):
                p = norm(path)
                if p is not None and (p in self._none or below(p, self._none | self._no_exec)):
                    deny(name, p)
                return real[name](path)
            return fake

        def stat(name):
            def fake(path, *args, **kwargs):
                p = norm(path)
                if p is not None and (p in self._stat or below(p, self._none | self._no_exec)):
                    deny(name, p)
                return real[name](path, *args, **kwargs)
            return fake

        for name in ("scandir", "listdir"):
            monkeypatch.setattr(os, name, listing(name))
        for name in ("stat", "lstat"):
            monkeypatch.setattr(os, name, stat(name))

    def _abs(self, rel: str) -> str:
        return os.path.abspath(os.path.join(self.root, rel))

    def none(self, rel: str) -> None:
        self._none.add(self._abs(rel))

    def no_exec(self, rel: str) -> None:
        self._no_exec.add(self._abs(rel))

    def stat(self, rel: str) -> None:
        self._stat.add(self._abs(rel))

    def clear(self) -> None:
        self._none.clear()
        self._no_exec.clear()
        self._stat.clear()


@pytest.fixture()
def deny_access(monkeypatch, tmp_path):
    return DenyAccess(monkeypatch, tmp_path)
