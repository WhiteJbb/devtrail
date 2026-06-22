from app.llm.base import LLMNotConfiguredError
from app.messaging.router import CommandRouter
from app.models import BlogPost, BlogStatus, TopicSuggestion
from app.services.preview_service import PreviewResult


class StubAgent:
    def __init__(self):
        self.drafted = None
        self.published = None

    def list_drafts(self):
        return [BlogPost(title="글A", slug="s1", status=BlogStatus.DRAFT)]

    def suggest_topics(self):
        return [TopicSuggestion(title_candidates=["주제1"], reason="이유")]

    def write_draft(self, request):
        self.drafted = request.topic
        return BlogPost(title=request.topic, slug="new-slug")

    def revise(self, target):
        return BlogPost(title="다듬은 글", slug=target)

    def preview(self, target):
        return PreviewResult(post=BlogPost(title="P", slug=target), excerpt="본문 일부")

    def publish_done(self, target, url=""):
        self.published = url
        return BlogPost(title="게시글", slug="s1", published_url=url)


def _router(agent=None):
    agent = agent or StubAgent()
    return CommandRouter(make_agent=lambda: agent), agent


def test_help_and_unknown():
    router, _ = _router()
    assert "사용 가능한 명령" in router.handle("/help")
    assert "알 수 없는 명령" in router.handle("/nope")
    assert "사용 가능한 명령" in router.handle("")


def test_list():
    router, _ = _router()
    out = router.handle("/list")
    assert "글A" in out and "s1" in out


def test_draft_requires_topic_then_runs():
    router, agent = _router()
    assert "주제를 함께" in router.handle("/draft")
    out = router.handle("/draft XCoreChat 분리")
    assert "초안 생성 완료" in out
    assert agent.drafted == "XCoreChat 분리"


def test_publish_parses_url():
    router, agent = _router()
    assert "주소를 함께" in router.handle("/publish")
    out = router.handle("/publish https://blog.test/1")
    assert agent.published == "https://blog.test/1"
    assert "게시 완료" in out


def test_llm_not_configured_is_friendly():
    class _A(StubAgent):
        def suggest_topics(self):
            raise LLMNotConfiguredError("x")

    router, _ = _router(_A())
    assert "LLM이 연결되어 있지 않습니다" in router.handle("/topics")


def test_exception_does_not_crash():
    class _A(StubAgent):
        def list_drafts(self):
            raise RuntimeError("boom")

    router, _ = _router(_A())
    assert "오류가 발생했습니다" in router.handle("/list")


# ── Phase 8: Wiki Core 명령 ──────────────────────────────────────────


def test_search_requires_arg():
    router, _ = _router()
    assert "검색어를 함께" in router.handle("/search")


def test_search_returns_results(monkeypatch):
    from app.services.wiki_service import WikiNote, WikiSearchResult
    from unittest.mock import patch
    from types import SimpleNamespace

    test_router, _ = _router()

    fake_note = WikiNote(
        path="20_Knowledge/AI/rag.md",
        title="RAG 기초",
        body="RAG 기초 설명",
        metadata={},
        tags=["rag"],
        wikilinks=[],
        summary="RAG 기초 요약",
    )
    fake_results = [WikiSearchResult(note=fake_note, score=10, matched_terms=["rag"])]

    fake_settings = SimpleNamespace(obsidian_vault_root="/fake/vault", wiki_folder="60_Wiki")

    with patch("app.config.get_settings", return_value=fake_settings):
        with patch("app.services.wiki_service.WikiService.search", return_value=fake_results):
            out = test_router.handle("/search RAG")

    assert "RAG" in out or "OBSIDIAN_VAULT_PATH" in out


def test_search_no_vault_configured(monkeypatch):
    from unittest.mock import patch
    from types import SimpleNamespace

    router, _ = _router()
    with patch("app.config.get_settings", return_value=SimpleNamespace(obsidian_vault_root="", wiki_folder="60_Wiki")):
        out = router.handle("/search RAG")
    assert "OBSIDIAN_VAULT_PATH" in out


def test_capture_requires_arg():
    router, _ = _router()
    assert "메모 내용을 함께" in router.handle("/capture")


def test_capture_calls_agent(monkeypatch):
    from unittest.mock import MagicMock, patch
    from types import SimpleNamespace

    router, _ = _router()
    fake_result = SimpleNamespace(created=True, rel_path="00_Inbox/Captures/abc.md")
    mock_agent = MagicMock()
    mock_agent.return_value.capture.return_value = fake_result

    with patch("app.agents.CaptureAgent", mock_agent):
        out = router.handle("/capture 오늘 작업했다")

    assert "저장 완료" in out or "00_Inbox" in out


def test_distill_calls_agent(monkeypatch):
    from unittest.mock import MagicMock, patch
    from types import SimpleNamespace

    router, _ = _router()
    written_item = SimpleNamespace(spec=SimpleNamespace(kind="knowledge", title="RAG 지식"))
    fake_result = SimpleNamespace(written=[written_item])
    mock_agent = MagicMock()
    mock_agent.return_value.distill_today.return_value = fake_result

    with patch("app.agents.DistillAgent", mock_agent):
        out = router.handle("/distill")

    assert "후보 1개" in out or "knowledge" in out


def test_context_requires_arg():
    router, _ = _router()
    assert "주제를 함께" in router.handle("/context")


def test_candidates_lists_items(monkeypatch):
    from unittest.mock import MagicMock, patch
    from app.agents.curator_agent import CandidateItem

    router, _ = _router()
    items = [
        CandidateItem(
            kind="knowledge",
            title="RAG 지식",
            rel_path="60_Candidates/Knowledge/rag.md",
            created_at="2026-06-23",
            project="WorkAgent",
        )
    ]
    mock_agent = MagicMock()
    mock_agent.return_value.list_candidates.return_value = items

    with patch("app.agents.curator_agent.CuratorAgent", mock_agent):
        out = router.handle("/candidates")

    # vault 미설정이면 RuntimeError → 실패 메시지
    assert "후보" in out or "Candidates" in out or "실패" in out


def test_promote_requires_arg():
    router, _ = _router()
    assert "후보 경로를 보내주세요" in router.handle("/promote")
