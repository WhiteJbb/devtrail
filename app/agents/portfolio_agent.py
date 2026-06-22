"""Portfolio Agent — 프로젝트 기록 기반 포트폴리오 설명 초안."""

from __future__ import annotations

from pathlib import Path

from app.agents.doc_agent import DocAgent


class PortfolioAgent(DocAgent):
    prompt_name = "portfolio"

    def _out_dir(self) -> Path:
        return self.settings.portfolio_path
