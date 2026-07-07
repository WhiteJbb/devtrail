"""Open Loops Agent — 작업 기록에서 미해결 이슈 패치 후보를 만든다.

40_AgentMemory/05_OpenLoops.md를 직접 수정하지 않고
60_Candidates/MemoryPatches/에 패치 후보를 생성한다.
실제 반영은 apply-memory-patch 명령으로 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_task_llm_provider
from app.prompts import render_prompt
from app.services.candidate_writer import CandidateSpec, CandidateWriteResult, CandidateWriter
from app.services.json_utils import complete_json
from app.services.wiki_service import WikiNote, WikiService


_TARGET_FILE = "40_AgentMemory/05_OpenLoops.md"
_SOURCE_PREFIXES = ("10_Worklog/Sessions/", "10_Worklog/Daily/", "00_Inbox/URLs/", "00_Inbox/Memos/", "50_Outputs/Todo/")
_MAX_NOTE_CHARS = 3000
_MAX_NOTES = 15


@dataclass(frozen=True)
class OpenLoopsResult:
    written: list[CandidateWriteResult]
    source_refs: list[str]


class OpenLoopsAgent:
    """최근 작업 기록을 읽어 Open Loops MemoryPatch 후보를 만든다."""

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
        self.writer = CandidateWriter(self.vault_dir, wiki_service=self.wiki_service, now=now)

    def suggest(self) -> OpenLoopsResult:
        notes = self._collect_notes()
        if not notes:
            return OpenLoopsResult(written=[], source_refs=[])

        context = self._render_context(notes)
        current = self._read_current_open_loops()
        prompt = render_prompt(
            "open_loops_patch",
            CONTEXT=context,
            CURRENT_OPEN_LOOPS=current,
        )
        data = complete_json(self._llm(), prompt)
        spec = self._build_spec(data, source_refs=[n.path for n in notes])
        if spec is None:
            return OpenLoopsResult(written=[], source_refs=[n.path for n in notes])
        written = self.writer.write_many([spec])
        return OpenLoopsResult(written=written, source_refs=[n.path for n in notes])

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("light", self.settings)

    def _collect_notes(self) -> list[WikiNote]:
        all_notes = self.wiki_service.scan_notes()
        notes = [n for n in all_notes if n.path.startswith(_SOURCE_PREFIXES)]
        # session 노트 우선, 최신순
        session = [n for n in notes if "session" in Path(n.path).name.lower()
                   and n.path.startswith("10_Worklog/Sessions/")]
        others = [n for n in notes if n not in session]
        session.sort(key=lambda n: n.path, reverse=True)
        others.sort(key=lambda n: n.path, reverse=True)
        return (session + others)[:_MAX_NOTES]

    def _render_context(self, notes: list[WikiNote]) -> str:
        parts: list[str] = []
        for note in notes:
            date = str(note.metadata.get("date") or note.metadata.get("created_at") or "")[:10]
            header = f"### {note.path}" + (f" (date={date})" if date else "")
            body = note.body.strip()
            if len(body) > _MAX_NOTE_CHARS:
                body = body[:_MAX_NOTE_CHARS].rstrip() + "\n...(일부 생략)"
            parts.append(f"{header}\n{body}")
        return "\n\n".join(parts)

    def _read_current_open_loops(self) -> str:
        path = self.vault_dir / _TARGET_FILE
        if not path.exists():
            return "(05_OpenLoops.md 없음 — 새로 생성될 예정)"
        text = path.read_text(encoding="utf-8").strip()
        return text[:3000] + ("\n...(일부 생략)" if len(text) > 3000 else "")

    def _build_spec(self, data: Any, source_refs: list[str]) -> CandidateSpec | None:
        if not isinstance(data, dict):
            return None

        add_items = data.get("add") or []
        complete_items = data.get("complete") or []
        defer_items = data.get("defer") or []
        rationale = str(data.get("rationale") or "").strip()

        if not add_items and not complete_items and not defer_items:
            return None

        now_str = (self.now or datetime.now()).strftime("%Y-%m-%d")
        lines = [f"# Open Loops Patch Candidate — {now_str}", ""]

        if add_items:
            lines += ["## 추가할 항목", ""]
            for item in add_items:
                if isinstance(item, str):
                    lines.append(f"- {item}")
                else:
                    priority = item.get("priority", "")
                    tag = f" [{priority}]" if priority else ""
                    lines.append(f"- {item.get('item', '')}{tag}")
            lines.append("")

        if complete_items:
            lines += ["## 완료 처리할 항목", ""]
            for item in complete_items:
                lines.append(f"- {item if isinstance(item, str) else item.get('item', '')}")
            lines.append("")

        if defer_items:
            lines += ["## 보류할 항목", ""]
            for item in defer_items:
                if isinstance(item, str):
                    lines.append(f"- {item}")
                else:
                    reason = item.get("reason", "")
                    lines.append(f"- {item.get('item', '')}" + (f" ({reason})" if reason else ""))
            lines.append("")

        if rationale:
            lines += ["## 근거", "", rationale, ""]

        body = "\n".join(lines).strip()
        return CandidateSpec(
            kind="memory_patch",
            title=f"Open Loops 패치 — {now_str}",
            summary=rationale[:200] if rationale else "Open Loops 업데이트 패치 후보",
            body=body,
            project="",
            tags=["open-loops", "memory-patch"],
            source_refs=[str(r) for r in source_refs],
        )
