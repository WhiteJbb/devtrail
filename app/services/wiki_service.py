"""Vault 파일 시스템 관리 서비스.

Obsidian vault의 스캐폴드 생성(init_vault), 노트 스캔/검색,
루트 index.md·log.md 관리를 담당한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter


_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")
_INLINE_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z가-힣][A-Za-z0-9가-힣_-]*)")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_+-]+")


VAULT_DIRS = [
    "00_Inbox/URLs",
    "00_Inbox/Memos",
    "00_Inbox/Raw/Attachments",  # media_handler가 Telegram 첨부를 저장
    "10_Worklog/Sessions",
    "10_Worklog/Daily",
    "10_Worklog/Summaries",  # worklog_agent 출력
    "10_Worklog/GitSummaries",  # capture_agent.capture_commit 출력
    "20_Knowledge",  # 승격 지식 — curator가 20_Knowledge/{project}/ 하위를 동적 생성
    # 프로젝트 정본 문서 구조 (기본 프로젝트 Devtrail 예시).
    # Context.md는 get_project_briefing이 읽고, Decisions/는 promote-candidate 대상.
    "30_Projects/Devtrail/Decisions",
    "30_Projects/Devtrail/Plans",  # 기능 단위 구현 계획 (세션 Plan은 SessionHandoffs)
    "30_Projects/Devtrail/Design",  # IA / UserScenarios / Personas
    "30_Projects/Devtrail/Conversations",  # 중요 대화 발췌
    "40_AgentMemory",  # 전역 메모리 — 실체는 루트 00_Profile.md ~ 05_OpenLoops.md
    "50_Outputs/Digest",
    "50_Outputs/WeeklyReview",
    "50_Outputs/Todo",  # todo_agent 출력
    "50_Outputs/Blog/Ideas",
    "50_Outputs/Blog/Drafts",
    "50_Outputs/Blog/Export",  # wiki_blog_agent export 출력
    "50_Outputs/Portfolio",
    "50_Outputs/Resume",
    "50_Outputs/Interview",
    "60_Candidates/Knowledge",
    "60_Candidates/Decisions",
    "60_Candidates/MemoryPatches",
    "60_Candidates/BlogIdeas",
    "60_Candidates/CareerBullets",
    "60_Candidates/SessionHandoffs",  # write_work_plan/write_session_process 출력
    "70_Tasks/Done",  # task_service (Active.md + 완료 태스크)
]


AGENT_MEMORY_FILES = {
    "40_AgentMemory/00_Profile.md": "Profile",
    "40_AgentMemory/01_CurrentFocus.md": "Current Focus",
    "40_AgentMemory/02_ProjectMap.md": "Project Map",
    "40_AgentMemory/03_WritingStyle.md": "Writing Style",
    "40_AgentMemory/04_CareerContext.md": "Career Context",
    "40_AgentMemory/05_OpenLoops.md": "Open Loops",
}


def mark_distilled(vault_dir: Path, notes: list) -> None:
    """needs_distill: True 인 노트를 처리 완료(False)로 표시한다."""
    for note in notes:
        if not note.metadata.get("needs_distill"):
            continue
        path = vault_dir / note.path
        try:
            post = frontmatter.load(str(path))
            post["needs_distill"] = False
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        except Exception:
            pass


@dataclass(frozen=True)
class VaultInitResult:
    vault_dir: Path
    created_dirs: list[Path] = field(default_factory=list)
    created_files: list[Path] = field(default_factory=list)
    existing_files: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class WikiNote:
    path: str
    title: str
    body: str
    metadata: dict[str, Any]
    tags: list[str]
    wikilinks: list[str]
    summary: str

    @property
    def note_type(self) -> str:
        return str(self.metadata.get("type", "") or "")


@dataclass(frozen=True)
class VaultIndex:
    notes: list[WikiNote]
    index_path: Path


@dataclass(frozen=True)
class WikiSearchResult:
    note: WikiNote
    score: int
    matched_terms: list[str]


class WikiService:
    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir

    # -- LLM Wiki Core: vault init / index / search -----------------

    def init_vault(self) -> VaultInitResult:
        """Create the Obsidian LLM Wiki folder skeleton without overwriting notes."""
        created_dirs: list[Path] = []
        created_files: list[Path] = []
        existing_files: list[Path] = []

        for rel in VAULT_DIRS:
            path = self.vault_dir / rel
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created_dirs.append(path)
            else:
                path.mkdir(parents=True, exist_ok=True)

        root_files = {
            "index.md": self._default_root_index(),
            "log.md": "# Log\n\n",
            "AGENTS.md": self._default_vault_agents(),
            ".gitattributes": "log.md merge=union\n",
        }
        for rel, content in root_files.items():
            self._write_if_missing(rel, content, created_files, existing_files)

        for rel, title in AGENT_MEMORY_FILES.items():
            self._write_if_missing(rel, self._default_agent_memory(title), created_files, existing_files)

        self.append_vault_log("init", "vault skeleton", [str(p.relative_to(self.vault_dir)) for p in created_files])
        return VaultInitResult(
            vault_dir=self.vault_dir,
            created_dirs=created_dirs,
            created_files=created_files,
            existing_files=existing_files,
        )

    def index_vault(self) -> VaultIndex:
        """Parse vault markdown files and update the root index.md catalog."""
        notes = self.scan_notes()
        self._write_root_index(notes)
        self.append_vault_log("index", f"{len(notes)} notes", ["index.md"])
        return VaultIndex(notes=notes, index_path=self.vault_dir / "index.md")

    def related_notes(self, rel_path: str, limit: int = 10) -> list[WikiSearchResult]:
        """주어진 노트와 관련된 노트를 태그·위키링크·제목 기반으로 찾는다."""
        notes = self.scan_notes()
        target = next((n for n in notes if n.path == rel_path), None)
        if target is None:
            return []

        # 태그 + wikilinks + 제목 단어로 쿼리 조합
        query_parts = list(target.tags) + target.wikilinks + self._tokenize(target.title)
        query = " ".join(dict.fromkeys(query_parts))  # 중복 제거, 순서 유지
        if not query.strip():
            return []

        results = [r for r in self._search_notes(notes, query, limit=limit + 1) if r.note.path != rel_path]
        return results[:limit]

    def search(self, query: str, limit: int = 10, prefixes: tuple[str, ...] | None = None) -> list[WikiSearchResult]:
        """Simple keyword search over parsed vault notes.

        prefixes가 주어지면 점수화·절단 전에 해당 경로 접두사로만 필터링한다 —
        전역 top-N을 먼저 뽑은 뒤 걸러내면, 노트가 많은 폴더(예: 세션 로그)가
        허용된 스코프 밖 결과로 top-N을 채워 스코프 안 결과가 잘려나갈 수 있다.
        """
        notes = self.scan_notes()
        if prefixes:
            notes = [n for n in notes if n.path.startswith(prefixes)]
        return self._search_notes(notes, query, limit=limit)

    def _search_notes(self, notes: list[WikiNote], query: str, limit: int = 10) -> list[WikiSearchResult]:
        terms = self._tokenize(query)
        if not terms:
            return []

        results: list[WikiSearchResult] = []
        for note in notes:
            score, matched = self._score_note(note, query, terms)
            if score > 0:
                results.append(WikiSearchResult(note=note, score=score, matched_terms=matched))

        results.sort(key=lambda r: (-r.score, r.note.path))
        return results[:limit]

    def scan_notes(self) -> list[WikiNote]:
        """Read markdown notes with YAML frontmatter, tags, and wiki links."""
        if not self.vault_dir.exists():
            return []

        notes: list[WikiNote] = []
        for path in sorted(self.vault_dir.rglob("*.md")):
            if self._should_skip_note(path):
                continue
            note = self._parse_note(path)
            if note is not None:
                notes.append(note)
        return notes

    def append_vault_log(self, action: str, label: str, outputs: list[str] | None = None) -> None:
        """Append an operation record to root log.md."""
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"## [{today}] {action} | {label}", ""]
        for output in outputs or []:
            lines.append(f"- output: {output}")
        lines.append("")
        with (self.vault_dir / "log.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _write_if_missing(
        self,
        rel_path: str,
        content: str,
        created_files: list[Path],
        existing_files: list[Path],
    ) -> None:
        path = self.vault_dir / rel_path
        if path.exists():
            existing_files.append(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created_files.append(path)

    def _should_skip_note(self, path: Path) -> bool:
        rel = path.relative_to(self.vault_dir)
        parts = rel.parts
        if any(part.startswith(".") for part in parts):
            return True
        if rel.as_posix() in {"index.md", "log.md", "AGENTS.md"}:
            return True
        return False

    def _parse_note(self, path: Path) -> WikiNote | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            raw = path.read_text(encoding="utf-8", errors="replace")

        if not raw.strip():
            return None

        try:
            post = frontmatter.loads(raw)
            metadata = dict(post.metadata)
            body = post.content.strip()
        except Exception:
            metadata = {}
            body = raw.strip()

        rel = path.relative_to(self.vault_dir).as_posix()
        title = self._derive_title(path, metadata, body)
        tags = self._extract_tags(metadata, body)
        wikilinks = sorted(set(_WIKILINK_RE.findall(body)))
        wikilinks = [link.split("|", 1)[0].split("#", 1)[0].strip() for link in wikilinks if link.strip()]
        summary = self._derive_summary(metadata, body)
        return WikiNote(
            path=rel,
            title=title,
            body=body,
            metadata=metadata,
            tags=tags,
            wikilinks=wikilinks,
            summary=summary,
        )

    def _derive_title(self, path: Path, metadata: dict[str, Any], body: str) -> str:
        title = str(metadata.get("title", "") or "").strip()
        if title:
            return title
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return path.stem

    def _derive_summary(self, metadata: dict[str, Any], body: str) -> str:
        for key in ("summary", "description"):
            value = str(metadata.get(key, "") or "").strip()
            if value:
                return value[:160]
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            stripped = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", stripped)
            stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
            stripped = _WIKILINK_RE.sub(lambda m: m.group(1), stripped)
            return stripped[:160]
        return ""

    def _extract_tags(self, metadata: dict[str, Any], body: str) -> list[str]:
        raw_tags = metadata.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [tag.strip() for tag in raw_tags.split(",")]
        tags = {str(tag).lstrip("#").lower() for tag in raw_tags if str(tag).strip()}
        tags.update(tag.lower() for tag in _INLINE_TAG_RE.findall(body))
        return sorted(tags)

    def _write_root_index(self, notes: list[WikiNote]) -> None:
        groups: dict[str, list[WikiNote]] = defaultdict(list)
        for note in notes:
            first = Path(note.path).parts[0] if Path(note.path).parts else "Notes"
            groups[first].append(note)

        today = datetime.now().strftime("%Y-%m-%d")
        lines = [
            "# Vault Index",
            "",
            f"_updated_at: {today}_",
            f"_note_count: {len(notes)}_",
            "",
        ]
        for group in sorted(groups):
            lines.append(f"## {group}")
            for note in sorted(groups[group], key=lambda n: n.path):
                detail = note.summary or note.note_type or ", ".join(note.tags)
                suffix = f" - {detail}" if detail else ""
                lines.append(f"- [{note.title}]({note.path}){suffix}")
                meta_bits = []
                if note.note_type:
                    meta_bits.append(f"type={note.note_type}")
                if note.tags:
                    meta_bits.append("tags=" + ",".join(note.tags))
                if note.wikilinks:
                    meta_bits.append("links=" + ",".join(note.wikilinks[:5]))
                if meta_bits:
                    lines.append(f"  - {' | '.join(meta_bits)}")
            lines.append("")

        self.vault_dir.mkdir(parents=True, exist_ok=True)
        (self.vault_dir / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _score_note(self, note: WikiNote, query: str, terms: list[str]) -> tuple[int, list[str]]:
        title = note.title.lower()
        body = note.body.lower()
        path = note.path.lower()
        tags = " ".join(note.tags).lower()
        links = " ".join(note.wikilinks).lower()
        query_l = query.lower()

        score = 0
        matched: list[str] = []
        if query_l and query_l in title:
            score += 25
        if query_l and query_l in body:
            score += 5

        for term in terms:
            term_score = 0
            if term in title:
                term_score += 10
            if term in tags:
                term_score += 8
            if term in path:
                term_score += 5
            if term in links:
                term_score += 3
            count = body.count(term)
            if count:
                term_score += min(count, 10)
            if term_score:
                matched.append(term)
                score += term_score
        return score, matched

    def _tokenize(self, text: str) -> list[str]:
        return [t.lower() for t in _TOKEN_RE.findall(text) if len(t.strip()) > 1]

    def _default_root_index(self) -> str:
        return "# Vault Index\n\n_Run `devtrail index-vault` to rebuild this catalog._\n"

    def _default_vault_agents(self) -> str:
        return (
            "# AGENTS.md\n\n"
            "This Obsidian vault is the shared memory bus for Devtrail and other AI tools.\n\n"
            "## Writable Areas\n\n"
            "- 00_Inbox/\n"
            "- 10_Worklog/\n"
            "- 50_Outputs/\n"
            "- 60_Candidates/\n"
            "- 70_Tasks/\n\n"
            "## Protected Areas\n\n"
            "- 20_Knowledge/\n"
            "- 30_Projects/\n"
            "- 40_AgentMemory/\n\n"
            "Protected areas should be changed through candidates or patches "
            "(promote-candidate / apply-memory-patch), then reviewed.\n"
        )

    def _default_agent_memory(self, title: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            "---\n"
            "type: agent_memory\n"
            "scope: global\n"
            "status: active\n"
            f"updated_at: {today}\n"
            "---\n\n"
            f"# {title}\n\n"
            "_Fill this note with durable context that future agents should know._\n"
        )
