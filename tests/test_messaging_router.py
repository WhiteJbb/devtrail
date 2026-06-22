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
