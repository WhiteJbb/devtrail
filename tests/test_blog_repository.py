import time

from app.models import BlogPost
from app.repositories.blog_repository import BlogRepository, slugify
from app.storage import MarkdownStorage


def make_repo(tmp_path):
    return BlogRepository(MarkdownStorage(tmp_path))


def test_slugify_ascii():
    assert slugify("XCoreChat Dev Split!") == "xcorechat-dev-split"


def test_build_slug_korean_has_date_prefix(tmp_path):
    repo = make_repo(tmp_path)
    slug = repo.build_slug("한글 제목")
    # 비ASCII만 있으면 날짜 + draft 형태로 떨어진다.
    assert slug.endswith("-draft")
    assert slug[:8].isdigit()


def test_save_and_get_latest(tmp_path):
    repo = make_repo(tmp_path)
    repo.save_draft(BlogPost(title="첫째", slug="20250101-a"))
    time.sleep(0.01)
    repo.save_draft(BlogPost(title="둘째", slug="20250102-b"))

    latest = repo.get_latest()
    assert latest is not None
    assert latest.title == "둘째"
    assert len(repo.list_drafts()) == 2


def test_save_draft_autogenerates_slug(tmp_path):
    repo = make_repo(tmp_path)
    post = BlogPost(title="Auto Slug Title", slug="")
    repo.save_draft(post)
    assert post.slug
    assert repo.get_by_slug(post.slug) is not None


def test_get_by_slug_missing(tmp_path):
    assert make_repo(tmp_path).get_by_slug("nope") is None
