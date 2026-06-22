from app.models import BlogPost
from app.notion.mock_client import MockNotionClient
from app.repositories.blog_repository import BlogRepository
from app.repositories.notion_blog_repository import NotionBlogRepository
from app.services.notion_sync_service import NotionSyncService
from app.storage import MarkdownStorage


def _setup(tmp_path):
    blog_repo = BlogRepository(MarkdownStorage(tmp_path / "drafts"))
    notion_repo = NotionBlogRepository(MockNotionClient(tmp_path / "notion.json"))
    service = NotionSyncService(blog_repo, notion_repo)
    return blog_repo, notion_repo, service


def test_dry_run_does_not_write(tmp_path):
    blog_repo, notion_repo, service = _setup(tmp_path)
    blog_repo.save_draft(BlogPost(title="A", slug="20250101-a"))

    report = service.sync(dry_run=True)
    assert report.dry_run is True
    assert report.mode == "mock"
    assert len(report.created) == 1
    # 실제 반영 없음
    assert notion_repo.list_rows() == []


def test_sync_creates_and_writes_back_page_id(tmp_path):
    blog_repo, notion_repo, service = _setup(tmp_path)
    blog_repo.save_draft(BlogPost(title="A", slug="20250101-a"))

    report = service.sync(dry_run=False)
    assert len(report.created) == 1
    assert len(notion_repo.list_rows()) == 1

    # 로컬 frontmatter에 page_id가 기록되어야 한다.
    reloaded = blog_repo.get_by_slug("20250101-a")
    assert reloaded is not None
    assert reloaded.notion_page_id


def test_second_sync_is_update_not_duplicate(tmp_path):
    blog_repo, notion_repo, service = _setup(tmp_path)
    blog_repo.save_draft(BlogPost(title="A", slug="20250101-a"))

    service.sync(dry_run=False)
    report2 = service.sync(dry_run=False)

    assert len(report2.updated) == 1
    assert len(report2.created) == 0
    assert len(notion_repo.list_rows()) == 1  # 중복 생성 없음
