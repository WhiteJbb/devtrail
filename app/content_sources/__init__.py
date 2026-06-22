"""콘텐츠 수집 계층.

데이터를 '읽기'만 한다. 저장/동기화는 repositories/storage 계층 책임.
각 source는 ContentSource 프로토콜을 따르며 list[SourceChunk]를 반환한다.
"""

from app.content_sources.base import ContentSource
from app.content_sources.collector import SourceCollector
from app.content_sources.git_source import GitSource
from app.content_sources.local_doc_source import LocalDocSource

__all__ = [
    "ContentSource",
    "SourceCollector",
    "GitSource",
    "LocalDocSource",
]
