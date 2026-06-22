"""에이전트 공용 — source collector 조립.

BlogAgent와 WorklogAgent가 같은 소스(local docs/git/notion)를 쓰므로 한곳에 모은다.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.content_sources.collector import SourceCollector
from app.content_sources.git_source import GitSource
from app.content_sources.local_doc_source import LocalDocSource
from app.content_sources.notion_source import NotionSource
from app.notion.factory import get_notion_client


def build_source_collector(settings: Settings, repo_dir: Path) -> SourceCollector:
    sources = [
        LocalDocSource(settings.docs_path),
        GitSource(repo_dir, limit=settings.git_log_limit),
        NotionSource(
            get_notion_client(settings),
            idea_database_id=settings.notion_idea_database_id,
            worklog_database_id=settings.notion_worklog_database_id,
            source_page_ids=settings.source_page_ids,
        ),
    ]
    return SourceCollector(sources, char_budget=settings.context_char_budget)
