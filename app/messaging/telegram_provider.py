"""Telegram Bot API provider (httpx 기반 long-polling).

별도 SDK 없이 Bot API의 getUpdates/sendMessage만 사용한다. 공개 서버/웹훅이 필요 없어
윈도우 로컬에서도 양방향 동작한다.
"""

from __future__ import annotations

import httpx

from app.messaging.base import IncomingMessage

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_LEN = 4000  # 텔레그램 메시지 길이 한도(4096) 여유


class TelegramProvider:
    name = "telegram"

    def __init__(self, token: str, poll_timeout: int = 50):
        self.token = token
        self.poll_timeout = poll_timeout

    def _url(self, method: str) -> str:
        return _API.format(token=self.token, method=method)

    def send(self, chat_id: str, text: str) -> None:
        # 길이 한도를 넘으면 잘라서 여러 번 보낸다.
        for i in range(0, len(text) or 1, _MAX_LEN):
            chunk = text[i : i + _MAX_LEN] or text
            httpx.post(
                self._url("sendMessage"),
                json={"chat_id": chat_id, "text": chunk},
                timeout=30.0,
            ).raise_for_status()
            if not text:
                break

    def get_updates(self, offset: int | None = None) -> tuple[list[IncomingMessage], int]:
        params: dict = {"timeout": self.poll_timeout}
        if offset is not None:
            params["offset"] = offset
        resp = httpx.get(
            self._url("getUpdates"),
            params=params,
            timeout=self.poll_timeout + 10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        messages: list[IncomingMessage] = []
        next_offset = offset or 0
        for upd in data.get("result", []):
            update_id = upd.get("update_id", 0)
            next_offset = max(next_offset, update_id + 1)
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            text = msg.get("text")
            chat = msg.get("chat", {})
            if text is None or "id" not in chat:
                continue
            messages.append(
                IncomingMessage(chat_id=str(chat["id"]), text=text, update_id=update_id)
            )
        return messages, next_offset
