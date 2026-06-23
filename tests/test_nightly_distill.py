"""NightlyDistillAgent 단위 테스트."""

import json
from datetime import datetime

from app.agents.capture_agent import CaptureAgent
from app.agents.nightly_distill_agent import NightlyDistillAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _distill_response():
    return json.dumps(
        {
            "knowledge": [{"title": "지식 후보", "summary": "요약", "body": "내용", "project": "", "tags": [], "source_refs": []}],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [{"title": "블로그 후보", "summary": "요약", "body": "내용", "project": "", "tags": [], "source_refs": []}],
        },
        ensure_ascii=False,
    )


def _career_response():
    return json.dumps(
        {
            "career_bullets": [
                {
                    "title": "WorkAgent 자동화 구현",
                    "project": "WorkAgent",
                    "source_evidence": "세션 노트",
                    "resume_bullets": ["• 자동화"],
                    "portfolio_description": "설명",
                    "interview_points": [],
                    "caveats": "",
                    "source_refs": [],
                    "tags": ["career"],
                }
            ]
        },
        ensure_ascii=False,
    )


class _MultiCallLLM:
    """distill 호출과 career 호출에 순서대로 다른 응답을 반환하는 LLM stub."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    name = "multi"
    model = "multi"

    def complete(self, prompt: str, system: str = "") -> str:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]


def _seed_session(vault):
    CaptureAgent(settings=_settings(vault), now=datetime(2026, 6, 23, 9, 0, 0)).capture_session(
        project="WorkAgent"
    )


def test_run_creates_all_candidate_types(tmp_path):
    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    # distill: knowledge + blog_idea = 2
    assert len(result.distill.written) == 2
    # career: 1
    assert len(result.career.written) == 1

    rels = [w.rel_path for w in result.distill.written]
    assert any(r.startswith("60_Candidates/Knowledge/") for r in rels)
    assert any(r.startswith("60_Candidates/BlogIdeas/") for r in rels)
    assert result.career.written[0].rel_path.startswith("60_Candidates/CareerBullets/")


def test_run_saves_digest(tmp_path):
    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert result.digest_path is not None
    assert result.digest_path.exists()
    assert result.digest_rel_path.startswith("50_Outputs/Digest/")
    text = result.digest_path.read_text(encoding="utf-8")
    assert "Daily Digest" in text
    assert "블로그 후보" in text


def test_run_no_llm_call_when_no_notes(tmp_path):
    """오늘 노트가 없으면 LLM을 호출하지 않는다."""
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert llm.calls == 0
    assert result.distill.written == []
    assert result.career.written == []


def test_run_no_telegram_when_not_configured(tmp_path):
    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert result.sent_telegram is False
