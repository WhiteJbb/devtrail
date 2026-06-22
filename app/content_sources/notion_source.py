"""Notion 아이디어/worklog DB를 읽는 content source."""

from __future__ import annotations

from app.models import SourceChunk
from app.notion.client import NotionClient


class NotionSource:
    """idea/worklog Notion DB의 레코드를 SourceChunk로 읽는다.

    database_id가 비어 있거나 읽기에 실패하면 빈 리스트를 반환한다(파이프라인 안전).
    mock 클라이언트는 시드된 레코드가 없으면 빈 리스트를 돌려준다.
    """

    name = "notion"

    def __init__(
        self,
        client: NotionClient,
        idea_database_id: str = "",
        worklog_database_id: str = "",
    ):
        self.client = client
        self.idea_database_id = idea_database_id
        self.worklog_database_id = worklog_database_id

    def _fetch_db(self, database_id: str, source_type: str) -> list[SourceChunk]:
        if not database_id:
            return []
        try:
            records = self.client.query_records(database_id)
        except Exception:
            return []
        return [
            SourceChunk(
                source_type=source_type,
                ref=rec.id,
                title=rec.title,
                text=rec.text or rec.title,
            )
            for rec in records
            if (rec.text or rec.title)
        ]

    def fetch(self) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        chunks += self._fetch_db(self.idea_database_id, "notion-idea")
        chunks += self._fetch_db(self.worklog_database_id, "notion-worklog")
        return chunks
