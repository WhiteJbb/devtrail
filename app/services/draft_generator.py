"""초안 생성 서비스."""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.models import BlogPost, BlogStatus, DraftRequest
from app.prompts import render_prompt
from app.repositories.blog_repository import BlogRepository
from app.services.json_utils import complete_json


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
        ctx_text = context.as_prompt_text()

        # 1단계: 메타데이터(소형 JSON — title/summary/tags/source_refs)
        meta_prompt = render_prompt(
            "write_draft_meta",
            TOPIC=request.topic,
            CONTEXT=ctx_text,
        )
        data = complete_json(self.llm, meta_prompt)
        source_refs = data.get("source_refs") or context.refs

        # 2단계: 본문(순수 마크다운 — JSON 안에 담지 않아 개행 깨짐 없음)
        body_prompt = render_prompt(
            "write_draft_body",
            TOPIC=request.topic,
            CONTEXT=ctx_text,
        )
        body = self.llm.complete(body_prompt).strip()

        post = BlogPost(
            title=data.get("title") or request.topic,
            slug="",  # repository가 날짜 prefix로 생성
            body=body,
            summary=data.get("summary", ""),
            tags=data.get("tags") or request.tags,
            source_project=request.source_project,
            status=BlogStatus.DRAFT,
            source_refs=source_refs,
        )
        self.repository.save_draft(post)
        return post
