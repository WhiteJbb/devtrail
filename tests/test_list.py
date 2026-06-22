import time

from typer.testing import CliRunner

from app import cli
from app.agents.blog_agent import BlogAgent
from app.config import Settings
from app.models import BlogPost, BlogStatus

runner = CliRunner()


def _agent(tmp_path):
    return BlogAgent(settings=Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER=""))


def test_list_drafts_sorted_desc(tmp_path):
    agent = _agent(tmp_path)
    agent.repository.save_draft(BlogPost(title="첫째", slug="a"))
    time.sleep(0.01)
    agent.repository.save_draft(BlogPost(title="둘째", slug="b"))

    posts = agent.list_drafts()
    assert [p.title for p in posts] == ["둘째", "첫째"]


def test_cli_list_empty(monkeypatch, tmp_path):
    class _A(_agent(tmp_path).__class__):
        def __init__(self, *a, **k):
            super().__init__(settings=Settings(WORKSPACE_DIR=str(tmp_path / "empty"), LLM_PROVIDER=""))

    monkeypatch.setattr(cli, "BlogAgent", _A)
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    assert "저장된 초안이 없습니다" in result.output


def test_cli_list_shows_entries(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    agent.repository.save_draft(BlogPost(title="공개글", slug="20250101-x", status=BlogStatus.PUBLISHED))

    monkeypatch.setattr(cli, "BlogAgent", lambda *a, **k: agent)
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    assert "공개글" in result.output
    assert "published" in result.output
    assert "총 1건" in result.output
