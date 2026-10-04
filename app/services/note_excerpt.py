"""세션 노트에서 필요한 '## Heading' 섹션만 골라 LLM 입력 예산 안에 넣는다."""

from __future__ import annotations


def excerpt_sections(body: str, headings: tuple[str, ...]) -> str:
    """body에서 지정된 '## Heading' 섹션만 headings 순서대로 발췌한다.

    문서 순서가 아니라 headings 인자 순서를 따른다 — excerpt는 뒤에서 truncate되므로
    다음 세션에 가장 필요한 섹션(Next Session)을 앞에 둬야 잘려도 덜 아프다.
    """
    lines = body.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            current = heading if heading in headings else None
            if current is not None:
                sections.setdefault(current, []).append(line)
            continue
        if current is not None:
            sections[current].append(line)
    ordered = ["\n".join(sections[h]).strip() for h in headings if h in sections]
    return "\n\n".join(part for part in ordered if part).strip()


def prioritized_excerpt(body: str, headings: tuple[str, ...], limit: int) -> str:
    """limit을 넘는 노트는 앞에서 자르지 않고 headings 섹션을 우선해 담는다.

    Process 형식 노트는 What Changed·Files Touched가 앞에 있어, 앞에서 자르면
    Project Decisions·Agent Execution Notes·Next Session이 통째로 빠진다.
    해당 섹션이 없는 노트(다른 형식)는 기존대로 앞에서 자른다.
    """
    body = body.strip()
    if len(body) <= limit:
        return body
    picked = excerpt_sections(body, headings) or body
    if len(picked) > limit:
        picked = picked[:limit].rstrip() + "\n...(일부 생략)"
    return picked
