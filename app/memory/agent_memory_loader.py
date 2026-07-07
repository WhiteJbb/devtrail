"""AgentMemory 로더 — 40_AgentMemory/*.md를 읽어 문맥 블록을 반환한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import frontmatter


_AGENT_MEMORY_FILES = [
    "40_AgentMemory/00_Profile.md",
    "40_AgentMemory/01_CurrentFocus.md",
    "40_AgentMemory/02_ProjectMap.md",
    "40_AgentMemory/03_WritingStyle.md",
    "40_AgentMemory/04_CareerContext.md",
    "40_AgentMemory/05_OpenLoops.md",
    "40_AgentMemory/06_Lessons.md",
]

_MAX_FILE_CHARS = 2000


@dataclass(frozen=True)
class AgentMemoryBlock:
    rel_path: str
    title: str
    body: str


@dataclass(frozen=True)
class AgentMemory:
    blocks: list[AgentMemoryBlock] = field(default_factory=list)

    @property
    def source_refs(self) -> list[str]:
        return [b.rel_path for b in self.blocks if b.body.strip()]

    def render(self) -> str:
        parts: list[str] = []
        for block in self.blocks:
            if not block.body.strip():
                continue
            parts.append(f"### {block.title}\n\n{block.body.strip()}")
        return "\n\n".join(parts)


class AgentMemoryLoader:
    """40_AgentMemory/ 루트 파일들을 읽어 AgentMemory를 반환한다."""

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir

    def load(self) -> AgentMemory:
        blocks: list[AgentMemoryBlock] = []
        for rel in _AGENT_MEMORY_FILES:
            path = self.vault_dir / rel
            if not path.exists():
                continue
            block = self._read_block(path, rel)
            if block is not None:
                blocks.append(block)
        return AgentMemory(blocks=blocks)

    def _read_block(self, path: Path, rel: str) -> AgentMemoryBlock | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            return None

        try:
            post = frontmatter.loads(raw)
            body = post.content.strip()
            metadata = dict(post.metadata)
        except Exception:
            body = raw.strip()
            metadata = {}

        title = (
            str(metadata.get("title", "") or "").strip()
            or self._h1_from_body(body)
            or self._title_from_path(path)
        )
        if not body:
            return None

        if len(body) > _MAX_FILE_CHARS:
            body = body[:_MAX_FILE_CHARS].rstrip() + "\n...(일부 생략)"

        return AgentMemoryBlock(rel_path=rel, title=title, body=body)

    def _h1_from_body(self, body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return ""

    def _title_from_path(self, path: Path) -> str:
        stem = path.stem
        # "00_Profile" → "Profile"
        if "_" in stem:
            parts = stem.split("_", 1)
            if parts[0].isdigit():
                return parts[1]
        return stem
