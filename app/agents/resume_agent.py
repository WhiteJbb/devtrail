"""Resume Agent — 이력서 bullet / 자기소개서 초안."""

from __future__ import annotations

from pathlib import Path

from app.agents.doc_agent import DocAgent


class ResumeAgent(DocAgent):
    prompt_name = "resume"

    def _out_dir(self) -> Path:
        return self.settings.resume_path
