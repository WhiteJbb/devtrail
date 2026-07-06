"""오늘의 복습 질문 — 10_Worklog/Sessions/의 최신 Learning Recovery에서 질문 1개를 뽑는다.

docs/service-improvement-plan.md P6. 새 커맨드를 만들지 않고 push-digest --daily에
값만 얹기 위한 순수 조회 헬퍼다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frontmatter


@dataclass(frozen=True)
class ReviewQuestion:
    project: str
    unclear_concept: str
    question: str
    source_rel_path: str


def pick_review_question(vault_dir: Path) -> ReviewQuestion | None:
    """가장 최근 세션 기록의 Learning Recovery에서 복습 질문 1개를 찾는다. 없으면 None."""
    sessions_dir = vault_dir / "10_Worklog" / "Sessions"
    if not sessions_dir.exists():
        return None

    for md_path in sorted(sessions_dir.glob("*.md"), reverse=True):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        question = _extract_section_first_line(post.content, "다음에 직접 설명해봐야 할 질문", numbered=True)
        if not question:
            continue

        unclear = _extract_section_first_line(post.content, "내가 아직 완전히 이해하지 못한 개념", numbered=False)
        rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
        return ReviewQuestion(
            project=str(post.metadata.get("project", "") or ""),
            unclear_concept=unclear,
            question=question,
            source_rel_path=rel,
        )
    return None


def _extract_section_first_line(body: str, heading_contains: str, numbered: bool) -> str:
    """`### {heading}` 섹션의 첫 번째 실질 내용 줄을 반환한다."""
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("###") and heading_contains in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("#"):
            break
        if not stripped:
            continue
        text = stripped
        if numbered and text[0].isdigit():
            text = text.split(".", 1)[-1].strip()
        elif text.startswith("- "):
            text = text[2:].strip()
        if text:
            return text
    return ""
