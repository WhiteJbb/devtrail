"""로컬 Claude 훅과 MCP 프로세스의 세션 마커 경로·수명을 관리한다."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_LIVE_WINDOW = timedelta(hours=12)


def marker_path(repo_root: Path, session_id: str) -> Path:
    """원본 ID를 파일명에 노출하지 않고 세션별 경로를 만든다."""
    key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return repo_root / ".claude" / ".vault-mcp" / "mcp_sessions" / f"{key}.json"


def write_json_atomic(path: Path, data: dict) -> None:
    """훅과 MCP가 읽는 마커를 부분 파일로 노출하지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
            prefix=f".{path.stem}.", suffix=".tmp",
        ) as temp:
            temp_path = Path(temp.name)
            json.dump(data, temp, ensure_ascii=False)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def read_marker(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_process_alive(pid: int) -> bool:
    """현재 머신에서 PID가 살아 있는지 확인한다."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        process = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not process:
            return False
        try:
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            return (
                bool(kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)))
                and exit_code.value == still_active
            )
        finally:
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def live_mcp_markers(repo_root: Path, now: datetime | None = None) -> list[dict]:
    """같은 repo의 최근 12시간 내 살아 있는 MCP 프로세스 마커를 반환한다."""
    root = repo_root.resolve()
    directory = root / ".claude" / ".vault-mcp" / "mcp_sessions"
    current = now or datetime.now().astimezone()
    markers: list[dict] = []
    try:
        paths = directory.glob("*.json")
        for path in paths:
            marker = read_marker(path)
            if marker is None:
                continue
            try:
                session_id = str(marker["session_id"])
                marker_root = Path(marker["repo_root"]).resolve()
                updated_at = datetime.fromisoformat(str(marker["updated_at"]))
                pid = int(marker["pid"])
                expected_path = marker_path(root, session_id)
            except (KeyError, TypeError, ValueError, OSError):
                continue
            if marker_root != root or path.resolve() != expected_path.resolve():
                continue
            current_for_marker = (
                current.astimezone(updated_at.tzinfo)
                if updated_at.tzinfo
                else current.astimezone().replace(tzinfo=None)
            )
            age = current_for_marker - updated_at
            if age < timedelta(0) or age >= _LIVE_WINDOW or not is_process_alive(pid):
                continue
            markers.append(marker)
    except OSError:
        return []
    return markers


def unique_live_mcp_marker(repo_root: Path) -> dict | None:
    """같은 repo의 live MCP marker가 정확히 하나일 때만 반환한다."""
    markers = live_mcp_markers(repo_root)
    return markers[0] if len(markers) == 1 else None
