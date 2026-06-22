"""설정 기반 NotionClient 선택.

NOTION_API_KEY + Blog DB id가 모두 있으면 RealNotionClient, 아니면 MockNotionClient.
"""

from __future__ import annotations

from app.config import Settings
from app.notion.client import NotionClient
from app.notion.mock_client import MockNotionClient


def get_notion_client(settings: Settings) -> NotionClient:
    if settings.notion_enabled:
        # 실제 연동: notion-client 미설치 시 NotionConfigError가 올라온다.
        from app.notion.real_client import RealNotionClient

        return RealNotionClient(
            api_key=settings.notion_api_key,
            blog_database_id=settings.notion_blog_database_id,
        )
    return MockNotionClient(settings.notion_mock_path)
