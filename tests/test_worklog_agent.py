"""WorklogAgent 테스트 — 새 Vault 기반 아키텍처."""

from pathlib import Path

from app.agents.worklog_agent import WorklogAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _vault_settings(tmp_path: Path) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(tmp_path))


def test_worklog_agent_requires_vault():
    """OBSIDIAN_VAULT_PATH가 없으면 RuntimeError."""
    settings = Settings(OBSIDIAN_VAULT_PATH="", OBSIDIAN_VAULT_DIR="")
    try:
        WorklogAgent(settings=settings)
        assert False, "RuntimeError가 발생해야 합니다"
    except RuntimeError:
        pass


def test_worklog_agent_saves_to_vault(tmp_path, monkeypatch):
    """WorklogAgent가 10_Worklog/Summaries/ 에 저장한다."""
    settings = _vault_settings(tmp_path)
    agent = WorklogAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 한 일\n- 작업"))

    result = agent.generate()

    assert result.path.exists()
    assert "10_Worklog" in str(result.path)
    assert "Summaries" in str(result.path)
    assert "## 한 일" in result.path.read_text(encoding="utf-8")


def test_worklog_agent_uses_raw_notes(tmp_path, monkeypatch):
    """00_Inbox 에 raw 기록이 있으면 컨텍스트에 포함된다."""
    settings = _vault_settings(tmp_path)
    inbox_dir = tmp_path / "00_Inbox" / "Captures"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "20250101-120000-memo.md").write_text(
        "---\ntype: capture\ndate: 2025-01-01\n---\n환경 분리 작업 완료",
        encoding="utf-8",
    )

    captured = {}

    class CaptureLLM:
        name = "capture"
        def complete(self, prompt: str, system: str = "") -> str:
            captured["prompt"] = prompt
            return "## 한 일\n- 환경 분리"

    agent = WorklogAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: CaptureLLM())
    agent.generate()

    assert "환경 분리 작업 완료" in captured.get("prompt", "")


def test_worklog_agent_save_false_no_file(tmp_path, monkeypatch):
    """save=False이면 파일을 만들지 않는다."""
    settings = _vault_settings(tmp_path)
    agent = WorklogAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 한 일\n- 작업"))

    result = agent.generate(save=False)

    assert result.text == "## 한 일\n- 작업"
    assert not result.path.exists()
