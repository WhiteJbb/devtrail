"""메신저 연동 계층 — 또 하나의 '입구'.

CLI처럼 얇은 어댑터다. 들어온 메시지를 명령으로 해석해 BlogAgent를 호출하고
결과를 답장한다. provider(텔레그램 등)는 교체 가능하게 분리한다.
"""

from app.messaging.base import IncomingMessage, MessengerProvider
from app.messaging.bot import MessengerBot
from app.messaging.factory import get_messenger_provider
from app.messaging.router import CommandRouter

__all__ = [
    "IncomingMessage",
    "MessengerProvider",
    "MessengerBot",
    "CommandRouter",
    "get_messenger_provider",
]
