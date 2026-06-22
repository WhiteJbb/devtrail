"""작업 회고 생성 서비스.

수집한 source(git/worklog/notion)로 LLM에 회고 정리를 요청한다.
초안 생성과 달리 마크다운 본문을 그대로 반환한다(구조화 JSON 불필요).
"""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.prompts import render_prompt


class WorklogSummarizer:
    def __init__(self, collector: SourceCollector, llm: LLMProvider):
        self.collector = collector
        self.llm = llm

    def summarize(self) -> str:
        context = self.collector.collect()
        prompt = render_prompt("worklog_summary", CONTEXT=context.as_prompt_text())
        return self.llm.complete(prompt).strip()
