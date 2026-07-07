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
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from app import vault_tools
from app.config import get_settings

_SESSION_ID = str(uuid4())

mcp = FastMCP("devtrail-vault")


def _session_marker_path() -> Path:
    """Tier 1 SessionStart/Stop 훅이 참조할 마커 파일 경로.

    이 저장소의 .claude/settings.json에는 아직 등록하지 않았다(사용자 결정) — 훅
    스크립트만 scripts/hooks/에 준비해두고, 등록 여부는 사람이 판단한다.
    """
    return Path.cwd() / ".claude" / ".vault-mcp" / "current_session.json"


def _write_session_marker(process_written: bool) -> None:
    marker = _session_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "session_id": _SESSION_ID,
                    "process_written": process_written,
                    "updated_at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # 훅 연동은 best-effort — 마커 기록 실패로 tool 자체를 막지 않는다


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
    result = vault_tools.get_project_briefing(project_or_repo, settings=get_settings())
    return dataclasses.asdict(result)


@mcp.tool()
def search_vault(query: str, limit: int = 10) -> list[dict]:
    """read_scope 안의 노트를 검색하고 status=stable/candidate를 함께 반환한다."""
    hits = vault_tools.search_vault(query, limit=limit, settings=get_settings())
    return [dataclasses.asdict(h) for h in hits]


@mcp.tool()
def read_note(rel_path: str) -> str:
    """scope 안의 노트 전문을 읽는다. scope 밖 경로는 오류를 반환한다."""
    return vault_tools.read_note(rel_path, settings=get_settings())


@mcp.tool()
def record_note(kind: str, title: str, body: str, project: str = "") -> dict:
    """작업 중 결정/지식/아이디어를 60_Candidates/에 후보로 기록한다.

    kind는 knowledge/decision/blog_idea/career_bullet만 허용한다.
    """
    result = vault_tools.record_note(kind, title, body, project=project, settings=get_settings())
    return _candidate_result_dict(result)


@mcp.tool()
def record_agent_improvement(project: str, issue: str, improvement: str, evidence: str = "") -> dict:
    """반복 실수, 개선할 작업 방식, 프로젝트별 주의사항을 MemoryPatch 후보로 기록한다."""
    result = vault_tools.record_agent_improvement(project, issue, improvement, evidence, settings=get_settings())
    return _candidate_result_dict(result)


@mcp.tool()
def write_work_plan(project: str, goal: str, context_read: str, scope: str, approach: str, risks: str) -> dict:
    """작업 시작 전, 실제 수정 전에 Plan을 기록한다. session_id는 서버가 자동 주입한다.

    여러 항목이 있는 필드는 한 문단으로 잇지 말고 markdown 불릿/번호 리스트로
    작성한다 — 기록은 사람이 다시 읽는 문서다. 같은 세션에서 재호출하면 기존
    Plan이 갱신된다(새 파일이 생기지 않음).
    """
    result = vault_tools.write_work_plan(
        project, goal, context_read, scope, approach, risks, session_id=_SESSION_ID, settings=get_settings()
    )
    return _candidate_result_dict(result)


@mcp.tool()
def write_session_process(
    project: str,
    what_changed: str,
    files_touched: str,
    project_decisions: dict,
    implementation_trace: str,
    agent_execution_notes: dict,
    docs_update_candidates: str,
    next_session: str,
    learning_recovery: dict,
) -> dict:
    """컴팩팅 전 또는 세션 종료 시 Process를 기록한다. session_id는 서버가 자동 주입한다.

    project_decisions: {decision, reason, alternatives, final_judge}
    agent_execution_notes: {blocked, mistakes, next_checks, better_approach,
        evidence, scope, confidence, requires_user_review}
    learning_recovery: {ai_led, unclear_concepts, questions, related_candidates}

    여러 항목이 있는 필드는 한 문단으로 잇지 말고 markdown 불릿/번호 리스트로
    작성한다. 기록 후 작업이 더 이어졌다면(커밋 발생) 세션을 끝내기 전에 이 tool을
    다시 호출한다 — 같은 세션 기록(Process/워크로그)이 새 파일 없이 갱신된다.
    agent_execution_notes 중 next_checks/better_approach만 Lessons 패치 후보로
    증류되므로, 이 두 필드는 다른 세션에도 통하는 일반화된 교훈으로 쓴다.
    """
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
    # 모듈 import 시점이 아니라 서버가 실제로 시작될 때만 마커를 (재)생성한다 —
    # import만으로 마커가 생기면(REPL, 향후 eager import 등) 라이브 세션의 진짜
    # 마커를 덮어쓸 수 있다.
    _write_session_marker(process_written=False)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
