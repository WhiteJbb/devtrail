"""Obsidian 볼트 소스 — 볼트 안 .md 노트를 읽는다.

OBSIDIAN_VAULT_DIR를 설정하면 활성화된다.
OBSIDIAN_TAGS로 태그 필터링, OBSIDIAN_FOLDERS로 폴더 필터링(둘 다 선택).
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

from app.models import SourceChunk

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")
_INLINE_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z가-힣][A-Za-z0-9가-힣_-]*)")


class ObsidianSource:
    """Obsidian 볼트에서 노트를 읽어 SourceChunk 리스트로 반환한다.

    - tags: 지정 시 frontmatter tags 또는 인라인 #tag가 일치하는 노트만 읽음
    - folders: 지정 시 해당 폴더(볼트 기준 상대경로) 안 노트만 읽음
    - 읽기 실패한 파일은 조용히 건너뜀(파이프라인을 멈추지 않음)
    """

    name = "obsidian"

    def __init__(
        self,
        vault_dir: Path,
        tags: list[str] | None = None,
        folders: list[str] | None = None,
    ):
        self.vault_dir = vault_dir
        self.tags = [t.lstrip("#").lower() for t in tags] if tags else []
        self.folders = folders or []

    def fetch(self) -> list[SourceChunk]:
        if not self.vault_dir.exists():
            return []

        chunks: list[SourceChunk] = []
        for path in self._candidate_paths():
            chunk = self._load(path)
            if chunk is not None:
                chunks.append(chunk)
        return chunks

    # ------------------------------------------------------------------
    def _candidate_paths(self):
        if self.folders:
            for folder in self.folders:
                base = self.vault_dir / folder
                if base.is_dir():
                    yield from sorted(base.rglob("*.md"))
        else:
            yield from sorted(self.vault_dir.rglob("*.md"))

    def _load(self, path: Path) -> SourceChunk | None:
        try:
            post = frontmatter.load(str(path))
        except Exception:
            return None

        body = post.content.strip()
        if not body:
            return None

        if self.tags and not self._has_tag(post, body):
            return None

        rel = path.relative_to(self.vault_dir)
        clean_text = _WIKILINK_RE.sub(lambda m: m.group(1), body)

        return SourceChunk(
            source_type="obsidian",
            ref=str(rel),
            title=path.stem,
            text=clean_text,
        )

    def _has_tag(self, post: frontmatter.Post, body: str) -> bool:
        fm_tags = post.get("tags") or []
        if isinstance(fm_tags, str):
            fm_tags = [t.strip() for t in fm_tags.split(",")]
        fm_lower = {t.lstrip("#").lower() for t in fm_tags}
        if fm_lower & set(self.tags):
            return True

        inline = {m.lower() for m in _INLINE_TAG_RE.findall(body)}
        return bool(inline & set(self.tags))
