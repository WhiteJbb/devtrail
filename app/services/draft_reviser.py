"""초안 다듬기 서비스.

기존 초안을 source 범위 안에서 문장/구조만 개선한다. 새 사실을 추가하지 않는다.
revise_draft 프롬프트를 사용하며, 결과로 기존 초안(slug/생성시각/notion_page_id 유지)을 갱신한다.
"""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.models import BlogPost
from app.prompts import render_prompt
from app.repositories.blog_repository import BlogRepository
from app.services.json_utils import complete_json


class DraftReviser:
    def __init__(
        self,
        collector: SourceCollector,
        llm: LLMProvider,
        repository: BlogRepository,
    ):
        self.collector = collector
        self.llm = llm
        self.repository = repository

    def revise(self, target: str = "latest") -> BlogPost | None:
        if target == "latest":
            post = self.repository.get_latest()
        else:
            post = self.repository.get_by_slug(target)
        if post is None:
            return None

        context = self.collector.collect()
        draft_text = f"# {post.title}\n\n{post.body}"
        prompt = render_prompt(
            "revise_draft",
            DRAFT=draft_text,
            CONTEXT=context.as_prompt_text(),
        )
        data = complete_json(self.llm, prompt)

        # 메타데이터는 기존 값을 보존하고, 모델이 준 값이 있을 때만 갱신한다.
        post.title = data.get("title") or post.title
        post.summary = data.get("summary") or post.summary
        if data.get("tags"):
            post.tags = data["tags"]
        if data.get("source_refs"):
            post.source_refs = data["source_refs"]
        post.body = data.get("body") or post.body

        self.repository.save_draft(post)  # slug/created_at 유지, updated_at 갱신
        return post
