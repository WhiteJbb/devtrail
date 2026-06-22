"""로컬 draft 저장소 — MarkdownStorage를 감싸 도메인 단위 조회/저장을 제공."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from app.models import BlogPost
from app.storage import MarkdownStorage


def slugify(text: str, max_len: int = 60) -> str:
    """제목/주제를 파일명에 안전한 slug로 변환.

    ASCII 영숫자/하이픈만 남긴다. 한글 등 비ASCII만으로 이뤄진 제목은
    slug가 비어버리므로 호출측에서 날짜 prefix를 붙여 유일성을 보장한다.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len]


class BlogRepository:
    """draft 파일을 BlogPost 단위로 다룬다."""

    def __init__(self, storage: MarkdownStorage):
        self.storage = storage

    def build_slug(self, title: str) -> str:
        """제목 기반 slug. 날짜 prefix로 정렬성과 유일성을 확보."""
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        base = slugify(title)
        return f"{date}-{base}" if base else f"{date}-draft"

    def save_draft(self, post: BlogPost) -> Path:
        if not post.slug:
            post.slug = self.build_slug(post.title)
        post.updated_at = datetime.now(timezone.utc)
        return self.storage.save(post)

    def list_drafts(self) -> list[BlogPost]:
        """모든 draft를 updated_at 내림차순으로 반환."""
        posts = [self.storage.load(p) for p in self.storage.list_files()]
        return sorted(posts, key=lambda p: p.updated_at, reverse=True)

    def get_latest(self) -> BlogPost | None:
        posts = self.list_drafts()
        return posts[0] if posts else None

    def get_by_slug(self, slug: str) -> BlogPost | None:
        path = self.storage.path_for(slug)
        if not path.is_file():
            return None
        return self.storage.load(path)
