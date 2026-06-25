"""Telegram Bot API provider (httpx 기반 long-polling).

별도 SDK 없이 Bot API의 getUpdates/sendMessage만 사용한다. 공개 서버/웹훅이 필요 없어
윈도우 로컬에서도 양방향 동작한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from app.messaging.base import IncomingMessage

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_LEN = 4000  # 텔레그램 메시지 길이 한도(4096) 여유


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_to_html(text: str) -> str:
    """Markdown을 Telegram HTML로 변환한다.

    코드 블록/인라인 코드 안의 내용은 변환하지 않고 HTML 엔티티만 이스케이프한다.
    """
    # 코드 블록/인라인 코드를 먼저 분리해 저장 (내부 변환 방지)
    placeholders: dict[str, str] = {}
    counter = [0]

    def save(html: str) -> str:
        key = f"\x00PLACEHOLDER{counter[0]}\x00"
        placeholders[key] = html
        counter[0] += 1
        return key

    # ``` 코드 블록
    def replace_code_block(m: re.Match) -> str:
        inner = _escape_html(m.group(1).strip("\n"))
        return save(f"<pre><code>{inner}</code></pre>")

    text = re.sub(r"```[^\n]*\n?([\s\S]*?)```", replace_code_block, text)

    # `인라인 코드`
    def replace_inline(m: re.Match) -> str:
        return save(f"<code>{_escape_html(m.group(1))}</code>")

    text = re.sub(r"`([^`\n]+)`", replace_inline, text)

    # 나머지 텍스트 HTML 이스케이프
    text = _escape_html(text)

    # ## 헤더 → <b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    # **bold**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    # *italic* (단독 *)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", text)
    # _italic_
    text = re.sub(r"(?<![_\w])_([^_\n]+)_(?![_\w])", r"<i>\1</i>", text)

    # 플레이스홀더 복원
    for key, val in placeholders.items():
        text = text.replace(key, val)

    return text


class TelegramProvider:
    name = "telegram"

    def __init__(self, token: str, poll_timeout: int = 50):
        self.token = token
        self.poll_timeout = poll_timeout

    def _url(self, method: str) -> str:
        return _API.format(token=self.token, method=method)

    def send(self, chat_id: str, text: str) -> None:
        html = _md_to_html(text)
        # 길이 한도를 넘으면 잘라서 여러 번 보낸다.
        for i in range(0, len(html) or 1, _MAX_LEN):
            chunk = html[i : i + _MAX_LEN] or html
            httpx.post(
                self._url("sendMessage"),
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=30.0,
            ).raise_for_status()
            if not html:
                break

    def send_with_buttons(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict]],
    ) -> None:
        """인라인 키보드 버튼과 함께 메시지를 전송한다."""
        html = _md_to_html(text)
        httpx.post(
            self._url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": html[:_MAX_LEN],
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": buttons},
            },
            timeout=30.0,
        ).raise_for_status()

    def _answer_callback(self, callback_query_id: str, text: str = "") -> None:
        """콜백 쿼리에 응답해 버튼 로딩 상태를 해제한다."""
        try:
            httpx.post(
                self._url("answerCallbackQuery"),
                json={"callback_query_id": callback_query_id, "text": text},
                timeout=10.0,
            )
        except Exception:
            pass

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

            # 인라인 버튼 탭 — callback_query로 들어온다
            cbq = upd.get("callback_query")
            if cbq:
                self._answer_callback(cbq["id"])
                chat = cbq.get("message", {}).get("chat", {})
                chat_id = str(chat.get("id", ""))
                if chat_id and cbq.get("data"):
                    messages.append(IncomingMessage(
                        chat_id=chat_id,
                        text=cbq["data"],
                        update_id=update_id,
                        callback_query_id=cbq["id"],
                    ))
                continue

            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))
            if not chat_id:
                continue

            text = msg.get("text") or ""
            caption = msg.get("caption") or ""
            voice_file_id = ""
            photo_file_id = ""

            if msg.get("voice"):
                voice_file_id = str(msg["voice"].get("file_id", ""))
            elif msg.get("photo"):
                photos = msg["photo"]
                if photos:
                    photo_file_id = str(photos[-1].get("file_id", ""))

            # 텍스트도 없고 미디어도 없으면 skip
            if not text and not voice_file_id and not photo_file_id:
                continue

            messages.append(IncomingMessage(
                chat_id=chat_id,
                text=text,
                update_id=update_id,
                voice_file_id=voice_file_id,
                photo_file_id=photo_file_id,
                caption=caption,
            ))
        return messages, next_offset

    def download_file(self, file_id: str, dest_dir: Path, filename: str = "") -> Path:
        """Telegram file_id를 받아 dest_dir에 다운로드하고 저장 경로를 반환한다."""
        resp = httpx.get(
            self._url("getFile"),
            params={"file_id": file_id},
            timeout=30.0,
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        content = httpx.get(file_url, timeout=60.0).content

        dest_dir.mkdir(parents=True, exist_ok=True)
        name = filename or Path(file_path).name
        dest = dest_dir / name
        dest.write_bytes(content)
        return dest
