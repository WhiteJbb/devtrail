"""Mock Notion 클라이언트 — JSON 파일 백엔드.

실제 Notion 키가 없을 때 기본으로 쓰인다. Blog DB 행을 로컬 JSON에 저장해
sync 워크플로우를 실제 API 없이 검증/사용할 수 있게 한다.
idea/worklog 레코드는 같은 JSON에 미리 시드해 두면 읽어온다.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import NotionBlogRow, NotionRecord


class MockNotionClient:
    kind = "mock"

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._data = self._load()

    # ----- 저장소 -----
    def _load(self) -> dict:
        if self.store_path.is_file():
            try:
                return json.loads(self.store_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"blog_rows": {}, "records": {}}

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _next_page_id(self) -> str:
        return f"mock-{len(self._data['blog_rows']) + 1:04d}"

    # ----- NotionClient 구현 -----
    def upsert_blog_row(self, row: NotionBlogRow) -> NotionBlogRow:
        rows = self._data["blog_rows"]
        # page_id가 있으면 그 키로, 없으면 slug로 기존 행을 찾는다.
        key = row.page_id
        if key is None:
            for existing_key, existing in rows.items():
                if existing.get("slug") == row.slug:
                    key = existing_key
                    break
        if key is None:
            key = self._next_page_id()

        stored = row.model_copy(update={"page_id": key})
        rows[key] = stored.model_dump()
        self._save()
        return stored

    def query_blog_rows(self) -> list[NotionBlogRow]:
        return [NotionBlogRow(**v) for v in self._data["blog_rows"].values()]

    def query_records(self, database_id: str) -> list[NotionRecord]:
        records = self._data.get("records", {}).get(database_id, [])
        return [NotionRecord(**r) for r in records]
