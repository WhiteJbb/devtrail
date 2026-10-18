"""세션 노트 Learning Recovery 렌더 정규화 · /topics 라우터."""

from pathlib import Path

from app.messaging.router import CommandRouter
from app.vault_tools import _render_process_body


# ── 세션 노트 Learning Recovery 렌더 정규화 ──────────────────────────────────


def _render(recovery: dict) -> str:
    return _render_process_body(
        what_changed="x",
        files_touched="y",
        decisions={},
        implementation_trace="z",
        notes={},
        docs_update_candidates="",
        next_session="",
        recovery=recovery,
    )


def test_render_strips_existing_bullet_prefix():
    """호출자가 '- a\\n- b' 형태로 넘겨도 '- - ' 이중 불릿이 생기면 안 된다."""
    body = _render({
        "ai_led": "- 조사 전부\n- 구현 전부",
        "unclear_concepts": "- 개념 하나",
        "questions": "- 질문인가?",
        "related_candidates": "",
    })
    assert "- -" not in body
    assert "- 조사 전부" in body
    assert "- 구현 전부" in body
    assert "- 개념 하나" in body
    assert "1. 질문인가?" in body


def test_render_strips_number_prefix_in_questions():
    body = _render({
        "ai_led": "",
        "unclear_concepts": "",
        "questions": "1. 첫 질문?\n2. 둘째 질문?",
        "related_candidates": "",
    })
    assert "1. 첫 질문?" in body
    assert "2. 둘째 질문?" in body
    assert "1. 1." not in body


def test_render_plain_string_still_gets_bullet():
    body = _render({
        "ai_led": "한 줄 설명",
        "unclear_concepts": "",
        "questions": "",
        "related_candidates": "",
    })
    assert "- 한 줄 설명" in body


# ── /topics 라우터 핸들러 (인텐트 위임 dead-end 수정) ────────────────────────


def test_router_topics_lists_titles(monkeypatch):
    """자연어 suggest-topics 인텐트가 위임하는 /topics가 도움말이 아니라 주제를 반환해야 한다."""
    from types import SimpleNamespace

    result = SimpleNamespace(
        written=[SimpleNamespace(spec=SimpleNamespace(title="LLM 커밋 요약 자동화"))]
    )

    class FakeDistill:
        def __init__(self, *args, **kwargs):
            pass

        def suggest_blog_topics(self):
            return result

    monkeypatch.setattr("app.agents.DistillAgent", FakeDistill)
    reply = CommandRouter().handle("/topics")
    assert "LLM 커밋 요약 자동화" in reply
    assert "알 수 없는 명령" not in reply


def test_router_topics_empty(monkeypatch):
    from types import SimpleNamespace

    class FakeDistill:
        def __init__(self, *args, **kwargs):
            pass

        def suggest_blog_topics(self):
            return SimpleNamespace(written=[])

    monkeypatch.setattr("app.agents.DistillAgent", FakeDistill)
    reply = CommandRouter().handle("/topics")
    assert "주제가 안 보여요" in reply
