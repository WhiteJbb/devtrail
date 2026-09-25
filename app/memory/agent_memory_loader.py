"""AgentMemory 로더 — 40_AgentMemory/*.md를 읽어 문맥 블록을 반환한다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
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
_PROJECT_PATCH_MARKER = re.compile(r"(?m)^<!-- devtrail-memory-patch: (.+) -->\s*$")


@dataclass(frozen=True)
class AgentMemoryBlock:
    rel_path: str
    title: str
    body: str
    updated_at: str = ""  # frontmatter updated_at > 파일 mtime 순으로 채운 YYYY-MM-DD


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

    def load(self, project: str = "") -> AgentMemory:
        blocks: list[AgentMemoryBlock] = []
        for rel in _AGENT_MEMORY_FILES:
            path = self.vault_dir / rel
            if not path.exists():
                continue
            block = self._read_block(path, rel, project)
            if block is not None:
                blocks.append(block)
        return AgentMemory(blocks=blocks)

    def _read_block(self, path: Path, rel: str, project: str = "") -> AgentMemoryBlock | None:
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

        if rel in ("40_AgentMemory/05_OpenLoops.md", "40_AgentMemory/06_Lessons.md"):
            body = self._filter_project_patches(body, project)
            if not body.strip():
                return None
        if len(body) > _MAX_FILE_CHARS:
            if rel in ("40_AgentMemory/05_OpenLoops.md", "40_AgentMemory/06_Lessons.md"):
                body = "...(앞부분 생략)\n" + body[-_MAX_FILE_CHARS:].lstrip()
            else:
                body = body[:_MAX_FILE_CHARS].rstrip() + "\n...(뒷부분 생략)"

        updated_at = str(metadata.get("updated_at", "") or "").strip()
        if not updated_at:
            try:
                updated_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
            except OSError:
                updated_at = ""

        return AgentMemoryBlock(rel_path=rel, title=title, body=body, updated_at=updated_at)

    @staticmethod
    def _filter_project_patches(body: str, project: str) -> str:
        """새 형식의 project-scope 패치만 해당 프로젝트에 한정한다."""
        matches = list(_PROJECT_PATCH_MARKER.finditer(body))
        if not matches:
            return body

        kept = [body[:matches[0].start()]]
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            try:
                metadata = json.loads(match.group(1))
            except (TypeError, ValueError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            patch_body = body[match.end():end]
            if str(metadata.get("scope", "")).strip().lower() != "project":
                kept.extend((match.group(0), patch_body))
            elif project and str(metadata.get("project", "")).strip().casefold() == project.strip().casefold():
                kept.extend((match.group(0), patch_body))
        return "".join(kept).strip()

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
