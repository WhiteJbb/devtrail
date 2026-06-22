"""블로그 주제 추천 결과 모델."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TopicSuggestion(BaseModel):
    """suggest-topics가 내놓는 주제 한 건."""

    title_candidates: list[str] = Field(default_factory=list)
    reason: str = ""
    outline: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
