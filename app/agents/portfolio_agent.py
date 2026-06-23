"""Portfolio Agent — 전체 프로젝트 기반 포트폴리오 초안 (Vault 기반)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_task_llm_provider
from app.memory.agent_memory_loader import AgentMemoryLoader
from app.memory.project_memory_loader import ProjectMemoryLoader
from app.prompts import render_prompt
from app.services.wiki_service import WikiService


@dataclass(frozen=True)
class PortfolioResult:
    text: str
    path: Path
    source_refs: list[str] = field(default_factory=list)


class PortfolioAgent:
    """40_AgentMemory + 30_Projects 전체를 읽어 포트폴리오 설명 초안을 생성한다."""

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

    def generate(self, save: bool = True) -> PortfolioResult:
        source_refs: list[str] = []
        parts: list[str] = []

        # 1. Agent Memory (Profile, ProjectMap 등)
        agent_mem = AgentMemoryLoader(self.vault_dir).load()
        agent_section = agent_mem.render()
        source_refs.extend(agent_mem.source_refs)
        if agent_section.strip():
            parts.append(f"## Agent Memory\n\n{agent_section}")

        # 2. 전체 프로젝트 컨텍스트
        project_mem = ProjectMemoryLoader(self.vault_dir).load()
        project_section = project_mem.render_all()
        source_refs.extend(project_mem.source_refs)
        if project_section.strip():
            parts.append(f"## 프로젝트 경험\n\n{project_section}")

        context = (
            "\n\n".join(parts)
            if parts
            else "(컨텍스트 없음 — 40_AgentMemory와 30_Projects/*/Context.md를 채워주세요)"
        )

        prompt = render_prompt("portfolio", CONTEXT_PACK=context)
        text = self._llm().complete(prompt)

        today = (self.now or datetime.now()).strftime("%Y%m%d")
        rel_path = f"50_Outputs/Portfolio/{today}-portfolio.md"
        path = self.vault_dir / rel_path

        if save:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            self.wiki_service.append_vault_log("portfolio", "포트폴리오 초안", [rel_path])

        return PortfolioResult(text=text, path=path, source_refs=source_refs)

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("writer", self.settings)
