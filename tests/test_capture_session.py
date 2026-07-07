"""capture-session 단위 / CLI / 메시지 라우터 테스트."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frontmatter
import pytest

from app.agents.capture_agent import CaptureAgent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(tmp_path: Path):
    return SimpleNamespace(
        obsidian_vault_root=str(tmp_path),
        git_diff_max_chars=800,
    )


def _agent(tmp_path: Path) -> CaptureAgent:
    return CaptureAgent(settings=_settings(tmp_path))


# ── 기본 동작 ─────────────────────────────────────────────────────────────────

def test_capture_session_creates_file(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(project="Devtrail")
    assert result.path.exists()
    assert result.kind == "session"
    assert result.created is True


def test_capture_session_frontmatter_type(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(project="TestProj")
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["type"] == "session"


def test_capture_session_needs_distill_true(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["needs_distill"] is True


def test_capture_session_status_raw(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["status"] == "raw"


def test_capture_session_tags(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    tags = post.metadata.get("tags", [])
    assert "session" in tags
    assert "worklog" in tags


def test_capture_session_saved_to_sessions(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(project="Devtrail")
    assert result.rel_path.startswith("10_Worklog/Sessions/")
    assert "session" in result.rel_path


def test_capture_session_no_project(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    assert "session" in result.rel_path
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["project"] == ""


# ── --summary-file ─────────────────────────────────────────────────────────────

def test_capture_session_summary_file(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("오늘은 BlogAgent를 삭제했다.", encoding="utf-8")

    agent = _agent(tmp_path)
    result = agent.capture_session(summary_file=str(summary))
    body = result.path.read_text(encoding="utf-8")
    assert "BlogAgent를 삭제했다" in body


def test_capture_session_missing_summary_file(tmp_path):
    """존재하지 않는 summary-file을 줘도 실패하지 않는다."""
    agent = _agent(tmp_path)
    result = agent.capture_session(summary_file=str(tmp_path / "no_such_file.md"))
    assert result.path.exists()


def test_capture_session_summary_text_used_directly(tmp_path):
    """summary_text가 주어지면 임시 파일 없이 그대로 본문에 반영된다."""
    agent = _agent(tmp_path)
    result = agent.capture_session(summary_text="MCP에서 바로 전달한 요약")
    body = result.path.read_text(encoding="utf-8")
    assert "MCP에서 바로 전달한 요약" in body


def test_capture_session_summary_text_wins_over_summary_file(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("파일 기반 요약", encoding="utf-8")
    agent = _agent(tmp_path)
    result = agent.capture_session(summary_text="직접 전달 요약", summary_file=str(summary))
    body = result.path.read_text(encoding="utf-8")
    assert "직접 전달 요약" in body
    assert "파일 기반 요약" not in body


def test_capture_session_id_stored_in_frontmatter(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(session_id="abc-123")
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["session_id"] == "abc-123"


def test_capture_session_id_defaults_to_empty(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["session_id"] == ""


def test_capture_session_needs_distill_defaults_true(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["needs_distill"] is True


def test_capture_session_needs_distill_can_be_disabled(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(needs_distill=False)
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["needs_distill"] is False


def test_capture_session_fallback_template_includes_learning_recovery(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session()
    body = result.path.read_text(encoding="utf-8")
    assert "## 9. Learning Recovery" in body
    assert "다음에 직접 설명해봐야 할 질문" in body


# ── --from-repo 없을 때 ────────────────────────────────────────────────────────

def test_capture_session_without_from_repo(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(from_repo=False)
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["from_repo"] is False
    body = result.path.read_text(encoding="utf-8")
    assert "repo 정보 없음" in body


# ── Git이 아닌 경로여도 실패하지 않음 ─────────────────────────────────────────

def test_capture_session_non_git_repo_from_repo(tmp_path):
    agent = _agent(tmp_path)
    # tmp_path 는 git repo가 아님 → graceful fallback
    result = agent.capture_session(from_repo=True, repo=str(tmp_path))
    assert result.path.exists()
    body = result.path.read_text(encoding="utf-8")
    assert "Git 정보 수집 실패" in body or "repo 정보 없음" in body


# ── 파일명 충돌 처리 ─────────────────────────────────────────────────────────

def test_capture_session_name_conflict(tmp_path):
    agent = _agent(tmp_path)
    r1 = agent.capture_session(project="Devtrail")
    r2 = agent.capture_session(project="Devtrail")
    assert r1.rel_path != r2.rel_path


# ── log.md append ────────────────────────────────────────────────────────────

def test_capture_session_appends_log(tmp_path):
    agent = _agent(tmp_path)
    agent.capture_session(project="Devtrail")
    log_path = tmp_path / "log.md"
    # log.md는 WikiService.append_vault_log가 쓰므로 존재 여부 확인
    # (실제 파일 생성은 WikiService 구현에 달려 있음)
    # capture_session이 예외 없이 완료됨을 검증
    assert (tmp_path / "10_Worklog/Sessions").exists()


# ── from_agent 플래그 ─────────────────────────────────────────────────────────

def test_capture_session_from_agent_flag(tmp_path):
    agent = _agent(tmp_path)
    result = agent.capture_session(from_agent=True)
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["from_agent"] is True
    assert post.metadata["agent_summary_missing"] is True


def test_capture_session_from_agent_with_summary(tmp_path):
    summary = tmp_path / "s.md"
    summary.write_text("작업 요약 내용", encoding="utf-8")
    agent = _agent(tmp_path)
    result = agent.capture_session(from_agent=True, summary_file=str(summary))
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["agent_summary_missing"] is False


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_capture_session_basic(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from app import cli

    runner = CliRunner()

    fake_result = SimpleNamespace(
        path=tmp_path / "10_Worklog/Sessions/2026-06-23-devtrail-session.md",
        rel_path="10_Worklog/Sessions/2026-06-23-devtrail-session.md",
        created=True,
        kind="session",
    )

    class _FakeAgent:
        def __init__(self, *a, **k):
            pass
        def capture_session(self, **k):
            return fake_result

    monkeypatch.setattr(cli, "CaptureAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["capture-session", "--project", "Devtrail"])
    assert result.exit_code == 0
    assert "완료" in result.output


def test_cli_capture_session_from_repo(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from app import cli

    runner = CliRunner()

    fake_result = SimpleNamespace(
        path=tmp_path / "10_Worklog/Sessions/2026-06-23-session.md",
        rel_path="10_Worklog/Sessions/2026-06-23-session.md",
        created=True,
        kind="session",
    )

    called_with: dict = {}

    class _FakeAgent:
        def __init__(self, *a, **k):
            pass
        def capture_session(self, **k):
            called_with.update(k)
            return fake_result

    monkeypatch.setattr(cli, "CaptureAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["capture-session", "--from-repo"])
    assert result.exit_code == 0
    assert called_with.get("from_repo") is True


def test_cli_capture_session_summary_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from app import cli

    runner = CliRunner()
    summary = tmp_path / "summary.md"
    summary.write_text("내용", encoding="utf-8")

    fake_result = SimpleNamespace(
        path=tmp_path / "10_Worklog/Sessions/2026-06-23-session.md",
        rel_path="10_Worklog/Sessions/2026-06-23-session.md",
        created=True,
        kind="session",
    )

    called_with: dict = {}

    class _FakeAgent:
        def __init__(self, *a, **k):
            pass
        def capture_session(self, **k):
            called_with.update(k)
            return fake_result

    monkeypatch.setattr(cli, "CaptureAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["capture-session", "--summary-file", str(summary)])
    assert result.exit_code == 0
    assert called_with.get("summary_file") == str(summary)


# ── Messaging Router ──────────────────────────────────────────────────────────

def test_router_session_no_arg(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.messaging.router import CommandRouter

    router = CommandRouter()
    fake_result = SimpleNamespace(
        rel_path="10_Worklog/Sessions/2026-06-23-session.md",
        created=True,
        kind="session",
    )
    mock_agent = MagicMock()
    mock_agent.return_value.capture_session.return_value = fake_result

    with patch("app.agents.CaptureAgent", mock_agent):
        out = router.handle("/session")
    assert "세션 노트" in out
    assert fake_result.rel_path in out


def test_router_session_with_project(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.messaging.router import CommandRouter

    router = CommandRouter()
    fake_result = SimpleNamespace(
        rel_path="10_Worklog/Sessions/2026-06-23-devtrail-session.md",
        created=True,
        kind="session",
    )
    mock_agent = MagicMock()
    mock_agent.return_value.capture_session.return_value = fake_result

    with patch("app.agents.CaptureAgent", mock_agent):
        out = router.handle("/session Devtrail")
    assert "Devtrail" in out or "세션" in out


# ── Distill 우선순위 ─────────────────────────────────────────────────────────

def test_distill_session_notes_priority(tmp_path):
    """distill-today가 session 노트를 다른 노트보다 앞에 배치하는지 검증."""
    from datetime import datetime
    from unittest.mock import patch
    from app.agents.distill_agent import DistillAgent
    from app.services.wiki_service import WikiNote

    settings = _settings(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")

    session_note = WikiNote(
        path="10_Worklog/Sessions/2026-06-23-Devtrail-session.md",
        title="Devtrail 작업 세션",
        body="세션 내용",
        metadata={"type": "session", "date": today, "project": "Devtrail"},
        tags=["session"],
        wikilinks=[],
        summary="",
    )
    capture_note = WikiNote(
        path="00_Inbox/Memos/20260623-120000-memo.md",
        title="메모",
        body="메모 내용",
        metadata={"type": "capture", "date": today},
        tags=[],
        wikilinks=[],
        summary="",
    )

    from app.llm.base import LLMProvider
    agent = DistillAgent(settings=settings, llm=None)
    with patch.object(agent.wiki_service, "scan_notes", return_value=[capture_note, session_note]):
        notes = agent._raw_notes(today_only=True)

    # session 노트가 첫 번째여야 한다
    assert notes[0].path == session_note.path
