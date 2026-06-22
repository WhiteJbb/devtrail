import json

from app.content_sources.notion_source import NotionSource
from app.notion.mock_client import MockNotionClient


def _client_with(tmp_path, data):
    store = tmp_path / "notion.json"
    store.write_text(json.dumps(data), encoding="utf-8")
    return MockNotionClient(store)


def test_reads_db_page_bodies(tmp_path):
    # body가 있으면 요약이 아니라 본문을 읽어야 한다.
    client = _client_with(
        tmp_path,
        {
            "blog_rows": {},
            "records": {
                "db-idea": [{"id": "i1", "title": "아이디어", "text": "짧은요약", "body": "## 본문\n자세한 내용"}],
            },
        },
    )
    chunks = NotionSource(client, idea_database_id="db-idea").fetch()
    assert len(chunks) == 1
    assert chunks[0].source_type == "notion-idea"
    assert "자세한 내용" in chunks[0].text  # 본문 사용
    assert "짧은요약" not in chunks[0].text


def test_body_falls_back_to_summary(tmp_path):
    client = _client_with(
        tmp_path,
        {"blog_rows": {}, "records": {"db-idea": [{"id": "i1", "title": "t", "text": "요약만"}]}},
    )
    chunks = NotionSource(client, idea_database_id="db-idea").fetch()
    assert chunks[0].text == "요약만"


def test_reads_explicit_source_pages(tmp_path):
    client = _client_with(
        tmp_path,
        {"blog_rows": {}, "records": {}, "pages": {"pg-1": "# 정리 문서\n환경 분리 정리"}},
    )
    chunks = NotionSource(client, source_page_ids=["pg-1"]).fetch()
    assert len(chunks) == 1
    assert chunks[0].source_type == "notion-doc"
    assert "환경 분리 정리" in chunks[0].text


def test_empty_returns_nothing(tmp_path):
    client = MockNotionClient(tmp_path / "notion.json")
    assert NotionSource(client).fetch() == []
