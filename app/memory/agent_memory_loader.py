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
# Lessons는 프로젝트 필터 뒤에도 5천 자를 넘어 tail 2000자면 최근 패치 1~2개만 남았다(2026-10-19 실측 37%).
# OpenLoops도 Devtrail 블록이 2000자를 넘었다(2026-10-21). briefing 쪽 상한은 vault_tools._MEMORY_APPEND_MAX_CHARS.
# ponytail: 고정 상한. briefing 예산을 누르면 오래된 교훈 정리(요약·만료)로 간다
_LESSONS_MAX_CHARS = 8000
# 마커 아래 블록을 프로젝트별로 거르는 파일. 마커 앞부분은 전역. CurrentFocus는 사람이 쓰지만
# 한 프로젝트 얘기(Devtrail 완성)가 다른 repo 세션에 최우선 관심사로 들어가 잡음이었다(2026-10-18).
_PROJECT_SCOPED_FILES = (
    "40_AgentMemory/01_CurrentFocus.md",
    "40_AgentMemory/05_OpenLoops.md",
    "40_AgentMemory/06_Lessons.md",
)
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

        if rel in _PROJECT_SCOPED_FILES:
            body = self._filter_project_patches(body, project)
            if not body.strip():
                return None
        limit = _LESSONS_MAX_CHARS if rel in ("40_AgentMemory/05_OpenLoops.md", "40_AgentMemory/06_Lessons.md") else _MAX_FILE_CHARS
        if len(body) > limit:
            if rel in ("40_AgentMemory/05_OpenLoops.md", "40_AgentMemory/06_Lessons.md"):
                body = "...(앞부분 생략)\n" + body[-limit:].lstrip()
            else:
                body = body[:limit].rstrip() + "\n...(뒷부분 생략)"

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
