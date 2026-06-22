"""범용 문서 Agent 베이스.

'source 수집 → 프롬프트 → 마크다운 저장' 형태 Agent의 공통 골격.
Portfolio/Resume Agent가 prompt_name과 출력 경로만 지정해 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.context_builder import build_source_collector
from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.services.doc_summary_service import DocSummaryService


@dataclass
class DocResult:
    text: str
    path: Path


class DocAgent:
    """서브클래스가 prompt_name과 _out_dir만 지정하면 동작한다."""

    prompt_name: str = ""

    def __init__(self, settings: Settings | None = None, repo_dir: Path | None = None):
        self.settings = settings or get_settings()
        self.repo_dir = repo_dir or Path.cwd()

    def _llm(self) -> LLMProvider:
        return get_llm_provider(self.settings)

    def _out_dir(self) -> Path:
        raise NotImplementedError

    def generate(self, save: bool = True) -> DocResult:
        collector = build_source_collector(self.settings, self.repo_dir)
        text = DocSummaryService(collector, self._llm(), self.prompt_name).summarize()

        path = self._out_dir() / f"{datetime.now(timezone.utc):%Y%m%d}.md"
        if save:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        return DocResult(text=text, path=path)
