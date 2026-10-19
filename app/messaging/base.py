"""메신저 provider 인터페이스."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class MessengerNotConfiguredError(RuntimeError):
    """메신저 provider 설정이 미비할 때(토큰 없음 등)."""


@runtime_checkable
class MessengerProvider(Protocol):
    """메신저 송신 공통 인터페이스(텔레그램/매터모스트 등 공용)."""

    name: str

    def send(self, chat_id: str, text: str) -> None:
        """chat_id로 텍스트 전송."""
        ...
