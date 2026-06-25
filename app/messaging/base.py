"""메신저 provider 인터페이스."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    chat_id: str
    text: str = ""
    update_id: int
    voice_file_id: str = ""
    photo_file_id: str = ""
    caption: str = ""
    callback_query_id: str = ""  # non-empty when message originated from an inline button tap


class MessengerNotConfiguredError(RuntimeError):
    """메신저 provider 설정이 미비할 때(토큰 없음 등)."""


@runtime_checkable
class MessengerProvider(Protocol):
    """메신저 송수신 공통 인터페이스(텔레그램/매터모스트 등 공용)."""

    name: str

    def send(self, chat_id: str, text: str) -> None:
        """chat_id로 텍스트 전송."""
        ...

    def get_updates(self, offset: int | None = None) -> tuple[list[IncomingMessage], int]:
        """새 메시지들과 다음 offset을 반환(long-polling 기반)."""
        ...
