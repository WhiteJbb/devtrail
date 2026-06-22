from pathlib import Path

from typer.testing import CliRunner

from app import cli
from app.config import get_settings
from app.services.wiki_service import WikiService


runner = CliRunner()


def test_init_vault_creates_skeleton_without_overwrite(tmp_path):
    service = WikiService(tmp_path)
    result = service.init_vault()

    assert (tmp_path / "00_Inbox" / "Captures").is_dir()
    assert (tmp_path / "20_Knowledge" / "RAG").is_dir()
    assert (tmp_path / "40_AgentMemory" / "00_Profile.md").exists()
    assert (tmp_path / "90_Templates" / "Knowledge.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert result.created_files

    agents = tmp_path / "AGENTS.md"
    agents.write_text("custom rules", encoding="utf-8")
    service.init_vault()
    assert agents.read_text(encoding="utf-8") == "custom rules"


def test_index_vault_parses_frontmatter_tags_and_wikilinks(tmp_path):
    note = tmp_path / "20_Knowledge" / "RAG" / "hybrid-search.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "type: knowledge\n"
        "tags: [rag, search]\n"
        "summary: 검색 전략 정리\n"
        "---\n\n"
        "# Hybrid Search\n\n"
        "BM25와 [[Vector Search|벡터 검색]]을 같이 쓴다. #retrieval\n",
        encoding="utf-8",
    )

    result = WikiService(tmp_path).index_vault()
    assert len(result.notes) == 1
    indexed = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "Hybrid Search" in indexed
    assert "type=knowledge" in indexed
    assert "rag" in result.notes[0].tags
    assert "retrieval" in result.notes[0].tags
    assert result.notes[0].wikilinks == ["Vector Search"]


def test_search_returns_relevant_notes(tmp_path):
    rag = tmp_path / "20_Knowledge" / "RAG" / "rag.md"
    infra = tmp_path / "20_Knowledge" / "Infra" / "docker.md"
    rag.parent.mkdir(parents=True)
    infra.parent.mkdir(parents=True)
    rag.write_text("# RAG Pipeline\n\n검색 증강 생성과 벡터 검색", encoding="utf-8")
    infra.write_text("# Docker\n\n컨테이너 실행", encoding="utf-8")

    results = WikiService(tmp_path).search("벡터 검색")
    assert results
    assert results[0].note.path == "20_Knowledge/RAG/rag.md"


def test_cli_init_index_search(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        init = runner.invoke(cli.app, ["init-vault"])
        assert init.exit_code == 0
        assert "Vault 초기화 완료" in init.output

        note = tmp_path / "20_Knowledge" / "AI" / "agent.md"
        note.write_text("# Agent Memory\n\n작업 맥락 기록", encoding="utf-8")

        index = runner.invoke(cli.app, ["index-vault"])
        assert index.exit_code == 0
        assert "Vault index 갱신 완료" in index.output

        search = runner.invoke(cli.app, ["search", "작업 맥락"])
        assert search.exit_code == 0
        assert "Agent Memory" in search.output
    finally:
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        get_settings.cache_clear()
