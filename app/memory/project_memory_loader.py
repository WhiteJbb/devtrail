"""ProjectMemory 로더 — 30_Projects/*/Context.md를 읽어 프로젝트 문맥을 반환한다."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter


_MAX_FILE_CHARS = 3000


@dataclass(frozen=True)
class ProjectContext:
    project: str
    rel_path: str
    body: str
    tags: list[str] = field(default_factory=list)
    status: str = ""


@dataclass(frozen=True)
class ProjectMemory:
    contexts: list[ProjectContext] = field(default_factory=list)

    def find(self, project_name: str) -> ProjectContext | None:
        """대소문자 무시 프로젝트명으로 Context를 찾는다."""
        name_lower = project_name.lower()
        for ctx in self.contexts:
            if ctx.project.lower() == name_lower:
                return ctx
        return None

    def match_topic(self, topic: str) -> list[ProjectContext]:
        """토픽 문자열에서 언급된 프로젝트 Context를 찾는다."""
        topic_lower = topic.lower()
        return [ctx for ctx in self.contexts if ctx.project.lower() in topic_lower]

    @property
    def source_refs(self) -> list[str]:
        return [ctx.rel_path for ctx in self.contexts]

    def render_all(self) -> str:
        parts: list[str] = []
        for ctx in self.contexts:
            parts.append(f"### {ctx.project} ({ctx.rel_path})\n\n{ctx.body.strip()}")
        return "\n\n".join(parts)

    def render_for(self, project_name: str) -> str:
        ctx = self.find(project_name)
        if ctx is None:
            return ""
        return ctx.body.strip()


class ProjectMemoryLoader:
    """30_Projects/*/Context.md 파일들을 읽어 ProjectMemory를 반환한다."""

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir

    def load(self) -> ProjectMemory:
        projects_dir = self.vault_dir / "30_Projects"
        if not projects_dir.exists():
            return ProjectMemory()

        contexts: list[ProjectContext] = []
        for context_path in sorted(projects_dir.glob("*/Context.md")):
            ctx = self._read_context(context_path)
            if ctx is not None:
                contexts.append(ctx)
        return ProjectMemory(contexts=contexts)

    def _read_context(self, path: Path) -> ProjectContext | None:
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

        if not body:
            return None

        rel_path = str(path.relative_to(self.vault_dir)).replace("\\", "/")
        project = str(metadata.get("project", "") or "").strip() or path.parent.name

        tags_raw = metadata.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",")]
        tags = [str(t) for t in tags_raw if str(t).strip()]

        if len(body) > _MAX_FILE_CHARS:
            body = body[:_MAX_FILE_CHARS].rstrip() + "\n...(일부 생략)"

        return ProjectContext(
            project=project,
            rel_path=rel_path,
            body=body,
            tags=tags,
            status=str(metadata.get("status", "") or ""),
        )
