"""ProjectAgent — 특정 프로젝트에 대한 요약/포트폴리오/면접 질문 초안 생성."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_writer_llm_provider
from app.memory.context_pack_builder import ContextPackBuilder
from app.prompts import render_prompt
from app.services.wiki_service import WikiService


@dataclass(frozen=True)
class ProjectResult:
    project: str
    output_type: str
    text: str
    path: Path
    source_refs: list[str]


class ProjectAgent:
    """프로젝트 이름을 받아 요약·포트폴리오·면접 질문 초안을 생성한다."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)
        self.builder = ContextPackBuilder(self.vault_dir, wiki_service=self.wiki_service)

    def summarize_project(self, project: str) -> ProjectResult:
        """프로젝트 Context Pack을 읽고 800자 이내 요약을 생성한다."""
        pack = self.builder.build(project)
        prompt = render_prompt("summarize_project", CONTEXT_PACK=pack.render())
        text = self._llm().complete(prompt)
        return self._save(project, "summary", text, pack.source_refs)

    def portfolio_draft(self, project: str) -> ProjectResult:
        """포트폴리오 설명 초안을 50_Outputs/Portfolio/에 저장한다."""
        pack = self.builder.build(project)
        prompt = render_prompt("portfolio_project", CONTEXT_PACK=pack.render())
        text = self._llm().complete(prompt)
        return self._save(project, "portfolio", text, pack.source_refs)

    def interview_questions(self, project: str) -> ProjectResult:
        """면접 예상 질문·답변 초안을 50_Outputs/Interview/에 저장한다."""
        pack = self.builder.build(project)
        prompt = render_prompt("interview_questions", CONTEXT_PACK=pack.render())
        text = self._llm().complete(prompt)
        return self._save(project, "interview", text, pack.source_refs)

    def _save(self, project: str, output_type: str, text: str, source_refs: list[str]) -> ProjectResult:
        output_dirs = {
            "summary": "50_Outputs/Portfolio",
            "portfolio": "50_Outputs/Portfolio",
            "interview": "50_Outputs/Interview",
        }
        out_dir = self.vault_dir / output_dirs[output_type]
        out_dir.mkdir(parents=True, exist_ok=True)

        today = (self.now or datetime.now()).strftime("%Y%m%d")
        slug = project.lower().replace(" ", "-")
        rel_path = f"{output_dirs[output_type]}/{today}-{output_type}-{slug}.md"
        path = self.vault_dir / rel_path
        path.write_text(text + "\n", encoding="utf-8")

        self.wiki_service.append_vault_log(output_type, project, [rel_path])

        return ProjectResult(
            project=project,
            output_type=output_type,
            text=text,
            path=path,
            source_refs=source_refs,
        )

    def _llm(self) -> LLMProvider:
        return self.llm or get_writer_llm_provider(self.settings)
