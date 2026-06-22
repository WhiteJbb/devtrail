"""초안 생성 서비스."""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.models import BlogPost, BlogStatus, DraftRequest
from app.prompts import render_prompt
from app.repositories.blog_repository import BlogRepository
from app.services.json_utils import extract_json_object


class DraftGenerator:
    """주제와 수집 컨텍스트로 LLM 초안을 생성해 로컬에 저장한다."""

    def __init__(
        self,
        collector: SourceCollector,
        llm: LLMProvider,
        repository: BlogRepository,
    ):
        self.collector = collector
        self.llm = llm
        self.repository = repository

    def generate(self, request: DraftRequest) -> BlogPost:
        context = self.collector.collect()
        prompt = render_prompt(
            "write_draft",
            TOPIC=request.topic,
            CONTEXT=context.as_prompt_text(),
        )
        raw = self.llm.complete(prompt)
        data = extract_json_object(raw)

        # LLM이 제시한 source_refs가 없으면 수집 컨텍스트의 refs로 대체.
        source_refs = data.get("source_refs") or context.refs

        post = BlogPost(
            title=data.get("title") or request.topic,
            slug="",  # repository가 날짜 prefix로 생성
            body=data.get("body", ""),
            summary=data.get("summary", ""),
            tags=data.get("tags") or request.tags,
            source_project=request.source_project,
            status=BlogStatus.DRAFT,
            source_refs=source_refs,
        )
        self.repository.save_draft(post)
        return post
