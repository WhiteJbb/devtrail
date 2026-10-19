"""메신저 연동 계층 — 송신 전용(digest·주간 회고·알림). 수신 봇은 2026-10-19 제거."""

from app.messaging.base import MessengerProvider
from app.messaging.factory import get_messenger_provider

__all__ = ["MessengerProvider", "get_messenger_provider"]
