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


_LONG_PROCESS = (
    "---\nproject: Devtrail\ncreated_at: 2025-01-01T09:00:00\ntype: session\n---\n\n"
    "# Process\n\n## What Changed\n- 변경 요약\n\n"
    "## Files Touched\n" + "- app/file.py — 수정\n" * 800 + "\n"
    "## Next Session\n1. 꼬리에 있는 다음 할 일\n"
)


def test_worklog_agent_keeps_tail_sections_of_long_process_note(tmp_path, monkeypatch):
    """긴 Process 노트를 앞에서 자르면 Next Session이 LLM에 도달하지 못한다."""
    settings = _vault_settings(tmp_path)
    session_dir = tmp_path / "10_Worklog" / "Sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "2025-01-01-devtrail-session.md").write_text(_LONG_PROCESS, encoding="utf-8")

    captured = {}

    class CaptureLLM:
        name = "capture"
        def complete(self, prompt: str, system: str = "") -> str:
            captured["prompt"] = prompt
            return "## 결과\n- 항목"

    agent = WorklogAgent(settings=settings)
    monkeypatch.setattr(agent, "_llm", lambda: CaptureLLM())
    agent.generate()

    assert "꼬리에 있는 다음 할 일" in captured["prompt"]
    assert "app/file.py" not in captured["prompt"]
