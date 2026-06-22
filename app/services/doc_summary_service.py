"""범용 문서 요약 서비스.

수집한 source를 지정한 프롬프트로 LLM에 넘겨 마크다운 본문을 반환한다.
Portfolio/Resume 등 '소스 → 마크다운 문서' 형태 Agent가 공유한다.
"""

from __future__ import annotations

from app.content_sources.collector import SourceCollector
from app.llm.base import LLMProvider
from app.prompts import render_prompt


class DocSummaryService:
    def __init__(self, collector: SourceCollector, llm: LLMProvider, prompt_name: str):
        self.collector = collector
        self.llm = llm
        self.prompt_name = prompt_name

    def summarize(self) -> str:
        context = self.collector.collect()
        prompt = render_prompt(self.prompt_name, CONTEXT=context.as_prompt_text())
        return self.llm.complete(prompt).strip()
