"""주제 추천 서비스."""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.models import TopicSuggestion
from app.prompts import render_prompt
from app.services.json_utils import extract_json_object


class TopicRecommender:
    """수집한 컨텍스트로 LLM에 주제 추천을 요청하고 결과를 파싱한다."""

    def __init__(self, collector: SourceCollector, llm: LLMProvider):
        self.collector = collector
        self.llm = llm

    def recommend(self) -> list[TopicSuggestion]:
        context = self.collector.collect()
        prompt = render_prompt("recommend_topics", CONTEXT=context.as_prompt_text())
        raw = self.llm.complete(prompt)
        data = extract_json_object(raw)

        suggestions: list[TopicSuggestion] = []
        for item in data.get("topics", []):
            suggestions.append(
                TopicSuggestion(
                    title_candidates=item.get("title_candidates", []),
                    reason=item.get("reason", ""),
                    outline=item.get("outline", []),
                    source_refs=item.get("source_refs", []),
                )
            )
        return suggestions
