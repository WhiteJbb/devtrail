"""Notion 동기화 서비스.

로컬 draft(frontmatter, 단일 진실원천)를 Notion Blog DB 행과 맞춘다.
- 새 draft → Notion에 행 생성
- 기존 draft → 상태/수정일/태그 등 갱신
- 생성 후 받은 page_id는 로컬 frontmatter에 다시 기록(정합성)
- dry_run이면 실제 반영 없이 계획만 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.repositories.blog_repository import BlogRepository
from app.repositories.notion_blog_repository import NotionBlogRepository


@dataclass
class SyncEntry:
    slug: str
    title: str
    action: str  # "create" | "update"


@dataclass
class SyncReport:
    mode: str          # "mock" | "real"
    dry_run: bool
    entries: list[SyncEntry] = field(default_factory=list)

    @property
    def created(self) -> list[SyncEntry]:
        return [e for e in self.entries if e.action == "create"]

    @property
    def updated(self) -> list[SyncEntry]:
        return [e for e in self.entries if e.action == "update"]


class NotionSyncService:
    def __init__(
        self,
        blog_repository: BlogRepository,
        notion_repository: NotionBlogRepository,
    ):
        self.blog_repository = blog_repository
        self.notion_repository = notion_repository

    def sync(self, dry_run: bool = False) -> SyncReport:
        report = SyncReport(mode=self.notion_repository.kind, dry_run=dry_run)

        # 기존 Notion 행을 slug로 색인(존재 여부 판단용).
        existing_slugs = {row.slug for row in self.notion_repository.list_rows()}

        for post in self.blog_repository.list_drafts():
            exists = bool(post.notion_page_id) or post.slug in existing_slugs
            action = "update" if exists else "create"
            report.entries.append(SyncEntry(slug=post.slug, title=post.title, action=action))

            if dry_run:
                continue

            row = self.notion_repository.upsert(post)
            # 새로 생성되어 page_id가 부여되면 로컬 frontmatter에 반영.
            if row.page_id and row.page_id != post.notion_page_id:
                post.notion_page_id = row.page_id
                self.blog_repository.save_draft(post)

        return report
