"""CuratorAgent — 60_Candidates/를 조회·승격·반영한다.

후보 노트를 공식 영역(20_Knowledge/, 30_Projects/*/Decisions/, 40_AgentMemory/)으로
옮기거나 패치를 적용한다. 공식 영역을 바로 덮어쓰지 않는다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter

from app.config import Settings, get_settings
from app.services.wiki_service import WikiService


_CANDIDATE_DIR = "60_Candidates"
_STALE_DAYS = 14

_PROMOTE_TARGETS = {
    "knowledge": "20_Knowledge",
    "decision": "30_Projects",
    "memory_patch": "40_AgentMemory",
    "blog_idea": "50_Outputs/Blog/Ideas",
}

_KIND_LABEL = {
    "knowledge": "Knowledge",
    "decision": "Decision",
    "memory_patch": "MemoryPatch",
    "blog_idea": "BlogIdea",
}


@dataclass(frozen=True)
class CandidateItem:
    kind: str
    title: str
    rel_path: str
    created_at: str
    project: str
    tags: list[str] = field(default_factory=list)
    is_stale: bool = False


@dataclass(frozen=True)
class PromoteResult:
    candidate_path: str
    promoted_path: str
    kind: str


class CuratorAgent:
    """Candidate 노트 관리 — 조회/미리보기/승격/패치 적용."""

    def __init__(self, settings: Settings | None = None, now: datetime | None = None) -> None:
        self.settings = settings or get_settings()
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)

    # ── 조회 ─────────────────────────────────────────────────────────

    def list_candidates(self) -> list[CandidateItem]:
        """60_Candidates/ 하위 모든 후보를 반환한다."""
        candidates_dir = self.vault_dir / _CANDIDATE_DIR
        if not candidates_dir.exists():
            return []

        items: list[CandidateItem] = []
        for md_path in sorted(candidates_dir.rglob("*.md")):
            item = self._parse_candidate(md_path)
            if item is not None:
                items.append(item)
        return items

    def preview_candidate(self, rel_path: str) -> str:
        """후보 노트의 전체 내용을 반환한다."""
        path = self.vault_dir / rel_path
        if not path.exists():
            raise ValueError(f"후보를 찾지 못했습니다: {rel_path}")
        return path.read_text(encoding="utf-8")

    def delete_candidate(self, rel_path: str) -> None:
        """후보 노트를 영구 삭제한다."""
        path = self.vault_dir / rel_path
        if not path.exists():
            raise ValueError(f"후보를 찾지 못했습니다: {rel_path}")
        path.unlink()

    # ── 승격 ─────────────────────────────────────────────────────────

    def promote_candidate(self, rel_path: str) -> PromoteResult:
        """후보 노트를 공식 영역으로 복사하고 status를 promoted로 변경한다."""
        src_path = self.vault_dir / rel_path
        if not src_path.exists():
            raise ValueError(f"후보를 찾지 못했습니다: {rel_path}")

        raw = src_path.read_text(encoding="utf-8")
        try:
            post = frontmatter.loads(raw)
            metadata: dict[str, Any] = dict(post.metadata)
            body = post.content
        except Exception:
            metadata = {}
            body = raw

        kind = self._normalize_kind(str(metadata.get("candidate_type") or metadata.get("type") or "knowledge"))
        project = str(metadata.get("project") or "").strip()
        promoted_rel = self._promoted_path(kind, project, src_path.name)

        promoted_path = self.vault_dir / promoted_rel
        promoted_path.parent.mkdir(parents=True, exist_ok=True)

        # status를 stable/accepted로 변경해서 공식 영역에 저장
        metadata["status"] = "accepted" if kind == "decision" else "stable"
        metadata["type"] = kind
        metadata.pop("candidate_type", None)
        today = (self.now or datetime.now()).strftime("%Y-%m-%d")
        metadata["promoted_at"] = today

        base_content = frontmatter.dumps(frontmatter.Post(body, **metadata))

        # 관련 노트 자동 링크 삽입 — 원본 삭제 전에 처리해 실패 시 롤백 가능
        related = self.wiki_service.related_notes(promoted_rel, limit=5)
        if related:
            link_lines = ["\n\n## 관련 노트\n"]
            for r in related:
                link_title = r.note.title or Path(r.note.path).stem
                link_lines.append(f"- [[{link_title}]]")
            base_content = base_content + "\n".join(link_lines) + "\n"

        promoted_path.write_text(base_content, encoding="utf-8")

        # 원본 candidate 삭제 — promoted 사본이 공식 영역에 저장된 뒤 삭제
        src_path.unlink()

        title = str(metadata.get("title") or src_path.stem)
        self.wiki_service.append_vault_log("promote", title, [promoted_rel])

        return PromoteResult(candidate_path=rel_path, promoted_path=promoted_rel, kind=kind)

    def promote_all(self, kind: str | None = None) -> list[PromoteResult]:
        """후보 전체(또는 지정 kind)를 일괄 승격한다."""
        items = self.list_candidates()
        if kind:
            items = [i for i in items if i.kind == kind]
        results = []
        for item in items:
            try:
                results.append(self.promote_candidate(item.rel_path))
            except Exception:
                pass
        return results

    def apply_memory_patch(self, rel_path: str) -> PromoteResult:
        """memory_patch 후보를 40_AgentMemory/ 대상 파일에 반영(append)한다."""
        src_path = self.vault_dir / rel_path
        if not src_path.exists():
            raise ValueError(f"후보를 찾지 못했습니다: {rel_path}")

        raw = src_path.read_text(encoding="utf-8")
        try:
            post = frontmatter.loads(raw)
            metadata = dict(post.metadata)
            patch_body = post.content.strip()
        except Exception:
            metadata = {}
            patch_body = raw.strip()

        # 대상 AgentMemory 파일 결정 (없으면 05_OpenLoops.md에 append)
        target_file = str(metadata.get("target_file") or "").strip()
        if not target_file:
            target_file = "40_AgentMemory/05_OpenLoops.md"

        target_path = self.vault_dir / target_file
        target_path.parent.mkdir(parents=True, exist_ok=True)

        today = (self.now or datetime.now()).strftime("%Y-%m-%d")
        append_text = f"\n\n<!-- patch applied {today} from {rel_path} -->\n\n{patch_body}"

        if target_path.exists():
            existing = target_path.read_text(encoding="utf-8")
            target_path.write_text(existing + append_text, encoding="utf-8")
        else:
            target_path.write_text(patch_body, encoding="utf-8")

        # 원본 candidate에 applied 마킹
        metadata["status"] = "applied"
        metadata["applied_to"] = target_file
        applied_post = frontmatter.Post(patch_body, **metadata)
        src_path.write_text(frontmatter.dumps(applied_post), encoding="utf-8")

        title = str(metadata.get("title") or src_path.stem)
        self.wiki_service.append_vault_log("apply-memory-patch", title, [target_file])

        return PromoteResult(candidate_path=rel_path, promoted_path=target_file, kind="memory_patch")

    # ── 내부 헬퍼 ────────────────────────────────────────────────────

    def _parse_candidate(self, path: Path) -> CandidateItem | None:
        try:
            raw = path.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            metadata = dict(post.metadata)
        except Exception:
            return None

        kind = self._normalize_kind(str(metadata.get("candidate_type") or metadata.get("type") or ""))
        if not kind:
            return None

        rel_path = str(path.relative_to(self.vault_dir)).replace("\\", "/")
        title = str(metadata.get("title") or "").strip() or self._h1_from_body(post.content) or path.stem
        tags_raw = metadata.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",")]
        tags = [str(t) for t in tags_raw]

        status = str(metadata.get("status") or "")
        if status in ("promoted", "applied"):
            return None

        created_at = str(metadata.get("created_at") or "")
        is_stale = False
        if created_at:
            try:
                created_date = datetime.strptime(created_at[:10], "%Y-%m-%d")
                is_stale = (self._now() - created_date).days > _STALE_DAYS
            except ValueError:
                pass

        return CandidateItem(
            kind=kind,
            title=title,
            rel_path=rel_path,
            created_at=created_at,
            project=str(metadata.get("project") or ""),
            tags=tags,
            is_stale=is_stale,
        )

    def _normalize_kind(self, kind: str) -> str:
        value = kind.strip().lower().replace("-", "_")
        aliases = {
            "knowledge_candidate": "knowledge",
            "decision_candidate": "decision",
            "decisions": "decision",
            "memory": "memory_patch",
            "memory_patches": "memory_patch",
            "blog": "blog_idea",
            "blog_ideas": "blog_idea",
            "candidate": "",
        }
        return aliases.get(value, value)

    def _promoted_path(self, kind: str, project: str, filename: str) -> str:
        base = _PROMOTE_TARGETS.get(kind, "20_Knowledge")
        if kind == "decision" and project:
            return f"30_Projects/{project}/Decisions/{filename}"
        if kind == "knowledge" and project:
            return f"20_Knowledge/{project}/{filename}"
        return f"{base}/{filename}"

    def _now(self) -> datetime:
        return self.now or datetime.now()

    def _h1_from_body(self, body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return ""
