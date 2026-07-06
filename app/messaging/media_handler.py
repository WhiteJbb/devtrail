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
        return "이 형식은 아직 처리하지 못해요. 텍스트·음성·사진·URL을 보내주세요."

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
            if llm:
                label = "🔗 링크 읽고 요약까지 해뒀어요 (URL 캡처 + 요약 완료)"
            else:
                label = "🔗 링크 저장해뒀어요 (URL 캡처 완료 — LLM 미설정이라 요약은 건너뛰었어요)"
            return (
                f"{label}\n└ {result.rel_path}\n\n"
                "오늘 밤 정제할 때 지식 후보로 같이 살펴볼게요."
            )
        except Exception as e:
            return f"링크를 저장하지 못했어요: {e}"

    def _handle_voice(self, msg: IncomingMessage) -> str:
        dest_dir = self.vault_dir / "00_Inbox" / "Raw" / "Attachments"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{stamp}-voice.ogg"
        try:
            file_path = self.provider.download_file(msg.voice_file_id, dest_dir, filename)
        except Exception as e:
            return f"음성 파일을 받지 못했어요: {e}"

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
                    f"🎙 음성 메모, 받아적어서 저장해뒀어요\n"
                    f"└ {result.rel_path}\n\n"
                    f"들은 내용: {transcript[:200]}"
                )
            except Exception as e:
                return f"받아적었는데 저장에 실패했어요: {e}"
        else:
            try:
                result = self.capture_agent.capture_attachment(
                    file_path=file_path, source="telegram_voice"
                )
                return (
                    f"🎙 음성 파일은 저장해뒀어요\n"
                    f"└ {result.rel_path}\n\n"
                    f"다만 STT provider가 설정되지 않아 텍스트 변환은 건너뛰었어요.\n"
                    f".env에 STT 설정을 추가하면 다음부터는 자동으로 받아적어드릴게요."
                )
            except Exception as e:
                return f"음성 파일 저장에 실패했어요: {e}"

    def _handle_image(self, msg: IncomingMessage) -> str:
        dest_dir = self.vault_dir / "00_Inbox" / "Raw" / "Attachments"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{stamp}-image.jpg"
        try:
            file_path = self.provider.download_file(msg.photo_file_id, dest_dir, filename)
        except Exception as e:
            return f"이미지를 받지 못했어요: {e}"

        try:
            result = self.capture_agent.capture_attachment(
                file_path=file_path,
                source="telegram_image",
                caption=msg.caption or msg.text,
            )
            return (
                f"🖼 이미지 캡처 완료 — 노트로 저장해뒀어요\n└ {result.rel_path}\n\n"
                "캡션을 같이 보내주시면 나중에 검색하기 좋아요."
            )
        except Exception as e:
            return f"이미지 저장에 실패했어요: {e}"
