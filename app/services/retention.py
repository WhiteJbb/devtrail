"""Vault 보존 정책 — 오래된 10_Worklog/Sessions/와 60_Candidates/SessionHandoffs/ 정리.

docs/service-improvement-plan.md P4. 사람이 실행하는 CLI 전용이다(destructive
action이므로 MCP tool로는 노출하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import frontmatter

from app.services.candidate_writer import SESSION_HANDOFF_DIR

DEFAULT_KEEP_PER_PROJECT = 3
DEFAULT_WORKLOG_RETENTION_DAYS = 30
DEFAULT_HANDOFF_RETENTION_DAYS = 30
DEFAULT_CANDIDATE_TTL_DAYS = 14

CANDIDATE_ARCHIVE_DIR = "60_Candidates/_Archive"

# TTL 만료 후보의 kind별 처분 (사용자 확정 정책):
# 재생성 가능한 파생물(raw 노트에서 다시 뽑을 수 있음)은 삭제,
# 사람 판단이 들어간 것은 _Archive/로 보관한다.
_EXPIRE_DELETE_KINDS = {"knowledge", "blog_idea", "career_bullet"}
_EXPIRE_ARCHIVE_KINDS = {"decision", "memory_patch"}


@dataclass(frozen=True)
class CleanupResult:
    deleted_worklog: list[str] = field(default_factory=list)
    deleted_handoffs: list[str] = field(default_factory=list)
    deleted_candidates: list[str] = field(default_factory=list)
    archived_candidates: list[str] = field(default_factory=list)
    dry_run: bool = False


def _parse_created_at(meta: dict, fallback_mtime: float) -> datetime:
    raw = str(meta.get("created_at", "") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw[:19].replace(" ", "T"))
        except ValueError:
            pass
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_mtime)


def cleanup_vault(
    vault_dir: Path,
    *,
    keep_per_project: int = DEFAULT_KEEP_PER_PROJECT,
    worklog_retention_days: int = DEFAULT_WORKLOG_RETENTION_DAYS,
    handoff_retention_days: int = DEFAULT_HANDOFF_RETENTION_DAYS,
    candidate_ttl_days: int = DEFAULT_CANDIDATE_TTL_DAYS,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """distill된 worklog 세션과, 프로젝트당 최신 N개를 넘는 SessionHandoffs를 정리한다.

    SessionHandoffs는 session_id로 Plan+Process를 한 그룹(세션)으로 묶어, 프로젝트별
    생성일 기준 최신 keep_per_project개 "세션"을 무조건 보존하고, 그 밖은
    handoff_retention_days를 넘으면 그룹 전체를 삭제한다 — 짝 없는 오래된 Plan도 이
    규칙에 자연히 포함된다. 파일 단위로 자르지 않으므로 Plan/Process 짝이 갈라지지
    않는다.
    """
    resolved_now = now or datetime.now()
    deleted_worklog = _cleanup_worklog_sessions(vault_dir, worklog_retention_days, resolved_now, dry_run)
    deleted_handoffs = _cleanup_session_handoffs(vault_dir, keep_per_project, handoff_retention_days, resolved_now, dry_run)
    deleted_candidates, archived_candidates = cleanup_candidates(
        vault_dir, ttl_days=candidate_ttl_days, dry_run=dry_run, now=resolved_now
    )
    return CleanupResult(
        deleted_worklog=deleted_worklog,
        deleted_handoffs=deleted_handoffs,
        deleted_candidates=deleted_candidates,
        archived_candidates=archived_candidates,
        dry_run=dry_run,
    )


def cleanup_candidates(
    vault_dir: Path,
    *,
    ttl_days: int = DEFAULT_CANDIDATE_TTL_DAYS,
    dry_run: bool = False,
    now: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """TTL이 지난 60_Candidates 후보를 kind별 정책으로 처분한다.

    - status=candidate + 재생성 가능 kind(knowledge/blog_idea/career_bullet) → 삭제
    - status=candidate + 사람 판단 kind(decision/memory_patch) → _Archive/<폴더>/ 이동
    - status=promoted/applied → 공식 영역에 사본이 있으므로 kind 무관 삭제
    - SessionHandoffs는 자체 정책(cleanup_vault)이 있으므로 제외

    반환: (deleted rel_paths, archived rel_paths)
    """
    from app.services.candidate_writer import _CANDIDATE_DIRS  # 순환 없음: retention→writer 단방향

    resolved_now = now or datetime.now()
    deleted: list[str] = []
    archived: list[str] = []

    for kind, rel_dir in _CANDIDATE_DIRS.items():
        if kind == "session_handoff":
            continue
        cand_dir = vault_dir / rel_dir
        if not cand_dir.exists():
            continue

        for md_path in sorted(cand_dir.glob("*.md")):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            meta = post.metadata
            # dedup 갱신(updated_at)이 있으면 그 시점 기준 — 갱신은 "아직 활발한 주제"
            # 신호이므로 created_at만 보면 살아있는 후보를 만료시킨다.
            if meta.get("updated_at"):
                last_active = _parse_created_at({"created_at": meta["updated_at"]}, md_path.stat().st_mtime)
            else:
                last_active = _parse_created_at(meta, md_path.stat().st_mtime)
            if (resolved_now - last_active).days <= ttl_days:
                continue

            status = str(meta.get("status", "") or "").strip().lower()
            rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")

            if status in ("promoted", "applied") or kind in _EXPIRE_DELETE_KINDS:
                deleted.append(rel)
                if not dry_run:
                    md_path.unlink()
            elif kind in _EXPIRE_ARCHIVE_KINDS:
                archive_dir = vault_dir / CANDIDATE_ARCHIVE_DIR / cand_dir.name
                archived.append(rel)
                if not dry_run:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dest = archive_dir / md_path.name
                    idx = 2
                    while dest.exists():
                        dest = archive_dir / f"{md_path.stem} ({idx}){md_path.suffix}"
                        idx += 1
                    md_path.rename(dest)
            # 알 수 없는 kind는 건드리지 않는다

    return deleted, archived


def _cleanup_worklog_sessions(vault_dir: Path, retention_days: int, now: datetime, dry_run: bool) -> list[str]:
    sessions_dir = vault_dir / "10_Worklog" / "Sessions"
    if not sessions_dir.exists():
        return []

    deleted: list[str] = []
    for md_path in sorted(sessions_dir.glob("*.md")):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = post.metadata
        if meta.get("needs_distill", True):
            continue  # 아직 distill되지 않은 raw 기록은 보존한다
        created = _parse_created_at(meta, md_path.stat().st_mtime)
        if (now - created).days <= retention_days:
            continue
        rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
        deleted.append(rel)
        if not dry_run:
            md_path.unlink()
    return deleted


def _cleanup_session_handoffs(
    vault_dir: Path, keep_per_project: int, retention_days: int, now: datetime, dry_run: bool
) -> list[str]:
    """SessionHandoffs를 session_id 단위(Plan+Process 짝)로 묶어 보존/삭제한다.

    파일 단위로 정리하면 keep-N 컷이 Plan/Process 짝 사이를 가를 수 있다 — 짝 중
    하나만 살아남으면 이후 briefing이 거짓 "미짝 Plan 경고"를 내고, 짝 없는
    Process가 그 stale session_id로 잘못 재귀속되는 문제로 이어진다. session_id가
    없는 파일은 파일 단독을 그룹으로 취급한다.
    """
    handoffs_root = vault_dir / SESSION_HANDOFF_DIR
    if not handoffs_root.exists():
        return []

    deleted: list[str] = []
    for project_dir in sorted(p for p in handoffs_root.iterdir() if p.is_dir()):
        groups: dict[str, list[tuple[datetime, Path]]] = {}
        for md_path in sorted(project_dir.glob("*.md")):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            created = _parse_created_at(post.metadata, md_path.stat().st_mtime)
            session_id = str(post.metadata.get("session_id", "") or "")
            group_key = session_id or f"__no_session_id__{md_path.name}"
            groups.setdefault(group_key, []).append((created, md_path))

        def _group_sort_key(item: tuple[str, list[tuple[datetime, Path]]]) -> tuple[float, str]:
            _key, files = item
            latest = max(created for created, _path in files)
            min_name = min(path.name for _created, path in files)
            return (-latest.timestamp(), min_name)

        ordered_groups = sorted(groups.items(), key=_group_sort_key)

        for _key, files in ordered_groups[keep_per_project:]:
            group_created = max(created for created, _path in files)
            if (now - group_created).days <= retention_days:
                continue
            for _created, md_path in files:
                rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
                deleted.append(rel)
                if not dry_run:
                    md_path.unlink()
    return deleted
