"""블로그 초안/문서 모델.

frontmatter가 단일 진실원천(SOT)이다. 이 모델의 메타데이터 필드가 그대로
draft `.md`의 YAML frontmatter로 직렬화되고, Notion DB 컬럼과 매핑된다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class BlogStatus(str, Enum):
    IDEA = "idea"
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BlogPost(BaseModel):
    """블로그 초안 한 건. 메타데이터(frontmatter) + 본문(body)."""

    title: str
    slug: str
    body: str = ""

    tags: list[str] = Field(default_factory=list)
    source_project: str = ""
    status: BlogStatus = BlogStatus.DRAFT
    summary: str = ""

    source_refs: list[str] = Field(default_factory=list)
    local_path: str = ""
    notion_page_id: str | None = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def metadata(self) -> dict:
        """frontmatter로 직렬화할 메타데이터(본문 제외).

        datetime은 ISO 문자열로, Enum은 값으로 내보낸다.
        """
        return {
            "title": self.title,
            "slug": self.slug,
            "tags": list(self.tags),
            "source_project": self.source_project,
            "status": self.status.value,
            "summary": self.summary,
            "source_refs": list(self.source_refs),
            "local_path": self.local_path,
            "notion_page_id": self.notion_page_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
