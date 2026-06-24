"""Telegram 미디어 메시지 처리 — voice / image / URL."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.messaging.base import IncomingMessage

_URL_RE = re.compile(
    r"^https?://[^\s/$.?#].[^\s]*$",
    re.IGNORECASE,
)


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


class TelegramMediaHandler:
    """TelegramProvider + CaptureAgent를 연결해 미디어 메시지를 처리한다."""

    def __init__(self, provider, capture_agent, vault_dir: Path, stt=None) -> None:
        self.provider = provider
        self.capture_agent = capture_agent
        self.vault_dir = vault_dir
        self.stt = stt

    def handle(self, msg: IncomingMessage) -> str:
        if msg.voice_file_id:
            return self._handle_voice(msg)
        if msg.photo_file_id:
            return self._handle_image(msg)
        return "알 수 없는 미디어 타입입니다."

    def handle_url(self, url: str) -> str:
        llm = None
        try:
            from app.config import get_settings
            from app.llm.factory import get_task_llm_provider
            llm = get_task_llm_provider("light", get_settings())
        except Exception:
            pass
        try:
            result = self.capture_agent.capture_url(url, source="telegram_url", llm=llm)
            label = "URL 캡처 + 요약 완료" if llm else "URL 캡처 완료"
            return f"{label}\n노트: {result.rel_path}"
        except Exception as e:
            return f"URL 캡처 실패: {e}"

    def _handle_voice(self, msg: IncomingMessage) -> str:
        dest_dir = self.vault_dir / "00_Inbox" / "Raw" / "Attachments"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{stamp}-voice.ogg"
        try:
            file_path = self.provider.download_file(msg.voice_file_id, dest_dir, filename)
        except Exception as e:
            return f"음성 파일 다운로드 실패: {e}"

        transcript = ""
        if self.stt is not None:
            try:
                transcript = self.stt.transcribe(file_path)
            except Exception:
                transcript = ""

        if transcript:
            try:
                result = self.capture_agent.capture(text=transcript, source="telegram_voice")
                return (
                    f"음성 캡처 완료\n"
                    f"텍스트: {transcript[:200]}\n"
                    f"노트: {result.rel_path}"
                )
            except Exception as e:
                return f"캡처 저장 실패: {e}"
        else:
            try:
                result = self.capture_agent.capture_attachment(
                    file_path=file_path, source="telegram_voice"
                )
                return (
                    f"음성 파일 저장 완료.\n\n"
                    f"STT provider가 설정되지 않아 텍스트 변환은 건너뜀.\n"
                    f"노트: {result.rel_path}"
                )
            except Exception as e:
                return f"attachment 저장 실패: {e}"

    def _handle_image(self, msg: IncomingMessage) -> str:
        dest_dir = self.vault_dir / "00_Inbox" / "Raw" / "Attachments"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{stamp}-image.jpg"
        try:
            file_path = self.provider.download_file(msg.photo_file_id, dest_dir, filename)
        except Exception as e:
            return f"이미지 다운로드 실패: {e}"

        try:
            result = self.capture_agent.capture_attachment(
                file_path=file_path,
                source="telegram_image",
                caption=msg.caption or msg.text,
            )
            return f"이미지 캡처 완료\n노트: {result.rel_path}"
        except Exception as e:
            return f"이미지 캡처 저장 실패: {e}"
