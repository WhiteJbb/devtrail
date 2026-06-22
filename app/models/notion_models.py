"""Notion 연동에 쓰는 모델."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NotionBlogRow(BaseModel):
    """Notion Blog DB의 한 행. BlogPost 메타데이터와 1:1 매핑된다."""

    title: str
    slug: str
    status: str = "draft"
    source_project: str = ""
    tags: list[str] = Field(default_factory=list)
    local_path: str = ""
    source_refs: list[str] = Field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    page_id: str | None = None


class NotionRecord(BaseModel):
    """idea/worklog DB에서 읽은 일반 레코드(블로그 행이 아님)."""

    id: str
    title: str = ""
    text: str = ""
