"""메신저 봇 루프 — provider/라우터/비서를 잇는다.

허용된 chat에서 온 메시지만 처리한다.
- "/명령" → CommandRouter(슬래시 명령)
- 그 외 자유 문장 → Assistant로 의도 분류 후 "실행할까요?" 확인을 받고 실행(항상 확인)
assistant가 없으면(LLM 미설정) 자유 문장은 도움말로 안내한다.
process_once는 네트워크 한 번 폴링 단위라 테스트하기 쉽다.
"""

from __future__ import annotations

from app.messaging.base import MessengerProvider
from app.messaging.router import CommandRouter

_YES = {"예", "네", "ㅇ", "응", "ok", "오케이", "yes", "y"}
_NO = {"아니", "아니오", "ㄴ", "취소", "cancel", "no", "n"}


class MessengerBot:
    def __init__(
        self,
        provider: MessengerProvider,
        router: CommandRouter,
        allowed_chat_ids: list[str] | None = None,
        default_chat_id: str = "",
        assistant=None,
    ):
        self.provider = provider
        self.router = router
        self.assistant = assistant
        self.allowed_chat_ids = set(allowed_chat_ids or [])
        self.default_chat_id = default_chat_id
        self._offset: int | None = None
        self._pending: dict[str, object] = {}  # chat_id → 확인 대기 중인 Intent

    def _is_allowed(self, chat_id: str) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def _handle_text(self, chat_id: str, text: str) -> str:
        t = (text or "").strip()
        low = t.lower()

        # 1) 확인 대기 중이면 예/아니오 처리
        if chat_id in self._pending:
            if low in _YES:
                intent = self._pending.pop(chat_id)
                try:
                    return self.assistant.execute(intent)
                except Exception as e:
                    return f"실행 중 오류: {e}"
            if low in _NO:
                self._pending.pop(chat_id)
                return "취소했습니다."
            # 그 외 입력은 새 요청으로 본다(대기 해제 후 계속)
            self._pending.pop(chat_id)

        # 2) 슬래시 명령은 그대로 실행
        if t.startswith("/"):
            return self.router.handle(t)

        # 3) 자유 문장 → 비서가 있으면 의도 분류 후 확인, 없으면 도움말
        if self.assistant is None:
            return self.router.handle(t)

        try:
            intent = self.assistant.interpret(t)
        except Exception as e:
            return f"이해하지 못했습니다: {e}"

        if intent.command in ("unknown", "help", ""):
            return self.assistant.help_text()

        self._pending[chat_id] = intent
        return f"해석: {self.assistant.describe(intent)}\n실행할까요? (예/아니오)"

    def process_once(self) -> int:
        """한 번 폴링해 들어온 메시지를 처리한다. 처리한 메시지 수를 반환."""
        messages, next_offset = self.provider.get_updates(self._offset)
        self._offset = next_offset
        handled = 0
        for msg in messages:
            if not self._is_allowed(msg.chat_id):
                continue
            reply = self._handle_text(msg.chat_id, msg.text)
            self.provider.send(msg.chat_id, reply)
            handled += 1
        return handled

    def run(self) -> None:  # pragma: no cover - 무한 루프(수동 실행)
        while True:
            self.process_once()

    def notify(self, text: str, chat_id: str = "") -> None:
        target = chat_id or self.default_chat_id
        if not target:
            raise ValueError("알림을 보낼 chat_id가 없습니다(TELEGRAM_CHAT_ID 설정).")
        self.provider.send(target, text)
