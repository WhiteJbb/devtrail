"""ContentSource 프로토콜."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import SourceChunk


@runtime_checkable
class ContentSource(Protocol):
    """컨텍스트를 읽어오는 소스의 공통 인터페이스.

    구현체는 외부(파일/Git/Notion)에서 내용을 읽어 SourceChunk 리스트로 돌려준다.
    읽기에 실패하면(파일 없음 등) 예외를 던지지 말고 빈 리스트를 반환해
    수집 파이프라인이 한 소스의 부재로 멈추지 않게 한다.
    """

    name: str

    def fetch(self) -> list[SourceChunk]:
        ...
