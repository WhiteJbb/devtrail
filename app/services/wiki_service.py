"""Wiki 파일 시스템 관리 서비스.

Obsidian 볼트 내 wiki 폴더(기본: 60_Wiki)의 페이지 읽기/쓰기,
index.md·log.md 관리를 담당한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class WikiService:
    def __init__(self, vault_dir: Path, wiki_folder: str = "60_Wiki") -> None:
        self.vault_dir = vault_dir
        self.wiki_dir = vault_dir / wiki_folder

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
