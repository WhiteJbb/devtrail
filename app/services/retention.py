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

    SessionHandoffs는 session_id로 Plan+Process를 한 그룹(세션)으로 묶어, 프로젝트별
    생성일 기준 최신 keep_per_project개 "세션"을 무조건 보존하고, 그 밖은
    handoff_retention_days를 넘으면 그룹 전체를 삭제한다 — 짝 없는 오래된 Plan도 이
    규칙에 자연히 포함된다. 파일 단위로 자르지 않으므로 Plan/Process 짝이 갈라지지
    않는다.
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
    """SessionHandoffs를 session_id 단위(Plan+Process 짝)로 묶어 보존/삭제한다.

    파일 단위로 정리하면 keep-N 컷이 Plan/Process 짝 사이를 가를 수 있다 — 짝 중
    하나만 살아남으면 이후 briefing이 거짓 "미짝 Plan 경고"를 내고, 짝 없는
    Process가 그 stale session_id로 잘못 재귀속되는 문제로 이어진다. session_id가
    없는 파일은 파일 단독을 그룹으로 취급한다.
    """
    handoffs_root = vault_dir / "60_Candidates" / "SessionHandoffs"
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
