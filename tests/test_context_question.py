"""app/services/context_question.py + /gap 회수 흐름 테스트 (Phase 2)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import frontmatter

from app.services.context_question import (
    format_context_block,
    generate_context_questions,
    mark_context_answered,
    pick_context_question,
)


class _FakeLLM:
    name = "fake"
    model = "fake"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, prompt: str, system: str = "") -> str:
        return self.payload


def _questions_response(*items: tuple[str, str]) -> str:
    return json.dumps(
        {"questions": [{"type": t, "question": q} for t, q in items]}, ensure_ascii=False
    )


def _write_session(vault: Path, name: str, body: str, created_at: str, **meta) -> Path:
    path = vault / "10_Worklog" / "Sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, project="Devtrail", created_at=created_at, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


_NOW = datetime(2026, 6, 23, 22, 0, 0)


def test_generate_writes_up_to_two_questions(tmp_path):
    path = _write_session(tmp_path, "s.md", "## What Changed\n- 훅 개편\n", "2026-06-23T09:00:00")
    llm = _FakeLLM(_questions_response(("WHY", "훅을 왜 바꿨어?"), ("OUTCOME", "뭐가 달라졌어?")))

    out = generate_context_questions(tmp_path, llm=llm, now=_NOW)

    assert [q.qtype for q in out] == ["WHY", "OUTCOME"]
    text = path.read_text(encoding="utf-8")
    assert "## Context Questions" in text
    assert "- [ ] [WHY] 훅을 왜 바꿨어?" in text
    assert "- [ ] [OUTCOME] 뭐가 달라졌어?" in text


def test_generate_truncates_to_hard_limit(tmp_path):
    """상한은 프롬프트가 아니라 코드가 지킨다 — LLM이 3개를 줘도 2개만 남는다."""
    path = _write_session(tmp_path, "s.md", "## What Changed\n- x\n", "2026-06-23T09:00:00")
    llm = _FakeLLM(
        _questions_response(("WHY", "1번?"), ("PROBLEM", "2번?"), ("FAILURE", "3번?"))
    )

    out = generate_context_questions(tmp_path, llm=llm, now=_NOW)

    assert len(out) == 2
    assert "3번?" not in path.read_text(encoding="utf-8")


def test_generate_skips_when_pending_question_exists(tmp_path):
    _write_session(
        tmp_path,
        "s.md",
        "## Context Questions\n\n- [ ] [WHY] 이미 있는 질문?\n",
        "2026-06-23T09:00:00",
    )
    llm = _FakeLLM(_questions_response(("WHY", "새 질문?")))

    assert generate_context_questions(tmp_path, llm=llm, now=_NOW) == []


def test_generate_ignores_other_days(tmp_path):
    _write_session(tmp_path, "s.md", "## What Changed\n- x\n", "2026-06-20T09:00:00")
    llm = _FakeLLM(_questions_response(("WHY", "질문?")))

    assert generate_context_questions(tmp_path, llm=llm, now=_NOW) == []


def test_generate_unknown_type_falls_back_to_why(tmp_path):
    _write_session(tmp_path, "s.md", "## What Changed\n- x\n", "2026-06-23T09:00:00")
    llm = _FakeLLM(_questions_response(("SOMETHING", "질문?")))

    out = generate_context_questions(tmp_path, llm=llm, now=_NOW)

    assert out[0].qtype == "WHY"


def test_answer_appends_new_recovery_section_and_revives_distill(tmp_path):
    path = _write_session(
        tmp_path,
        "s.md",
        "## Context Questions\n\n- [ ] [WHY] 훅을 왜 바꿨어?\n",
        "2026-06-23T09:00:00",
        needs_distill=False,
    )
    q = pick_context_question(tmp_path)

    assert mark_context_answered(tmp_path, q.source_rel_path, q.question, "mac에서 안 돌아서", now=_NOW)

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert "## Context Recovery" in post.content
    assert "- **[WHY] 훅을 왜 바꿨어?** (2026-06-23) — mac에서 안 돌아서" in post.content
    assert "- [x] [WHY] 훅을 왜 바꿨어?" in post.content
    assert post.metadata["needs_distill"] is True
    assert pick_context_question(tmp_path) is None


def test_answer_appends_to_existing_recovery_section(tmp_path):
    path = _write_session(
        tmp_path,
        "s.md",
        "## Context Questions\n\n- [ ] [WHY] 두 번째 질문?\n\n"
        "## Context Recovery\n\n- **[OUTCOME] 첫 질문?** (2026-06-22) — 첫 답변\n",
        "2026-06-23T09:00:00",
    )
    q = pick_context_question(tmp_path)

    assert mark_context_answered(tmp_path, q.source_rel_path, q.question, "두 번째 답변", now=_NOW)

    content = frontmatter.loads(path.read_text(encoding="utf-8")).content
    assert content.count("## Context Recovery") == 1
    assert "첫 답변" in content and "두 번째 답변" in content


def test_answer_returns_false_for_missing_note(tmp_path):
    assert not mark_context_answered(tmp_path, "10_Worklog/Sessions/none.md", "질문?", "답")


def test_format_context_block_lists_pending_only(tmp_path):
    _write_session(
        tmp_path,
        "s.md",
        "## Context Questions\n\n- [x] [WHY] 답한 질문?\n- [ ] [OUTCOME] 남은 질문?\n",
        "2026-06-23T09:00:00",
    )

    block = format_context_block(tmp_path)

    assert "맥락 회수 질문" in block
    assert "남은 질문?" in block
    assert "답한 질문?" not in block


def test_format_context_block_empty_without_questions(tmp_path):
    assert format_context_block(tmp_path) == ""


# ── /gap 라우팅 ──────────────────────────────────────────────────────────


def _router_with_vault(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.messaging.router import CommandRouter

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    get_settings.cache_clear()
    return CommandRouter()


def test_gap_command_shows_pending_question(tmp_path, monkeypatch):
    from app.config import get_settings

    _write_session(
        tmp_path, "s.md", "## Context Questions\n\n- [ ] [WHY] 훅을 왜 바꿨어?\n", "2026-06-23T09:00:00"
    )
    router = _router_with_vault(tmp_path, monkeypatch)
    try:
        out = router.handle("/gap")
    finally:
        get_settings.cache_clear()

    assert "훅을 왜 바꿨어?" in out
    assert "[WHY]" in out


def test_gap_command_records_answer(tmp_path, monkeypatch):
    from app.config import get_settings

    path = _write_session(
        tmp_path, "s.md", "## Context Questions\n\n- [ ] [WHY] 훅을 왜 바꿨어?\n", "2026-06-23T09:00:00"
    )
    router = _router_with_vault(tmp_path, monkeypatch)
    try:
        out = router.handle("/gap sh 디스패처가 필요해서")
    finally:
        get_settings.cache_clear()

    assert "기록해뒀어요" in out
    assert "sh 디스패처가 필요해서" in path.read_text(encoding="utf-8")


def test_gap_command_without_pending_question(tmp_path, monkeypatch):
    from app.config import get_settings

    router = _router_with_vault(tmp_path, monkeypatch)
    try:
        out = router.handle("/gap")
    finally:
        get_settings.cache_clear()

    assert "답할 맥락 질문이 없어요" in out
