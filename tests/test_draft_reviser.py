import json

from app.content_sources.collector import SourceCollector
from app.models import BlogPost, BlogStatus
from app.repositories.blog_repository import BlogRepository
from app.services.draft_reviser import DraftReviser
from app.storage import MarkdownStorage
from tests.conftest import FakeLLM, FakeSource, sample_chunks


def _setup(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path))
    collector = SourceCollector([FakeSource(sample_chunks())])
    return repo, collector


def test_revise_updates_body_keeps_identity(tmp_path):
    repo, collector = _setup(tmp_path)
    original = BlogPost(
        title="원제목",
        slug="20250101-a",
        body="대충 쓴 본문",
        status=BlogStatus.REVIEW,
        notion_page_id="pg-1",
    )
    repo.save_draft(original)
    created = repo.get_by_slug("20250101-a").created_at

    resp = json.dumps(
        {"title": "다듬은 제목", "summary": "요약", "tags": ["t"], "body": "## 문제\n정리된 본문"}
    )
    reviser = DraftReviser(collector, FakeLLM(resp), repo)
    post = reviser.revise("latest")

    assert post.title == "다듬은 제목"
    assert "정리된 본문" in post.body
    # 정체성 보존: slug/created_at/notion_page_id/status 유지
    assert post.slug == "20250101-a"
    assert post.notion_page_id == "pg-1"
    assert post.status == BlogStatus.REVIEW
    assert repo.get_by_slug("20250101-a").created_at == created


def test_revise_missing_returns_none(tmp_path):
    repo, collector = _setup(tmp_path)
    assert DraftReviser(collector, FakeLLM("{}"), repo).revise("latest") is None


def test_revise_keeps_old_values_when_model_omits(tmp_path):
    repo, collector = _setup(tmp_path)
    repo.save_draft(BlogPost(title="원제목", slug="s1", body="원본", tags=["keep"]))
    resp = json.dumps({"body": "새 본문"})  # title/tags 생략
    post = DraftReviser(collector, FakeLLM(resp), repo).revise("s1")
    assert post.title == "원제목"
    assert post.tags == ["keep"]
    assert post.body == "새 본문"
