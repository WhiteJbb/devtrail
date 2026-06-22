"""BlogPost ↔ NotionBlogRow ↔ Notion API 속성 매핑.

도메인 매핑(BlogPost↔Row)과 Notion API 매핑(Row↔properties)을 한곳에 모은다.
API 속성 매핑은 real_client에서만 쓰인다.
"""

from __future__ import annotations

from typing import Any

from app.models import BlogPost, BlogStatus, NotionBlogRow

# Notion Blog DB 컬럼명. 실제 DB 스키마와 맞춰야 한다(README에 문서화).
COL_TITLE = "Title"
COL_STATUS = "Status"
COL_SOURCE_PROJECT = "Source Project"
COL_TAGS = "Tags"
COL_LOCAL_PATH = "Local Path"
COL_CREATED_AT = "Created At"
COL_UPDATED_AT = "Updated At"
COL_SOURCE_REFS = "Source Refs"
COL_SLUG = "Slug"
COL_SUMMARY = "Summary"


# ----- 도메인 매핑 -----
def blog_post_to_row(post: BlogPost) -> NotionBlogRow:
    return NotionBlogRow(
        title=post.title,
        slug=post.slug,
        status=post.status.value,
        source_project=post.source_project,
        tags=list(post.tags),
        local_path=post.local_path,
        source_refs=list(post.source_refs),
        summary=post.summary,
        created_at=post.created_at.isoformat(),
        updated_at=post.updated_at.isoformat(),
        page_id=post.notion_page_id,
    )


# ----- Notion API 속성 매핑 (real_client 전용) -----
def _rich_text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value or ""}}]}


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value or ""}}]}


def row_to_properties(row: NotionBlogRow) -> dict[str, Any]:
    """NotionBlogRow → Notion pages API의 properties 페이로드."""
    return {
        COL_TITLE: _title(row.title),
        COL_STATUS: {"select": {"name": row.status}},
        COL_SOURCE_PROJECT: _rich_text(row.source_project),
        COL_TAGS: {"multi_select": [{"name": t} for t in row.tags]},
        COL_LOCAL_PATH: _rich_text(row.local_path),
        COL_SOURCE_REFS: _rich_text(", ".join(row.source_refs)),
        COL_SLUG: _rich_text(row.slug),
        COL_SUMMARY: _rich_text(row.summary),
        COL_CREATED_AT: {"date": {"start": row.created_at}} if row.created_at else {"date": None},
        COL_UPDATED_AT: {"date": {"start": row.updated_at}} if row.updated_at else {"date": None},
    }


def _read_rich_text(prop: dict) -> str:
    parts = prop.get("rich_text") or prop.get("title") or []
    return "".join(p.get("plain_text", p.get("text", {}).get("content", "")) for p in parts)


def page_to_row(page: dict) -> NotionBlogRow:
    """Notion page 객체 → NotionBlogRow."""
    props = page.get("properties", {})

    def text(col: str) -> str:
        return _read_rich_text(props.get(col, {}))

    status_prop = props.get(COL_STATUS, {}).get("select") or {}
    tags_prop = props.get(COL_TAGS, {}).get("multi_select") or []
    refs = text(COL_SOURCE_REFS)

    return NotionBlogRow(
        title=text(COL_TITLE),
        slug=text(COL_SLUG),
        status=status_prop.get("name", BlogStatus.DRAFT.value),
        source_project=text(COL_SOURCE_PROJECT),
        tags=[t.get("name", "") for t in tags_prop],
        local_path=text(COL_LOCAL_PATH),
        source_refs=[r.strip() for r in refs.split(",") if r.strip()],
        summary=text(COL_SUMMARY),
        page_id=page.get("id"),
    )
