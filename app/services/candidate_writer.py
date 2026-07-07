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
    "session_handoff": "60_Candidates/SessionHandoffs",
}

_NO_DEDUP_KINDS = {"session_handoff"}

SESSION_HANDOFF_DIR = _CANDIDATE_DIRS["session_handoff"]


@dataclass(frozen=True)
class CandidateSpec:
    kind: str
    title: str
    body: str
    summary: str = ""
    project: str = ""
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    handoff_type: str = ""
    session_id: str = ""
    evidence: str = ""
    scope: str = ""
    confidence: str = ""
    requires_user_review: bool = False
    target_file: str = ""  # memory_patch 전용: apply 시 반영될 40_AgentMemory 파일


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
            try:
                existing = frontmatter.loads(md_path.read_text(encoding="utf-8"))
                existing_title = str(existing.metadata.get("title") or "").strip()
                created_str = str(existing.metadata.get("created_at") or "")
                if created_str:
                    file_date = datetime.strptime(created_str[:10], "%Y-%m-%d")
                    if (today - file_date).days > _DEDUP_LOOKBACK_DAYS:
                        continue
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

        effective_dedup = dedup and kind not in _NO_DEDUP_KINDS
        if effective_dedup:
            existing = self.find_duplicate(spec)
            if existing:
                # 새로 쓰지 않고 기존 후보를 최신 내용으로 갱신한다 — "안 쓰기"만 하면
                # 오래된 초안이 검토 큐에 계속 남고 최신 정보가 유실된다.
                updated = self._update_existing(existing, spec)
                if updated is not None:
                    return updated
                # status가 candidate가 아니면(사람이 promote/수정한 파일) 덮어쓰지 않고
                # 기존 경로만 반환한다.
                return CandidateWriteResult(spec=spec, path=self.vault_dir / existing, rel_path=existing)

        rel_path = self._unique_rel_path(kind, spec.title, project=spec.project)
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)

        metadata: dict[str, Any] = {
            "type": "candidate",
            "candidate_type": kind,
            "title": spec.title.strip(),
            "status": "candidate",
            "created_at": self._now().strftime("%Y-%m-%dT%H:%M:%S"),
            "project": spec.project,
            "tags": spec.tags,
            "source_refs": spec.source_refs,
            # summary가 비면 본문 첫 의미 줄로 채운다 — list-candidates/digest/Telegram
            # 카드가 제목 외에 보여줄 한 줄이 생긴다.
            "summary": spec.summary or self._derive_summary(spec.body),
        }
        if kind == "session_handoff":
            metadata["handoff_type"] = spec.handoff_type
            metadata["session_id"] = spec.session_id
        if kind == "memory_patch":
            metadata["evidence"] = spec.evidence
            metadata["scope"] = spec.scope
            metadata["confidence"] = spec.confidence
            metadata["requires_user_review"] = spec.requires_user_review
            if spec.target_file:
                metadata["target_file"] = spec.target_file

        body = self._render_body(spec)
        post = frontmatter.Post(body, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        result = CandidateWriteResult(spec=spec, path=path, rel_path=rel_path)
        self.wiki_service.append_vault_log("distill", spec.title, [rel_path])
        return result

    def write_many(self, specs: list[CandidateSpec], dedup: bool = True) -> list[CandidateWriteResult]:
        return [self.write(spec, dedup=dedup) for spec in specs]

    def upsert_exact(self, spec: CandidateSpec) -> CandidateWriteResult:
        """제목이 정확히 같은 candidate가 있으면 갱신하고, 없으면 dedup 없이 새로 쓴다.

        같은 세션이 write를 재호출하는 경로(예: Process 재기록 후 memory_patch 갱신)용.
        유사도 dedup은 날짜만 다른 이전 세션 후보를 잘못 잡을 수 있어 정확 일치만 본다.
        """
        kind = self._normalize_kind(spec.kind)
        if kind not in _CANDIDATE_DIRS:
            raise ValueError(f"unsupported candidate kind: {spec.kind}")
        cand_dir = self.vault_dir / _CANDIDATE_DIRS[kind]
        if cand_dir.exists():
            target_title = spec.title.strip()
            for md_path in cand_dir.glob("*.md"):
                try:
                    existing = frontmatter.loads(md_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(existing.metadata.get("title") or "").strip() != target_title:
                    continue
                rel = str(md_path.relative_to(self.vault_dir)).replace("\\", "/")
                updated = self._update_existing(rel, spec)
                if updated is not None:
                    return updated
        return self.write(spec, dedup=False)

    def _update_existing(self, rel_path: str, spec: CandidateSpec) -> CandidateWriteResult | None:
        """유사 후보를 새 내용으로 갱신한다. status=candidate가 아니면 None (건드리지 않음).

        created_at·title은 보존하고 body를 교체하며, source_refs는 합집합으로 병합한다 —
        같은 주제가 여러 날 이어질 때 근거 노트가 누적돼야 promote 판단이 쉬워진다.
        """
        path = self.vault_dir / rel_path
        try:
            existing = frontmatter.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if str(existing.metadata.get("status", "") or "").strip().lower() != "candidate":
            return None

        merged_refs = list(dict.fromkeys(
            [str(r) for r in (existing.metadata.get("source_refs") or [])] + list(spec.source_refs)
        ))
        existing.metadata["updated_at"] = self._now().strftime("%Y-%m-%dT%H:%M:%S")
        existing.metadata["source_refs"] = merged_refs
        new_summary = spec.summary or self._derive_summary(spec.body)
        if new_summary:
            existing.metadata["summary"] = new_summary
        existing.content = self._render_body(spec)
        path.write_text(frontmatter.dumps(existing), encoding="utf-8")

        self.wiki_service.append_vault_log("distill-update", spec.title, [rel_path])
        return CandidateWriteResult(spec=spec, path=path, rel_path=rel_path)

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

    def _unique_rel_path(self, kind: str, title: str, project: str = "") -> str:
        base_dir = _CANDIDATE_DIRS[kind]
        if kind == "session_handoff":
            base_dir = handoff_project_dir(project)
        name = self._slug(title)
        rel = f"{base_dir}/{name}.md"
        if not (self.vault_dir / rel).exists():
            return rel
        idx = 2
        while True:
            rel = f"{base_dir}/{name} ({idx}).md"
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
            "session_handoffs": "session_handoff",
            "handoff": "session_handoff",
        }
        return aliases.get(value, value)

    @staticmethod
    def _derive_summary(body: str, limit: int = 120) -> str:
        """본문에서 헤딩·불릿 기호를 뗀 첫 의미 줄을 요약으로 뽑는다."""
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            stripped = re.sub(r"^[-*>\d.)\s]+", "", stripped).strip()
            if stripped:
                return stripped[:limit]
        return ""

    @staticmethod
    def _norm_title(title: str) -> str:
        """dedup 비교용 정규화: 소문자, 특수문자 제거, 공백 정리."""
        t = title.lower().strip()
        t = re.sub(r"[^0-9a-z가-힣\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _slug(self, value: str) -> str:
        """파일시스템 금지 문자만 제거하고 제목을 그대로 파일명으로 사용한다."""
        return slug_component(value)

    def _now(self) -> datetime:
        return self.now or datetime.now()


def slug_component(value: str) -> str:
    """경로 한 조각(파일명/폴더명)에 쓸 수 있게 파일시스템 금지 문자만 제거한다."""
    text = re.sub(r'[\\/:*?"<>|]', "", value.strip())
    return re.sub(r"\s+", " ", text).strip() or "candidate"


def handoff_project_dir(project: str) -> str:
    """session_handoff의 <Project> 하위 폴더 상대경로를 계산한다.

    CandidateWriter(쓰기), vault_tools(조회), retention(정리) 세 곳이 각자
    비슷한 계산을 하면 한 곳만 바뀌어도 briefing/cleanup이 조용히 빈 결과를
    내므로, 이 함수 하나로 통일한다.
    """
    sub = slug_component(project) if project.strip() else "_Unassigned"
    return f"{SESSION_HANDOFF_DIR}/{sub}"
