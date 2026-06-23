"""Telegram 미디어 처리 테스트 — voice / image / URL."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.messaging.base import IncomingMessage
from app.messaging.media_handler import TelegramMediaHandler, is_url


# ── is_url ────────────────────────────────────────────────────────────────────

def test_is_url_detects_http():
    assert is_url("https://github.com/foo/bar") is True


def test_is_url_detects_http_plain():
    assert is_url("http://example.com") is True


def test_is_url_rejects_plain_text():
    assert is_url("오늘 RAG 작업했음") is False
    assert is_url("/capture 메모") is False


# ── IncomingMessage 미디어 필드 ──────────────────────────────────────────────

def test_incoming_message_defaults():
    msg = IncomingMessage(chat_id="1", text="hello", update_id=1)
    assert msg.voice_file_id == ""
    assert msg.photo_file_id == ""
    assert msg.caption == ""


def test_incoming_message_voice():
    msg = IncomingMessage(chat_id="1", update_id=1, voice_file_id="abc123")
    assert msg.voice_file_id == "abc123"
    assert msg.text == ""


# ── TelegramMediaHandler — voice ─────────────────────────────────────────────

def test_handle_voice_no_stt(tmp_path):
    """STT 미설정이면 attachment note만 저장하고 안내 메시지를 반환한다."""
    fake_file = tmp_path / "00_Inbox" / "Raw" / "Attachments" / "voice.ogg"

    mock_provider = MagicMock()
    mock_provider.download_file.return_value = fake_file
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"fake ogg data")

    mock_capture = MagicMock()
    mock_capture.capture_attachment.return_value = MagicMock(rel_path="00_Inbox/Captures/note.md")

    handler = TelegramMediaHandler(
        provider=mock_provider,
        capture_agent=mock_capture,
        vault_dir=tmp_path,
        stt=None,
    )
    msg = IncomingMessage(chat_id="1", update_id=1, voice_file_id="abc123")
    reply = handler.handle(msg)

    assert "STT provider가 설정되지 않아" in reply
    mock_capture.capture_attachment.assert_called_once()
    call_kwargs = mock_capture.capture_attachment.call_args.kwargs
    assert call_kwargs.get("source") == "telegram_voice"


def test_handle_voice_with_stt(tmp_path):
    """STT가 설정되면 텍스트를 capture에 저장한다."""
    from app.llm.stt import MockSpeechToTextProvider

    fake_file = tmp_path / "voice.ogg"
    fake_file.write_bytes(b"data")

    mock_provider = MagicMock()
    mock_provider.download_file.return_value = fake_file

    mock_capture = MagicMock()
    mock_capture.capture.return_value = MagicMock(rel_path="00_Inbox/Captures/note.md")

    stt = MockSpeechToTextProvider(response="오늘 RAG 작업했음")
    handler = TelegramMediaHandler(
        provider=mock_provider,
        capture_agent=mock_capture,
        vault_dir=tmp_path,
        stt=stt,
    )
    msg = IncomingMessage(chat_id="1", update_id=1, voice_file_id="abc123")
    reply = handler.handle(msg)

    assert "RAG 작업했음" in reply
    mock_capture.capture.assert_called_once()
    assert mock_capture.capture.call_args.kwargs.get("source") == "telegram_voice"


# ── TelegramMediaHandler — image ─────────────────────────────────────────────

def test_handle_image(tmp_path):
    fake_file = tmp_path / "image.jpg"
    fake_file.write_bytes(b"jpeg data")

    mock_provider = MagicMock()
    mock_provider.download_file.return_value = fake_file

    mock_capture = MagicMock()
    mock_capture.capture_attachment.return_value = MagicMock(rel_path="00_Inbox/Captures/img.md")

    handler = TelegramMediaHandler(
        provider=mock_provider,
        capture_agent=mock_capture,
        vault_dir=tmp_path,
    )
    msg = IncomingMessage(chat_id="1", update_id=1, photo_file_id="img001", caption="스크린샷")
    reply = handler.handle(msg)

    assert "이미지 캡처 완료" in reply
    mock_capture.capture_attachment.assert_called_once()
    kwargs = mock_capture.capture_attachment.call_args.kwargs
    assert kwargs.get("source") == "telegram_image"
    assert kwargs.get("caption") == "스크린샷"


# ── TelegramMediaHandler — URL ───────────────────────────────────────────────

def test_handle_url(tmp_path):
    mock_provider = MagicMock()
    mock_capture = MagicMock()
    mock_capture.capture_url.return_value = MagicMock(rel_path="00_Inbox/Captures/url.md")

    handler = TelegramMediaHandler(
        provider=mock_provider,
        capture_agent=mock_capture,
        vault_dir=tmp_path,
    )
    reply = handler.handle_url("https://example.com/article")

    assert "URL 캡처 완료" in reply
    mock_capture.capture_url.assert_called_once()


# ── CaptureAgent.capture_attachment ─────────────────────────────────────────

def test_capture_attachment_voice(tmp_path):
    from app.agents.capture_agent import CaptureAgent
    from app.config import Settings

    settings = Settings(OBSIDIAN_VAULT_PATH=str(tmp_path), LLM_PROVIDER="")
    agent = CaptureAgent(settings=settings)

    attachment = tmp_path / "00_Inbox" / "Raw" / "Attachments" / "voice.ogg"
    attachment.parent.mkdir(parents=True, exist_ok=True)
    attachment.write_bytes(b"data")

    result = agent.capture_attachment(attachment, source="telegram_voice")

    assert result.rel_path.startswith("00_Inbox/Captures/")
    text = result.path.read_text(encoding="utf-8")
    assert "source: telegram_voice" in text
    assert "STT" in text


def test_capture_url_saves_note(tmp_path):
    from app.agents.capture_agent import CaptureAgent
    from app.config import Settings

    settings = Settings(OBSIDIAN_VAULT_PATH=str(tmp_path), LLM_PROVIDER="")
    agent = CaptureAgent(settings=settings)

    result = agent.capture_url("https://example.com", title="Example", source="telegram_url")

    assert result.rel_path.startswith("00_Inbox/Captures/")
    text = result.path.read_text(encoding="utf-8")
    assert "url: https://example.com" in text
    assert "title: Example" in text
    assert "source: telegram_url" in text
