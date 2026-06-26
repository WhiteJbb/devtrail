from app.messaging.router import CommandRouter


def _router():
    return CommandRouter()


def test_help_and_unknown():
    router = _router()
    assert "Work Agent" in router.handle("/help")
    assert "알 수 없는 명령" in router.handle("/nope")
    assert "Work Agent" in router.handle("")


def test_draft_requires_topic():
    router = _router()
    assert "주제를 함께" in router.handle("/write")
    assert "주제를 함께" in router.handle("/draft")


def test_publish_requires_url():
    router = _router()
    assert "주소를 함께" in router.handle("/publish")


def test_search_requires_arg():
    router = _router()
    assert "검색어를 함께" in router.handle("/search")


def test_search_no_vault_configured(monkeypatch):
    from unittest.mock import patch
    from types import SimpleNamespace

    router = _router()
    with patch("app.config.get_settings", return_value=SimpleNamespace(obsidian_vault_root="", wiki_folder="60_Wiki")):
        out = router.handle("/search RAG")
    assert "OBSIDIAN_VAULT_PATH" in out


def test_capture_requires_arg():
    router = _router()
    assert "메모 내용을 함께" in router.handle("/capture")


def test_capture_calls_agent(monkeypatch):
    from unittest.mock import MagicMock, patch
    from types import SimpleNamespace

    router = _router()
    fake_result = SimpleNamespace(created=True, rel_path="00_Inbox/Captures/abc.md")
    mock_agent = MagicMock()
    mock_agent.return_value.capture.return_value = fake_result

    with patch("app.agents.CaptureAgent", mock_agent):
        out = router.handle("/capture 오늘 작업했다")

    assert "저장 완료" in out or "00_Inbox" in out


def test_distill_calls_agent(monkeypatch):
    from unittest.mock import MagicMock, patch
    from types import SimpleNamespace

    router = _router()
    written_item = SimpleNamespace(spec=SimpleNamespace(kind="knowledge", title="RAG 지식"))
    fake_result = SimpleNamespace(written=[written_item])
    mock_agent = MagicMock()
    mock_agent.return_value.distill_today.return_value = fake_result

    with patch("app.agents.DistillAgent", mock_agent):
        out = router.handle("/distill")

    assert "후보 1개" in out or "knowledge" in out


def test_context_requires_arg():
    router = _router()
    assert "주제를 함께" in router.handle("/context")


def test_promote_requires_arg():
    router = _router()
    assert "후보 경로를 보내주세요" in router.handle("/promote")


def test_exception_does_not_crash(monkeypatch):
    from unittest.mock import MagicMock, patch

    router = _router()
    mock_agent = MagicMock()
    mock_agent.return_value.list_drafts.side_effect = RuntimeError("boom")

    with patch("app.agents.wiki_blog_agent.WikiBlogAgent", mock_agent):
        out = router.handle("/list")
    assert "오류가 발생했습니다" in out
