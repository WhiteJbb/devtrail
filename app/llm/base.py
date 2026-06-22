"""LLMProvider 인터페이스 및 예외."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMNotConfiguredError(RuntimeError):
    """LLM provider가 설정되지 않았을 때.

    이 경우 가짜 초안을 만들지 않고 사용자에게 명확히 안내한다(설계 원칙).
    """


class LLMError(RuntimeError):
    """LLM 호출 자체가 실패했을 때(네트워크/엔드포인트/모델 오류)."""


@runtime_checkable
class LLMProvider(Protocol):
    """텍스트 생성 provider 공통 인터페이스."""

    name: str
    model: str

    def complete(self, prompt: str, system: str = "") -> str:
        """프롬프트에 대한 완성 텍스트를 반환. 실패 시 LLMError."""
        ...
