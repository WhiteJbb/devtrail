"""`work-agent project-briefing` CLI 테스트 (P4.4 — SessionStart 훅이 호출하는 명령).

이 명령은 어떤 예외 상황에서도 훅 전체를 실패시키지 않도록 항상 exit code 0으로
끝나야 한다.
"""

from __future__ import annotations

from typer.testing import CliRunner

from app import cli
from app.config import get_settings

runner = CliRunner()


def test_project_briefing_exits_zero_without_vault(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli.app, ["project-briefing", "."])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0
    assert "OBSIDIAN_VAULT_PATH" in result.output


def test_project_briefing_prints_text(tmp_path, monkeypatch):
    (tmp_path / "30_Projects" / "Devtrail").mkdir(parents=True)
    (tmp_path / "30_Projects" / "Devtrail" / "Context.md").write_text(
        "---\nproject: Devtrail\n---\n\n프로젝트 컨텍스트 본문", encoding="utf-8"
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli.app, ["project-briefing", "Devtrail"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0
    assert "프로젝트 컨텍스트 본문" in result.output


def test_project_briefing_never_raises_on_unexpected_error(tmp_path, monkeypatch):
    """briefing 조회 중 예외가 나도 exit code 0으로 안내문만 출력해야 한다."""
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    get_settings.cache_clear()

    def _boom(*a, **k):
        raise RuntimeError("일부러 낸 에러")

    monkeypatch.setattr("app.vault_tools.get_project_briefing", _boom)
    try:
        result = runner.invoke(cli.app, ["project-briefing", "."])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0
    assert "briefing 조회 실패" in result.output
