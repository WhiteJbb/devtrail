"""Notion 문서 본문을 읽는 content source.

사용자가 Notion에 정리해 둔 문서(페이지 본문)를 초안 소스로 읽는다.
- idea/worklog DB: 각 행의 페이지 본문(블록)을 읽는다.
- source page ids: 명시한 페이지 본문을 직접 읽는다.

database_id/page_id가 비어 있거나 읽기에 실패하면 건너뛴다(파이프라인 안전).
mock 클라이언트는 시드된 본문이 없으면 빈 결과를 돌려준다.
"""

from __future__ import annotations

from app.models import SourceChunk
from app.notion.client import NotionClient


class NotionSource:
    name = "notion"

    def __init__(
        self,
        client: NotionClient,
        idea_database_id: str = "",
        worklog_database_id: str = "",
        source_page_ids: list[str] | None = None,
    ):
        self.client = client
        self.idea_database_id = idea_database_id
        self.worklog_database_id = worklog_database_id
        self.source_page_ids = source_page_ids or []

    def _page_text(self, page_id: str) -> str:
        try:
            return self.client.get_page_text(page_id)
        except Exception:
            return ""

    def _fetch_db(self, database_id: str, source_type: str) -> list[SourceChunk]:
        if not database_id:
            return []
        try:
            records = self.client.query_records(database_id)
        except Exception:
            return []

        chunks: list[SourceChunk] = []
        for rec in records:
            # 페이지 본문을 우선 사용하고, 없으면 행 요약/제목으로 폴백.
            body = self._page_text(rec.id) or rec.text or rec.title
            if not body:
                continue
            chunks.append(
                SourceChunk(source_type=source_type, ref=rec.id, title=rec.title, text=body)
            )
        return chunks

    def _fetch_pages(self) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        for page_id in self.source_page_ids:
            body = self._page_text(page_id)
            if not body:
                continue
            chunks.append(
                SourceChunk(
                    source_type="notion-doc",
                    ref=page_id,
                    title="",
                    text=body,
                )
            )
        return chunks

    def fetch(self) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        chunks += self._fetch_pages()
        chunks += self._fetch_db(self.idea_database_id, "notion-idea")
        chunks += self._fetch_db(self.worklog_database_id, "notion-worklog")
        return chunks
