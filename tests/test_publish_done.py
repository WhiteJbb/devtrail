from app.agents.blog_agent import BlogAgent
from app.config import Settings
from app.models import BlogPost, BlogStatus
from app.notion import mapping


def _agent(tmp_path):
    settings = Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER="")
    return BlogAgent(settings=settings)


def test_publish_done_marks_published_with_url(tmp_path):
    agent = _agent(tmp_path)
    agent.repository.save_draft(BlogPost(title="T", slug="s1", status=BlogStatus.REVIEW))

    post = agent.publish_done("s1", url="https://blog.example/123")
    assert post is not None
    assert post.status == BlogStatus.PUBLISHED
    assert post.published_url == "https://blog.example/123"

    # 로컬 frontmatter에 영속되어야 한다.
    reloaded = agent.repository.get_by_slug("s1")
    assert reloaded.status == BlogStatus.PUBLISHED
    assert reloaded.published_url == "https://blog.example/123"


def test_publish_done_writes_to_notion_mock(tmp_path):
    agent = _agent(tmp_path)
    agent.repository.save_draft(BlogPost(title="T", slug="s1"))
    agent.publish_done("s1", url="https://blog.example/9")

    from app.notion.factory import get_notion_client

    rows = get_notion_client(agent.settings).query_blog_rows()
    assert len(rows) == 1
    assert rows[0].status == "published"
    assert rows[0].published_url == "https://blog.example/9"


def test_publish_done_missing(tmp_path):
    assert _agent(tmp_path).publish_done("nope") is None


def test_published_url_survives_notion_property_roundtrip():
    from app.models import NotionBlogRow

    r = NotionBlogRow(title="t", slug="s", published_url="https://x.test/1")
    page = {"id": "pg", "properties": mapping.row_to_properties(r)}
    back = mapping.page_to_row(page)
    assert back.published_url == "https://x.test/1"
