from datetime import datetime
import subprocess

import pytest
from typer.testing import CliRunner

from app import cli
from app.agents.capture_agent import CaptureAgent
from app.config import Settings, get_settings


runner = CliRunner()


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="", MESSENGER_PROVIDER="")


def _agent(vault):
    return CaptureAgent(settings=_settings(vault), now=datetime(2026, 6, 23, 9, 10, 11))


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_capture_writes_inbox_note_and_log(tmp_path):
    result = _agent(tmp_path).capture("오늘 RAG 검색 정리", project="Devtrail")

    assert result.rel_path.startswith("00_Inbox/Memos/")
    text = result.path.read_text(encoding="utf-8")
    assert "type: capture" in text
    assert "project: Devtrail" in text
    assert "오늘 RAG 검색 정리" in text

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "capture | Devtrail" in log
    assert result.rel_path in log


def test_daily_log_is_idempotent(tmp_path):
    agent = _agent(tmp_path)
    first = agent.daily_log()
    first.path.write_text("custom daily log", encoding="utf-8")
    second = agent.daily_log()

    assert first.rel_path == "10_Worklog/Daily/2026-06-23.md"
    assert second.created is False
    assert second.path.read_text(encoding="utf-8") == "custom daily log"


def test_capture_commit_writes_git_summary(tmp_path):
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

    result = _agent(tmp_path).capture_commit(repo, project="Devtrail")

    assert result.rel_path.startswith("10_Worklog/GitSummaries/")
    text = result.path.read_text(encoding="utf-8")
    assert "type: git_summary" in text
    assert "first commit" in text
    assert "a.txt" in text


def test_cli_capture_and_daily_log(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        capture = runner.invoke(cli.app, ["capture", "작업 메모", "--project", "Devtrail"])
        assert capture.exit_code == 0
        assert "capture 생성 완료" in capture.output

        daily = runner.invoke(cli.app, ["daily-log"])
        assert daily.exit_code == 0
        assert "daily log 생성 완료" in daily.output

        assert list((tmp_path / "00_Inbox" / "Memos").glob("*.md"))
        assert (tmp_path / "10_Worklog" / "Daily").exists()
    finally:
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        get_settings.cache_clear()
