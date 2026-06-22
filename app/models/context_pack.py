"""ContextPack — 특정 주제에 필요한 문맥 묶음."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextPack:
    topic: str
    agent_memory_section: str
    project_section: str
    relevant_notes_section: str
    source_refs: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Context Pack 전체를 Markdown 문자열로 반환한다."""
        sections: list[str] = [f"# Context Pack\n\n주제: {self.topic}"]

        if self.agent_memory_section.strip():
            sections.append(f"## Agent Memory\n\n{self.agent_memory_section.strip()}")

        if self.project_section.strip():
            sections.append(f"## Project Context\n\n{self.project_section.strip()}")

        if self.relevant_notes_section.strip():
            sections.append(f"## Relevant Notes\n\n{self.relevant_notes_section.strip()}")

        if self.source_refs:
            refs = "\n".join(f"- {ref}" for ref in self.source_refs)
            sections.append(f"## Source Refs\n\n{refs}")

        sections.append(f"## Task\n\n{self.topic}")

        return "\n\n".join(sections)
