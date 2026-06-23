"""Git repo 상태 수집 헬퍼.

subprocess로 Git 명령을 실행해 현재 브랜치, 커밋, 변경 파일 등을 수집한다.
Git이 없거나 repo가 아니어도 예외 없이 빈 값으로 graceful fallback한다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RepoSnapshot:
    repo_path: str
    branch: str | None = None
    commit: str | None = None
    status_short: str = ""
    recent_commits: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    diff_stat: str = ""
    error: str | None = None


def capture_repo_snapshot(repo_path: str | Path) -> RepoSnapshot:
    """Git repo 상태를 수집해 RepoSnapshot으로 반환한다.

    Git이 없거나 repo가 아닌 경로여도 error 필드에 메시지를 담고 반환한다.
    """
    repo_path = str(Path(repo_path).resolve())
    snap = RepoSnapshot(repo_path=repo_path)

    def _run(args: list[str]) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except (FileNotFoundError, OSError):
            return None

    # git repo 확인
    if _run(["rev-parse", "--is-inside-work-tree"]) is None:
        snap.error = f"Not a git repository: {repo_path}"
        return snap

    snap.branch = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    snap.commit = _run(["rev-parse", "HEAD"])
    snap.status_short = _run(["status", "--short"]) or ""
    log_raw = _run(["log", "--oneline", "-5"]) or ""
    snap.recent_commits = [l for l in log_raw.splitlines() if l.strip()]
    diff_names = _run(["diff", "--name-only"]) or ""
    # Also get staged files
    staged_names = _run(["diff", "--name-only", "--staged"]) or ""
    all_changed: list[str] = []
    seen: set[str] = set()
    for name in (diff_names + "\n" + staged_names).splitlines():
        name = name.strip()
        if name and name not in seen:
            all_changed.append(name)
            seen.add(name)
    snap.changed_files = all_changed
    snap.diff_stat = _run(["diff", "--stat"]) or ""
    return snap
