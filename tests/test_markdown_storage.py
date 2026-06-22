from app.models import BlogPost, BlogStatus
from app.storage import MarkdownStorage


def test_save_load_roundtrip(tmp_path):
    storage = MarkdownStorage(tmp_path)
    post = BlogPost(
        title="XCoreChat 개발환경 분리",
        slug="20250622-xcorechat",
        body="## 문제\n운영과 개발이 섞였다.",
        tags=["rag", "infra"],
        source_project="XCoreChat",
        status=BlogStatus.DRAFT,
        source_refs=["worklog:worklog", "git:abc123"],
    )

    path = storage.save(post)
    assert path.exists()

    loaded = storage.load(path)
    assert loaded.title == post.title
    assert loaded.slug == post.slug
    assert loaded.tags == ["rag", "infra"]
    assert loaded.status == BlogStatus.DRAFT
    assert loaded.source_refs == post.source_refs
    assert "운영과 개발이 섞였다" in loaded.body
    # local_path가 frontmatter에 반영되어야 한다.
    assert loaded.local_path == str(path)


def test_save_fills_local_path(tmp_path):
    storage = MarkdownStorage(tmp_path)
    post = BlogPost(title="t", slug="s")
    storage.save(post)
    assert post.local_path == str(tmp_path / "s.md")
