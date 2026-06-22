"""Worklog Agent — 최근 작업을 자동 회고로 정리한다.

'source → 마크다운 문서' 형태이므로 DocAgent를 상속해 프롬프트명/출력경로만 지정한다.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.doc_agent import DocAgent


class WorklogAgent(DocAgent):
    prompt_name = "worklog_summary"

    def _out_dir(self) -> Path:
        return self.settings.worklogs_path
