"""Kimi (Moonshot AI) provider — OpenAI-compatible.

Kimi는 OpenAI chat/completions API를 그대로 사용한다.
OpenAICompatibleProvider에 base_url / api_key / model만 Kimi 설정으로 바꿔 재사용한다.
"""

from __future__ import annotations

from app.llm.openai_compatible_provider import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    """Kimi(Moonshot AI) provider. OpenAI-compatible이므로 부모 클래스를 그대로 재사용."""

    name = "kimi"
