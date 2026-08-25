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


def test_source_refs_render_as_wikilinks(tmp_path):
    """body의 ## Source Refs는 vault 내부 노트를 wikilink로 렌더링해야 한다.

    일반 텍스트 경로는 Obsidian 그래프/백링크에 잡히지 않아 후보 노트가 소스
    세션/메모와 연결되지 않는다. git 커밋 참조 같은 노트 외 참조는 그대로 둔다.
    """
    writer = _writer(tmp_path)
    spec = CandidateSpec(
        kind="knowledge",
        title="링크 렌더링 테스트",
        body="본문",
        source_refs=["10_Worklog/Sessions/2026-07-08-devtrail-session.md", "git:abc1234567"],
    )
    result = writer.write(spec)

    text = result.path.read_text(encoding="utf-8")
    assert "- [[10_Worklog/Sessions/2026-07-08-devtrail-session]]" in text
    assert "- git:abc1234567" in text
    # frontmatter의 source_refs는 코드가 읽는 데이터라 평문 경로를 유지한다
    post = frontmatter.loads(text)
    assert post.metadata["source_refs"] == [
        "10_Worklog/Sessions/2026-07-08-devtrail-session.md", "git:abc1234567",
    ]


# ── blog_idea thread 누적 ────────────────────────────────────────────


def _thread_spec(**kw) -> CandidateSpec:
    base = dict(
        kind="blog_idea",
        title="홈랩 구축기 — 1일차",
        summary="1일차 요지",
        body="## 핵심 메시지\n\n집에서 서버를 굴린 이야기.\n\n## 목차 초안\n\n1. 도입\n",
        thread="homelab-build-2026",
        source_refs=["10_Worklog/Sessions/day1.md"],
    )
    base.update(kw)
    return CandidateSpec(**base)


def test_thread_creates_new_file_with_thread_frontmatter(tmp_path):
    result = _writer(tmp_path, now=datetime(2026, 8, 24)).write(_thread_spec())

    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert post.metadata["thread"] == "homelab-build-2026"
    assert post.metadata["thread_last_added"] == 1


def test_thread_merges_into_existing_candidate(tmp_path):
    first = _writer(tmp_path, now=datetime(2026, 8, 24)).write(_thread_spec())
    second = _writer(tmp_path, now=datetime(2026, 8, 25)).write(
        _thread_spec(
            title="홈랩 구축기 — 2일차 NAS 붙이기",
            summary="NAS를 붙이며 겪은 문제",
            body="## 핵심 메시지\n\n완전히 다른 목차\n",
            source_refs=["10_Worklog/Sessions/day1.md", "10_Worklog/Sessions/day2.md"],
        )
    )

    ideas = list((tmp_path / "60_Candidates/BlogIdeas").glob("*.md"))
    assert len(ideas) == 1  # 새 파일이 생기지 않는다
    assert second.rel_path == first.rel_path

    post = frontmatter.loads(second.path.read_text(encoding="utf-8"))
    assert post.metadata["source_refs"] == [
        "10_Worklog/Sessions/day1.md",
        "10_Worklog/Sessions/day2.md",
    ]
    assert post.metadata["title"] == "홈랩 구축기 — 1일차"  # 제목은 유지
    assert "완전히 다른 목차" not in post.content
    assert "## Updates" in post.content
    assert "- 2026-08-25: NAS를 붙이며 겪은 문제" in post.content
    assert post.metadata["updated_at"].startswith("2026-08-25")
    assert post.metadata["thread_last_added"] == 1
    # 본문 Source Refs도 누적본으로 갱신된다
    assert "[[10_Worklog/Sessions/day2]]" in post.content


def test_thread_merge_appends_second_update_line(tmp_path):
    _writer(tmp_path, now=datetime(2026, 8, 24)).write(_thread_spec())
    _writer(tmp_path, now=datetime(2026, 8, 25)).write(
        _thread_spec(summary="2일차", source_refs=["10_Worklog/Sessions/day2.md"])
    )
    result = _writer(tmp_path, now=datetime(2026, 8, 26)).write(
        _thread_spec(summary="3일차", source_refs=["10_Worklog/Sessions/day3.md"])
    )

    content = frontmatter.loads(result.path.read_text(encoding="utf-8")).content
    assert content.index("- 2026-08-25: 2일차") < content.index("- 2026-08-26: 3일차")
    assert content.index("- 2026-08-26: 3일차") < content.index("## Source Refs")


def test_thread_slug_normalized_when_matching(tmp_path):
    first = _writer(tmp_path, now=datetime(2026, 8, 24)).write(_thread_spec())
    second = _writer(tmp_path, now=datetime(2026, 8, 25)).write(
        _thread_spec(thread="Homelab Build 2026", summary="표기만 다른 같은 thread")
    )
    assert second.rel_path == first.rel_path


def test_different_thread_slug_creates_separate_candidate(tmp_path):
    _writer(tmp_path, now=datetime(2026, 8, 24)).write(_thread_spec())
    _writer(tmp_path, now=datetime(2026, 8, 25)).write(
        _thread_spec(title="Vault 마이그레이션기", thread="vault-mcp-migration")
    )

    assert len(list((tmp_path / "60_Candidates/BlogIdeas").glob("*.md"))) == 2


def test_blog_idea_without_thread_keeps_existing_behavior(tmp_path):
    writer = _writer(tmp_path, now=datetime(2026, 8, 24))
    writer.write(_thread_spec(thread=""))
    result = writer.write(_thread_spec(title="완전히 다른 글감", thread="", summary="다른 요지"))

    assert len(list((tmp_path / "60_Candidates/BlogIdeas").glob("*.md"))) == 2
    post = frontmatter.loads(result.path.read_text(encoding="utf-8"))
    assert "thread" not in post.metadata
    assert "## Updates" not in post.content
