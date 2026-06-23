"""Distill Agent - turn raw vault traces into reviewable candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider
from app.llm.factory import get_task_llm_provider
from app.prompts import render_prompt
from app.services.candidate_writer import CandidateSpec, CandidateWriteResult, CandidateWriter
from app.services.json_utils import JSONParseError, complete_json
from app.services.wiki_service import WikiNote, WikiService


_RAW_PREFIXES = ("00_Inbox/", "10_Worklog/")
_KNOWLEDGE_PREFIXES = ("20_Knowledge/", "30_Projects/")
_CANDIDATE_PREFIX = "60_Candidates/"
_MAX_NOTE_CHARS = 3000
_MAX_RELATED = 12
_CHARS_PER_TOKEN = 3  # 한국어 혼용 기준 보수적 추정


@dataclass(frozen=True)
class DistillResult:
    written: list[CandidateWriteResult]
    source_refs: list[str]


class DistillAgent:
    """Create candidate notes from raw Obsidian vault records."""

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

    def distill_today(self) -> DistillResult:
        return self._distill(kind="all", today_only=True)

    def distill_range(self, days: int = 7) -> DistillResult:
        """최근 days일치 raw 기록을 정제한다 (weekly-distill용)."""
        return self._distill(kind="all", today_only=False, days=days)

    def suggest_knowledge(self) -> DistillResult:
        return self._distill(kind="knowledge", today_only=False)

    def suggest_blog_topics(self) -> DistillResult:
        return self._distill(kind="blog_idea", today_only=False)

    def suggest_memory_patch(self) -> DistillResult:
        return self._distill(kind="memory_patch", today_only=False)

    def _distill(self, kind: str, today_only: bool, days: int = 0) -> DistillResult:
        notes = self._raw_notes(today_only=today_only, days=days)
        if not notes:
            return DistillResult(written=[], source_refs=[])

        context = self._render_context(notes)
        related = self._find_related_knowledge(notes)
        related_section = self._render_related_knowledge(related)
        prompt = render_prompt(
            "distill_candidates",
            KIND=kind,
            DATE=self._date(),
            CONTEXT=context,
            RELATED_KNOWLEDGE=related_section,
        )
        try:
            data = complete_json(self._llm(), prompt)
        except JSONParseError as e:
            raise LLMError(f"LLM이 유효한 JSON을 반환하지 않았습니다: {e}") from e
        specs = self._parse_specs(data, source_refs=[n.path for n in notes], kind_filter=kind)
        written = self.writer.write_many(specs)
        return DistillResult(written=written, source_refs=[n.path for n in notes])

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("light", self.settings)

    def _raw_notes(self, today_only: bool, days: int = 0) -> list[WikiNote]:
        from datetime import timedelta
        today = self._date()
        notes = [
            note
            for note in self.wiki_service.scan_notes()
            if note.path.startswith(_RAW_PREFIXES) and not note.path.startswith("10_Worklog/GitSummaries/index")
        ]
        if today_only:
            notes = [note for note in notes if self._note_date(note) == today]
        elif days > 0:
            cutoff = ((self.now or datetime.now()) - timedelta(days=days)).strftime("%Y-%m-%d")
            notes = [note for note in notes if self._note_date(note) >= cutoff]

        # session 노트를 가장 먼저 배치 (10_Worklog/Daily/*session*.md)
        session_notes = [n for n in notes if "session" in Path(n.path).name.lower()
                         and n.path.startswith("10_Worklog/Daily/")]
        other_notes = [n for n in notes if n not in session_notes]
        session_notes.sort(key=lambda n: n.path, reverse=True)
        other_notes.sort(key=lambda n: n.path, reverse=True)
        limit = 40 if days > 1 else 20  # 주간은 더 많은 노트 허용
        return (session_notes + other_notes)[:limit]

    def _note_date(self, note: WikiNote) -> str:
        value = note.metadata.get("date") or note.metadata.get("created_at") or ""
        return str(value)[:10]

    def _find_related_knowledge(self, notes: list[WikiNote]) -> list[WikiNote]:
        """기존 Knowledge/Projects/Candidates 노트 중 관련된 것을 찾아 wikilink 후보로 반환."""
        terms: set[str] = set()
        for note in notes:
            proj = note.metadata.get("project")
            if proj:
                terms.add(str(proj))
            for tag in note.metadata.get("tags", []):
                terms.add(str(tag))
            for word in note.title.split():
                if len(word) > 2:
                    terms.add(word)
        if not terms:
            return []
        query = " ".join(list(terms)[:12])
        results = self.wiki_service.search(query, limit=_MAX_RELATED * 2)
        related: list[WikiNote] = []
        for r in results:
            note = r.note
            if note.path.startswith(_KNOWLEDGE_PREFIXES):
                related.append(note)
            elif (
                note.path.startswith(_CANDIDATE_PREFIX)
                and note.metadata.get("status") == "candidate"
            ):
                related.append(note)
            if len(related) >= _MAX_RELATED:
                break
        return related

    def _render_related_knowledge(self, related: list[WikiNote]) -> str:
        if not related:
            return "(관련 기존 지식 노트 없음)"
        lines = []
        for note in related:
            stem = Path(note.path).stem
            lines.append(f"- [[{stem}|{note.title}]] ({note.path})")
        return "\n".join(lines)

    def _render_context(self, notes: list[WikiNote]) -> str:
        # 전체 컨텍스트를 settings.context_char_budget 이하로 유지한다.
        budget = self.settings.context_char_budget
        parts: list[str] = []
        used = 0
        for note in notes:
            meta = []
            if note.note_type:
                meta.append(f"type={note.note_type}")
            if note.metadata.get("project"):
                meta.append(f"project={note.metadata.get('project')}")
            date = self._note_date(note)
            if date:
                meta.append(f"date={date}")
            header = f"### {note.path}"
            if meta:
                header += f" ({', '.join(meta)})"
            body = note.body.strip()
            if len(body) > _MAX_NOTE_CHARS:
                body = body[:_MAX_NOTE_CHARS].rstrip() + "\n...(일부 생략)"
            chunk = f"{header}\n{body}"
            if used + len(chunk) > budget:
                remaining = budget - used
                if remaining > len(header) + 80:
                    chunk = chunk[:remaining].rstrip() + "\n...(예산 초과로 생략)"
                    parts.append(chunk)
                break
            parts.append(chunk)
            used += len(chunk) + 2  # 구분자 "\n\n"
        return "\n\n".join(parts)

    def _parse_specs(self, data: Any, source_refs: list[str], kind_filter: str) -> list[CandidateSpec]:
        specs: list[CandidateSpec] = []
        if not isinstance(data, dict):
            return specs

        mapping = {
            "knowledge": "knowledge",
            "decisions": "decision",
            "memory_patches": "memory_patch",
            "blog_ideas": "blog_idea",
        }
        for key, kind in mapping.items():
            if kind_filter != "all" and kind != kind_filter:
                continue
            items = data.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                spec = self._spec_from_item(kind, item, source_refs)
                if spec is not None:
                    specs.append(spec)
        return specs

    def _spec_from_item(self, kind: str, item: dict[str, Any], fallback_refs: list[str]) -> CandidateSpec | None:
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        source_refs = item.get("source_refs") or fallback_refs
        if isinstance(source_refs, str):
            source_refs = [source_refs]
        # Source grounding: reject fabricated paths not in the actual note set
        valid_refs = [ref for ref in source_refs if str(ref) in fallback_refs]
        source_refs = valid_refs if valid_refs else fallback_refs
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        body = str(item.get("body") or item.get("details") or item.get("outline") or "").strip()
        summary = str(item.get("summary") or item.get("reason") or "").strip()
        return CandidateSpec(
            kind=kind,
            title=title,
            summary=summary,
            body=body,
            project=str(item.get("project") or ""),
            tags=[str(t) for t in tags],
            source_refs=[str(ref) for ref in source_refs],
        )

    def _date(self) -> str:
        return (self.now or datetime.now()).strftime("%Y-%m-%d")
