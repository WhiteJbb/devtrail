"""WikiBlogAgent — ContextPack을 기반으로 블로그 초안을 생성해 50_Outputs/Blog/Drafts/에 저장한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.memory.context_pack_builder import ContextPackBuilder
from app.models.context_pack import ContextPack
from app.prompts import render_prompt
from app.services.json_utils import complete_json
from app.services.wiki_service import WikiService


_DRAFTS_REL = "50_Outputs/Blog/Drafts"
_MAX_SLUG_CHARS = 60


@dataclass(frozen=True)
class WikiBlogDraft:
    title: str
    slug: str
    tags: list[str]
    source_refs: list[str]
    rel_path: str
    path: Path
    body: str


class WikiBlogAgent:
    """ContextPack → LLM → 50_Outputs/Blog/Drafts/ 저장."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)
        self.builder = ContextPackBuilder(self.vault_dir, wiki_service=self.wiki_service)

    def write_blog(self, topic: str, project: str = "") -> WikiBlogDraft:
        """topic으로 Context Pack을 만들고 블로그 초안을 생성한다."""
        pack = self.builder.build(topic)
        return self._generate_and_save(topic, project, pack)

    def _generate_and_save(self, topic: str, project: str, pack: ContextPack) -> WikiBlogDraft:
        prompt = render_prompt("write_wiki_blog", CONTEXT_PACK=pack.render())
        data = complete_json(self._llm(), prompt)

        title = str(data.get("title") or topic).strip()
        tags_raw = data.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
        tags = [str(t) for t in tags_raw]
        body = str(data.get("body") or "").strip()

        slug = self._slug(title)
        stamp = (self.now or datetime.now()).strftime("%Y%m%d")
        rel_path = f"{_DRAFTS_REL}/{stamp}-{slug}.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)

        today = (self.now or datetime.now()).strftime("%Y-%m-%d")
        metadata: dict[str, Any] = {
            "type": "draft",
            "output": "blog",
            "project": project,
            "status": "draft",
            "tags": tags,
            "source_refs": pack.source_refs,
            "created_at": today,
        }
        full_body = f"# {title}\n\n{body}" if body and not body.startswith("# ") else body
        post = frontmatter.Post(full_body, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        self.wiki_service.append_vault_log("write-blog", title, [rel_path])

        return WikiBlogDraft(
            title=title,
            slug=slug,
            tags=tags,
            source_refs=pack.source_refs,
            rel_path=rel_path,
            path=path,
            body=full_body,
        )

    def _llm(self) -> LLMProvider:
        return self.llm or get_llm_provider(self.settings)

    def _slug(self, value: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^0-9a-z가-힣_-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-_")
        return text[:_MAX_SLUG_CHARS] or "blog"
