import json

from app.models import NotionBlogRow
from app.notion.mock_client import MockNotionClient


def test_upsert_creates_then_updates(tmp_path):
    store = tmp_path / "notion.json"
    client = MockNotionClient(store)

    row = NotionBlogRow(title="첫 글", slug="20250101-a", status="draft")
    saved = client.upsert_blog_row(row)
    assert saved.page_id  # page_id 부여됨
    assert len(client.query_blog_rows()) == 1

    # 같은 slug로 다시 upsert → 갱신(행 수 그대로)
    saved.status = "review"
    client.upsert_blog_row(saved)
    rows = client.query_blog_rows()
    assert len(rows) == 1
    assert rows[0].status == "review"


def test_persistence_across_instances(tmp_path):
    store = tmp_path / "notion.json"
    MockNotionClient(store).upsert_blog_row(NotionBlogRow(title="t", slug="s"))
    # 새 인스턴스가 파일에서 다시 읽어온다.
    assert len(MockNotionClient(store).query_blog_rows()) == 1


def test_query_records_from_seed(tmp_path):
    store = tmp_path / "notion.json"
    store.write_text(
        json.dumps(
            {
                "blog_rows": {},
                "records": {"db-idea": [{"id": "r1", "title": "아이디어", "text": "RAG 분리"}]},
            }
        ),
        encoding="utf-8",
    )
    client = MockNotionClient(store)
    recs = client.query_records("db-idea")
    assert len(recs) == 1
    assert recs[0].text == "RAG 분리"
    assert client.query_records("db-empty") == []
