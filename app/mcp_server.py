"""MCP 서버 — Agent Session Lifecycle의 7개 정본 tool을 stdio로 노출한다.

Claude Code/Desktop 같은 MCP 클라이언트는 세션당 이 서버 프로세스를 1개 띄우므로,
프로세스 시작 시 session_id를 1회 생성해 모든 write 계열 tool 호출에 자동 주입한다.
에이전트가 session_id를 직접 들고 다니게 하면 컴팩팅 중 잊어버리는 것이 가장 확실한
실패 모드이므로(설계 문서 §3d), 서버가 상태를 소유하고 vault_tools의 함수들은
session_id를 인자로만 받는 상태 없는 함수로 유지한다.

등록: `devtrail mcp-serve`를 Claude Desktop의 `mcpServers` 설정 또는
`claude mcp add devtrail-vault -- devtrail mcp-serve`로 등록한다.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from app import vault_tools
from app.config import get_settings
from app.services.session_markers import marker_path, read_marker, write_json_atomic

_SESSION_ID = str(uuid4())
_PROCESS_STARTED_AT = datetime.now().isoformat()
_MARKER_LOCK = threading.RLock()

mcp = FastMCP("devtrail-vault")


def _session_marker_path() -> Path:
    """이 MCP 서버 프로세스 전용 marker 경로를 반환한다."""
    return marker_path(Path.cwd(), _SESSION_ID)


def _write_session_marker(
    process_written: bool | None = None, plan_written: bool | None = None
) -> None:
    """이 프로세스 전용 마커를 갱신한다. None인 필드는 기존 값을 보존한다.

    process_written은 Stop 훅(stop-process-check)이, plan_written은 PreToolUse
    훅(plan-check)이 같은 repo의 live MCP 프로세스가 하나일 때만 읽는다.
    """
    with _MARKER_LOCK:
        marker = _session_marker_path()
        existing = read_marker(marker) or {}
        data = {
            "session_id": _SESSION_ID,
            "repo_root": str(Path.cwd().resolve()),
            "pid": os.getpid(),
            "process_started_at": _PROCESS_STARTED_AT,
            "process_written": bool(existing.get("process_written")),
            "plan_written": bool(existing.get("plan_written")),
        }
        if process_written is not None:
            data["process_written"] = process_written
        if plan_written is not None:
            data["plan_written"] = plan_written
        data["updated_at"] = datetime.now().isoformat()
        try:
            write_json_atomic(marker, data)
        except OSError:
            pass  # 훅 연동은 best-effort — 마커 기록 실패로 tool 자체를 막지 않는다


def _touch_session_marker() -> None:
    """tool이 실제로 호출됐을 때 마커를 만든다 — "이 세션에 MCP가 살아 있다"의 증거.

    서버 기동만으로 쓰면 안 되는 이유: `claude mcp list`(devtrail doctor가 내부에서
    부른다)의 헬스체크는 서버를 띄웠다 **즉시 닫는다**. 그 탐침이 남긴
    plan_written=false 마커를 plan-check 훅이 "이번 세션에 MCP가 연결됐다"로 읽으면,
    MCP tool이 없는 세션이 12시간 동안 코드 수정을 차단당한다 — write_work_plan을
    호출할 수단이 없으므로 빠져나갈 방법이 없는 교착이다(2026-09-07 실제 발생).

    탐침은 tool을 호출하지 않으므로, 호출 시점으로 미루면 라이브 세션만 마커를 남긴다.
    마커는 MCP 프로세스별 파일이다. 훅은 repo 안에 최근 갱신된 live MCP marker가
    정확히 하나일 때만 읽으며, 동시에 복수 세션이면 잘못된 상태 강제를 피한다.
    """
    _write_session_marker()


def _candidate_result_dict(result) -> dict | None:
    if result is None:
        return None
    return {"rel_path": result.rel_path, "path": str(result.path), "title": result.spec.title}


@mcp.tool()
def get_project_briefing(project_or_repo: str) -> dict:
    """세션 시작 시 프로젝트 컨텍스트, 최근 handoff, decision, open loops를 반환한다.

    matched=False면 컨텍스트가 주입되지 않은 것이며 candidates에 후보 프로젝트명이
    담긴다 — 사용자에게 확인 후 .claude/vault.json에 저장하도록 안내해야 한다.
    """
    _touch_session_marker()
    result = vault_tools.get_project_briefing(project_or_repo, settings=get_settings())
    return dataclasses.asdict(result)


@mcp.tool()
def search_vault(query: str, limit: int = 10) -> list[dict]:
    """read_scope 안의 노트를 검색한다.

    status=stable(승격된 정본) / candidate(검토 대기 후보) / raw(세션·산출물 원문)이
    함께 반환되며 이 순서로 정렬된다. raw는 근거 조회용이지 확정 지식이 아니다.
    """
    _touch_session_marker()
    hits = vault_tools.search_vault(query, limit=limit, settings=get_settings())
    return [dataclasses.asdict(h) for h in hits]


@mcp.tool()
def read_note(rel_path: str) -> str:
    """scope 안의 노트 전문을 읽는다. scope 밖 경로는 오류를 반환한다.

    읽기 허용: 20_Knowledge/, 30_Projects/, 40_AgentMemory/, 60_Candidates/,
    10_Worklog/, 50_Outputs/, 70_Tasks/.
    """
    _touch_session_marker()
    return vault_tools.read_note(rel_path, settings=get_settings())


@mcp.tool()
def record_note(kind: str, title: str, body: str, project: str = "") -> dict:
    """작업 중 결정/지식/아이디어를 60_Candidates/에 후보로 기록한다.

    kind는 knowledge/decision/blog_idea/career_bullet만 허용한다.
    """
    _touch_session_marker()
    result = vault_tools.record_note(kind, title, body, project=project, settings=get_settings())
    return _candidate_result_dict(result)


@mcp.tool()
def record_agent_improvement(project: str, issue: str, improvement: str, evidence: str = "") -> dict:
    """반복 실수, 개선할 작업 방식, 프로젝트별 주의사항을 MemoryPatch 후보로 기록한다."""
    _touch_session_marker()
    result = vault_tools.record_agent_improvement(project, issue, improvement, evidence, settings=get_settings())
    return _candidate_result_dict(result)


@mcp.tool()
def write_work_plan(project: str, goal: str, context_read: str, scope: str, approach: str, risks: str) -> dict:
    """작업 시작 전, 실제 수정 전에 Plan을 기록한다. session_id는 서버가 자동 주입한다.

    여러 항목이 있는 필드는 한 문단으로 잇지 말고 markdown 불릿/번호 리스트로
    작성한다 — 기록은 사람이 다시 읽는 문서다. 같은 세션에서 재호출하면 기존
    Plan이 갱신된다(새 파일이 생기지 않음).
    """
    _touch_session_marker()
    result = vault_tools.write_work_plan(
        project, goal, context_read, scope, approach, risks, session_id=_SESSION_ID, settings=get_settings()
    )
    _write_session_marker(plan_written=True)
    return _candidate_result_dict(result)


@mcp.tool()
def write_session_process(
    project: str,
    what_changed: str | None = None,
    files_touched: str | None = None,
    project_decisions: dict | None = None,
    implementation_trace: str | None = None,
    agent_execution_notes: dict | None = None,
    docs_update_candidates: str | None = None,
    next_session: str | None = None,
    learning_recovery: dict | None = None,
    append_to: list[str] | None = None,
) -> dict:
    """컴팩팅 전 또는 세션 종료 시 Process를 기록한다. session_id는 서버가 자동 주입한다.

    project_decisions: {decision, reason, alternatives, final_judge}
    agent_execution_notes: {blocked, mistakes, next_checks, better_approach,
        evidence, scope, confidence, requires_user_review}
    learning_recovery: {ai_led, unclear_concepts, questions, related_candidates}

    여러 항목이 있는 필드는 한 문단으로 잇지 말고 markdown 불릿/번호 리스트로
    작성한다. agent_execution_notes 중 next_checks/better_approach만 Lessons 패치
    후보로 증류되므로, 이 두 필드는 다른 세션에도 통하는 일반화된 교훈으로 쓴다.

    **첫 호출**은 전체를 넘긴다(최소한 what_changed는 필요).

    **이어서 작업이 생겼을 때(커밋 발생 등)는 바뀐 필드만 넘긴다.** 생략한 필드는
    기존 기록이 그대로 유지되므로 Process 전체를 다시 쓸 필요가 없다. 기존 내용 뒤에
    이어붙이려면 `append_to`에 필드 이름을 준다:

        write_session_process(
            project="X",
            what_changed="5. PR #58 머지 후 브랜치 정리",
            next_session="1. ...",          # 교체
            append_to=["what_changed"],      # 이어붙임
        )
    """
    _touch_session_marker()
    result = vault_tools.write_session_process(
        project=project,
        what_changed=what_changed,
        files_touched=files_touched,
        project_decisions=project_decisions,
        implementation_trace=implementation_trace,
        agent_execution_notes=agent_execution_notes,
        docs_update_candidates=docs_update_candidates,
        next_session=next_session,
        learning_recovery=learning_recovery,
        session_id=_SESSION_ID,
        append_to=append_to,
        settings=get_settings(),
    )
    _write_session_marker(process_written=True)
    return {
        "session_id": result.session_id,
        "process": _candidate_result_dict(result.process),
        "worklog_rel_path": result.worklog_rel_path,
        "decision": _candidate_result_dict(result.decision),
        "memory_patch": _candidate_result_dict(result.memory_patch),
    }


def main() -> None:
    # 마커는 여기서 쓰지 않는다. 기동만으로 쓰면 `claude mcp list`의 헬스체크(서버를
    # 띄웠다 즉시 닫는다)까지 라이브 세션으로 기록돼, MCP tool이 없는 세션이 plan-check
    # 훅에 갇힌다 — 자세한 이유는 _touch_session_marker() 참고. 마커는 첫 tool 호출이
    # 만든다.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
