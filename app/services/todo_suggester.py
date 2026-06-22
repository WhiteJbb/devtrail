"""다음 할 일 제안 서비스.

수집한 source(git/worklog/todo/notion)로 LLM에 다음 할 일 정리를 요청한다.
회고와 마찬가지로 마크다운 본문을 그대로 반환한다.
"""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.prompts import render_prompt


class TodoSuggester:
    def __init__(self, collector: SourceCollector, llm: LLMProvider):
        self.collector = collector
        self.llm = llm

    def suggest(self) -> str:
        context = self.collector.collect()
        prompt = render_prompt("todo_suggest", CONTEXT=context.as_prompt_text())
        return self.llm.complete(prompt).strip()
