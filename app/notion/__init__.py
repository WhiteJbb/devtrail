"""Notion 연동 전용 계층.

Notion API 의존성을 이 계층에 격리한다. 상위는 NotionClient 인터페이스만 본다.
NOTION_API_KEY가 없으면 mock(JSON 백엔드)으로 동작한다.
"""

from app.notion.client import NotionClient
from app.notion.factory import get_notion_client
from app.notion.mock_client import MockNotionClient

__all__ = ["NotionClient", "MockNotionClient", "get_notion_client"]
