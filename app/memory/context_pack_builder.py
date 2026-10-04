"""ContextPackBuilder — 주제 관련 문맥을 자동 수집해 ContextPack을 반환한다."""

from __future__ import annotations

from pathlib import Path

from app.memory.agent_memory_loader import AgentMemoryLoader
from app.memory.project_memory_loader import ProjectMemoryLoader
from app.models.context_pack import ContextPack
from app.services.wiki_service import WikiService


_MAX_NOTES = 5
_NOTE_PREVIEW_CHARS = 600


class ContextPackBuilder:
    """AgentMemory + ProjectContext + related notes를 묶어 ContextPack을 반환한다."""

    def __init__(self, vault_dir: Path, wiki_service: WikiService | None = None) -> None:
        self.vault_dir = vault_dir
        self.wiki_service = wiki_service or WikiService(vault_dir)
        self._agent_loader = AgentMemoryLoader(vault_dir)
        self._project_loader = ProjectMemoryLoader(vault_dir)

    def build(self, topic: str) -> ContextPack:
        source_refs: list[str] = []

        # 1. Project Context — 토픽에서 프로젝트 이름 추출
        project_memory = self._project_loader.load()
        matched = project_memory.match_topic(topic)
        if matched:
            project_parts = []
            for ctx in matched:
                project_parts.append(f"#### {ctx.project}\n\n{ctx.body.strip()}")
                source_refs.append(ctx.rel_path)
            project_section = "\n\n".join(project_parts)
        else:
            project_section = ""

        # 프로젝트가 하나로 특정될 때 해당 범위의 AgentMemory만 포함한다.
        scoped_project = matched[0].project if len(matched) == 1 else ""
        agent_memory = self._agent_loader.load(project=scoped_project)
        agent_section = agent_memory.render()
        source_refs.extend(agent_memory.source_refs)

        # 3. Related Notes — keyword search (60_Candidates는 검토 전 임시 영역이므로 제외)
        related = self.wiki_service.search(
            topic,
            limit=_MAX_NOTES * 2,
            exclude_prefixes=("40_AgentMemory/", "60_Candidates/"),
        )
        note_parts: list[str] = []
        for result in related:
            note = result.note
            if len(note_parts) >= _MAX_NOTES:
                break
            preview = note.body.strip()
            if len(preview) > _NOTE_PREVIEW_CHARS:
                preview = preview[:_NOTE_PREVIEW_CHARS].rstrip() + "\n..."
            entry = f"#### {note.title} (`{note.path}`)\n\n{preview}"
            note_parts.append(entry)
            if note.path not in source_refs:
                source_refs.append(note.path)
        relevant_section = "\n\n".join(note_parts)

        return ContextPack(
            topic=topic,
            agent_memory_section=agent_section,
            project_section=project_section,
            relevant_notes_section=relevant_section,
            source_refs=source_refs,
        )
