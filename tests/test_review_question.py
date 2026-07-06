"""app/services/review_question.py + push-digest --daily 복습 질문 노출 테스트 (P6)."""

from __future__ import annotations

from pathlib import Path

from app.services.review_question import pick_review_question


def _write_session(vault: Path, name: str, project: str, body: str, created_at: str = "") -> Path:
    path = vault / "10_Worklog" / "Sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nproject: {project}\ncreated_at: {created_at}\n---\n\n{body}\n", encoding="utf-8"
    )
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
    _write_session(tmp_path, "2026-07-05-devtrail-session.md", "Devtrail", _LEARNING_RECOVERY, created_at="2026-07-05T10:00:00")
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
        created_at="2026-07-01T09:00:00",
    )
    _write_session(tmp_path, "2026-07-05-new-session.md", "NewProject", _LEARNING_RECOVERY, created_at="2026-07-05T09:00:00")
    rq = pick_review_question(tmp_path)
    assert rq.project == "NewProject"


def test_pick_review_question_skips_sessions_without_question_to_find_older_one(tmp_path):
    _write_session(tmp_path, "2026-07-01-with-question.md", "Devtrail", _LEARNING_RECOVERY, created_at="2026-07-01T09:00:00")
    _write_session(tmp_path, "2026-07-05-no-question.md", "Devtrail", "## What Changed\n- x\n", created_at="2026-07-05T09:00:00")
    rq = pick_review_question(tmp_path)
    assert rq is not None
    assert rq.source_rel_path == "10_Worklog/Sessions/2026-07-01-with-question.md"


def test_pick_review_question_uses_created_at_not_filename_suffix_order(tmp_path):
    """같은 날 두 번째 세션(파일명 충돌로 '-2' 접미사가 붙음)이 영원히 무시되면 안 된다(P2.2).

    ASCII상 '-'(0x2D) < '.'(0x2E)라 "...session-2.md"가 "...session.md"보다 파일명
    정렬에서 앞에 오고, 예전 코드는 이를 reverse=True로 정렬해 실제로는 더 나중에
    쓰인 두 번째 세션이 뒤로 밀려버렸다. created_at 기준으로는 두 번째(늦은) 세션이
    선택돼야 한다.
    """
    _write_session(
        tmp_path,
        "2026-07-05-devtrail-session.md",
        "Devtrail",
        _LEARNING_RECOVERY.replace("MCP stdio server lifecycle", "질문 A"),
        created_at="2026-07-05T09:00:00",
    )
    _write_session(
        tmp_path,
        "2026-07-05-devtrail-session-2.md",
        "Devtrail",
        _LEARNING_RECOVERY.replace("MCP stdio server lifecycle", "질문 B"),
        created_at="2026-07-05T18:00:00",
    )
    rq = pick_review_question(tmp_path)
    assert rq is not None
    assert rq.unclear_concept == "질문 B"


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
