"""Portfolio/Resume 에이전트 테스트 — 새 Vault 기반 아키텍처."""

from pathlib import Path

from app.agents.portfolio_agent import PortfolioAgent
from app.agents.resume_agent import ResumeAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _vault_settings(tmp_path: Path) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(tmp_path))


def test_resume_agent_requires_vault():
    """OBSIDIAN_VAULT_PATH가 없으면 RuntimeError."""
    settings = Settings(OBSIDIAN_VAULT_PATH="", OBSIDIAN_VAULT_DIR="")
    try:
        ResumeAgent(settings=settings)
        assert False, "RuntimeError가 발생해야 합니다"
    except RuntimeError:
        pass


def test_portfolio_agent_requires_vault():
    """OBSIDIAN_VAULT_PATH가 없으면 RuntimeError."""
    settings = Settings(OBSIDIAN_VAULT_PATH="", OBSIDIAN_VAULT_DIR="")
    try:
        PortfolioAgent(settings=settings)
        assert False, "RuntimeError가 발생해야 합니다"
    except RuntimeError:
        pass


def test_resume_agent_saves_to_vault(tmp_path, monkeypatch):
    """ResumeAgent가 50_Outputs/Resume/ 에 저장한다."""
    settings = _vault_settings(tmp_path)
    agent = ResumeAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 이력서 bullet\n- 한 일"))

    result = agent.generate()

    assert result.path.exists()
    assert "50_Outputs" in str(result.path)
    assert "Resume" in str(result.path)
    assert "이력서 bullet" in result.path.read_text(encoding="utf-8")


def test_portfolio_agent_saves_to_vault(tmp_path, monkeypatch):
    """PortfolioAgent가 50_Outputs/Portfolio/ 에 저장한다."""
    settings = _vault_settings(tmp_path)
    agent = PortfolioAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## XCoreChat\n- 한 줄 소개: RAG"))

    result = agent.generate()

    assert result.path.exists()
    assert "50_Outputs" in str(result.path)
    assert "Portfolio" in str(result.path)
    assert "XCoreChat" in result.path.read_text(encoding="utf-8")


def test_resume_agent_includes_project_context(tmp_path, monkeypatch):
    """30_Projects 에 Context.md가 있으면 컨텍스트에 포함된다."""
    settings = _vault_settings(tmp_path)
    project_dir = tmp_path / "30_Projects" / "XCoreChat"
    project_dir.mkdir(parents=True)
    (project_dir / "Context.md").write_text("---\nproject: XCoreChat\n---\nRAG 기반 챗봇", encoding="utf-8")

    captured = {}

    class CaptureLLM:
        name = "capture"
        def complete(self, prompt: str, system: str = "") -> str:
            captured["prompt"] = prompt
            return "## 이력서 bullet\n- XCoreChat 개발"

    agent = ResumeAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: CaptureLLM())
    agent.generate()

    assert "XCoreChat" in captured.get("prompt", "")
