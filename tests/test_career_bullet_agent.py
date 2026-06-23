"""CareerBulletAgent 단위 테스트."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.agents.capture_agent import CaptureAgent
from app.agents.career_bullet_agent import CareerBulletAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _seed_session(vault, project="WorkAgent"):
    CaptureAgent(settings=_settings(vault), now=datetime(2026, 6, 23, 9, 0, 0)).capture_session(
        project=project
    )


def _career_response(n=1):
    bullets = [
        {
            "title": f"XCoreChat 실시간 메시징 구현 {i}",
            "project": "XCoreChat",
            "source_evidence": "세션 노트에서 WebSocket 구현 언급",
            "resume_bullets": ["• WebSocket 기반 실시간 채팅 구현"],
            "portfolio_description": "실시간 채팅 시스템을 WebSocket으로 구현했다.",
            "interview_points": ["WebSocket vs SSE 비교"],
            "caveats": "",
            "source_refs": ["10_Worklog/Daily/session.md"],
            "tags": ["career", "portfolio"],
        }
        for i in range(n)
    ]
    return json.dumps({"career_bullets": bullets}, ensure_ascii=False)


def test_suggest_creates_career_bullet_candidates(tmp_path):
    _seed_session(tmp_path)
    llm = FakeLLM(_career_response(2))
    agent = CareerBulletAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.suggest()

    assert len(result.written) == 2
    for w in result.written:
        assert w.rel_path.startswith("60_Candidates/CareerBullets/")
        text = w.path.read_text(encoding="utf-8")
        assert "candidate_type: career_bullet" in text
        assert "source_refs" in text


def test_suggest_with_project_filter(tmp_path):
    _seed_session(tmp_path, project="XCoreChat")
    llm = FakeLLM(_career_response(1))
    agent = CareerBulletAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.suggest(project="XCoreChat")

    assert len(result.written) == 1
    # 프롬프트에 프로젝트 필터가 포함됐는지 확인
    assert "XCoreChat" in llm.last_prompt


def test_suggest_empty_when_no_notes(tmp_path):
    llm = FakeLLM(_career_response(0))
    agent = CareerBulletAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.suggest()

    assert result.written == []
    # 노트가 없으면 LLM 호출 자체를 안 함
    assert llm.last_prompt == ""


def test_suggest_no_fabricated_metrics_prompt(tmp_path):
    """프롬프트에 과장 금지 지시가 포함돼 있는지 확인."""
    _seed_session(tmp_path)
    llm = FakeLLM(_career_response(1))
    agent = CareerBulletAgent(settings=_settings(tmp_path), llm=llm)
    agent.suggest()

    assert "과장 금지" in llm.last_prompt or "없는 수치" in llm.last_prompt


def test_suggest_includes_source_refs(tmp_path):
    _seed_session(tmp_path)
    llm = FakeLLM(_career_response(1))
    agent = CareerBulletAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.suggest()

    assert len(result.written) == 1
    text = result.written[0].path.read_text(encoding="utf-8")
    assert "source_refs" in text
