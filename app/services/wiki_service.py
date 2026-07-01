"""Wiki 파일 시스템 관리 서비스.

Obsidian 볼트 내 wiki 폴더(기본: 60_Wiki)의 페이지 읽기/쓰기,
index.md·log.md 관리를 담당한다.
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
    "00_Inbox/Raw",
    "10_Worklog/Sessions",
    "10_Worklog/Daily",
    "10_Worklog/Weekly",
    "20_Knowledge/AI",
    "20_Knowledge/RAG",
    "20_Knowledge/Agent",
    "20_Knowledge/Infra",
    "20_Knowledge/Backend",
    "20_Knowledge/Frontend",
    "20_Knowledge/Career",
    "30_Projects/WorkAgent/Decisions",
    "30_Projects/WorkAgent/Issues",
    "30_Projects/WorkAgent/Logs",
    "40_AgentMemory/Core",
    "40_AgentMemory/ProjectSummaries",
    "50_Outputs/Digest",
    "50_Outputs/WeeklyReview",
    "50_Outputs/Blog/Ideas",
    "50_Outputs/Blog/Drafts",
    "50_Outputs/Blog/Review",
    "50_Outputs/Blog/Published",
    "50_Outputs/Portfolio",
    "50_Outputs/Resume",
    "50_Outputs/Interview",
    "60_Candidates/Knowledge",
    "60_Candidates/Decisions",
    "60_Candidates/MemoryPatches",
    "60_Candidates/BlogIdeas",
    "60_Candidates/CareerBullets",
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
    def __init__(self, vault_dir: Path, wiki_folder: str = "60_Wiki") -> None:
        self.vault_dir = vault_dir
        self.wiki_dir = vault_dir / wiki_folder

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

    def search(self, query: str, limit: int = 10) -> list[WikiSearchResult]:
        """Simple keyword search over parsed vault notes."""
        return self._search_notes(self.scan_notes(), query, limit=limit)

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
        return "# Vault Index\n\n_Run `work-agent index-vault` to rebuild this catalog._\n"

    def _default_vault_agents(self) -> str:
        return (
            "# AGENTS.md\n\n"
            "This Obsidian vault is the shared memory bus for Work Agent and other AI tools.\n\n"
            "## Writable Areas\n\n"
            "- 00_Inbox/\n"
            "- 10_Worklog/\n"
            "- 50_Outputs/Blog/Drafts/\n"
            "- 50_Outputs/Portfolio/\n"
            "- 50_Outputs/Resume/\n"
            "- 50_Outputs/Interview/\n"
            "- 60_Candidates/\n\n"
            "## Protected Areas\n\n"
            "- 20_Knowledge/\n"
            "- 40_AgentMemory/Core/\n"
            "- 30_Projects/*/Context.md\n\n"
            "Protected areas should be changed through candidates or patches, then reviewed.\n"
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

    # ── index / log ──────────────────────────────────────────────

    def get_index(self) -> str:
        p = self.wiki_dir / "index.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _parse_index_summaries(self) -> dict[str, str]:
        """기존 index.md에서 {page_path: summary} 추출."""
        index = self.get_index()
        summaries: dict[str, str] = {}
        # 예: - [제목](AI/rag-pipeline.md) — 요약
        pattern = re.compile(r"\[.+?\]\((.+?\.md)\)(?:\s+—\s+(.+))?")
        for m in pattern.finditer(index):
            path, summary = m.group(1), m.group(2) or ""
            summaries[path] = summary.strip()
        return summaries

    def rebuild_index(self, new_summaries: dict[str, str]) -> None:
        """wiki 폴더의 모든 페이지로 index.md를 재생성한다."""
        existing = self._parse_index_summaries()
        existing.update(new_summaries)  # 새 것으로 덮어쓰기

        groups: dict[str, list[str]] = defaultdict(list)
        for rel_path in sorted(self.list_pages()):
            p = Path(rel_path)
            group = p.parts[0] if len(p.parts) > 1 else "일반"
            summary = existing.get(rel_path, "")
            name = p.stem
            entry = f"- [{name}]({rel_path})"
            if summary:
                entry += f" — {summary}"
            groups[group].append(entry)

        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"# Wiki Index\n\n_업데이트: {today}_"]
        for group in sorted(groups):
            lines.append(f"\n## {group}")
            lines.extend(groups[group])

        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        (self.wiki_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def append_log(self, page_paths: list[str]) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        # 첫 경로의 stem을 레이블로 사용 (파싱 가능: grep "^## \[" log.md)
        label = Path(page_paths[0]).stem if page_paths else "unknown"
        op = "query" if any("(쿼리 저장)" in p for p in page_paths) else "ingest"
        header = f"## [{today}] {op} | {label}"
        entry = f"{header}\n\n" + "\n".join(f"- {p}" for p in page_paths) + "\n"
        log_path = self.wiki_dir / "log.md"
        existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        log_path.write_text(entry + "\n" + existing, encoding="utf-8")

    # ── source files (볼트 내 wiki 제외) ─────────────────────────

    def list_source_files(self, folder_filter: str = "") -> list[str]:
        """vault에서 wiki 폴더를 제외한 .md 파일 경로 목록."""
        result = []
        for f in sorted(self.vault_dir.rglob("*.md")):
            try:
                f.relative_to(self.wiki_dir)
                continue  # wiki 폴더 내부 → 제외
            except ValueError:
                pass
            rel = str(f.relative_to(self.vault_dir))
            if folder_filter and not rel.lower().startswith(folder_filter.lower()):
                continue
            result.append(rel)
        return result

    def list_source_files_grouped(self, folder_filter: str = "") -> str:
        """폴더별로 그룹화된 소스 파일 목록을 문자열로 반환."""
        from collections import defaultdict
        groups: dict[str, list[str]] = defaultdict(list)
        for rel in self.list_source_files(folder_filter):
            parts = Path(rel).parts
            group = str(Path(*parts[:2])) if len(parts) > 2 else parts[0]
            groups[group].append(Path(rel).name)

        lines = []
        for group in sorted(groups):
            files = groups[group]
            lines.append(f"\n### {group}/ ({len(files)}개)")
            for name in files[:30]:  # 폴더당 최대 30개 표시
                lines.append(f"  - {name}")
            if len(files) > 30:
                lines.append(f"  - ... 외 {len(files) - 30}개")
        return "\n".join(lines)

    def read_source(self, rel_path: str, max_chars: int = 0) -> str:
        p = self.vault_dir / rel_path
        if not p.exists():
            return ""
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            text = p.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars] if max_chars else text

    # ── wiki pages ───────────────────────────────────────────────

    def list_pages(self) -> list[str]:
        if not self.wiki_dir.exists():
            return []
        skip = {"index.md", "log.md"}
        return [
            str(f.relative_to(self.wiki_dir))
            for f in sorted(self.wiki_dir.rglob("*.md"))
            if f.name not in skip
        ]

    def write_page(self, rel_path: str, content: str) -> Path:
        dest = self.wiki_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest

    def read_page(self, rel_path: str) -> str:
        p = self.wiki_dir / rel_path
        return p.read_text(encoding="utf-8") if p.exists() else ""
