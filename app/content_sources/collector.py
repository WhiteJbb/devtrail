"""수집(collect) + 정제(trim) — 여러 소스를 모아 예산 한도로 컨텍스트를 만든다.

모든 파일을 무작정 LLM에 넣지 않는다. 소스별 상한과 전체 문자 예산을 두어
컨텍스트가 비대해지지 않게 자른다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.content_sources.base import ContentSource
from app.models import SourceChunk


@dataclass
class CollectedContext:
    """수집·정제된 컨텍스트."""

    chunks: list[SourceChunk]

    @property
    def refs(self) -> list[str]:
        """source_refs 표기에 쓸 참조 목록(중복 제거, 순서 유지)."""
        seen: dict[str, None] = {}
        for c in self.chunks:
            seen.setdefault(c.as_ref(), None)
        return list(seen.keys())

    def as_prompt_text(self) -> str:
        """프롬프트에 끼워 넣을 컨텍스트 블록 문자열."""
        blocks = []
        for c in self.chunks:
            header = f"### [{c.source_type}] {c.title or c.ref}".rstrip()
            blocks.append(f"{header}\n(ref: {c.as_ref()})\n{c.text}")
        return "\n\n".join(blocks)


class SourceCollector:
    """등록된 소스들을 fetch해 하나의 CollectedContext로 합친다."""

    def __init__(
        self,
        sources: list[ContentSource],
        char_budget: int = 12000,
        per_chunk_limit: int = 4000,
    ):
        self.sources = sources
        self.char_budget = char_budget
        self.per_chunk_limit = per_chunk_limit

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n…(이하 생략)"

    def collect(self) -> CollectedContext:
        kept: list[SourceChunk] = []
        used = 0
        for source in self.sources:
            try:
                chunks = source.fetch()
            except Exception:
                # 소스 하나가 깨져도 수집 전체를 멈추지 않는다.
                chunks = []
            for chunk in chunks:
                if used >= self.char_budget:
                    return CollectedContext(chunks=kept)
                remaining = self.char_budget - used
                limit = min(self.per_chunk_limit, remaining)
                text = self._truncate(chunk.text, limit)
                kept.append(chunk.model_copy(update={"text": text}))
                used += len(text)
        return CollectedContext(chunks=kept)
