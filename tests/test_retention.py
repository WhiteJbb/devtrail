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


def _write_handoff(
    vault: Path, project: str, name: str, created_at: str, handoff_type: str = "plan", session_id: str = ""
) -> Path:
    path = vault / "60_Candidates" / "SessionHandoffs" / project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "candidate",
        "candidate_type": "session_handoff",
        "handoff_type": handoff_type,
        "created_at": created_at,
        "session_id": session_id,
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


def test_full_timestamp_created_at_is_parsed_correctly(tmp_path):
    """created_at이 초 단위 ISO 타임스탬프(P2.1)여도 날짜 계산이 올바라야 한다."""
    _write_session(tmp_path, "old.md", "2026-05-01T23:59:59", needs_distill=False)
    _write_session(tmp_path, "recent.md", "2026-07-01T00:00:01", needs_distill=False)
    result = cleanup_vault(tmp_path, now=_NOW)
    assert "10_Worklog/Sessions/old.md" in result.deleted_worklog
    assert "10_Worklog/Sessions/recent.md" not in result.deleted_worklog


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


# ── session_id 기반 짝 보존 (P2.3) ───────────────────────────────────────────


def test_plan_process_pair_kept_or_deleted_together(tmp_path):
    """keep=3(파일 아님, 세션 단위)일 때 오래된 짝이 쪼개지지 않아야 한다.

    2개 세션(짝)뿐이면 keep_per_project=3 "세션" 기준으로는 둘 다 보존 대상이다.
    파일 단위로 자르면(구 로직) top-3 파일 안에 오래된 짝 중 하나만 들어가고
    나머지 1개는 items[3:]로 밀려 retention_days(66일 > 30일)에 걸려 삭제되므로
    Process만 없어지고 Plan이 남는 식으로 짝이 갈라진다.
    """
    _write_handoff(tmp_path, "Devtrail", "old-plan.md", "2025-05-01", "plan", session_id="old-sess")
    _write_handoff(tmp_path, "Devtrail", "old-process.md", "2025-05-01", "process", session_id="old-sess")
    _write_handoff(tmp_path, "Devtrail", "new-plan.md", "2026-07-01", "plan", session_id="new-sess")
    _write_handoff(tmp_path, "Devtrail", "new-process.md", "2026-07-01", "process", session_id="new-sess")

    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)

    handoff_dir = tmp_path / "60_Candidates/SessionHandoffs/Devtrail"
    remaining = {p.name for p in handoff_dir.glob("*.md")}
    # 세션(그룹)이 2개뿐이므로 keep=3 안에 전부 들어가 아무것도 삭제되지 않아야 한다.
    # 파일 단위였다면 4개 중 top-3만 무조건 보존되고 나머지 1개(오래된 짝의 절반)가
    # retention_days를 넘겨 삭제되며 짝이 갈라졌을 것이다.
    assert remaining == {"old-plan.md", "old-process.md", "new-plan.md", "new-process.md"}
    assert result.deleted_handoffs == []


def test_plan_process_pair_deleted_together_when_beyond_keep(tmp_path):
    """보존 대상 밖(keep 초과)이 되면 짝 전체가 함께 삭제돼야 한다."""
    _write_handoff(tmp_path, "Devtrail", "old-plan.md", "2025-05-01", "plan", session_id="old-sess")
    _write_handoff(tmp_path, "Devtrail", "old-process.md", "2025-05-01", "process", session_id="old-sess")
    _write_handoff(tmp_path, "Devtrail", "new-plan.md", "2026-07-01", "plan", session_id="new-sess")
    _write_handoff(tmp_path, "Devtrail", "new-process.md", "2026-07-01", "process", session_id="new-sess")

    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=1, handoff_retention_days=30)

    handoff_dir = tmp_path / "60_Candidates/SessionHandoffs/Devtrail"
    remaining = {p.name for p in handoff_dir.glob("*.md")}
    assert remaining == {"new-plan.md", "new-process.md"}
    assert set(result.deleted_handoffs) == {
        "60_Candidates/SessionHandoffs/Devtrail/old-plan.md",
        "60_Candidates/SessionHandoffs/Devtrail/old-process.md",
    }


def test_same_created_at_cleanup_is_deterministic_across_runs(tmp_path):
    """같은 created_at을 가진 여러 파일에서 결과가 실행마다 달라지면 안 된다."""
    for i in range(4):
        _write_handoff(tmp_path, "Devtrail", f"plan-{i}.md", "2026-01-01", session_id=f"sess-{i}")

    result1 = cleanup_vault(tmp_path, now=_NOW, keep_per_project=2, handoff_retention_days=30, dry_run=True)
    result2 = cleanup_vault(tmp_path, now=_NOW, keep_per_project=2, handoff_retention_days=30, dry_run=True)
    assert result1.deleted_handoffs == result2.deleted_handoffs


def test_files_without_session_id_are_treated_as_independent_groups(tmp_path):
    """session_id가 없는 기존 파일들은 기존처럼 파일 단위로 최신 N개가 보존돼야 한다."""
    for i in range(5):
        _write_handoff(tmp_path, "Devtrail", f"plan-{i}.md", f"2026-01-{i + 1:02d}")
    result = cleanup_vault(tmp_path, now=_NOW, keep_per_project=3, handoff_retention_days=30)
    remaining = list((tmp_path / "60_Candidates/SessionHandoffs/Devtrail").glob("*.md"))
    assert len(remaining) == 3
    assert len(result.deleted_handoffs) == 2
