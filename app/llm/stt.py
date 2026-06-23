"""Speech-to-Text provider 인터페이스.

초기 구현은 Mock provider만 포함한다.
외부 STT (OpenAI Whisper, local Whisper 등)는 이 Protocol을 구현해서 주입한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechToTextProvider(Protocol):
    name: str

    def transcribe(self, file_path: Path) -> str:
        """음성 파일 경로를 받아 텍스트를 반환한다."""
        ...


class MockSpeechToTextProvider:
    """테스트용 고정 응답 STT provider."""

    name = "mock"

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.last_file: Path | None = None

    def transcribe(self, file_path: Path) -> str:
        self.last_file = file_path
        return self.response


def get_stt_provider() -> SpeechToTextProvider | None:
    """설정된 STT provider를 반환한다. 미설정이면 None.

    TODO: STT_PROVIDER 환경변수 지원 (whisper, openai-whisper 등).
    """
    return None
