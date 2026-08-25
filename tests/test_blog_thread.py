"""BlogIdea thread 조회 헬퍼와 digest 블록."""

from __future__ import annotations

import json
from datetime import datetime

from app.config import Settings
from app.services.blog_thread import format_thread_block, format_thread_context, list_threads
from app.services.candidate_writer import CandidateSpec, CandidateWriter
from tests.conftest import FakeLLM


def _spec(**kw) -> CandidateSpec:
    base = dict(
        kind="blog_idea",
        title="홈랩 구축기",
        summary="1일차 요지",
        body="## 핵심 메시지\n\n집에서 서버를 굴리는 이야기.\n\n## 목차 초안\n\n1. 도입\n",
        thread="homelab-build-2026",
        source_refs=["10_Worklog/Sessions/day1.md"],
    )
    base.update(kw)
    return CandidateSpec(**base)


def test_list_threads_returns_slug_title_and_ref_count(tmp_path):
    writer = CandidateWriter(tmp_path, now=datetime(2026, 8, 24))
    writer.write(_spec())
    writer.write(_spec(kind="blog_idea", title="단발성 글감", thread="", summary="단발"))

    threads = list_threads(tmp_path)

    assert [(t.slug, t.title, t.source_count) for t in threads] == [
        ("homelab-build-2026", "홈랩 구축기", 1)
    ]
    assert "homelab-build-2026" in format_thread_context(tmp_path)


def test_format_thread_context_without_threads(tmp_path):
    assert format_thread_context(tmp_path) == "(진행 중인 thread 없음)"


def test_thread_block_only_for_today_updates(tmp_path):
    writer = CandidateWriter(tmp_path, now=datetime(2026, 8, 24))
    writer.write(_spec())

    assert format_thread_block(tmp_path, "2026-08-25") == ""

    CandidateWriter(tmp_path, now=datetime(2026, 8, 25)).write(
        _spec(summary="2일차 요지", source_refs=["10_Worklog/Sessions/day2.md"])
    )
    block = format_thread_block(tmp_path, "2026-08-25")

    assert "홈랩 구축기" in block
    assert "새로 추가된 세션 1개" in block
    assert "누적 소스 2개" in block


def test_blog_write_from_idea_works_on_merged_thread(tmp_path):
    """thread 후보는 source_refs가 긴 BlogIdea일 뿐 — `blog write --idea` 경로가 그대로 동작해야 한다."""
    from app.agents.wiki_blog_agent import WikiBlogAgent

    for day, marker in (("day1", "SESSION_ONE"), ("day2", "SESSION_TWO")):
        path = tmp_path / "10_Worklog/Sessions" / f"{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ncreated_at: 2026-08-2{day[-1]}\n---\n{marker} 본문\n", encoding="utf-8")

    CandidateWriter(tmp_path, now=datetime(2026, 8, 24)).write(_spec())
    result = CandidateWriter(tmp_path, now=datetime(2026, 8, 25)).write(
        _spec(summary="2일차 요지", source_refs=["10_Worklog/Sessions/day2.md"])
    )

    llm = FakeLLM(
        json.dumps(
            {"title": "홈랩 구축기", "tags": ["homelab"], "body": "## 배경\n\n본문"},
            ensure_ascii=False,
        )
    )
    settings = Settings(OBSIDIAN_VAULT_PATH=str(tmp_path), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")
    draft, warnings = WikiBlogAgent(settings=settings, llm=llm).write_blog_from_idea(result.rel_path)

    assert warnings == []
    assert "SESSION_ONE" in llm.last_prompt and "SESSION_TWO" in llm.last_prompt
    assert draft.source_refs == [
        "10_Worklog/Sessions/day1.md",
        "10_Worklog/Sessions/day2.md",
        result.rel_path,
    ]
