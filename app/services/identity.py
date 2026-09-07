"""기록 주체 식별 — 어느 노드(host)에서 어느 에이전트(agent)가 남긴 기록인가.

멀티 노드(rpi4 · macmini · macbook) · 멀티 에이전트로 기록이 들어오기 시작하면
"이 세션은 어디서 누가 남겼나"를 사후에 복원할 방법이 없다. 기록 시점의 프로세스
환경에만 있는 정보라서 소급이 안 된다 — 그래서 기록이 쌓이기 전에 넣는다.

값을 확신할 수 없으면 빈 문자열을 남긴다. 추측해서 채우면 나중에
"macmini에서 반복되는 문제" 같은 집계가 조용히 틀린 답을 낸다 — 빈 값은
집계에서 빠지지만, 틀린 값은 결론을 바꾼다.
"""

from __future__ import annotations

import os
import socket

# 셸 훅(scripts/activity/*)이 쓰는 host 값과 대조될 값이다. 훅은 pwsh
# $env:COMPUTERNAME / bash hostname을 쓰는데, 같은 머신에서는 이 함수의
# socket.gethostname()과 같은 문자열이 나온다(Windows 데스크톱 실측).
_AGENT_ENV_OVERRIDE = "DEVTRAIL_AGENT"

# Claude Code가 자식 프로세스에 넣는 표식. MCP 서버는 클라이언트가 띄우는
# 자식이라 이 환경을 물려받는다.
_CLAUDE_CODE_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def resolve_host() -> str:
    """이 기록을 남기는 머신의 이름. 취득 실패 시 빈 문자열."""
    try:
        return socket.gethostname().strip()
    except OSError:
        return ""


def resolve_agent(explicit: str = "") -> str:
    """기록을 남기는 에이전트 식별자.

    우선순위는 신뢰도 순이다: 호출자가 명시한 값 → 사용자가 설정한
    `DEVTRAIL_AGENT` → 프로세스 환경에서 감지 → 빈 문자열.

    환경 감지를 마지막에 두는 이유: Codex·Cursor 등 다른 에이전트가 자신을
    선언할 방법이 코드 수정이어서는 안 된다. `DEVTRAIL_AGENT`가 그 창구다.
    """
    if explicit.strip():
        return _normalize(explicit)

    override = os.environ.get(_AGENT_ENV_OVERRIDE, "")
    if override.strip():
        return _normalize(override)

    if any(os.environ.get(marker, "").strip() for marker in _CLAUDE_CODE_MARKERS):
        return "claude-code"

    return ""


def _normalize(value: str) -> str:
    """소문자·하이픈으로 통일한다 — 같은 에이전트가 두 이름으로 집계되지 않게."""
    return "-".join(value.strip().lower().split())
