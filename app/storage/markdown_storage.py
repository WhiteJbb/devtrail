"""Markdown frontmatter ↔ BlogPost 직렬화 및 파일 I/O.

frontmatter가 단일 진실원천이다. 저장 시 BlogPost.metadata()를 YAML frontmatter로,
본문을 그 아래 마크다운으로 쓴다. 로드 시 역과정을 수행한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter

from app.models import BlogPost, BlogStatus


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"날짜 형식을 해석할 수 없습니다: {value!r}")


class MarkdownStorage:
    """draft 디렉토리에 BlogPost를 `.md`(frontmatter 포함)로 읽고 쓴다."""

    def __init__(self, drafts_dir: Path):
        self.drafts_dir = drafts_dir

    def path_for(self, slug: str) -> Path:
        return self.drafts_dir / f"{slug}.md"

    def to_text(self, post: BlogPost) -> str:
        """BlogPost를 frontmatter 포함 마크다운 문자열로 직렬화."""
        doc = frontmatter.Post(post.body, **post.metadata())
        return frontmatter.dumps(doc)

    def save(self, post: BlogPost) -> Path:
        """draft를 파일로 저장하고 local_path를 채운 경로를 반환."""
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(post.slug)
        post.local_path = str(path)
        # local_path가 frontmatter에도 반영되도록 직렬화는 갱신 후에 수행.
        path.write_text(self.to_text(post), encoding="utf-8")
        return path

    def load(self, path: Path) -> BlogPost:
        """`.md` 파일을 BlogPost로 역직렬화."""
        doc = frontmatter.loads(path.read_text(encoding="utf-8"))
        meta = doc.metadata
        return BlogPost(
            title=meta.get("title", path.stem),
            slug=meta.get("slug", path.stem),
            body=doc.content,
            tags=list(meta.get("tags") or []),
            source_project=meta.get("source_project", ""),
            status=BlogStatus(meta.get("status", BlogStatus.DRAFT.value)),
            summary=meta.get("summary", ""),
            source_refs=list(meta.get("source_refs") or []),
            local_path=meta.get("local_path", str(path)),
            notion_page_id=meta.get("notion_page_id") or None,
            published_url=meta.get("published_url", ""),
            created_at=_parse_dt(meta["created_at"]) if meta.get("created_at") else datetime.now(),
            updated_at=_parse_dt(meta["updated_at"]) if meta.get("updated_at") else datetime.now(),
        )

    def list_files(self) -> list[Path]:
        """draft 디렉토리의 모든 `.md` 파일 경로."""
        if not self.drafts_dir.exists():
            return []
        return sorted(self.drafts_dir.glob("*.md"))
