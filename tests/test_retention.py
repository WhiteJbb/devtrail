"""app/services/retention.py 보존 정책 테스트 (docs/service-improvement-plan.md P4)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter

from app.services.retention import cleanup_vault


def _write_session(vault: Path, name: str, created_at: str, needs_distill: bool) -> Path:
    path = vault / "10_Worklog" / "Sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "session", "created_at": created_at, "needs_distill": needs_distill}
    path.write_text(frontmatter.dumps(frontmatter.Post("본문", **meta)), encoding="utf-8")
    return path


def _write_handoff(vault: Path, project: str, name: str, created_at: str, handoff_type: str = "plan") -> Path:
    path = vault / "60_Candidates" / "SessionHandoffs" / project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "candidate",
        "candidate_type": "session_handoff",
        "handoff_type": handoff_type,
        "created_at": created_at,
    }
    path.write_text(frontmatter.dumps(frontmatter.Post("본문", **meta)), encoding="utf-8")
    return path


_NOW = datetime(2026, 7, 6)


# ── worklog Sessions ─────────────────────────────────────────────────────────


def test_distilled_old_session_is_deleted(tmp_path):
    _write_session(tmp_path, "old.md", "2026-05-01", needs_distill=False)
    result = cleanup_vault(tmp_path, now=_NOW)
    assert "10_Worklog/Sessions/old.md" in result.deleted_worklog
    assert not (tmp_path / "10_Worklog/Sessions/old.md").exists()


def test_undistilled_old_session_is_preserved(tmp_path):
    _write_session(tmp_path, "raw.md", "2026-05-01", needs_distill=True)
    result = cleanup_vault(tmp_path, now=_NOW)
    assert result.deleted_worklog == []
    assert (tmp_path / "10_Worklog/Sessions/raw.md").exists()


def test_recent_distilled_session_is_preserved(tmp_path):
    _write_session(tmp_path, "recent.md", "2026-07-01", needs_distill=False)
    result = cleanup_vault(tmp_path, now=_NOW)
    assert result.deleted_worklog == []


def test_dry_run_reports_without_deleting(tmp_path):
    _write_session(tmp_path, "old.md", "2026-05-01", needs_distill=False)
    result = cleanup_vault(tmp_path, now=_NOW, dry_run=True)
    assert "10_Worklog/Sessions/old.md" in result.deleted_worklog
    assert (tmp_path / "10_Worklog/Sessions/old.md").exists()


# ── SessionHandoffs ──────────────────────────────────────────────────────────


def test_keeps_latest_n_per_project_regardless_of_age(tmp_path):
    for i in range(5):
        _write_handoff(tmp_path, "Devtrail", f"plan-{i}.md", f"2026-01-{i + 1:02d}")
    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)
    remaining = list((tmp_path / "60_Candidates/SessionHandoffs/Devtrail").glob("*.md"))
    assert len(remaining) == 3
    assert len(result.deleted_handoffs) == 2


def test_handoff_within_retention_window_beyond_keep_n_survives(tmp_path):
    for i in range(5):
        _write_handoff(tmp_path, "Devtrail", f"plan-{i}.md", "2026-07-01")
    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)
    # 최신 3개를 넘는 2개도 아직 30일 이내라 삭제되지 않는다
    assert result.deleted_handoffs == []


def test_orphan_old_plan_beyond_window_is_cleaned(tmp_path):
    # 최신 3개 Plan/Process + 아주 오래된 미짝 Plan 1개
    for i in range(3):
        _write_handoff(tmp_path, "Devtrail", f"recent-{i}.md", "2026-07-01")
    _write_handoff(tmp_path, "Devtrail", "orphan-plan.md", "2025-01-01", handoff_type="plan")
    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)
    assert "60_Candidates/SessionHandoffs/Devtrail/orphan-plan.md" in result.deleted_handoffs


def test_multiple_projects_handled_independently(tmp_path):
    for i in range(5):
        _write_handoff(tmp_path, "Devtrail", f"a-{i}.md", f"2026-01-{i + 1:02d}")
    for i in range(2):
        _write_handoff(tmp_path, "OtherProject", f"b-{i}.md", f"2026-01-{i + 1:02d}")
    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)
    assert len(list((tmp_path / "60_Candidates/SessionHandoffs/Devtrail").glob("*.md"))) == 3
    assert len(list((tmp_path / "60_Candidates/SessionHandoffs/OtherProject").glob("*.md"))) == 2
    assert len(result.deleted_handoffs) == 2


def test_no_handoffs_dir_returns_empty(tmp_path):
    result = cleanup_vault(tmp_path, now=_NOW)
    assert result.deleted_handoffs == []
    assert result.deleted_worklog == []
