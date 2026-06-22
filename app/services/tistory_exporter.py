"""티스토리 게시용 export.

티스토리 공식 Open API는 2024년 종료되어 자동 게시가 불가능하다. 따라서
글쓰기 화면에 바로 붙여넣을 수 있는 형식(HTML 또는 마크다운)으로 본문을 변환해
workspace/blogs/에 저장한다. 제목/태그는 티스토리의 별도 입력란에 넣도록 안내한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import markdown as md

from app.models import BlogPost, BlogStatus
from app.repositories.blog_repository import BlogRepository

_MD_EXTENSIONS = ["fenced_code", "tables", "nl2br", "sane_lists"]


@dataclass
class TistoryExportResult:
    post: BlogPost
    path: Path
    fmt: str  # "html" | "md"


class TistoryExporter:
    def __init__(self, repository: BlogRepository, blogs_dir: Path):
        self.repository = repository
        self.blogs_dir = blogs_dir

    def _render(self, post: BlogPost, fmt: str) -> str:
        if fmt == "md":
            # 티스토리 마크다운 모드에 그대로 붙여넣는 본문(제목/태그 제외).
            return post.body.strip() + "\n"
        # 기본: HTML 모드에 붙여넣을 변환 결과.
        return md.markdown(post.body, extensions=_MD_EXTENSIONS)

    def export(self, target: str = "latest", fmt: str = "html") -> TistoryExportResult | None:
        fmt = fmt.lower()
        if fmt not in ("html", "md"):
            raise ValueError("format은 'html' 또는 'md'여야 합니다.")

        if target == "latest":
            post = self.repository.get_latest()
        else:
            post = self.repository.get_by_slug(target)
        if post is None:
            return None

        self.blogs_dir.mkdir(parents=True, exist_ok=True)
        ext = "html" if fmt == "html" else "md"
        path = self.blogs_dir / f"{post.slug}.{ext}"
        path.write_text(self._render(post, fmt), encoding="utf-8")

        # 게시 준비 단계로 상태 추적 갱신.
        if post.status in (BlogStatus.IDEA, BlogStatus.DRAFT):
            post.status = BlogStatus.REVIEW
            self.repository.save_draft(post)

        return TistoryExportResult(post=post, path=path, fmt=fmt)
