"""BlogIdea thread 조회 — 여러 날의 세션이 누적된 글감 후보를 읽는다.

thread 자체의 누적(병합)은 CandidateWriter가 결정적으로 처리한다. 여기는
distill 프롬프트 컨텍스트와 digest 블록이 공유하는 읽기 전용 헬퍼다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frontmatter

from app.services.candidate_writer import BLOG_IDEA_DIR, thread_slug


@dataclass(frozen=True)
class ThreadInfo:
    slug: str
    title: str
    rel_path: str
    source_count: int
    last_added: int  # 마지막 갱신에서 추가된 소스 수
    last_active: str  # updated_at 또는 created_at의 날짜 (YYYY-MM-DD)


def list_threads(vault_dir: Path) -> list[ThreadInfo]:
    """검토 대기 중인 BlogIdea 후보 중 thread가 붙은 것을 최근 활동순으로 반환한다."""
    cand_dir = vault_dir / BLOG_IDEA_DIR
    if not cand_dir.exists():
        return []

    threads: list[ThreadInfo] = []
    for md_path in sorted(cand_dir.glob("*.md")):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = post.metadata
        slug = thread_slug(str(meta.get("thread") or ""))
        if not slug:
            continue
        if str(meta.get("status", "") or "").strip().lower() != "candidate":
            continue
        refs = meta.get("source_refs") or []
        last_active = str(meta.get("updated_at") or meta.get("created_at") or "")[:10]
        try:
            last_added = int(meta.get("thread_last_added") or 0)
        except (TypeError, ValueError):
            last_added = 0
        threads.append(
            ThreadInfo(
                slug=slug,
                title=str(meta.get("title") or md_path.stem).strip(),
                rel_path=str(md_path.relative_to(vault_dir)).replace("\\", "/"),
                source_count=len(refs),
                last_added=last_added,
                last_active=last_active,
            )
        )
    threads.sort(key=lambda t: t.last_active, reverse=True)
    return threads


def format_thread_context(vault_dir: Path) -> str:
    """distill 프롬프트에 넣을 기존 thread 목록. 없으면 안내 한 줄."""
    threads = list_threads(vault_dir)
    if not threads:
        return "(진행 중인 thread 없음)"
    return "\n".join(
        f"- `{t.slug}` — {t.title} (누적 소스 {t.source_count}개, 최근 갱신 {t.last_active or '미상'})"
        for t in threads
    )


def format_thread_block(vault_dir: Path, date: str) -> str:
    """오늘 소스가 추가된 thread만 digest 블록으로 만든다. 없으면 빈 문자열."""
    try:
        updated = [t for t in list_threads(vault_dir) if t.last_active == date]
    except Exception:
        return ""
    if not updated:
        return ""
    lines = ["**글감 thread 현황**"]
    for t in updated:
        lines.append(
            f"- {t.title} (`{t.slug}`) — 새로 추가된 세션 {t.last_added}개, 누적 소스 {t.source_count}개"
        )
    return "\n".join(lines)
