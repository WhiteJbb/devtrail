"""Career Bullet Agent — 작업 기록에서 이력서/포트폴리오 후보를 추출한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_task_llm_provider
from app.prompts import render_prompt
from app.services.candidate_writer import CandidateSpec, CandidateWriteResult, CandidateWriter
from app.services.json_utils import complete_json
from app.services.wiki_service import WikiNote, WikiService


_SOURCE_PREFIXES = (
    "10_Worklog/Sessions/",
    "10_Worklog/Daily/",
    "10_Worklog/GitSummaries/",
    "00_Inbox/URLs/",
    "00_Inbox/Memos/",
    "10_Worklog/Summaries/",
)
_KNOWLEDGE_PREFIXES = ("20_Knowledge/", "30_Projects/")
_MAX_NOTE_CHARS = 3000
_MAX_NOTES = 20


@dataclass(frozen=True)
class CareerBulletResult:
    written: list[CandidateWriteResult]
    source_refs: list[str]


class CareerBulletAgent:
    """작업 기록 + 프로젝트 컨텍스트에서 이력서/포폴 bullet 후보를 만든다."""

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
        self.writer = CandidateWriter(self.vault_dir, wiki_service=self.wiki_service, now=now)

    def suggest(self, project: str = "") -> CareerBulletResult:
        notes = self._collect_notes(project)
        if not notes:
            return CareerBulletResult(written=[], source_refs=[])

        context = self._render_context(notes)
        existing = self._render_existing_knowledge(project)
        prompt = render_prompt(
            "career_bullets",
            PROJECT_FILTER=project or "전체 프로젝트",
            CONTEXT=context,
            EXISTING_KNOWLEDGE=existing,
        )
        data = complete_json(self._llm(), prompt)
        specs = self._parse_specs(data, source_refs=[n.path for n in notes])
        written = self.writer.write_many(specs)
        from app.services.wiki_service import mark_distilled
        mark_distilled(self.vault_dir, notes)
        return CareerBulletResult(written=written, source_refs=[n.path for n in notes])

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("writer", self.settings)

    def _note_date(self, note: WikiNote) -> str:
        value = note.metadata.get("date") or note.metadata.get("created_at") or ""
        return str(value)[:10]

    def _collect_notes(self, project: str) -> list[WikiNote]:
        from datetime import timedelta
        cutoff = ((self.now or datetime.now()) - timedelta(days=7)).strftime("%Y-%m-%d")
        all_notes = self.wiki_service.scan_notes()
        notes = [
            n for n in all_notes
            if n.path.startswith(_SOURCE_PREFIXES)
            and self._note_date(n) >= cutoff
            and n.metadata.get("needs_distill") is not False
        ]
        if project:
            notes = [n for n in notes if str(n.metadata.get("project") or "").lower() == project.lower()
                     or project.lower() in n.title.lower()]

        # session 노트 우선
        session = [n for n in notes if "session" in Path(n.path).name.lower()
                   and n.path.startswith("10_Worklog/Sessions/")]
        others = [n for n in notes if n not in session]
        session.sort(key=lambda n: n.path, reverse=True)
        others.sort(key=lambda n: n.path, reverse=True)
        return (session + others)[:_MAX_NOTES]

    def _render_existing_knowledge(self, project: str) -> str:
        all_notes = self.wiki_service.scan_notes()
        related = [n for n in all_notes if n.path.startswith(_KNOWLEDGE_PREFIXES)]
        if project:
            related = [n for n in related if project.lower() in n.path.lower()
                       or project.lower() in n.title.lower()]
        if not related:
            return "(기존 Knowledge/Projects 없음)"
        lines = []
        for note in related[:8]:
            lines.append(f"- [[{Path(note.path).stem}]] ({note.path}) — {note.title}")
        return "\n".join(lines)

    def _render_context(self, notes: list[WikiNote]) -> str:
        parts: list[str] = []
        for note in notes:
            meta = []
            if note.metadata.get("project"):
                meta.append(f"project={note.metadata.get('project')}")
            date = str(note.metadata.get("date") or note.metadata.get("created_at") or "")[:10]
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

    def _parse_specs(self, data: object, source_refs: list[str]) -> list[CandidateSpec]:
        specs: list[CandidateSpec] = []
        if not isinstance(data, dict):
            return specs
        items = data.get("career_bullets") or []
        if not isinstance(items, list):
            return specs
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            refs = item.get("source_refs") or source_refs
            if isinstance(refs, str):
                refs = [refs]
            tags = item.get("tags") or ["career", "portfolio"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            lines = []
            if item.get("source_evidence"):
                lines += ["## 원본 작업 근거", "", str(item["source_evidence"]), ""]
            bullets = item.get("resume_bullets") or []
            if bullets:
                lines += ["## 이력서 bullet 후보", ""]
                for b in bullets:
                    lines.append(f"- {b}")
                lines.append("")
            if item.get("portfolio_description"):
                lines += ["## 포트폴리오 설명 후보", "", str(item["portfolio_description"]), ""]
            interview = item.get("interview_points") or []
            if interview:
                lines += ["## 면접에서 설명할 포인트", ""]
                for p in interview:
                    lines.append(f"- {p}")
                lines.append("")
            if item.get("caveats"):
                lines += ["## 주의할 점", "", str(item["caveats"]), ""]
            body = "\n".join(lines).strip()

            specs.append(CandidateSpec(
                kind="career_bullet",
                title=title,
                summary=str(item.get("source_evidence") or "")[:200],
                body=body,
                project=str(item.get("project") or ""),
                tags=[str(t) for t in tags],
                source_refs=[str(r) for r in refs],
            ))
        return specs
