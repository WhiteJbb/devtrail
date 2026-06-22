from app.models import BlogPost, BlogStatus
from app.repositories.blog_repository import BlogRepository
from app.services.tistory_exporter import TistoryExporter
from app.storage import MarkdownStorage


def _setup(tmp_path):
    repo = BlogRepository(MarkdownStorage(tmp_path / "drafts"))
    exporter = TistoryExporter(repo, tmp_path / "blogs")
    return repo, exporter


def test_export_html(tmp_path):
    repo, exporter = _setup(tmp_path)
    body = "## 문제\n본문\n\n- 항목\n\n```bash\ndocker compose up\n```"
    repo.save_draft(BlogPost(title="T", slug="s1", body=body))

    result = exporter.export("latest", "html")
    assert result is not None
    assert result.path.suffix == ".html"
    html = result.path.read_text(encoding="utf-8")
    assert "<h2>" in html
    assert "<li>" in html
    assert "<pre><code" in html  # 펜스 코드블록이 보존되어야 한다


def test_export_md_keeps_body(tmp_path):
    repo, exporter = _setup(tmp_path)
    repo.save_draft(BlogPost(title="T", slug="s1", body="## 문제\n본문"))
    result = exporter.export("s1", "md")
    assert result.path.suffix == ".md"
    assert "## 문제" in result.path.read_text(encoding="utf-8")


def test_export_marks_review(tmp_path):
    repo, exporter = _setup(tmp_path)
    repo.save_draft(BlogPost(title="T", slug="s1", body="x", status=BlogStatus.DRAFT))
    exporter.export("s1", "html")
    # 상태 추적: draft → review
    assert repo.get_by_slug("s1").status == BlogStatus.REVIEW


def test_export_missing_returns_none(tmp_path):
    _, exporter = _setup(tmp_path)
    assert exporter.export("latest", "html") is None


def test_invalid_format_raises(tmp_path):
    repo, exporter = _setup(tmp_path)
    repo.save_draft(BlogPost(title="T", slug="s1", body="x"))
    import pytest

    with pytest.raises(ValueError):
        exporter.export("s1", "pdf")
