"""Blog Agent — 요청 단위로 소스/서비스/저장소를 조율한다.

계층을 조립하는 곳. CLI는 이 클래스만 호출한다.
LLM provider는 필요한 시점에 lazy하게 만든다(preview는 LLM 없이 동작).
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.content_sources.collector import SourceCollector
from app.content_sources.git_source import GitSource
from app.content_sources.local_doc_source import LocalDocSource
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.models import BlogPost, DraftRequest, TopicSuggestion
from app.repositories.blog_repository import BlogRepository
from app.services.draft_generator import DraftGenerator
from app.services.preview_service import PreviewResult, PreviewService
from app.services.topic_recommender import TopicRecommender
from app.storage import MarkdownStorage


class BlogAgent:
    def __init__(self, settings: Settings | None = None, repo_dir: Path | None = None):
        self.settings = settings or get_settings()
        self.repo_dir = repo_dir or Path.cwd()
        self.repository = BlogRepository(MarkdownStorage(self.settings.drafts_path))

    # ----- 내부 조립 -----
    def _collector(self) -> SourceCollector:
        sources = [
            LocalDocSource(self.settings.docs_path),
            GitSource(self.repo_dir, limit=self.settings.git_log_limit),
        ]
        return SourceCollector(sources, char_budget=self.settings.context_char_budget)

    def _llm(self) -> LLMProvider:
        # 미설정이면 LLMNotConfiguredError가 올라가고 CLI가 안내한다.
        return get_llm_provider(self.settings)

    # ----- 유스케이스 -----
    def suggest_topics(self) -> list[TopicSuggestion]:
        recommender = TopicRecommender(self._collector(), self._llm())
        return recommender.recommend()

    def write_draft(self, request: DraftRequest) -> BlogPost:
        generator = DraftGenerator(self._collector(), self._llm(), self.repository)
        return generator.generate(request)

    def preview(self, target: str = "latest") -> PreviewResult | None:
        return PreviewService(self.repository).preview(target)
