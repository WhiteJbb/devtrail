"""메신저 봇 루프 — provider와 라우터를 잇는다.

허용된 chat에서 온 메시지만 라우터로 넘겨 처리하고 답장한다. 알림(outbound)도 제공.
process_once는 네트워크 한 번 폴링 단위라 테스트하기 쉽다.
"""

from __future__ import annotations

from app.messaging.base import MessengerProvider
from app.messaging.router import CommandRouter


class MessengerBot:
    def __init__(
        self,
        provider: MessengerProvider,
        router: CommandRouter,
        allowed_chat_ids: list[str] | None = None,
        default_chat_id: str = "",
    ):
        self.provider = provider
        self.router = router
        # 허용 목록이 비어 있으면 모든 chat 허용(권장하지 않음 — 경고는 CLI에서).
        self.allowed_chat_ids = set(allowed_chat_ids or [])
        self.default_chat_id = default_chat_id
        self._offset: int | None = None

    def _is_allowed(self, chat_id: str) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def process_once(self) -> int:
        """한 번 폴링해 들어온 메시지를 처리한다. 처리한 메시지 수를 반환."""
        messages, next_offset = self.provider.get_updates(self._offset)
        self._offset = next_offset
        handled = 0
        for msg in messages:
            if not self._is_allowed(msg.chat_id):
                # 허용되지 않은 사용자에겐 응답하지 않는다(스팸/오남용 방지).
                continue
            reply = self.router.handle(msg.text)
            self.provider.send(msg.chat_id, reply)
            handled += 1
        return handled

    def run(self) -> None:  # pragma: no cover - 무한 루프(수동 실행)
        while True:
            self.process_once()

    def notify(self, text: str, chat_id: str = "") -> None:
        """알림(outbound) 전송. chat_id 생략 시 default_chat_id 사용."""
        target = chat_id or self.default_chat_id
        if not target:
            raise ValueError("알림을 보낼 chat_id가 없습니다(TELEGRAM_CHAT_ID 설정).")
        self.provider.send(target, text)
