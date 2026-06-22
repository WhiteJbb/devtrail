"""Worklog Agent — 최근 작업을 자동 회고로 정리한다.

Blog Agent와 같은 source 계층(git/worklog/notion)을 재사용한다. 두 번째 확장 모듈.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.context_builder import build_source_collector
from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.services.worklog_summarizer import WorklogSummarizer


@dataclass
class WorklogResult:
    text: str
    path: Path


class WorklogAgent:
    def __init__(self, settings: Settings | None = None, repo_dir: Path | None = None):
        self.settings = settings or get_settings()
        self.repo_dir = repo_dir or Path.cwd()

    def _llm(self) -> LLMProvider:
        return get_llm_provider(self.settings)

    def generate(self, save: bool = True) -> WorklogResult:
        collector = build_source_collector(self.settings, self.repo_dir)
        text = WorklogSummarizer(collector, self._llm()).summarize()

        path = self.settings.worklogs_path / f"{datetime.now(timezone.utc):%Y%m%d}.md"
        if save:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        return WorklogResult(text=text, path=path)
