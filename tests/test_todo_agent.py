"""TodoAgent 테스트 — 새 Vault 기반 아키텍처."""

from pathlib import Path

from app.agents.todo_agent import TodoAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _vault_settings(tmp_path: Path) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(tmp_path))


def test_todo_agent_requires_vault():
    """OBSIDIAN_VAULT_PATH가 없으면 RuntimeError."""
    settings = Settings(OBSIDIAN_VAULT_PATH="", OBSIDIAN_VAULT_DIR="")
    try:
        TodoAgent(settings=settings)
        assert False, "RuntimeError가 발생해야 합니다"
    except RuntimeError:
        pass


def test_todo_agent_saves_to_vault(tmp_path, monkeypatch):
    """TodoAgent가 50_Outputs/Todo/ 에 저장한다."""
    settings = _vault_settings(tmp_path)
    agent = TodoAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 다음 할 일\n- [ ] 작업"))

    result = agent.generate()

    assert result.path.exists()
    assert "50_Outputs" in str(result.path)
    assert "Todo" in str(result.path)
    assert "다음 할 일" in result.path.read_text(encoding="utf-8")


def test_todo_agent_uses_raw_notes(tmp_path, monkeypatch):
    """10_Worklog 에 raw 기록이 있으면 컨텍스트에 포함된다."""
    settings = _vault_settings(tmp_path)
    daily_dir = tmp_path / "10_Worklog" / "Daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2025-01-01.md").write_text(
        "---\ntype: worklog\ndate: 2025-01-01\n---\n헬스체크 미완",
        encoding="utf-8",
    )

    captured = {}

    class CaptureLLM:
        name = "capture"
        def complete(self, prompt: str, system: str = "") -> str:
            captured["prompt"] = prompt
            return "## 다음 할 일\n- [ ] 헬스체크 추가"

    agent = TodoAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: CaptureLLM())
    agent.generate()

    assert "헬스체크 미완" in captured.get("prompt", "")


def test_todo_agent_save_false_no_file(tmp_path, monkeypatch):
    """save=False이면 파일을 만들지 않는다."""
    settings = _vault_settings(tmp_path)
    agent = TodoAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 다음 할 일\n- [ ] 작업"))

    result = agent.generate(save=False)

    assert result.text == "## 다음 할 일\n- [ ] 작업"
    assert not result.path.exists()
