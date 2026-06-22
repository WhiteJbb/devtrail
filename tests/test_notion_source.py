import json

from app.content_sources.notion_source import NotionSource
from app.notion.mock_client import MockNotionClient


def test_reads_idea_and_worklog(tmp_path):
    store = tmp_path / "notion.json"
    store.write_text(
        json.dumps(
            {
                "blog_rows": {},
                "records": {
                    "db-idea": [{"id": "i1", "title": "아이디어", "text": "RAG 분리"}],
                    "db-work": [{"id": "w1", "title": "작업", "text": "vLLM 연결"}],
                },
            }
        ),
        encoding="utf-8",
    )
    client = MockNotionClient(store)
    src = NotionSource(client, idea_database_id="db-idea", worklog_database_id="db-work")
    chunks = src.fetch()

    types = {c.source_type for c in chunks}
    assert types == {"notion-idea", "notion-worklog"}


def test_empty_db_ids_return_nothing(tmp_path):
    client = MockNotionClient(tmp_path / "notion.json")
    assert NotionSource(client).fetch() == []
