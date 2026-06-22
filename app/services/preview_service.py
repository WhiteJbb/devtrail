"""미리보기 서비스 — LLM 불필요."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import BlogPost
from app.repositories.blog_repository import BlogRepository


@dataclass
class PreviewResult:
    post: BlogPost
    excerpt: str


class PreviewService:
    """최신(또는 지정) 초안의 메타데이터와 본문 일부를 돌려준다."""

    def __init__(self, repository: BlogRepository, excerpt_chars: int = 600):
        self.repository = repository
        self.excerpt_chars = excerpt_chars

    def _excerpt(self, body: str) -> str:
        body = body.strip()
        if len(body) <= self.excerpt_chars:
            return body
        return body[: self.excerpt_chars].rstrip() + "\n…"

    def preview(self, target: str = "latest") -> PreviewResult | None:
        if target == "latest":
            post = self.repository.get_latest()
        else:
            post = self.repository.get_by_slug(target)
        if post is None:
            return None
        return PreviewResult(post=post, excerpt=self._excerpt(post.body))
