"""실제 Notion API 클라이언트 (notion-client 기반).

구조는 갖추되, 실제 키로의 동작 검증은 다음 단계 과제다. 기본 동작은 mock이며
NOTION_API_KEY + DB id가 모두 있을 때만 factory가 이 클라이언트를 선택한다.
notion-client는 optional 의존성이라 import는 호출 시점에 수행한다.
"""

from __future__ import annotations

from app.models import NotionBlogRow, NotionRecord
from app.notion import mapping


class NotionConfigError(RuntimeError):
    """notion-client 미설치 등 실제 연동 준비 미비."""


class RealNotionClient:
    kind = "real"

    def __init__(self, api_key: str, blog_database_id: str):
        self.api_key = api_key
        self.blog_database_id = blog_database_id
        self._client = self._make_client(api_key)

    @staticmethod
    def _make_client(api_key: str):
        try:
            from notion_client import Client  # optional dependency
        except ImportError as e:  # pragma: no cover - 설치 안내용
            raise NotionConfigError(
                "notion-client가 설치되어 있지 않습니다. `pip install notion-client` 후 사용하세요."
            ) from e
        return Client(auth=api_key)

    def upsert_blog_row(self, row: NotionBlogRow) -> NotionBlogRow:
        props = mapping.row_to_properties(row)
        if row.page_id:
            page = self._client.pages.update(page_id=row.page_id, properties=props)
        else:
            page = self._client.pages.create(
                parent={"database_id": self.blog_database_id}, properties=props
            )
        return mapping.page_to_row(page)

    def query_blog_rows(self) -> list[NotionBlogRow]:
        result = self._client.databases.query(database_id=self.blog_database_id)
        return [mapping.page_to_row(p) for p in result.get("results", [])]

    def query_records(self, database_id: str) -> list[NotionRecord]:
        if not database_id:
            return []
        result = self._client.databases.query(database_id=database_id)
        records: list[NotionRecord] = []
        for page in result.get("results", []):
            row = mapping.page_to_row(page)
            records.append(
                NotionRecord(
                    id=page.get("id", ""),
                    title=row.title,
                    text=row.summary or row.title,
                )
            )
        return records

    def get_page_text(self, page_id: str) -> str:
        if not page_id:
            return ""
        lines: list[str] = []
        cursor: str | None = None
        # 블록은 페이지네이션되므로 has_more가 끝날 때까지 순회.
        while True:
            kwargs = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self._client.blocks.children.list(**kwargs)
            for block in resp.get("results", []):
                text = mapping.block_to_text(block)
                if text:
                    lines.append(text)
            if resp.get("has_more"):
                cursor = resp.get("next_cursor")
            else:
                break
        return "\n".join(lines).strip()
