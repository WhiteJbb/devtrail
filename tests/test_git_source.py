import subprocess

import pytest

from app.content_sources.git_source import GitSource


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        _git(repo, "init")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git 사용 불가")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "tester")
    (repo / "a.txt").write_text("hello", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "first commit")
    return repo


def test_reads_recent_commits(git_repo):
    chunks = GitSource(git_repo, limit=5).fetch()
    assert len(chunks) == 1
    c = chunks[0]
    assert c.source_type == "git"
    assert "first commit" in c.title
    assert "a.txt" in c.text


def test_includes_diff_content(git_repo):
    chunks = GitSource(git_repo, limit=5, include_diff=True).fetch()
    text = chunks[0].text
    assert "변경 내용(일부)" in text
    assert "hello" in text  # 추가된 라인이 diff에 보임


def test_diff_can_be_disabled(git_repo):
    chunks = GitSource(git_repo, limit=5, include_diff=False).fetch()
    assert "변경 내용(일부)" not in chunks[0].text


def test_diff_respects_max_chars(git_repo):
    chunks = GitSource(git_repo, limit=5, include_diff=True, diff_max_chars=10).fetch()
    assert "diff 일부 생략" in chunks[0].text


def test_non_repo_returns_empty(tmp_path):
    assert GitSource(tmp_path, limit=5).fetch() == []
