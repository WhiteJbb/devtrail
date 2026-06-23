"""OpenLoopsAgent 단위 테스트."""

import json
from datetime import datetime

import pytest

from app.agents.capture_agent import CaptureAgent
from app.agents.open_loops_agent import OpenLoopsAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _seed_session(vault):
    CaptureAgent(settings=_settings(vault), now=datetime(2026, 6, 23, 9, 0, 0)).capture_session(
        project="WorkAgent"
    )


def _loops_response():
    return json.dumps(
        {
            "add": [{"item": "STT provider 설정 필요", "source_ref": "10_Worklog/Daily/session.md", "priority": "medium"}],
            "complete": [],
            "defer": [{"item": "wiki-lint 자동화", "reason": "우선순위 낮음"}],
            "rationale": "STT 미설정 이슈가 새로 생겼다.",
        },
        ensure_ascii=False,
    )


def test_suggest_creates_memory_patch_candidate(tmp_path):
    _seed_session(tmp_path)
    llm = FakeLLM(_loops_response())
    agent = OpenLoopsAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.suggest()

    assert len(result.written) == 1
    w = result.written[0]
    assert w.rel_path.startswith("60_Candidates/MemoryPatches/")
    text = w.path.read_text(encoding="utf-8")
    assert "candidate_type: memory_patch" in text
    assert "추가할 항목" in text
    assert "보류할 항목" in text


def test_does_not_modify_agent_memory_directly(tmp_path):
    """update-open-loops는 40_AgentMemory를 직접 수정하면 안 된다."""
    _seed_session(tmp_path)
    llm = FakeLLM(_loops_response())
    agent = OpenLoopsAgent(settings=_settings(tmp_path), llm=llm)

    agent.suggest()

    open_loops_path = tmp_path / "40_AgentMemory" / "05_OpenLoops.md"
    assert not open_loops_path.exists()


def test_suggest_empty_when_no_notes(tmp_path):
    llm = FakeLLM(_loops_response())
    agent = OpenLoopsAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.suggest()

    assert result.written == []
    assert llm.last_prompt == ""


def test_reads_existing_open_loops(tmp_path):
    """기존 05_OpenLoops.md가 있으면 프롬프트에 포함한다."""
    _seed_session(tmp_path)
    loops_dir = tmp_path / "40_AgentMemory"
    loops_dir.mkdir(parents=True, exist_ok=True)
    (loops_dir / "05_OpenLoops.md").write_text("- [ ] 기존 미해결 이슈", encoding="utf-8")

    llm = FakeLLM(_loops_response())
    agent = OpenLoopsAgent(settings=_settings(tmp_path), llm=llm)
    agent.suggest()

    assert "기존 미해결 이슈" in llm.last_prompt
