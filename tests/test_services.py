import json

from app.content_sources.collector import SourceCollector
from app.models import DraftRequest
from app.repositories.blog_repository import BlogRepository
from app.services.draft_generator import DraftGenerator
from app.services.preview_service import PreviewService
from app.services.topic_recommender import TopicRecommender
from app.storage import MarkdownStorage
from tests.conftest import FakeLLM, FakeSource, sample_chunks


def _collector():
    return SourceCollector([FakeSource(sample_chunks())])


def test_topic_recommender_parses_topics():
    resp = json.dumps(
        {
            "topics": [
                {
                    "title_candidates": ["RAG 환경 분리"],
                    "reason": "worklog에 분리 작업이 있음",
                    "outline": ["문제", "해결"],
                    "source_refs": ["worklog:worklog"],
                }
            ]
        }
    )
    rec = TopicRecommender(_collector(), FakeLLM(resp))
    out = rec.recommend()
    assert len(out) == 1
    assert out[0].title_candidates == ["RAG 환경 분리"]
    assert out[0].source_refs == ["worklog:worklog"]


def test_topic_recommender_excludes_existing_titles():
    llm = FakeLLM(json.dumps({"topics": []}))
    rec = TopicRecommender(_collector(), llm)
    rec.recommend(exclude_titles=["이미 쓴 주제 A"])
    # 제외 목록이 프롬프트에 반영되어야 한다.
    assert "이미 쓴 주제 A" in llm.last_prompt


def test_draft_generator_saves(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path))
    resp = json.dumps(
        {
            "title": "XCoreChat 개발환경 분리",
            "summary": "운영/개발 분리",
            "tags": ["rag", "infra"],
            "source_refs": ["worklog:worklog"],
            "body": "## 문제\n섞였다.\n## 해결\n분리했다.",
        }
    )
    gen = DraftGenerator(_collector(), FakeLLM(resp), repo)
    post = gen.generate(DraftRequest(topic="환경 분리", source_project="XCoreChat"))

    assert post.title == "XCoreChat 개발환경 분리"
    assert post.tags == ["rag", "infra"]
    assert post.source_project == "XCoreChat"
    assert post.local_path
    # 실제로 저장되어 다시 읽을 수 있어야 한다.
    reloaded = repo.get_by_slug(post.slug)
    assert reloaded is not None
    assert "분리했다" in reloaded.body


def test_draft_generator_falls_back_to_context_refs(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path))
    resp = json.dumps({"title": "t", "body": "b"})  # source_refs 없음
    gen = DraftGenerator(_collector(), FakeLLM(resp), repo)
    post = gen.generate(DraftRequest(topic="x"))
    assert post.source_refs  # 수집 컨텍스트 refs로 채워짐


def test_preview_latest_and_excerpt(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path))
    resp = json.dumps({"title": "긴 글", "body": "가" * 1000})
    DraftGenerator(_collector(), FakeLLM(resp), repo).generate(DraftRequest(topic="x"))

    result = PreviewService(repo, excerpt_chars=100).preview("latest")
    assert result is not None
    assert result.excerpt.endswith("…")
    assert len(result.excerpt) <= 110


def test_preview_missing_returns_none(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path))
    assert PreviewService(repo).preview("latest") is None
