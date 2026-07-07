"""init-project 스캐폴드 테스트 — 서비스 / CLI / briefing 연동."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from app import cli
from app.config import get_settings
from app.memory.project_memory_loader import ProjectMemoryLoader
from app.services.wiki_service import PROJECT_SUBDIRS, WikiService


runner = CliRunner()


# ── 서비스 ────────────────────────────────────────────────────────────────────

def test_init_project_creates_scaffold(tmp_path):
    result = WikiService(tmp_path).init_project("Orbit")

    base = tmp_path / "30_Projects" / "Orbit"
    for sub in PROJECT_SUBDIRS:
        assert (base / sub).is_dir()
    assert (base / "Context.md").exists()
    assert (base / "PromptLog.md").exists()
    assert (base / "Design" / "IA.md").exists()
    assert (base / "Design" / "UserScenarios.md").exists()
    assert (base / "Design" / "Personas.md").exists()
    assert result.created_files


def test_init_project_preserves_existing_files(tmp_path):
    service = WikiService(tmp_path)
    service.init_project("Orbit")
    context = tmp_path / "30_Projects" / "Orbit" / "Context.md"
    context.write_text("custom context", encoding="utf-8")

    again = service.init_project("Orbit")

    assert context.read_text(encoding="utf-8") == "custom context"
    assert not again.created_files


def test_init_project_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError):
        WikiService(tmp_path).init_project("  ")


def test_init_project_context_is_loadable_by_project_memory(tmp_path):
    """생성된 Context.md의 body가 비어 있지 않아 ProjectMemoryLoader가 인식해야 한다."""
    WikiService(tmp_path).init_project("Orbit")

    memory = ProjectMemoryLoader(tmp_path).load()

    ctx = memory.find("orbit")  # 대소문자 무시 매칭
    assert ctx is not None
    assert ctx.project == "Orbit"


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_init_project_with_repo_mapping(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    vault.mkdir()
    repo.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    get_settings.cache_clear()

    try:
        out = runner.invoke(cli.app, ["init-project", "Orbit", "--repo", str(repo)])
        assert out.exit_code == 0, out.output
        assert "프로젝트 초기화 완료" in out.output

        config = json.loads((repo / ".claude" / "vault.json").read_text(encoding="utf-8"))
        assert config["project"] == "Orbit"
    finally:
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        get_settings.cache_clear()


def test_cli_init_project_repo_mapping_preserves_other_keys(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    vault.mkdir()
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "vault.json").write_text(
        json.dumps({"project": "Old", "other": True}), encoding="utf-8"
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    get_settings.cache_clear()

    try:
        out = runner.invoke(cli.app, ["init-project", "Orbit", "--repo", str(repo)])
        assert out.exit_code == 0, out.output

        config = json.loads((repo / ".claude" / "vault.json").read_text(encoding="utf-8"))
        assert config["project"] == "Orbit"
        assert config["other"] is True
    finally:
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        get_settings.cache_clear()
