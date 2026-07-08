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
                    "title": "Devtrail 자동화 구현",
                    "project": "Devtrail",
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
        project="Devtrail"
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


def test_digest_session_line_includes_first_bullet(tmp_path):
    """digest '오늘 한 일'은 제목만이 아니라 본문 첫 불릿을 붙여야 한다.

    세션 노트 제목은 대부분 '<프로젝트> 작업 세션'으로 동일해, 제목만 나열하면
    같은 줄이 세션 수만큼 반복돼 하루를 구분할 수 없다.
    """
    CaptureAgent(settings=_settings(tmp_path), now=datetime(2026, 6, 23, 9, 0, 0)).capture_session(
        project="Devtrail",
        summary_text="## What Changed\n- **훅 크로스플랫폼화** — sh 디스패처 도입\n- weekly fallback 추가",
        from_agent=True,
    )
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert "Devtrail 작업 세션 — 훅 크로스플랫폼화 — sh 디스패처 도입" in result.digest_text


def test_daily_digest_includes_review_question_block(tmp_path):
    """nightly-distill의 daily digest에도 push-digest --daily와 같은 복습 질문이 붙어야 한다(P5.5).

    이전에는 이 블록 조립이 app/cli.py의 push_digest 핸들러에만 인라인돼 있어,
    Telegram 전송본에는 붙고 50_Outputs/Digest/에 저장되는 파일에는 없어 두
    산출물이 영구히 달라졌다.
    """
    session_path = tmp_path / "10_Worklog" / "Sessions" / "2026-06-23-devtrail-session.md"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        "---\nproject: Devtrail\ncreated_at: 2026-06-23T09:00:00\n---\n\n"
        "## Learning Recovery\n\n"
        "### 내가 아직 완전히 이해하지 못한 개념\n- MCP stdio server lifecycle\n\n"
        "### 다음에 직접 설명해봐야 할 질문\n1. MCP stdio 서버는 상시 데몬과 무엇이 다른가?\n",
        encoding="utf-8",
    )

    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))
    result = agent.run()

    assert "오늘의 학습 회수" in result.digest_text
    assert "MCP stdio 서버는 상시 데몬과 무엇이 다른가?" in result.digest_text


def test_weekly_digest_does_not_include_review_question_block(tmp_path):
    """복습 질문은 '하루 1개' 원칙이므로 weekly digest에는 붙지 않아야 한다."""
    session_path = tmp_path / "10_Worklog" / "Sessions" / "2026-06-23-devtrail-session.md"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        "---\nproject: Devtrail\ncreated_at: 2026-06-23T09:00:00\n---\n\n"
        "## Learning Recovery\n\n"
        "### 다음에 직접 설명해봐야 할 질문\n1. 질문 내용\n",
        encoding="utf-8",
    )

    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))
    result = agent.run(weekly=True)

    assert "오늘의 학습 회수" not in result.digest_text


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


# ── 후보 TTL 정리 + 저위험 패치 자동 반영 ────────────────────────────────────


def test_run_expires_old_candidates(tmp_path):
    import frontmatter as fm
    old = tmp_path / "60_Candidates" / "Knowledge" / "stale.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "candidate", "candidate_type": "knowledge", "title": "stale",
            "status": "candidate", "created_at": "2026-05-01"}
    old.write_text(fm.dumps(fm.Post("본문", **meta)), encoding="utf-8")

    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert "60_Candidates/Knowledge/stale.md" in result.expired_candidates
    assert not old.exists()
    assert "## 후보 정리 (TTL 초과)" in result.digest_text


def test_run_auto_applies_low_risk_patches(tmp_path):
    import frontmatter as fm
    patch = tmp_path / "60_Candidates" / "MemoryPatches" / "auto.md"
    patch.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "candidate", "candidate_type": "memory_patch", "title": "자동 교훈",
            "status": "candidate", "created_at": "2026-06-23",
            "requires_user_review": False,
            "target_file": "40_AgentMemory/06_Lessons.md"}
    patch.write_text(fm.dumps(fm.Post("## 교훈\n\n.venv로 테스트", **meta)), encoding="utf-8")

    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert result.auto_applied_patches
    lessons = (tmp_path / "40_AgentMemory" / "06_Lessons.md").read_text(encoding="utf-8")
    assert ".venv로 테스트" in lessons
    # 원본은 applied 마킹
    applied = fm.loads(patch.read_text(encoding="utf-8"))
    assert applied.metadata["status"] == "applied"


def test_run_leaves_review_required_patches_alone(tmp_path):
    import frontmatter as fm
    patch = tmp_path / "60_Candidates" / "MemoryPatches" / "manual.md"
    patch.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "candidate", "candidate_type": "memory_patch", "title": "검토 필요",
            "status": "candidate", "created_at": "2026-06-23",
            "requires_user_review": True}
    patch.write_text(fm.dumps(fm.Post("본문", **meta)), encoding="utf-8")

    _seed_session(tmp_path)
    llm = _MultiCallLLM([_distill_response(), _career_response()])
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run()

    assert result.auto_applied_patches == []
    assert fm.loads(patch.read_text(encoding="utf-8")).metadata["status"] == "candidate"
