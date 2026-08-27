"""app/services/activity_hook.py 테스트 (docs/activity-collector-design.md §4)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.services import activity_hook


@pytest.fixture(params=activity_hook.SHELLS)
def shell(request) -> str:
    return request.param


# ── 훅 스크립트 ──────────────────────────────────────────────────────────────


def test_hook_scripts_are_ascii_only(shell):
    """프로필 인코딩이 환경마다 달라(cp949·utf-8) 블록에 비ASCII를 넣으면 깨진다."""
    script = activity_hook.hook_script(shell)
    script.encode("ascii")  # 비ASCII가 섞이면 여기서 실패한다


def test_hook_scripts_are_marker_wrapped(shell):
    script = activity_hook.hook_script(shell)
    assert script.startswith(activity_hook.MARKER_BEGIN)
    assert activity_hook.MARKER_END in script


def test_bash_hook_registers_prompt_command_idempotently():
    script = activity_hook.hook_script("bash")
    assert "PROMPT_COMMAND" in script
    assert "*:__devtrail_activity:*" in script  # 중복 등록 방지 가드


def test_pwsh_hook_preserves_previous_prompt():
    script = activity_hook.hook_script("pwsh")
    assert "DevtrailActivityPrevPrompt" in script
    assert "try {" in script  # 수집 실패가 셸을 깨면 안 된다


# ── install / uninstall ──────────────────────────────────────────────────────


def test_install_appends_block(tmp_path, shell):
    profile = tmp_path / "profile"
    profile.write_text("echo 기존 내용\n", encoding="utf-8")

    activity_hook.install(shell, profile)

    text = profile.read_text(encoding="utf-8")
    assert "echo 기존 내용" in text
    assert activity_hook.MARKER_BEGIN in text


def test_install_creates_missing_profile(tmp_path, shell):
    profile = tmp_path / "nested" / "profile"
    activity_hook.install(shell, profile)
    assert activity_hook.MARKER_BEGIN in profile.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path, shell):
    """재설치는 블록을 쌓지 않고 갈아끼운다 — 프로필마다 훅이 여러 벌 돌면 안 된다."""
    profile = tmp_path / "profile"
    activity_hook.install(shell, profile)
    activity_hook.install(shell, profile)

    text = profile.read_text(encoding="utf-8")
    assert text.count(activity_hook.MARKER_BEGIN) == 1
    assert text.count(activity_hook.MARKER_END) == 1


def test_uninstall_removes_only_the_block(tmp_path, shell):
    profile = tmp_path / "profile"
    profile.write_text("echo before\n", encoding="utf-8")
    activity_hook.install(shell, profile)
    with profile.open("a", encoding="utf-8") as f:
        f.write("echo after\n")

    assert activity_hook.uninstall(shell, profile) is True

    text = profile.read_text(encoding="utf-8")
    assert "echo before" in text
    assert "echo after" in text
    assert activity_hook.MARKER_BEGIN not in text


def test_uninstall_without_block_reports_false(tmp_path, shell):
    profile = tmp_path / "profile"
    profile.write_text("echo only mine\n", encoding="utf-8")
    assert activity_hook.uninstall(shell, profile) is False
    assert profile.read_text(encoding="utf-8") == "echo only mine\n"


def test_install_preserves_non_utf8_profile_bytes(tmp_path, shell):
    """cp949로 저장된 프로필에 붙여도 남의 줄이 깨지면 안 된다."""
    profile = tmp_path / "profile"
    profile.write_bytes("echo 한글 설정\n".encode("cp949"))

    activity_hook.install(shell, profile)

    raw = profile.read_bytes()
    assert "echo 한글 설정".encode("cp949") in raw
    assert activity_hook.MARKER_BEGIN.encode("ascii") in raw


def test_is_installed_reflects_install_state(tmp_path, shell):
    profile = tmp_path / "profile"
    assert activity_hook.is_installed(shell, profile) is False
    activity_hook.install(shell, profile)
    assert activity_hook.is_installed(shell, profile) is True


def test_unknown_shell_raises():
    with pytest.raises(activity_hook.ActivityHookError):
        activity_hook.hook_script("fish")


# ── 이벤트 읽기 / status ─────────────────────────────────────────────────────


def _write_events(home: Path, day: date, lines: list[str]) -> None:
    path = activity_hook.activity_dir(home) / f"{day.isoformat()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_events_skips_broken_lines(tmp_path):
    """훅이 쓰다 만 줄 하나가 하루치 수집을 통째로 막으면 안 된다."""
    today = date.today()
    _write_events(
        tmp_path,
        today,
        [
            json.dumps({"ts": "2026-08-27T10:00:00", "cmd": "docker ps"}),
            '{"ts": "2026-08-27T10:01:00", "cmd": "잘린',
            "",
            json.dumps({"ts": "2026-08-27T10:02:00", "cmd": "git status"}),
        ],
    )

    events = activity_hook.read_events(home=tmp_path)
    assert [e["cmd"] for e in events] == ["docker ps", "git status"]


def test_read_events_missing_file_returns_empty(tmp_path):
    assert activity_hook.read_events(home=tmp_path) == []


def test_status_counts_today_and_reports_last_event(tmp_path):
    today = date.today()
    _write_events(
        tmp_path,
        today,
        [
            json.dumps({"ts": "2026-08-27T10:00:00", "cmd": "docker ps"}),
            json.dumps({"ts": "2026-08-27T10:02:00", "cmd": "git status"}),
        ],
    )
    profiles = {shell: tmp_path / f"{shell}-profile" for shell in activity_hook.SHELLS}
    activity_hook.install("bash", profiles["bash"])

    result = activity_hook.status(home=tmp_path, profiles=profiles)

    assert result.today_events == 2
    assert result.last_event["cmd"] == "git status"
    installed = {s.shell: s.installed for s in result.shells}
    assert installed == {"bash": True, "pwsh": False}
