"""Vault 보존 정책 — 오래된 10_Worklog/Sessions/와 60_Candidates/SessionHandoffs/ 정리.

docs/service-improvement-plan.md P4. 사람이 실행하는 CLI 전용이다(destructive
action이므로 MCP tool로는 노출하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import frontmatter

DEFAULT_KEEP_PER_PROJECT = 3
DEFAULT_WORKLOG_RETENTION_DAYS = 30
DEFAULT_HANDOFF_RETENTION_DAYS = 30


@dataclass(frozen=True)
class CleanupResult:
    deleted_worklog: list[str] = field(default_factory=list)
    deleted_handoffs: list[str] = field(default_factory=list)
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
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """distill된 worklog 세션과, 프로젝트당 최신 N개를 넘는 SessionHandoffs를 정리한다.

    SessionHandoffs는 Plan/Process 구분 없이 프로젝트별 생성일 기준 최신
    keep_per_project개를 무조건 보존하고, 그 밖은 handoff_retention_days를
    넘으면 삭제한다 — 짝 없는 오래된 Plan도 이 규칙에 자연히 포함된다.
    """
    resolved_now = now or datetime.now()
    deleted_worklog = _cleanup_worklog_sessions(vault_dir, worklog_retention_days, resolved_now, dry_run)
    deleted_handoffs = _cleanup_session_handoffs(vault_dir, keep_per_project, handoff_retention_days, resolved_now, dry_run)
    return CleanupResult(deleted_worklog=deleted_worklog, deleted_handoffs=deleted_handoffs, dry_run=dry_run)


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
    handoffs_root = vault_dir / "60_Candidates" / "SessionHandoffs"
    if not handoffs_root.exists():
        return []

    deleted: list[str] = []
    for project_dir in sorted(p for p in handoffs_root.iterdir() if p.is_dir()):
        items: list[tuple[datetime, Path]] = []
        for md_path in project_dir.glob("*.md"):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            created = _parse_created_at(post.metadata, md_path.stat().st_mtime)
            items.append((created, md_path))

        items.sort(key=lambda pair: pair[0], reverse=True)
        for created, md_path in items[keep_per_project:]:
            if (now - created).days <= retention_days:
                continue
            rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
            deleted.append(rel)
            if not dry_run:
                md_path.unlink()
    return deleted
