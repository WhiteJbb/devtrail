"""app/services/review_question.py + push-digest --daily 복습 질문 노출 테스트 (P6)."""

from __future__ import annotations

from pathlib import Path

from app.services.review_question import pick_review_question


def _write_session(vault: Path, name: str, project: str, body: str) -> Path:
    path = vault / "10_Worklog" / "Sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nproject: {project}\n---\n\n{body}\n", encoding="utf-8")
    return path


_LEARNING_RECOVERY = (
    "## Learning Recovery\n\n"
    "### AI가 주도적으로 처리한 부분\n- MCP 서버 배선\n\n"
    "### 내가 아직 완전히 이해하지 못한 개념\n- MCP stdio server lifecycle\n\n"
    "### 다음에 직접 설명해봐야 할 질문\n"
    "1. Claude Code가 MCP stdio 서버를 실행하는 방식은 상시 데몬과 무엇이 다른가?\n"
)


def test_pick_review_question_returns_none_without_sessions_dir(tmp_path):
    assert pick_review_question(tmp_path) is None


def test_pick_review_question_returns_none_without_questions(tmp_path):
    _write_session(tmp_path, "2026-07-01-devtrail-session.md", "Devtrail", "## What Changed\n- x\n")
    assert pick_review_question(tmp_path) is None


def test_pick_review_question_extracts_project_and_question(tmp_path):
    _write_session(tmp_path, "2026-07-05-devtrail-session.md", "Devtrail", _LEARNING_RECOVERY)
    rq = pick_review_question(tmp_path)
    assert rq is not None
    assert rq.project == "Devtrail"
    assert rq.unclear_concept == "MCP stdio server lifecycle"
    assert rq.question == "Claude Code가 MCP stdio 서버를 실행하는 방식은 상시 데몬과 무엇이 다른가?"


def test_pick_review_question_uses_most_recent_session(tmp_path):
    _write_session(
        tmp_path,
        "2026-07-01-old-session.md",
        "OldProject",
        _LEARNING_RECOVERY.replace("MCP stdio server lifecycle", "옛날 개념"),
    )
    _write_session(tmp_path, "2026-07-05-new-session.md", "NewProject", _LEARNING_RECOVERY)
    rq = pick_review_question(tmp_path)
    assert rq.project == "NewProject"


def test_pick_review_question_skips_sessions_without_question_to_find_older_one(tmp_path):
    _write_session(tmp_path, "2026-07-01-with-question.md", "Devtrail", _LEARNING_RECOVERY)
    _write_session(tmp_path, "2026-07-05-no-question.md", "Devtrail", "## What Changed\n- x\n")
    rq = pick_review_question(tmp_path)
    assert rq is not None
    assert rq.source_rel_path == "10_Worklog/Sessions/2026-07-01-with-question.md"


# ── push-digest --daily CLI 통합 ─────────────────────────────────────────────


def test_cli_push_digest_daily_includes_review_question(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from app import cli
    from app.config import get_settings

    _write_session(tmp_path, "2026-07-05-devtrail-session.md", "Devtrail", _LEARNING_RECOVERY)

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("MESSENGER_PROVIDER", "telegram")
    monkeypatch.setenv("LLM_PROVIDER", "")
    get_settings.cache_clear()

    sent: dict = {}

    class _FakeProvider:
        name = "telegram"

        def send(self, chat_id, text):
            sent["chat_id"] = chat_id
            sent["text"] = text

    monkeypatch.setattr("app.messaging.get_messenger_provider", lambda settings: _FakeProvider())

    runner = CliRunner()
    result = runner.invoke(cli.app, ["push-digest", "--daily"])

    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "오늘의 학습 회수" in sent["text"]
    assert "MCP stdio 서버를 실행하는 방식은 상시 데몬과 무엇이 다른가?" in sent["text"]
