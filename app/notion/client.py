"""NotionClient 프로토콜."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import NotionBlogRow, NotionRecord


@runtime_checkable
class NotionClient(Protocol):
    """Notion 연동의 공통 인터페이스(mock/real 공용).

    kind: "mock" 또는 "real" — 호출측이 동작 모드를 표시할 때 사용.
    """

    kind: str

    def upsert_blog_row(self, row: NotionBlogRow) -> NotionBlogRow:
        """slug(또는 page_id) 기준으로 Blog DB 행을 생성/갱신하고 page_id가 채워진 행을 반환."""
        ...

    def query_blog_rows(self) -> list[NotionBlogRow]:
        """Blog DB의 모든 행을 반환."""
        ...

    def query_records(self, database_id: str) -> list[NotionRecord]:
        """idea/worklog 등 일반 DB의 레코드를 반환(본문 없이 제목/요약 수준)."""
        ...

    def get_page_text(self, page_id: str) -> str:
        """페이지 본문(블록 내용)을 평문으로 반환. 없으면 빈 문자열."""
        ...
