"""Worklog Agent — 최근 raw 기록을 읽어 작업 회고를 생성한다 (Vault 기반)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_task_llm_provider
from app.prompts import render_prompt
from app.services.wiki_service import WikiNote, WikiService


_RAW_PREFIXES = ("00_Inbox/", "10_Worklog/")
_MAX_NOTE_CHARS = 3000
_MAX_NOTES = 20


@dataclass(frozen=True)
class WorklogResult:
    text: str
    path: Path


class WorklogAgent:
    """최근 raw 기록(00_Inbox, 10_Worklog)을 읽어 작업 회고를 vault에 저장한다."""

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
        self.wiki_service = WikiService(self.vault_dir)

    def generate(self, save: bool = True) -> WorklogResult:
        notes = self._recent_notes()
        if notes:
            context = self._render_context(notes)
        else:
            context = "(최근 raw 기록 없음 — capture 또는 capture-commit을 먼저 실행하세요)"

        prompt = render_prompt("worklog_summary", CONTEXT_PACK=context)
        text = self._llm().complete(prompt)

        today = (self.now or datetime.now()).strftime("%Y%m%d")
        rel_path = f"10_Worklog/Summaries/{today}-worklog.md"
        path = self.vault_dir / rel_path

        if save:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            self.wiki_service.append_vault_log("worklog", "작업 회고", [rel_path])

        return WorklogResult(text=text, path=path)

    def _recent_notes(self) -> list[WikiNote]:
        notes = [
            note
            for note in self.wiki_service.scan_notes()
            if note.path.startswith(_RAW_PREFIXES)
        ]
        notes.sort(key=lambda n: n.path, reverse=True)
        return notes[:_MAX_NOTES]

    def _render_context(self, notes: list[WikiNote]) -> str:
        parts: list[str] = []
        for note in notes:
            meta = []
            if note.note_type:
                meta.append(f"type={note.note_type}")
            if note.metadata.get("project"):
                meta.append(f"project={note.metadata.get('project')}")
            date = str(note.metadata.get("date") or "")[:10]
            if date:
                meta.append(f"date={date}")
            header = f"### {note.path}"
            if meta:
                header += f" ({', '.join(meta)})"
            body = note.body.strip()
            if len(body) > _MAX_NOTE_CHARS:
                body = body[:_MAX_NOTE_CHARS].rstrip() + "\n...(일부 생략)"
            parts.append(f"{header}\n{body}")
        return "\n\n".join(parts)

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("writer", self.settings)
