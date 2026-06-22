from app.models import BlogPost, BlogStatus
from app.notion import mapping


def test_blog_post_to_row():
    post = BlogPost(
        title="환경 분리",
        slug="20250622-split",
        status=BlogStatus.REVIEW,
        tags=["rag", "infra"],
        source_project="XCoreChat",
        source_refs=["worklog:worklog"],
        notion_page_id="page-1",
    )
    row = mapping.blog_post_to_row(post)
    assert row.title == "환경 분리"
    assert row.status == "review"
    assert row.tags == ["rag", "infra"]
    assert row.page_id == "page-1"


def test_row_to_properties_and_back():
    from app.models import NotionBlogRow

    row = NotionBlogRow(
        title="제목",
        slug="s1",
        status="draft",
        source_project="P",
        tags=["a", "b"],
        local_path="/x/s1.md",
        source_refs=["git:abc", "worklog:worklog"],
        summary="요약",
    )
    props = mapping.row_to_properties(row)
    # Notion page 객체 형태로 감싸 역매핑.
    page = {"id": "pg-1", "properties": props}
    back = mapping.page_to_row(page)
    assert back.title == "제목"
    assert back.slug == "s1"
    assert back.tags == ["a", "b"]
    assert back.source_refs == ["git:abc", "worklog:worklog"]
    assert back.page_id == "pg-1"
