"""CandidateWriter의 session_handoff kind 확장 동작을 검증한다."""

from __future__ import annotations

from datetime import datetime

import frontmatter

from app.services.candidate_writer import CandidateSpec, CandidateWriter


def _writer(tmp_path, now=None):
    return CandidateWriter(vault_dir=tmp_path, now=now or datetime(2026, 7, 5))


def test_session_handoff_routes_into_project_subdir(tmp_path):
    writer = _writer(tmp_path)
    spec = CandidateSpec(
        kind="session_handoff",
        title="Plan — Devtrail — 2026-07-05 — abc123",
        body="# Plan\n\n## Goal\n- test",
        project="Devtrail",
        handoff_type="plan",
        session_id="abc123",
    )
    result = writer.write(spec)

    assert result.rel_path == "60_Candidates/SessionHandoffs/Devtrail/Plan — Devtrail — 2026-07-05 — abc123.md"
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["candidate_type"] == "session_handoff"
    assert post.metadata["handoff_type"] == "plan"
    assert post.metadata["session_id"] == "abc123"


def test_session_handoff_without_project_goes_to_unassigned(tmp_path):
    writer = _writer(tmp_path)
    spec = CandidateSpec(kind="session_handoff", title="Plan — 2026-07-05 — xyz", body="body", handoff_type="plan")
    result = writer.write(spec)
    assert result.rel_path.startswith("60_Candidates/SessionHandoffs/_Unassigned/")


def test_session_handoff_dedup_disabled_even_with_similar_titles(tmp_path):
    writer = _writer(tmp_path)
    spec1 = CandidateSpec(
        kind="session_handoff", title="Plan — vault-mcp 작업", body="first", project="Devtrail", handoff_type="plan"
    )
    spec2 = CandidateSpec(
        kind="session_handoff", title="Plan — vault-mcp 작업", body="second", project="Devtrail", handoff_type="plan"
    )
    result1 = writer.write(spec1)
    result2 = writer.write(spec2)

    assert result1.rel_path != result2.rel_path
    assert (tmp_path / result1.rel_path).exists()
    assert (tmp_path / result2.rel_path).exists()


def test_session_handoff_excluded_from_dedup_even_when_dedup_true_passed(tmp_path):
    writer = _writer(tmp_path)
    spec = CandidateSpec(kind="session_handoff", title="Process — Devtrail", body="x", project="Devtrail")
    r1 = writer.write(spec, dedup=True)
    r2 = writer.write(spec, dedup=True)
    assert r1.rel_path != r2.rel_path


def test_knowledge_dedup_still_active(tmp_path):
    writer = _writer(tmp_path)
    spec1 = CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="a")
    spec2 = CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="b")
    r1 = writer.write(spec1)
    r2 = writer.write(spec2)
    assert r1.rel_path == r2.rel_path  # dedup 유지: 동일 후보 재사용


def test_memory_patch_includes_evidence_confidence_review_fields(tmp_path):
    writer = _writer(tmp_path)
    spec = CandidateSpec(
        kind="memory_patch",
        title="반복 실수 — 경로 확인 누락",
        body="다음부터 경로를 먼저 확인한다",
        evidence="세션 중 3회 발생",
        confidence="medium",
        requires_user_review=True,
    )
    result = writer.write(spec)
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["evidence"] == "세션 중 3회 발생"
    assert post.metadata["confidence"] == "medium"
    assert post.metadata["requires_user_review"] is True


def test_write_many_forwards_dedup_flag(tmp_path):
    writer = _writer(tmp_path)
    specs = [
        CandidateSpec(kind="session_handoff", title="Plan A", body="a", project="Devtrail"),
        CandidateSpec(kind="session_handoff", title="Plan A", body="b", project="Devtrail"),
    ]
    results = writer.write_many(specs, dedup=True)
    # session_handoff는 dedup 예외이므로 write_many(dedup=True)를 넘겨도 둘 다 새로 써진다.
    assert results[0].rel_path != results[1].rel_path


def test_session_handoffs_alias_normalizes(tmp_path):
    writer = _writer(tmp_path)
    spec = CandidateSpec(kind="session-handoffs", title="Plan alias test", body="x", project="Devtrail")
    result = writer.write(spec)
    assert "SessionHandoffs" in result.rel_path
