"""Todo Agent — 최근 작업 기반 다음 할 일을 제안한다.

'source → 마크다운 문서' 형태이므로 DocAgent를 상속해 프롬프트명/출력경로만 지정한다.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.doc_agent import DocAgent


class TodoAgent(DocAgent):
    prompt_name = "todo_suggest"

    def _out_dir(self) -> Path:
        return self.settings.todos_path
