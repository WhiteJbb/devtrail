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
        scope="project",
        confidence="medium",
        requires_user_review=True,
    )
    result = writer.write(spec)
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["evidence"] == "세션 중 3회 발생"
    assert post.metadata["scope"] == "project"
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

# ── 갱신형 dedup ─────────────────────────────────────────────────────────────


def test_dedup_updates_existing_candidate_body(tmp_path):
    """유사 후보 재생성 시 새 파일 대신 기존 파일의 body가 갱신된다."""
    writer = _writer(tmp_path)
    r1 = writer.write(CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="옛 내용",
                                    source_refs=["10_Worklog/Sessions/a.md"]))
    r2 = writer.write(CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="새 내용",
                                    source_refs=["10_Worklog/Sessions/b.md"]))

    assert r1.rel_path == r2.rel_path
    post = frontmatter.loads(r2.path.read_text(encoding="utf-8"))
    assert "새 내용" in post.content
    assert "옛 내용" not in post.content
    assert post.metadata["updated_at"]
    # source_refs는 합집합으로 병합
    assert "10_Worklog/Sessions/a.md" in post.metadata["source_refs"]
    assert "10_Worklog/Sessions/b.md" in post.metadata["source_refs"]


def test_long_title_produces_short_filename_but_full_title_preserved(tmp_path):
    """title이 길어도 파일명은 잘리고(경로 길이 제한 회피), frontmatter/본문 title은 그대로 남는다."""
    writer = _writer(tmp_path)
    long_title = (
        "Devtrail — Windows에서 셸 스크립트를 만들거나 이동하면 git에 실행 비트 없이(100644) 커밋된다. "
        "PR #35의 scripts/mac 이동이 그렇게 커밋돼, Mac nightly가 07-06부터 매일 밤 'Permission denied'로 "
        "1단계(update-devtrail)에서 중단됐다."
    )
    spec = CandidateSpec(kind="memory_patch", title=long_title, body="원인과 해결")
    result = writer.write(spec)

    filename = result.path.stem
    assert len(filename) <= 50
    assert not filename.endswith(" ")

    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["title"] == long_title
    assert long_title in post.content  # 본문 H1에도 원문 그대로


def test_dedup_does_not_touch_promoted_candidate(tmp_path):
    """사람이 promote한 파일(status!=candidate)은 덮어쓰지 않는다."""
    writer = _writer(tmp_path)
    r1 = writer.write(CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="원본"))
    post = frontmatter.loads(r1.path.read_text(encoding="utf-8"))
    post.metadata["status"] = "promoted"
    r1.path.write_text(frontmatter.dumps(post), encoding="utf-8")

    r2 = writer.write(CandidateSpec(kind="knowledge", title="RAG 파이프라인 구조", body="변경 시도"))

    assert r2.rel_path == r1.rel_path
    final = frontmatter.loads(r1.path.read_text(encoding="utf-8"))
    assert "원본" in final.content
    assert "변경 시도" not in final.content
