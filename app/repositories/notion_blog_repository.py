"""Notion Blog DB 저장소 — NotionClient를 BlogPost 도메인으로 감싼다."""

from __future__ import annotations

from app.models import BlogPost, NotionBlogRow
from app.notion import mapping
from app.notion.client import NotionClient


class NotionBlogRepository:
    def __init__(self, client: NotionClient):
        self.client = client

    @property
    def kind(self) -> str:
        return self.client.kind

    def upsert(self, post: BlogPost) -> NotionBlogRow:
        """BlogPost 메타데이터를 Notion Blog DB 행으로 생성/갱신."""
        row = mapping.blog_post_to_row(post)
        return self.client.upsert_blog_row(row)

    def list_rows(self) -> list[NotionBlogRow]:
        return self.client.query_blog_rows()

    def find_by_slug(self, slug: str) -> NotionBlogRow | None:
        for row in self.client.query_blog_rows():
            if row.slug == slug:
                return row
        return None
