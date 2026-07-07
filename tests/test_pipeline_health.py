"""app/services/pipeline_health.py — nightly-distill 정지 감지 테스트."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.services.pipeline_health import check_pipeline_health, stale_warning


def _write_digest(vault: Path, date: str) -> None:
    digest_dir = vault / "50_Outputs" / "Digest"
    digest_dir.mkdir(parents=True, exist_ok=True)
    (digest_dir / f"{date}-daily-digest.md").write_text("digest", encoding="utf-8")


def test_no_digest_dir_returns_unknown(tmp_path):
    health = check_pipeline_health(tmp_path)
    assert health.last_digest_date == ""
    assert health.age_days is None
    assert health.is_stale is False
    assert stale_warning(health) == ""


def test_fresh_digest_is_not_stale(tmp_path):
    _write_digest(tmp_path, "2026-07-07")
    health = check_pipeline_health(tmp_path, now=datetime(2026, 7, 8))
    assert health.last_digest_date == "2026-07-07"
    assert health.age_days == 1
    assert health.is_stale is False


def test_old_digest_is_stale_with_warning(tmp_path):
    _write_digest(tmp_path, "2026-07-04")
    health = check_pipeline_health(tmp_path, now=datetime(2026, 7, 8))
    assert health.is_stale is True
    warning = stale_warning(health)
    assert "2026-07-04" in warning
    assert "4일" in warning


def test_uses_latest_digest_by_filename_date(tmp_path):
    _write_digest(tmp_path, "2026-07-01")
    _write_digest(tmp_path, "2026-07-07")
    health = check_pipeline_health(tmp_path, now=datetime(2026, 7, 8))
    assert health.last_digest_date == "2026-07-07"


def test_ignores_non_digest_files(tmp_path):
    digest_dir = tmp_path / "50_Outputs" / "Digest"
    digest_dir.mkdir(parents=True)
    (digest_dir / "README.md").write_text("설명", encoding="utf-8")
    health = check_pipeline_health(tmp_path)
    assert health.age_days is None
