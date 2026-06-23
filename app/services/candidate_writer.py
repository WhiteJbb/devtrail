"""Candidate note writer for the Obsidian Wiki Core."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import frontmatter

from app.services.wiki_service import WikiService

_DEDUP_THRESHOLD = 0.85  # 제목 유사도 임계값
_DEDUP_LOOKBACK_DAYS = 14  # 최근 N일 이내 후보만 dedup 대상


_CANDIDATE_DIRS = {
    "knowledge": "60_Candidates/Knowledge",
    "decision": "60_Candidates/Decisions",
    "memory_patch": "60_Candidates/MemoryPatches",
    "blog_idea": "60_Candidates/BlogIdeas",
    "career_bullet": "60_Candidates/CareerBullets",
}


@dataclass(frozen=True)
class CandidateSpec:
    kind: str
    title: str
    body: str
    summary: str = ""
    project: str = ""
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateWriteResult:
    spec: CandidateSpec
    path: Path
    rel_path: str


class CandidateWriter:
    """Write generated candidates only under 60_Candidates."""

    def __init__(self, vault_dir: Path, wiki_service: WikiService | None = None, now: datetime | None = None) -> None:
        self.vault_dir = vault_dir
        self.wiki_service = wiki_service or WikiService(vault_dir)
        self.now = now

    def find_duplicate(self, spec: CandidateSpec) -> str | None:
        """같은 kind 폴더에서 유사 제목의 기존 후보를 찾아 rel_path를 반환한다. 없으면 None."""
        kind = self._normalize_kind(spec.kind)
        if kind not in _CANDIDATE_DIRS:
            return None
        cand_dir = self.vault_dir / _CANDIDATE_DIRS[kind]
        if not cand_dir.exists():
            return None

        today = self._now()
        norm_new = self._norm_title(spec.title)

        for md_path in cand_dir.glob("*.md"):
            # 파일명에서 날짜 파싱 (20250623-... 형식)
            stem = md_path.stem
            try:
                file_date = datetime.strptime(stem[:8], "%Y%m%d")
                if (today - file_date).days > _DEDUP_LOOKBACK_DAYS:
                    continue
            except ValueError:
                continue  # 날짜 파싱 실패 파일은 lookback 대상에서 제외

            try:
                existing = frontmatter.loads(md_path.read_text(encoding="utf-8"))
                existing_title = str(existing.metadata.get("title") or "").strip()
            except Exception:
                continue

            if not existing_title:
                continue

            ratio = SequenceMatcher(None, norm_new, self._norm_title(existing_title)).ratio()
            if ratio >= _DEDUP_THRESHOLD:
                return str(md_path.relative_to(self.vault_dir)).replace("\\", "/")

        return None

    def write(self, spec: CandidateSpec, dedup: bool = True) -> CandidateWriteResult:
        kind = self._normalize_kind(spec.kind)
        if kind not in _CANDIDATE_DIRS:
            raise ValueError(f"unsupported candidate kind: {spec.kind}")
        if not spec.title.strip():
            raise ValueError("candidate title is empty")

        if dedup:
            existing = self.find_duplicate(spec)
            if existing:
                # 기존 후보 경로를 반환 (새로 쓰지 않음)
                existing_path = self.vault_dir / existing
                return CandidateWriteResult(spec=spec, path=existing_path, rel_path=existing)

        rel_path = self._unique_rel_path(kind, spec.title)
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)

        metadata: dict[str, Any] = {
            "type": "candidate",
            "candidate_type": kind,
            "title": spec.title.strip(),
            "status": "candidate",
            "created_at": self._now().strftime("%Y-%m-%d"),
            "project": spec.project,
            "tags": spec.tags,
            "source_refs": spec.source_refs,
            "summary": spec.summary,
        }

        body = self._render_body(spec)
        post = frontmatter.Post(body, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        result = CandidateWriteResult(spec=spec, path=path, rel_path=rel_path)
        self.wiki_service.append_vault_log("distill", spec.title, [rel_path])
        return result

    def write_many(self, specs: list[CandidateSpec]) -> list[CandidateWriteResult]:
        return [self.write(spec) for spec in specs]

    def _render_body(self, spec: CandidateSpec) -> str:
        body = spec.body.strip()
        if not body:
            body = spec.summary.strip() or "(내용 후보 없음)"
        if body.startswith("# "):
            rendered = body
        else:
            rendered = f"# {spec.title.strip()}\n\n{body}"
        if spec.source_refs:
            refs = "\n".join(f"- {ref}" for ref in spec.source_refs)
            rendered += f"\n\n## Source Refs\n\n{refs}"
        return rendered.strip() + "\n"

    def _unique_rel_path(self, kind: str, title: str) -> str:
        base_dir = _CANDIDATE_DIRS[kind]
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        slug = self._slug(title)
        rel = f"{base_dir}/{stamp}-{slug}.md"
        if not (self.vault_dir / rel).exists():
            return rel
        idx = 2
        while True:
            rel = f"{base_dir}/{stamp}-{slug}-{idx}.md"
            if not (self.vault_dir / rel).exists():
                return rel
            idx += 1

    def _normalize_kind(self, kind: str) -> str:
        value = kind.strip().lower().replace("-", "_")
        aliases = {
            "knowledge_candidate": "knowledge",
            "decision_candidate": "decision",
            "decisions": "decision",
            "memory": "memory_patch",
            "memory_patches": "memory_patch",
            "blog": "blog_idea",
            "blog_ideas": "blog_idea",
            "career_bullets": "career_bullet",
            "career": "career_bullet",
        }
        return aliases.get(value, value)

    @staticmethod
    def _norm_title(title: str) -> str:
        """dedup 비교용 정규화: 소문자, 특수문자 제거, 공백 정리."""
        t = title.lower().strip()
        t = re.sub(r"[^0-9a-z가-힣\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _slug(self, value: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^0-9a-z가-힣_-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-_")
        return text or "candidate"

    def _now(self) -> datetime:
        return self.now or datetime.now()
