"""파이프라인 개선 사항 테스트 — dedup, interactive apply, promote+wiki, weekly-distill."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.capture_agent import CaptureAgent
from app.agents.distill_agent import DistillAgent
from app.agents.nightly_distill_agent import NightlyDistillAgent
from app.config import Settings
from app.services.candidate_writer import CandidateSpec, CandidateWriter
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _seed_session(vault, days_ago=0, project="WorkAgent"):
    dt = datetime.now() - timedelta(days=days_ago)
    CaptureAgent(settings=_settings(vault), now=dt).capture_session(project=project)


# ── Candidate Dedup ───────────────────────────────────────────────────────────

def test_dedup_prevents_duplicate_title(tmp_path):
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23, 9, 0))
    spec = CandidateSpec(kind="knowledge", title="RAG 검색 전략", body="내용", source_refs=[])
    r1 = writer.write(spec)
    r2 = writer.write(spec)  # 같은 제목 재시도

    assert r1.rel_path == r2.rel_path  # 동일 파일 반환
    # 실제로 두 번째 파일은 생성되지 않음
    files = list((tmp_path / "60_Candidates" / "Knowledge").glob("*.md"))
    assert len(files) == 1


def test_dedup_similar_title_blocked(tmp_path):
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23, 9, 0))
    spec1 = CandidateSpec(kind="knowledge", title="RAG 검색 전략 개요", body="내용", source_refs=[])
    spec2 = CandidateSpec(kind="knowledge", title="RAG 검색 전략 개요 정리", body="내용2", source_refs=[])
    r1 = writer.write(spec1)
    r2 = writer.write(spec2)

    assert r1.rel_path == r2.rel_path


def test_dedup_different_title_allowed(tmp_path):
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23, 9, 0))
    spec1 = CandidateSpec(kind="knowledge", title="RAG 검색 전략", body="내용", source_refs=[])
    spec2 = CandidateSpec(kind="knowledge", title="vLLM 배포 가이드", body="내용2", source_refs=[])
    r1 = writer.write(spec1)
    r2 = writer.write(spec2)

    assert r1.rel_path != r2.rel_path


def test_dedup_different_kind_allowed(tmp_path):
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23, 9, 0))
    spec1 = CandidateSpec(kind="knowledge", title="RAG 전략", body="내용", source_refs=[])
    spec2 = CandidateSpec(kind="blog_idea", title="RAG 전략", body="내용2", source_refs=[])
    r1 = writer.write(spec1)
    r2 = writer.write(spec2)

    assert r1.rel_path != r2.rel_path  # kind가 다르면 별도 파일


def test_dedup_disabled(tmp_path):
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23, 9, 0))
    spec = CandidateSpec(kind="knowledge", title="RAG 검색 전략", body="내용", source_refs=[])
    r1 = writer.write(spec, dedup=False)
    r2 = writer.write(spec, dedup=False)

    assert r1.rel_path != r2.rel_path  # dedup 비활성 → 각각 생성


def test_dedup_old_candidates_ignored(tmp_path):
    """_DEDUP_LOOKBACK_DAYS보다 오래된 후보는 dedup 대상에서 제외한다."""
    from app.services.candidate_writer import _DEDUP_LOOKBACK_DAYS
    old_date = datetime.now() - timedelta(days=_DEDUP_LOOKBACK_DAYS + 1)
    writer_old = CandidateWriter(vault_dir=tmp_path, now=old_date)
    spec = CandidateSpec(kind="knowledge", title="RAG 검색 전략", body="내용", source_refs=[])
    r1 = writer_old.write(spec)

    writer_new = CandidateWriter(vault_dir=tmp_path, now=datetime.now())
    r2 = writer_new.write(spec)

    assert r1.rel_path != r2.rel_path  # 오래된 후보는 무시 → 새로 생성


# ── distill_range (weekly) ────────────────────────────────────────────────────

def _distill_response():
    return json.dumps({
        "knowledge": [{"title": "지식", "summary": "요약", "body": "내용", "project": "", "tags": [], "source_refs": []}],
        "decisions": [], "memory_patches": [], "blog_ideas": [],
    }, ensure_ascii=False)


def test_distill_range_collects_multi_day_notes(tmp_path):
    for days_ago in range(5):
        _seed_session(tmp_path, days_ago=days_ago)

    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm)
    result = agent.distill_range(days=7)

    assert len(result.written) == 1
    # 5일치 노트가 컨텍스트에 포함됐는지 확인
    assert len(result.source_refs) >= 3


def test_distill_range_excludes_old_notes(tmp_path):
    _seed_session(tmp_path, days_ago=0)   # 오늘
    _seed_session(tmp_path, days_ago=10)  # 10일 전 (범위 밖)

    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm)
    result = agent.distill_range(days=7)

    # source_refs에 오늘 노트만 있어야 함
    assert len(result.source_refs) == 1


# ── weekly-distill digest ─────────────────────────────────────────────────────

def _career_response():
    return json.dumps({"career_bullets": []}, ensure_ascii=False)


class _TwoCallLLM:
    name = "two"; model = "two"
    def __init__(self, r1, r2):
        self.responses = [r1, r2]; self.calls = 0
    def complete(self, prompt, system=""):
        r = self.responses[min(self.calls, 1)]; self.calls += 1; return r


def test_weekly_distill_saves_weekly_digest(tmp_path):
    _seed_session(tmp_path)
    llm = _TwoCallLLM(_distill_response(), _career_response())
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run(weekly=True)

    assert result.digest_rel_path.endswith("-weekly-digest.md")
    assert result.digest_path is not None and result.digest_path.exists()
    assert "Weekly Digest" in result.digest_path.read_text(encoding="utf-8")


def test_daily_distill_saves_daily_digest(tmp_path):
    _seed_session(tmp_path)
    llm = _TwoCallLLM(_distill_response(), _career_response())
    agent = NightlyDistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23))

    result = agent.run(weekly=False)

    assert result.digest_rel_path.endswith("-daily-digest.md")
    assert "Daily Digest" in result.digest_path.read_text(encoding="utf-8")


# ── promote → wiki 자동 연동 (CLI 레벨) ─────────────────────────────────────

def test_promote_candidate_cli_calls_wiki_ingest(tmp_path):
    from typer.testing import CliRunner
    from app import cli
    from app.services.candidate_writer import CandidateWriter
    import frontmatter

    # knowledge 후보 파일 생성
    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23))
    spec = CandidateSpec(kind="knowledge", title="테스트 지식", body="내용", source_refs=[])
    result = writer.write(spec)

    runner = CliRunner()
    with patch("app.cli.get_settings") as mock_settings, \
         patch("app.agents.wiki_agent.build_wiki_agent") as mock_wiki:
        mock_settings.return_value = _settings(tmp_path)
        mock_wiki.return_value = MagicMock(ingest=MagicMock(return_value="wiki 1개 갱신"))

        response = runner.invoke(cli.app, ["promote-candidate", result.rel_path])

    assert response.exit_code == 0
    assert "승격 완료" in response.output
    mock_wiki.assert_called_once()


def test_promote_candidate_no_wiki_flag(tmp_path):
    from typer.testing import CliRunner
    from app import cli

    writer = CandidateWriter(vault_dir=tmp_path, now=datetime(2026, 6, 23))
    spec = CandidateSpec(kind="knowledge", title="테스트 지식2", body="내용", source_refs=[])
    result = writer.write(spec)

    runner = CliRunner()
    with patch("app.cli.get_settings") as mock_settings, \
         patch("app.agents.wiki_agent.build_wiki_agent") as mock_wiki:
        mock_settings.return_value = _settings(tmp_path)

        response = runner.invoke(cli.app, ["promote-candidate", result.rel_path, "--no-wiki"])

    assert response.exit_code == 0
    mock_wiki.assert_not_called()
