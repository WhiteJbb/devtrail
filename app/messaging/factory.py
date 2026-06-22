"""설정 기반 메신저 provider 선택."""

from __future__ import annotations

from app.config import Settings
from app.messaging.base import MessengerNotConfiguredError, MessengerProvider


def get_messenger_provider(settings: Settings) -> MessengerProvider:
    provider = (settings.messenger_provider or "").strip().lower()

    if not provider:
        raise MessengerNotConfiguredError(
            "MESSENGER_PROVIDER가 설정되지 않았습니다. .env에서 'telegram'으로 지정하세요."
        )

    if provider == "telegram":
        if not settings.telegram_bot_token:
            raise MessengerNotConfiguredError("TELEGRAM_BOT_TOKEN이 비어 있습니다.")
        from app.messaging.telegram_provider import TelegramProvider

        return TelegramProvider(token=settings.telegram_bot_token)

    raise MessengerNotConfiguredError(f"지원하지 않는 MESSENGER_PROVIDER: {provider!r}")
