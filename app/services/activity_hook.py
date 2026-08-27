"""셸 활동 수집 훅 설치·제거·상태 — docs/activity-collector-design.md §4.

훅은 수집만 하고 판단하지 않는다("멍청한 훅"). 세션 묶기·잡음 필터·요약은
sessionizer(PR B)가 맡는다 — 훅을 고칠 일이 없어야 여러 셸과 나중의 원격
노드에 안전하게 뿌릴 수 있다.

훅 스크립트를 ASCII로만 쓰는 이유: 블록이 사용자의 `$PROFILE`·`.bashrc`에
그대로 들어가는데 그 파일들의 인코딩이 환경마다(cp949·utf-8) 다르다. 프로필
읽기/쓰기를 surrogateescape 바이트 왕복으로 처리하는 것도 같은 이유다 —
남의 파일에 우리 블록만 덧붙이고 나머지 바이트는 건드리지 않는다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

SHELLS = ("pwsh", "bash")

MARKER_BEGIN = "# >>> devtrail activity >>>"
MARKER_END = "# <<< devtrail activity <<<"

_HOOK_FILES = {"pwsh": "pwsh-hook.ps1", "bash": "bash-hook.sh"}
_SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts" / "activity"

_BLOCK_RE = re.compile(
    rf"\n*{re.escape(MARKER_BEGIN)}.*?{re.escape(MARKER_END)}[^\n]*\n?",
    re.DOTALL,
)


class ActivityHookError(RuntimeError):
    """훅 설치·제거 중 사용자가 고쳐야 하는 오류."""


@dataclass(frozen=True)
class ShellStatus:
    shell: str
    profile: Path | None
    installed: bool
    error: str = ""


@dataclass(frozen=True)
class ActivityStatus:
    activity_dir: Path
    shells: list[ShellStatus] = field(default_factory=list)
    today_events: int = 0
    last_event: dict | None = None


def activity_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".devtrail" / "activity"


def hook_script(shell: str) -> str:
    _validate_shell(shell)
    path = _SCRIPT_DIR / _HOOK_FILES[shell]
    if not path.exists():
        raise ActivityHookError(f"훅 스크립트를 찾을 수 없습니다: {path}")
    return path.read_text(encoding="ascii").replace("\r\n", "\n")


def default_profile(shell: str) -> Path:
    """셸이 실제로 읽는 프로필 경로. 원격 노드·WSL은 CLI의 --profile로 지정한다."""
    _validate_shell(shell)
    if shell == "bash":
        return Path.home() / ".bashrc"
    return _powershell_profile()


def install(shell: str, profile: Path | None = None) -> Path:
    """마커 블록을 프로필에 넣는다. 이미 있으면 최신 내용으로 갈아끼운다."""
    target = profile or default_profile(shell)
    text = _strip_block(_read_text(target))
    if text and not text.endswith("\n"):
        text += "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_text(target, text + hook_script(shell))
    return target


def uninstall(shell: str, profile: Path | None = None) -> bool:
    """마커 블록만 지운다. 사용자가 직접 쓴 나머지 줄은 그대로 둔다."""
    target = profile or default_profile(shell)
    original = _read_text(target)
    stripped = _strip_block(original)
    if stripped == original:
        return False
    _write_text(target, stripped)
    return True


def is_installed(shell: str, profile: Path | None = None) -> bool:
    target = profile or default_profile(shell)
    return MARKER_BEGIN in _read_text(target)


def read_events(day: date | None = None, home: Path | None = None) -> list[dict]:
    """하루치 JSONL을 읽는다. 깨진 줄은 조용히 건너뛴다 — 훅이 쓰다 만 줄이
    수집 전체를 막으면 안 된다."""
    path = activity_dir(home) / f"{(day or date.today()).isoformat()}.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def status(home: Path | None = None, profiles: dict[str, Path] | None = None) -> ActivityStatus:
    profiles = profiles or {}
    shells = []
    for shell in SHELLS:
        try:
            target = profiles.get(shell) or default_profile(shell)
        except ActivityHookError as e:
            shells.append(ShellStatus(shell=shell, profile=None, installed=False, error=str(e)))
            continue
        shells.append(ShellStatus(shell=shell, profile=target, installed=is_installed(shell, target)))

    events = read_events(home=home)
    return ActivityStatus(
        activity_dir=activity_dir(home),
        shells=shells,
        today_events=len(events),
        last_event=events[-1] if events else None,
    )


def _validate_shell(shell: str) -> None:
    if shell not in SHELLS:
        raise ActivityHookError(f"지원하지 않는 셸입니다: {shell} (가능: {', '.join(SHELLS)})")


def _powershell_profile() -> Path:
    """$PROFILE 경로는 PowerShell 버전·OneDrive 리디렉션에 따라 달라서
    추측하지 않고 셸에 직접 묻는다."""
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if not found:
            continue
        try:
            done = subprocess.run(
                [found, "-NoProfile", "-Command", "$PROFILE"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        path = done.stdout.strip()
        if done.returncode == 0 and path:
            return Path(path)
    raise ActivityHookError(
        "PowerShell을 찾지 못했습니다. --profile로 프로필 경로를 직접 지정하세요."
    )


def _strip_block(text: str) -> str:
    return _BLOCK_RE.sub("\n", text).lstrip("\n") if MARKER_BEGIN in text else text


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))
