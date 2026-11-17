"""structured project briefing (get_project_briefing(structured=True)) 계약 테스트.

기본 briefing 회귀는 tests/test_vault_tools.py가 맡는다. 여기서는 structured 응답의
구분·근거 위치·예산·생략·식별 한계를 고정 fixture vault로 검사한다.
"""

from __future__ import annotations

import errno
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import vault_tools
from app.services import project_briefing as pb
from app.services.vault_source import content_version, split_source_lines

TODAY = datetime.now().strftime("%Y-%m-%d")
FOLLOW_UP_UNKNOWN_TEXT = "후속 작업 유무를 확인하지 못한 기록 있음"


def _settings(vault: Path, project_map: str = ""):
    return SimpleNamespace(obsidian_vault_root=str(vault), devtrail_project_map=project_map, git_diff_max_chars=800)


def _w(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _fm(**meta) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in meta.items()) + "---\n"


def _ctx(vault: Path, body: str, project: str = "Devtrail", updated_at: str = TODAY, folder: str = "") -> Path:
    return _w(vault, f"30_Projects/{folder or project}/Context.md",
              _fm(type="project_context", project=project, status="active", updated_at=updated_at) + body)


def _handoff(vault: Path, name: str, kind: str, sid: str, at: str, body: str, project: str = "Devtrail",
             updated_at: str = "") -> Path:
    meta = dict(type="candidate", candidate_type="session_handoff", title=name, project=project, status="candidate",
                created_at=at, handoff_type=kind, session_id=sid, host="mini", agent="claude-code")
    if updated_at:
        meta["updated_at"] = updated_at
    return _w(vault, f"60_Candidates/SessionHandoffs/{project}/{name}.md", _fm(**meta) + body)


def _process(next_session: str, what_changed: str = "- 변경 기록") -> str:
    return f"# Process\n\n## What Changed\n\n{what_changed}\n\n## Next Session\n\n{next_session}\n"


def _brief(vault: Path, project: str = "Devtrail", **kw) -> dict:
    return vault_tools.get_structured_project_briefing(project, settings=_settings(vault, **kw))


def _section(resp: dict, key: str) -> dict:
    return next(s for s in resp["sections"] if s["key"] == key)


def _items(resp: dict, key: str) -> list[dict]:
    return _section(resp, key)["items"]


def _file_lines(vault: Path, rel: str) -> list[str]:
    return split_source_lines((vault / rel).read_bytes().decode("utf-8").lstrip("﻿"))[0]


def _mcp_read_note(monkeypatch, vault: Path, read: dict):
    """omissions/requires_read의 read 인자를 **그대로** MCP read_note tool 함수에 넘긴다 (인자 이름·추가 필드 검사)."""
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "get_settings", lambda: _settings(vault))
    monkeypatch.setattr(mcp_server, "_touch_session_marker", lambda: None)
    return mcp_server.mcp._tool_manager.get_tool("read_note").fn(**read)


def _all_items(resp: dict) -> list[dict]:
    return [i for s in resp["sections"] if s["key"] != "gaps" for i in s["items"]]


TEMPLATE_CONTEXT = (
    "\n# Devtrail — Project Context\n\n"
    "> 이 파일은 `get_project_briefing`이 세션 시작 시 자동 주입하는 프로젝트 정본 컨텍스트다.\n"
    "> 배경·목표·제약이 바뀔 때마다 갱신한다.\n\n"
    "## 배경\n\n_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_\n\n"
    "## 목표\n\n- \n\n"
    "## 제약 / 원칙\n\n- 사용자의 결정이 필요한 부분은 진행하지 말고 질문한다\n\n"
    "## 관련 문서\n\n- 구현 계획: [[Plans/]]\n"
)


# ── AC-1: 기본 호출 유지 + structured 스키마 ─────────────────────────────────


def test_default_briefing_keys_and_text_unchanged_by_structured_option(tmp_path):
    from app import mcp_server

    _ctx(tmp_path, TEMPLATE_CONTEXT)
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
    s = _settings(tmp_path)
    legacy = vault_tools.get_project_briefing("Devtrail", settings=s)
    tool = mcp_server.mcp._tool_manager.get_tool("get_project_briefing").fn
    mcp_server.get_settings = lambda: s  # type: ignore[assignment]
    try:
        default = tool(project_or_repo="Devtrail")
        explicit_false = tool(project_or_repo="Devtrail", structured=False)
        structured = tool(project_or_repo="Devtrail", structured=True)
    finally:
        from app.config import get_settings

        mcp_server.get_settings = get_settings  # type: ignore[assignment]
    assert set(default) == {"project", "matched", "candidates", "text", "source_refs"}
    assert default == explicit_false
    assert default["text"] == legacy.text and default["source_refs"] == legacy.source_refs
    for key in ("schema_version", "generated_at", "matching", "sections", "omissions", "warnings", "partial",
                "critical_omission", "requires_read", "sources", "text", "budget"):
        assert key in structured, key
    assert structured["schema_version"] == pb.SCHEMA_VERSION
    datetime.fromisoformat(structured["generated_at"])
    assert [s["key"] for s in structured["sections"]] == list(pb.DISPLAY_ORDER)
    # structured도 기본 호출의 키를 모두 갖는다 — 같은 뜻(확정 프로젝트·후보·사용한 문서 경로)
    assert set(default) <= set(structured)
    assert structured["project"] == default["project"] and structured["matched"] is True
    assert structured["candidates"] == []
    assert structured["source_refs"] == [s["path"] for s in structured["sources"] if "excluded" not in s]
    assert set(default["source_refs"]) <= set(structured["source_refs"])


# ── AC-2: 구분·정리·보존 ─────────────────────────────────────────────────────


def test_sections_are_separated_by_explicit_headings_only(tmp_path):
    _ctx(tmp_path, "# Devtrail\n\n## 배경\n\n지식 OS다.\n\n## 제약\n\n- 공식 영역 직접 쓰기 금지\n\n"
                   "## 운영 메모\n\n- 반드시 dev 브랜치에서만 작업한다\n")
    _handoff(tmp_path, "plan1", "plan", "s1", "2026-11-10T09:00:00", "# Plan\n\n## Goal\n\n- 목표 G\n")
    _handoff(tmp_path, "proc1", "process", "s1", "2026-11-10T10:00:00", _process("- 후속 N", "- 결과 W"))
    resp = _brief(tmp_path)
    constraints = _items(resp, "constraints")
    assert [i["label"] for i in constraints] == ["제약"]
    # 제약성 문장이라도 제목이 제약이 아니면 맥락으로 남긴다 (내용을 읽고 분류하지 않는다)
    ctx_labels = [i["label"] for i in _items(resp, "context")]
    assert "운영 메모" in ctx_labels and "배경" in ctx_labels
    recent = _items(resp, "recent")
    assert {i["kind"] for i in recent} == {"session_result", "plan_goal"}
    follow = _items(resp, "follow_ups")
    assert [i["kind"] for i in follow] == ["next_session"]
    assert "목표 G" not in json.dumps(follow, ensure_ascii=False)  # Plan Goal은 후속 항목이 아니다
    assert "목표 G" in resp["text"]
    text = resp["text"]
    assert text.index("## 1. 제약") < text.index("## 2. 프로젝트 맥락") < text.index("## 3. 기록된 최근 결과·결정") \
        < text.index("## 4. 명시적 후속 항목") < text.index("## 5. 정보 부족·경고·근거")


def test_known_scaffolding_and_repeated_titles_are_cleaned_but_real_content_kept(tmp_path):
    body = TEMPLATE_CONTEXT + "\n## 아무도 모르는 제목\n\n_(직접 쓴 괄호 메모)_\n- 실제 내용\n"
    _ctx(tmp_path, body)
    resp = _brief(tmp_path)
    text = resp["text"]
    for scaffold in ("이 파일은 `get_project_briefing`이", "배경·목표·제약이 바뀔 때마다", "왜 존재하는지",
                     "# Devtrail — Project Context"):
        assert scaffold not in text
    # 템플릿이 넣는 실제 제약 문장·모르는 제목과 그 아래 내용(템플릿과 비슷한 형식 포함)은 지우지 않는다
    assert "- 사용자의 결정이 필요한 부분은 진행하지 말고 질문한다" in text
    assert "## 아무도 모르는 제목" in text and "_(직접 쓴 괄호 메모)_" in text and "- 실제 내용" in text
    assert "- 구현 계획: [[Plans/]]" in text
    cleaned = {c["heading"] for c in _section(resp, "context")["cleaned_sections"]}
    assert {"배경", "목표"} <= cleaned  # 빈 틀뿐인 절은 정리 목록으로 드러난다


def test_cleanup_keeps_code_fence_lines_and_repeated_process_headings(tmp_path):
    _ctx(tmp_path, "## 배경\n\n```bash\n# 주석은 제목이 아니다\n- \n```\n")
    _handoff(tmp_path, "proc", "process", "s1", "2026-11-10T10:00:00", _process("- 할 일"))
    resp = _brief(tmp_path)
    ctx = _items(resp, "context")[0]
    joined = "\n".join(seg["text"] for seg in ctx["segments"])
    assert "# 주석은 제목이 아니다" in joined and "\n- \n" in joined
    nxt = _items(resp, "follow_ups")[0]
    assert nxt["segments"][0]["text"] == "- 할 일"  # '## Next Session' 반복 제목은 항목 이름으로만 남긴다
    assert any(c["reason"] == "repeated_title" for c in nxt["cleaned"])


# ── AC-3: 창·정렬·귀속 ───────────────────────────────────────────────────────


def test_recent_windows_and_order_match_default_briefing(tmp_path):
    _ctx(tmp_path, "## 배경\n\n배경\n")
    for i in range(7):
        _w(tmp_path, f"30_Projects/Devtrail/Decisions/d{i}.md",
           _fm(title=f"결정{i}", project="Devtrail", status="accepted", created_at=f"2026-10-0{i + 1}")
           + f"# 결정{i}\n\n## 결정\n\n결정 내용 {i}\n")
    _w(tmp_path, "60_Candidates/Decisions/c1.md",
       _fm(title="후보 결정", project="Devtrail", status="candidate", candidate_type="decision",
           created_at="2026-10-05T12:00:00", summary="후보 요약 한 줄") + "# 후보 결정\n\n본문\n")
    entries = [("s0", "2026-09-01T09:00:00", "2026-09-24T12:00:00"), ("s1", "2026-09-24T11:00:00", ""),
               ("s2", "2026-09-24T10:00:00", ""), ("s3", "2026-09-24T09:00:00", "")]
    for sid, created, updated in entries:
        _handoff(tmp_path, f"plan-{sid}", "plan", sid, created, "# Plan\n\n## Goal\n\n- goal\n")
        _handoff(tmp_path, f"process-{sid}", "process", sid, created, _process(f"- NEXT_{sid}"), updated_at=updated)
    resp = _brief(tmp_path)
    recent = _section(resp, "recent")
    expected_decisions = vault_tools.get_decisions("Devtrail", limit=5, settings=_settings(tmp_path))
    assert [d["path"] for d in recent["decisions"]] == [d["rel_path"] for d in expected_decisions]
    assert len(recent["decisions"]) == 5
    statuses = {d["path"]: d["status"] for d in recent["decisions"]}
    assert statuses["60_Candidates/Decisions/c1.md"] == "candidate"
    cand = next(i for i in recent["items"] if i["path"] == "60_Candidates/Decisions/c1.md")
    assert cand["decision_status"] == "candidate" and cand["record_tier"] == "candidate"
    assert cand["excerpt_basis"] == "frontmatter summary" and cand["segments"][0]["text"].startswith("summary:")
    assert cand["recorded_at"] == {"value": "2026-10-05T12:00:00", "source": "meta:created_at"}
    promoted = next(i for i in recent["items"] if i["decision_status"] == "promoted")
    assert promoted["record_tier"] == "stable"
    assert [s["session_id"] for s in recent["sessions"]] == ["s0", "s1", "s2"]
    follow_ids = [i["session_id"] for i in _items(resp, "follow_ups")]
    assert follow_ids == ["s0", "s1", "s2"]
    s0 = next(i for i in _items(resp, "follow_ups") if i["session_id"] == "s0")
    assert s0["recorded_at"] == {"value": "2026-09-24T12:00:00", "source": "meta:updated_at"}


def test_other_project_and_unattributed_material_is_not_injected(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- 우리 제약\n")
    _ctx(tmp_path, "## 제약\n\n- OTHER_CONSTRAINT\n", project="Other")
    _handoff(tmp_path, "other-proc", "process", "o1", "2026-11-12T10:00:00", _process("- OTHER_NEXT"), project="Other")
    _w(tmp_path, "60_Candidates/Decisions/other.md",
       _fm(title="OTHER_DECISION", project="Other", status="candidate", created_at="2026-11-12") + "## 결정\n\nX\n")
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       "# OpenLoops\n\n- GLOBAL_LOOP\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Other"} -->\n## Other\n\n- OTHER_LOOP\n\n'
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n- OWN_LOOP\n\n'
       "<!-- devtrail-memory-patch: {broken -->\n## ???\n\n- BROKEN_LOOP\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       "# Lessons\n\n- GLOBAL_LESSON\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Other"} -->\n- OTHER_LESSON\n')
    resp = _brief(tmp_path)
    dumped = json.dumps(resp, ensure_ascii=False)
    for foreign in ("OTHER_CONSTRAINT", "OTHER_NEXT", "OTHER_DECISION", "OTHER_LOOP", "OTHER_LESSON", "BROKEN_LOOP"):
        assert foreign not in resp["text"], foreign
        assert foreign not in dumped, foreign
    follow = _items(resp, "follow_ups")
    assert [i["segments"][0]["text"] for i in follow] == ["- OWN_LOOP"]
    assert follow[0]["scope"] == "project"
    common = [i for i in _items(resp, "context") if i["scope"] == "common"]
    assert {i["kind"] for i in common} == {"common_open_loops", "lessons"}
    assert all(i["project"] == "" for i in common)
    excluded = _section(resp, "context")["excluded"]
    assert excluded == {"other_project_blocks": 2, "unattributed_blocks": 1}
    gap = next(g for g in _section(resp, "gaps")["items"] if g["code"] == "unattributed_block_excluded")
    assert gap["path"] == "40_AgentMemory/05_OpenLoops.md"


def test_unresolved_identification_injects_nothing(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- HIDDEN_CONSTRAINT\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- HIDDEN_NEXT"))
    repo = tmp_path / "repos" / "Devtrail"
    repo.mkdir(parents=True)
    # 기본 briefing은 디렉터리 이름으로 매칭하지만 structured는 명시적 근거만 쓴다
    legacy = vault_tools.get_project_briefing(str(repo), settings=_settings(tmp_path))
    assert legacy.matched is True
    resp = _brief(tmp_path, str(repo))
    assert resp["matched"] is False and resp["matching"]["status"] == "unresolved"
    assert "이름만으로는 확정하지 않습니다" in resp["matching"]["hint"]
    assert all(not s["items"] for s in resp["sections"] if s["key"] != "gaps")
    assert "HIDDEN_" not in json.dumps(resp, ensure_ascii=False)
    assert any(g["code"] == "project_unresolved" for g in _section(resp, "gaps")["items"])
    assert _section(resp, "follow_ups")["state"] == "not_evaluated"
    # .claude/vault.json으로 명시하면 확정된다
    (repo / ".claude").mkdir()
    (repo / ".claude" / "vault.json").write_text('{"project": "Devtrail"}', encoding="utf-8")
    resp = _brief(tmp_path, str(repo))
    assert resp["matched"] and resp["matching"]["method"] == "local_mapping"


def test_ambiguous_same_name_projects_are_not_merged(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- A\n", project="Dup", folder="dup-a")
    _ctx(tmp_path, "## 제약\n\n- B\n", project="Dup", folder="dup-b")
    resp = _brief(tmp_path, "Dup")
    assert resp["matching"]["status"] == "ambiguous" and len(resp["matching"]["candidates"]) == 2
    assert not _items(resp, "constraints")


# ── AC-4: 후속 항목 ──────────────────────────────────────────────────────────


def test_follow_ups_keep_failures_and_same_name_tasks_without_merging(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p-old", "process", "s-old", "2026-11-01T10:00:00",
             _process("- 배포 재시도 (실패: 권한)", "- 배포 실패"))
    _handoff(tmp_path, "p-mid", "process", "s-mid", "2026-11-02T10:00:00", _process("- 문서 정리", "- 문서 정리"))
    _handoff(tmp_path, "p-new", "process", "s-new", "2026-11-03T10:00:00", _process("- 문서 정리", "- 배포 성공"))
    resp = _brief(tmp_path)
    follow = _items(resp, "follow_ups")
    assert [(i["session_id"], i["segments"][0]["text"]) for i in follow] == [
        ("s-new", "- 문서 정리"), ("s-mid", "- 문서 정리"), ("s-old", "- 배포 재시도 (실패: 권한)")]
    assert all(i["follow_up_state"] == "items" for i in follow)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "has_items"
    assert "완료 여부" in sec["message"]
    assert "resolved" not in json.dumps(follow)  # 해결 상태를 추론해 붙이지 않는다


def test_explicit_none_is_scoped_and_distinct_from_unknown(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-03T10:00:00", _process("없음"))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "none_in_scope" and sec["complete"] is True
    # 확정 설계 #7 문구 그대로 — 완전히 읽었고 명시된 후속 항목이 없을 때
    assert sec["message"].startswith(pb.FOLLOW_UP_NONE) and pb.FOLLOW_UP_UNKNOWN not in sec["message"]
    assert "범위 밖" in sec["message"] and sec["message"] in resp["text"]
    item = sec["items"][0]
    assert item["follow_up_state"] == "explicit_none" and item["segments"][0]["text"] == "없음"
    assert "명시적 없음 — 이 기록 범위 한정" in resp["text"]

    # 빈 틀("- ")은 '없음'이 아니라 확인 불가다
    _handoff(tmp_path, "p0", "process", "s0", "2026-11-02T10:00:00", _process("- "))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and sec["message"].startswith(pb.FOLLOW_UP_UNKNOWN)
    assert pb.FOLLOW_UP_NONE not in sec["message"]
    assert any(s["state"] == "empty" for s in sec["sources_checked"])
    # 빈 틀은 읽기 실패가 아니라 데이터 부족으로 구분한다
    assert sec["unknown_reasons"] == {"read_failed_or_skipped": 0, "partial": False, "data_insufficient": 1,
                                      "no_sessions": False}
    assert any(g["code"] == "follow_up_section_empty" for g in _section(resp, "gaps")["items"])

    # "없음"으로 시작하는 문장은 명시적 없음으로 보지 않는다
    _handoff(tmp_path, "p0", "process", "s0", "2026-11-02T10:00:00", _process("- 없음 — 단 실측 확인은 남음"))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "has_items"


def test_missing_next_session_plan_only_and_no_sessions_are_unknown(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    resp = _brief(tmp_path)
    assert _section(resp, "follow_ups")["state"] == "unknown"
    assert any(g["code"] == "no_sessions" for g in _section(resp, "gaps")["items"])

    _handoff(tmp_path, "plan", "plan", "s1", "2026-11-03T09:00:00", "# Plan\n\n## Goal\n\n- 목표만\n")
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and not sec["items"]
    assert [s["state"] for s in sec["sources_checked"] if s["source"] == "next_session"] == ["no_process"]
    assert any(g["code"] == "orphan_plan" for g in _section(resp, "gaps")["items"])

    _handoff(tmp_path, "proc", "process", "s1", "2026-11-03T10:00:00", "# Process\n\n## What Changed\n\n- x\n")
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and sec["message"].startswith(pb.FOLLOW_UP_UNKNOWN)
    assert [s["state"] for s in sec["sources_checked"] if s["source"] == "next_session"] == ["missing"]
    assert sec["unknown_reasons"]["data_insufficient"] == 1 and sec["unknown_reasons"]["read_failed_or_skipped"] == 0
    assert any(g["code"] == "follow_up_section_missing" for g in _section(resp, "gaps")["items"])


def test_partial_read_failure_makes_follow_ups_unknown_not_none(tmp_path, monkeypatch):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-03T10:00:00", _process("없음"))
    _handoff(tmp_path, "p2", "process", "s2", "2026-11-04T10:00:00", _process("- 숨은 후속"))
    _deny_reads(monkeypatch, tmp_path / "60_Candidates/SessionHandoffs/Devtrail/p2.md")
    resp = _brief(tmp_path)
    assert resp["partial"] is True
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and sec["complete"] is False
    assert sec["message"].startswith(pb.FOLLOW_UP_UNKNOWN) and "partial" in sec["message"]
    assert sec["unknown_reasons"]["partial"] is True and sec["unknown_reasons"]["data_insufficient"] == 0
    assert any(w["code"] == "read_failed" and w["path"].endswith("p2.md") for w in resp["warnings"])
    assert "숨은 후속" not in resp["text"]


def _deny_reads(monkeypatch, *paths: Path) -> None:
    denied = {str(p) for p in paths}
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def guard(self):
        if str(self) in denied or str(self.resolve()) in denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))

    def read_bytes(self):
        guard(self)
        return real_bytes(self)

    def read_text(self, *a, **k):
        guard(self)
        return real_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)


# ── AC-5: 원문 위치·버전·비연속 구간 ─────────────────────────────────────────


def test_every_segment_matches_source_and_rereads_with_expected_version(tmp_path):
    _ctx(tmp_path, TEMPLATE_CONTEXT + "\n## 금지 사항\n\n- 운영 PM 직접 수정 금지\n- \n- 비밀값 커밋 금지\n")
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       '# OpenLoops\n\n<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n'
       "### 실효 확인\n\n- (2026-11-01) 실측\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- 다음"))
    s = _settings(tmp_path)
    resp = vault_tools.get_structured_project_briefing("Devtrail", settings=s)
    versions = {src["path"]: src["source_version"] for src in resp["sources"]}
    non_contiguous = 0
    for item in _all_items(resp):
        lines = _file_lines(tmp_path, item["path"])
        assert item["source_version"] == versions[item["path"]] == content_version((tmp_path / item["path"]).read_bytes())
        if not item["contiguous"]:
            non_contiguous += 1
        prev_end = 0
        for seg in item["segments"]:
            assert seg["start_line"] > prev_end
            prev_end = seg["end_line"]
            assert seg["text"] == "\n".join(lines[seg["start_line"] - 1:seg["end_line"]])
            assert seg["text"] in resp["text"]
            page = vault_tools.read_source(item["path"], start_line=seg["start_line"],
                                           max_lines=seg["end_line"] - seg["start_line"] + 1,
                                           expected_version=item["source_version"], settings=s)
            assert page["ok"] and page["content"] == seg["text"]
    assert non_contiguous >= 1  # 빈 불릿 정리로 끊긴 구간은 여러 구간으로 나뉜다
    banned = next(i for i in _items(resp, "constraints") if i["label"] == "금지 사항")
    assert len(banned["segments"]) == 2 and banned["cleaned"] == [
        {"lines": [banned["segments"][0]["end_line"] + 1] * 2, "reason": "empty_scaffolding"}]
    # 원문이 바뀌면 같은 인자의 다시 읽기가 버전 불일치로 거절된다
    path = tmp_path / banned["path"]
    path.write_bytes(path.read_bytes() + "- 새 줄\n".encode())
    seg = banned["segments"][0]
    page = vault_tools.read_source(banned["path"], start_line=seg["start_line"], max_lines=1,
                                   expected_version=banned["source_version"], settings=s)
    assert not page["ok"] and page["error"]["code"] == "version_mismatch"


def test_crlf_and_bom_sources_keep_line_numbers(tmp_path):
    text = "﻿" + _fm(project="Devtrail", updated_at=TODAY) + "## 제약\r\n\r\n- CRLF 제약\r\n"
    path = tmp_path / "30_Projects/Devtrail/Context.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(text.replace("\n", "\r\n").replace("\r\r\n", "\r\n").encode("utf-8"))
    s = _settings(tmp_path)
    resp = vault_tools.get_structured_project_briefing("Devtrail", settings=s)
    seg = _items(resp, "constraints")[0]["segments"][0]
    page = vault_tools.read_source("30_Projects/Devtrail/Context.md", start_line=seg["start_line"],
                                   max_lines=seg["end_line"] - seg["start_line"] + 1,
                                   expected_version=_items(resp, "constraints")[0]["source_version"], settings=s)
    assert page["content"] == seg["text"] and "- CRLF 제약" in seg["text"] and "\r" not in seg["text"]


# ── AC-6: 예산·생략·판단 한계 ────────────────────────────────────────────────


def test_late_constraint_in_long_context_is_kept_before_context(tmp_path, monkeypatch):
    background = "".join(f"- 배경 기록 {i}: " + "설명 " * 20 + "\n" for i in range(400))  # 약 4만 자
    _ctx(tmp_path, "## 배경\n\n" + background + "\n## 제약\n\n- LATE_CONSTRAINT 공식 영역 직접 쓰기 금지\n")
    # 기본 briefing은 로더 상한(5000자) 때문에 후반 제약이 보이지 않는다 — structured는 보인다
    legacy = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "LATE_CONSTRAINT" not in legacy.text
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert "LATE_CONSTRAINT" in resp["text"]
    assert resp["critical_omission"] is False and resp["requires_read"] == []
    om = next(o for o in resp["omissions"] if o["section"] == "context")
    assert om["critical"] is False and om["reason"] in ("group_cap", "budget")
    lines = _file_lines(tmp_path, om["path"])
    item = next(i for i in _items(resp, "context") if i["id"] == om["item"])
    assert om["lines"][0] == item["segments"][-1]["end_line"] + 1  # 생략은 보여준 줄 바로 다음부터
    page = _mcp_read_note(monkeypatch, tmp_path, om["read"])
    assert page["ok"] and page["start_line"] == om["lines"][0]
    assert page["content"].splitlines()[0] == lines[om["lines"][0] - 1]


def test_constraints_over_budget_raise_critical_omission_with_exact_resume(tmp_path, monkeypatch):
    rules = "".join(f"- 규칙 {i:04d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(300))  # 약 4만 자
    _ctx(tmp_path, "## 원칙\n\n" + rules)
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert resp["critical_omission"] is True and "critical_omission" in resp["text"]
    om = next(o for o in resp["omissions"] if o["critical"])
    assert [r["read"] for r in resp["requires_read"]] == [om["read"]]
    assert resp["requires_read"][0]["lines"] == om["lines"]
    item = _items(resp, "constraints")[0]
    assert item["shown"] == "partial"
    assert om["lines"][0] == item["segments"][-1]["end_line"] + 1 and om["lines"][1] == item["span"][1]
    lines = _file_lines(tmp_path, om["path"])
    # 본문에는 완전한 줄만 — 각 줄이 원문 한 줄과 같다
    shown = set(lines)
    body_lines = [l for l in resp["text"].splitlines() if l.startswith("- 규칙 ")]
    assert body_lines and all(l in shown for l in body_lines)
    assert f"생략 L{om['lines'][0]}-L{om['lines'][1]}" in resp["text"]
    assert om["read"]["max_lines"] == min(400, om["lines"][1] - om["lines"][0] + 1)
    assert set(om["read"]) == {"rel_path", "structured", "start_line", "max_lines", "expected_version"}
    page = _mcp_read_note(monkeypatch, tmp_path, resp["requires_read"][0]["read"])
    assert page["ok"] and page["start_line"] == om["lines"][0]
    assert page["content"].splitlines()[0] == lines[om["lines"][0] - 1]
    assert page["end_line"] == om["lines"][1] or page["next"] is not None  # 남은 구간은 next로 이어진다


def test_overlong_single_line_is_never_cut(tmp_path, monkeypatch):
    giant = "- " + "가" * 30000
    _ctx(tmp_path, "## 제약\n\n" + giant + "\n- 짧은 제약\n")
    long_next = "- " + "나" * 5000
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process(long_next))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert "가" * 100 not in resp["text"] and "나" * 100 not in resp["text"]
    c = next(o for o in resp["omissions"] if o["section"] == "constraints")
    assert c["reason"] == "line_too_long" and c["line_chars"] == len(giant) and c["critical"]
    # 16000자를 넘는 줄은 structured로 받을 수 없다 — 전문 읽기 인자를 준다
    assert c["structured_readable"] is False and c["read"] == {"rel_path": c["path"]}
    full = _mcp_read_note(monkeypatch, tmp_path, c["read"])
    assert giant in full
    n = next(o for o in resp["omissions"] if o["section"] == "follow_ups")
    assert n["reason"] == "line_too_long" and n["structured_readable"] is True
    page = _mcp_read_note(monkeypatch, tmp_path, n["read"])
    assert page["ok"] and page["content"].splitlines()[0] == long_next
    assert resp["critical_omission"] is True


def test_unreadable_context_is_critical_and_partial(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "## 제약\n\n- 못 읽는 제약\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- 다음"))
    _deny_reads(monkeypatch, ctx)
    resp = _brief(tmp_path)
    assert resp["partial"] is True and resp["critical_omission"] is True
    # 등록부가 그 폴더를 못 읽어도 세션 폴더로 프로젝트는 확정된다 — 이때 "Context 없음"으로 숨기지 않는다
    assert resp["matching"]["status"] == "resolved"
    assert _section(resp, "constraints")["state"] == "unknown"
    assert {"path": "30_Projects/Devtrail/Context.md", "reason": "context_unverifiable",
            "read": {"rel_path": "30_Projects/Devtrail/Context.md"}, "unverified": True} in resp["requires_read"]
    assert not any(g["code"] == "no_context" for g in _section(resp, "gaps")["items"])
    assert "못 읽는 제약" not in resp["text"]


def test_empty_vault_and_unregistered_mapping_report_limits(tmp_path):
    resp = _brief(tmp_path)
    assert resp["matched"] is False and resp["partial"] is False
    codes = [g["code"] for g in _section(resp, "gaps")["items"]]
    assert "vault_empty" in codes and "project_unresolved" in codes
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS

    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"projects": {"Ghost": {"aliases": ["ghost-alias"]}}}), encoding="utf-8")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", "# Lessons\n\n- 공통 교훈\n")
    resp = _brief(tmp_path, "ghost-alias", project_map=str(mapping))
    assert resp["matching"]["status"] == "unregistered"
    codes = [g["code"] for g in _section(resp, "gaps")["items"]]
    assert "unregistered" in codes
    assert [i["scope"] for i in _items(resp, "context")] == ["common"]


def test_stale_context_and_memory_are_reported(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n", updated_at="2020-01-01")
    _w(tmp_path, "40_AgentMemory/01_CurrentFocus.md", _fm(updated_at="2020-01-01") + "# Current Focus\n\n- 오래된 초점\n")
    resp = _brief(tmp_path)
    codes = [g["code"] for g in _section(resp, "gaps")["items"]]
    assert "context_stale" in codes and "memory_stale" in codes


def test_response_and_source_metadata_sizes_are_measured(tmp_path):
    _ctx(tmp_path, TEMPLATE_CONTEXT)
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- 다음"))
    resp = _brief(tmp_path)
    b = resp["budget"]
    assert b["text_chars"] == len(resp["text"]) <= b["text_max_chars"] == 20000
    assert b["response_chars"] == len(json.dumps(resp, ensure_ascii=False))
    assert b["sources_meta_chars"] == len(json.dumps(resp["sources"], ensure_ascii=False))
    assert b["budget_order"][0] == "constraint" and b["display_order"][0] == "constraints"


def test_large_response_warns_instead_of_hiding(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "RESPONSE_WARN_CHARS", 1000)
    _ctx(tmp_path, TEMPLATE_CONTEXT)
    resp = _brief(tmp_path)
    assert any(w["code"] == "response_large" for w in resp["warnings"])
    assert resp["budget"]["response_chars"] == len(json.dumps(resp, ensure_ascii=False))


def test_many_unreadable_handoffs_keep_text_under_cap(tmp_path, monkeypatch):
    _ctx(tmp_path, "## 제약\n\n- 제약 하나\n")
    paths = [_handoff(tmp_path, f"p{i:03d}-" + "긴이름" * 10, "process", f"s{i}", "2026-11-10T10:00:00",
                      _process("- x")) for i in range(150)]
    _deny_reads(monkeypatch, *paths)
    resp = _brief(tmp_path)
    assert resp["partial"] is True and len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert "- 제약 하나" in resp["text"]
    assert _section(resp, "follow_ups")["state"] == "unknown"
    assert len(_section(resp, "follow_ups")["sources_checked"]) >= 150


def test_follow_ups_keep_a_location_line_even_when_constraints_fill_budget(tmp_path):
    rules = "".join(f"- 규칙 {i:04d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(300))
    _ctx(tmp_path, "## 원칙\n\n" + rules)
    long_next = "".join(f"- 후속 {k}: " + "설명 " * 30 + "\n" for k in range(40))  # 1500자 상한을 넘는다
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process(long_next))
    resp = _brief(tmp_path)
    assert resp["critical_omission"] is True and len(resp["text"]) <= pb.TEXT_MAX_CHARS
    nxt = _items(resp, "follow_ups")[0]
    # 발췌가 예산 때문에 빠져도 위치는 고정부(후속 기록 위치 목록)에 남는다 — 예약으로 제약 예산을 가져가지 않는다
    assert f"{nxt['id']} 세션 1 next_session · {nxt['path']} L{nxt['span'][0]}-L{nxt['span'][1]}" in resp["text"]
    om = next(o for o in resp["omissions"] if o["item"] == nxt["id"])
    assert om["path"] == nxt["path"] and om["read"]["rel_path"] == nxt["path"]


def test_permission_denied_memory_dir_is_partial_not_crash(tmp_path, deny_access):
    _ctx(tmp_path, "## 제약\n\n- 제약\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n- 숨은 루프\n')
    deny_access.none("40_AgentMemory")
    resp = _brief(tmp_path)
    assert deny_access.hits
    assert resp["partial"] is True and "숨은 루프" not in resp["text"]
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown"  # OpenLoops를 못 읽었으니 '범위 한정 없음'이라고 말할 수 없다
    assert any(s["source"] == "project_open_loops" and s["state"] == "unreadable" for s in sec["sources_checked"])


# ── 독립 리뷰에서 재현된 결함의 회귀 ─────────────────────────────────────────


@pytest.mark.parametrize("marker", [
    "<!-- devtrail-memory-patch: {broken -->",
    '<!-- devtrail-memory-patch: {"scope": "project", "project": "core"} -->',
])
def test_unattributed_open_loops_block_makes_follow_ups_unknown(tmp_path, marker):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _ctx(tmp_path, "## 배경\n\ny\n", project="Other")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"projects": {"Devtrail": {"aliases": ["core"]}, "Other": {"aliases": ["core"]}}}),
                       encoding="utf-8")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", f"# OpenLoops\n\n{marker}\n## ?\n\n- 배포 전 롤백 확인\n")
    resp = _brief(tmp_path, project_map=str(mapping))
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and sec["complete"] is False
    assert any(s["state"] == "unattributed" for s in sec["sources_checked"])
    assert "롤백 확인" not in resp["text"]


def test_scaffold_only_open_loops_block_is_unknown_but_emptied_block_is_none(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))
    marker = '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n'
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", f"# OpenLoops\n\n{marker}\n- \n")
    assert _section(_brief(tmp_path), "follow_ups")["state"] == "unknown"
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", f"# OpenLoops\n\n{marker}")
    assert _section(_brief(tmp_path), "follow_ups")["state"] == "none_in_scope"


def test_long_fixed_parts_never_exceed_text_cap(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- 제약 하나\n")
    _w(tmp_path, "30_Projects/Devtrail/Decisions/huge.md",
       _fm(title="긴" * 21000, project="Devtrail", status="accepted", created_at="2026-11-01") + "본문\n")
    for i in range(260):
        _handoff(tmp_path, f"plan-{i:03d}", "plan", "same", f"2026-11-01T10:{i % 60:02d}:00", "# Plan\n\n## Scope\n\nx\n")
    _handoff(tmp_path, "proc-long", "process", "s" * 20500, "2026-11-02T10:00:00", _process("- 다음"))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert "- 제약 하나" in resp["text"]


def test_unlistable_decision_and_handoff_folders_are_partial_not_empty(tmp_path, deny_access):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _w(tmp_path, "30_Projects/Devtrail/Decisions/d.md", _fm(title="숨은 결정", project="Devtrail") + "## 결정\n\nX\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- 숨은 후속"))
    deny_access.none("30_Projects/Devtrail/Decisions")
    deny_access.none("60_Candidates/SessionHandoffs/Devtrail")
    resp = _brief(tmp_path)
    assert deny_access.hits and resp["partial"] is True
    codes = [g["code"] for g in _section(resp, "gaps")["items"]]
    assert "decisions_unverifiable" in codes and "sessions_unverifiable" in codes
    assert "no_decisions" not in codes and "no_sessions" not in codes
    assert _section(resp, "follow_ups")["state"] == "unknown"
    assert sum(w["code"] == "read_failed" for w in resp["warnings"]) >= 2


def test_deep_constraint_heading_is_a_constraint_and_unclosed_fence_is_reported(tmp_path):
    memo = "".join(f"- 구현 메모 {i}: " + "설명 " * 30 + "\n" for i in range(80))
    _ctx(tmp_path, "## 구현 메모\n\n" + memo + "\n#### 금지\n\n- prod DB에 직접 쓰기 금지\n\n#### 기타\n\n- 그 밖의 메모\n")
    resp = _brief(tmp_path)
    c = _items(resp, "constraints")
    assert [i["label"] for i in c] == ["금지"] and "- prod DB에 직접 쓰기 금지" in resp["text"]
    assert "그 밖의 메모" not in json.dumps(c, ensure_ascii=False)  # 같은 단계의 다음 제목에서 제약 절이 끝난다
    _ctx(tmp_path, "## 배경\n\n```\n코드\n\n## 제약\n\n- 펜스 뒤 제약\n")
    resp = _brief(tmp_path)
    assert any(g["code"] == "unclosed_code_fence" for g in _section(resp, "gaps")["items"])


def test_promoted_decisions_are_read_from_the_actual_context_folder(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n", folder="devtrail-dir")
    _w(tmp_path, "30_Projects/devtrail-dir/Decisions/d.md",
       _fm(title="폴더 결정", project="Devtrail", status="accepted", created_at="2026-11-01") + "## 결정\n\n폴더 안 결정\n")
    resp = _brief(tmp_path)
    assert [d["title"] for d in _section(resp, "recent")["decisions"]] == ["폴더 결정"]
    assert "폴더 안 결정" in resp["text"]
    # 기본 briefing의 결정 조회(project_dir 없음)는 그대로다
    assert vault_tools._list_decisions(tmp_path, "Devtrail") == []


def test_append_files_keep_newest_lines_inside_one_block(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    lessons = "".join(f"- (2026-10-{i % 28 + 1:02d}) 교훈 {i:02d}: " + "설명 " * 60 + "\n" for i in range(40))
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", "# Lessons\n\n" + lessons)
    resp = _brief(tmp_path)
    item = next(i for i in _items(resp, "context") if i["kind"] == "lessons")
    om = next(o for o in resp["omissions"] if o["item"] == item["id"])
    assert item["segments"][-1]["text"].splitlines()[-1].startswith("- (2026-10-12) 교훈 39")
    assert om["lines"][0] == 3 and om["lines"][1] == item["segments"][0]["start_line"] - 1
    text = resp["text"]
    assert text.index(f"생략 L{om['lines'][0]}-L{om['lines'][1]}") < text.index("교훈 39")


# ── 병합 리뷰 지적 회귀: 읽기 경계 밖 메타데이터, 펜스 규칙, 이어읽기 인자 ──────


def test_links_outside_read_boundary_are_never_opened_or_described(tmp_path, monkeypatch):
    _ctx(tmp_path, "## 제약\n\n- 우리 제약\n")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    secret_decision = outside / "decision.md"
    secret_decision.write_text(_fm(title="OUTSIDE_TITLE", project="Devtrail", status="candidate",
                                   created_at="2099-01-01", summary="OUTSIDE_SUMMARY") + "## 결정\n\nOUTSIDE_BODY\n",
                               encoding="utf-8")
    secret_handoff = outside / "handoff.md"
    secret_handoff.write_text(_fm(title="OUTSIDE_HANDOFF", project="Devtrail", handoff_type="process",
                                  session_id="OUTSIDE_SID", host="OUTSIDE_HOST", created_at="2099-01-01T00:00:00")
                              + _process("- OUTSIDE_NEXT"), encoding="utf-8")
    links = {
        "60_Candidates/Decisions/link.md": secret_decision,
        "30_Projects/Devtrail/Decisions/link.md": secret_decision,
        "60_Candidates/SessionHandoffs/Devtrail/link.md": secret_handoff,
    }
    for rel, target in links.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).symlink_to(target)
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))

    opened: list[str] = []
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def read_bytes(self):
        opened.append(str(Path(self).resolve()))
        return real_bytes(self)

    def read_text(self, *a, **k):
        opened.append(str(Path(self).resolve()))
        return real_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    resp = _brief(tmp_path)
    dumped = json.dumps(resp, ensure_ascii=False)
    assert "OUTSIDE" not in dumped
    assert str(secret_decision) not in opened and str(secret_handoff) not in opened
    skipped = {w["path"] for w in resp["warnings"] if w["code"] == "link_skipped"}
    # 공유 후보 폴더의 링크는 소속을 모르므로 파일명 없이 폴더 경로·건수로만 남는다
    assert skipped == {"30_Projects/Devtrail/Decisions/link.md", "60_Candidates/SessionHandoffs/Devtrail/link.md",
                       "60_Candidates/Decisions/"}
    shared = next(w for w in resp["warnings"] if w["path"] == "60_Candidates/Decisions/")
    assert shared["count"] == 1 and shared["attribution"] == "unverified"
    assert "60_Candidates/Decisions/link.md" not in dumped
    # 건너뛴 세션 링크가 있으니 '없음'이라고 단정하지 않는다
    assert _section(resp, "follow_ups")["state"] == "unknown"
    # 기본 briefing은 그대로다 (링크를 따라 읽는 기존 동작은 바꾸지 않았다)
    legacy = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "OUTSIDE_TITLE" in legacy.text


def test_attribution_failures_expose_only_path_and_state(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- 우리 제약\n")
    _ctx(tmp_path, "## 배경\n\n다른 프로젝트\n", project="Other")
    _w(tmp_path, "30_Projects/Devtrail/Decisions/foreign.md",
       _fm(title="FOREIGN_TITLE", project="Other", status="accepted", created_at="2099-01-01") + "## 결정\n\nFOREIGN_BODY\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Devtrail/foreign.md",
       _fm(title="FOREIGN_HANDOFF", project="Other", handoff_type="process", session_id="FOREIGN_SID",
           host="FOREIGN_HOST", agent="FOREIGN_AGENT", created_at="2099-01-01T00:00:00") + _process("- FOREIGN_NEXT"))
    resp = _brief(tmp_path)
    assert "FOREIGN" not in json.dumps(resp, ensure_ascii=False)
    recent = _section(resp, "recent")
    assert {"path": "30_Projects/Devtrail/Decisions/foreign.md", "status": "promoted", "item": None,
            "state": "attribution_mismatch"} in recent["decisions"]
    session = recent["sessions"][0]
    assert session["session_id"] is None and session["host"] is None
    assert session["handoffs"] == [{"path": "60_Candidates/SessionHandoffs/Devtrail/foreign.md", "items": [],
                                    "state": "attribution_mismatch"}]
    assert _section(resp, "follow_ups")["state"] == "unknown"


@pytest.mark.parametrize("block", [
    "~~~markdown\n```\n# 안쪽 제목\n~~~\n",           # 다른 종류 펜스는 닫지 않는다
    "````\n```\n# 안쪽 제목\n````\n",                 # 여는 길이보다 짧은 펜스는 닫지 않는다
    "```python\n# 안쪽 제목\n``` 정보\n```\n",          # 정보 문자열이 붙은 펜스는 닫는 펜스가 아니다
    "    ```\n    # 들여쓴 코드\n",                     # 4칸 들여쓴 줄은 펜스가 아니다
])
def test_fence_rules_keep_real_constraint_heading_after_code_block(tmp_path, block):
    _ctx(tmp_path, "## 배경\n\n" + block + "\n## 제약\n\n- FENCE_AFTER_CONSTRAINT\n")
    resp = _brief(tmp_path)
    assert [i["label"] for i in _items(resp, "constraints")] == ["제약"]
    assert "- FENCE_AFTER_CONSTRAINT" in resp["text"]
    assert not any(g["code"] == "unclosed_code_fence" for g in _section(resp, "gaps")["items"])
    ctx = _items(resp, "context")[0]
    assert "# 안쪽 제목" in "\n".join(seg["text"] for seg in ctx["segments"]) or "들여쓴" in block


def test_late_constraint_after_mixed_fence_in_long_context_is_critical_or_kept(tmp_path):
    memo = "".join(f"- 메모 {i}: " + "설명 " * 30 + "\n" for i in range(120))
    _ctx(tmp_path, "## 배경\n\n~~~markdown\n```\n~~~\n\n" + memo + "\n## 제약\n\n- LATE_FENCED_CONSTRAINT\n")
    resp = _brief(tmp_path)
    assert "- LATE_FENCED_CONSTRAINT" in resp["text"]
    assert _section(resp, "constraints")["state"] == "items"


# ── 병합 리뷰 2차 지적 회귀: 블록 밖 제목, 중첩 제약 범위 ─────────────────────


@pytest.mark.parametrize("rel", ["40_AgentMemory/06_Lessons.md", "40_AgentMemory/01_CurrentFocus.md",
                                 "40_AgentMemory/05_OpenLoops.md"])
def test_title_line_inside_other_project_block_is_replaced_by_file_name(tmp_path, rel):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _ctx(tmp_path, "## 배경\n\ny\n", project="Other")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))
    _w(tmp_path, rel, _fm(updated_at="2020-01-01")
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Other"} -->\n# PRIVATE_OTHER_TITLE\n\n- 남의 내용\n\n'
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n- 우리 내용\n')
    resp = _brief(tmp_path)
    dumped = json.dumps(resp, ensure_ascii=False)
    assert "PRIVATE_OTHER_TITLE" not in dumped and "남의 내용" not in dumped
    stem = Path(rel).stem
    assert next(s for s in resp["sources"] if s["path"] == rel)["title"] == stem
    assert any(g["code"] == "memory_stale" and g["message"].startswith(stem)
               for g in _section(resp, "gaps")["items"]) or rel.endswith("06_Lessons.md")
    assert "- 우리 내용" in resp["text"]


def test_title_line_in_common_or_own_block_is_kept(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       "# 공통 교훈 제목\n\n- 공통\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n- 우리 교훈\n')
    resp = _brief(tmp_path)
    assert next(s for s in resp["sources"] if s["path"] == "40_AgentMemory/06_Lessons.md")["title"] == "공통 교훈 제목"


def test_nested_deep_constraint_scope_ends_at_sibling_heading(tmp_path):
    _ctx(tmp_path, "## 구현 메모\n\n- 메모\n\n#### 제약\n\n- 깊은 제약\n\n##### 금지\n\n- 금지 항목\n\n"
                   "##### 세부 설명\n\n- 제약 설명\n\n#### 결과\n\n- 작업 성공\n\n###### 결과 세부\n\n- 결과 세부 내용\n")
    resp = _brief(tmp_path)
    constraint_text = "\n".join(seg["text"] for i in _items(resp, "constraints") for seg in i["segments"])
    for kept in ("- 깊은 제약", "- 금지 항목", "- 제약 설명"):
        assert kept in constraint_text
    assert "작업 성공" not in constraint_text and "결과 세부" not in constraint_text
    context_text = "\n".join(seg["text"] for i in _items(resp, "context") for seg in i["segments"])
    assert "- 작업 성공" in context_text and "- 결과 세부 내용" in context_text and "- 메모" in context_text
    labels = {i["label"]: i["kind"] for i in _all_items(resp)}
    assert labels["제약"] == "constraint" and labels["결과"] == "context_section"


def test_constraint_inheritance_uses_all_headings_not_only_item_starts(tmp_path):
    # ## 원칙 아래 #### 하위는 제약(상속)이고, 다음 ## 배경부터는 맥락이다
    _ctx(tmp_path, "## 원칙\n\n- 원칙 하나\n\n#### 하위 세부\n\n- 상속된 제약\n\n## 배경\n\n#### 배경 하위\n\n- 배경 세부\n")
    resp = _brief(tmp_path)
    constraint_text = "\n".join(seg["text"] for i in _items(resp, "constraints") for seg in i["segments"])
    assert "- 상속된 제약" in constraint_text and "배경 세부" not in constraint_text
    assert [i["label"] for i in _items(resp, "constraints")] == ["원칙"]


def test_context_blocks_unit():
    heads = [(1, 2, "메모"), (3, 4, "제약"), (5, 5, "금지"), (7, 5, "세부 설명"), (9, 4, "결과"), (11, 6, "결과 세부"),
             (13, 2, "규칙"), (15, 3, "하위")]
    assert pb._context_blocks(heads) == [
        (1, 2, "메모", False), (3, 4, "제약", True), (9, 4, "결과", False), (13, 2, "규칙", True), (15, 3, "하위", True)]


# ── 확정 설계 #7: 표시 순서와 예산 배정 순서 ─────────────────────────────────


def test_display_and_budget_orders_follow_design_7():
    assert pb.DISPLAY_ORDER == ("constraints", "context", "recent", "follow_ups", "gaps")
    assert [k for k, _ in pb.BUDGET_STAGES] == ["constraints", "context", "follow_ups", "recent"]
    assert [g for _, gs in pb.BUDGET_STAGES for g in gs] == list(pb.BUDGET_ORDER)
    assert set(pb.BUDGET_ORDER) == set(pb.GROUP_CAPS) == set(pb.ITEM_CAPS)
    # 묶음이 속한 갈래와 예산 단계가 같다 — Plan Goal·결정·What Changed는 후속 항목이 아니라 최근 결과·결정 단계다
    stage_of = {g: k for k, gs in pb.BUDGET_STAGES for g in gs}
    assert stage_of["plan_goal"] == stage_of["decision"] == stage_of["session_result"] == "recent"
    assert stage_of["next_session"] == stage_of["project_open_loops"] == "follow_ups"
    assert stage_of["common_open_loops"] == "context"  # 공통 OpenLoops는 이 프로젝트 후속 항목이 아니다


def _order_vault(tmp_path):
    """제약 + 맥락(Context 6천 자대·CurrentFocus·Lessons) + 후속 3세션 + 결정 5건 + What Changed 3세션이 20000자를 조금 넘는다."""
    _ctx(tmp_path, "## 제약\n\n- ORDER_CONSTRAINT 공식 영역 직접 쓰기 금지\n\n## 배경\n\n"
         + "".join(f"- CTX_LINE {i}: " + "맥락 설명 " * 18 + "\n" for i in range(50)))
    mk = '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
    _w(tmp_path, "40_AgentMemory/01_CurrentFocus.md",
       "# Current Focus\n\n" + mk + "".join(f"- FOCUS_{k}: " + "초점 " * 30 + "\n" for k in range(10)))
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       "# Lessons\n\n" + "".join(mk + f"- LESSON_{k}: " + "교훈 " * 40 + "\n\n" for k in range(14)))
    for r in range(3):
        sid = f"s{r}"
        nxt = "".join(f"- NEXT_{sid}_{k}: " + "후속 " * 30 + "\n" for k in range(6))
        wc = "".join(f"- WC_{sid}_{k}: " + "결과 " * 35 + "\n" for k in range(10))
        _handoff(tmp_path, f"proc-{sid}", "process", sid, f"2026-11-1{r}T10:00:00", _process(nxt, wc))
    for i in range(5):
        _w(tmp_path, f"30_Projects/Devtrail/Decisions/d{i}.md",
           _fm(type="decision", title=f"결정 {i}", project="Devtrail", status="accepted", created_at=f"2026-11-0{i + 1}")
           + f"# 결정 {i}\n\n## 결정\n\n" + "".join(f"- DEC_{i}_{k}: " + "결정 근거 " * 12 + "\n" for k in range(5)))


def test_budget_runs_out_in_recent_stage_not_in_context(tmp_path, monkeypatch):
    """예산이 모자라면 최근 결과·결정이 먼저 줄고, 맥락과 명시된 후속 항목은 예산 때문에 잘리지 않는다."""
    _order_vault(tmp_path)
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS

    def budget_cut(key):
        return [i for i in _items(resp, key) if i.get("omission", {}).get("reason") == "budget"]

    assert budget_cut("recent"), "fixture가 예산을 넘지 않는다 — 최근 결과·결정에서 예산이 바닥나야 한다"
    assert not budget_cut("constraints") and not budget_cut("context") and not budget_cut("follow_ups")
    assert all(i["shown"] == "full" for i in _items(resp, "follow_ups"))
    assert all(i["shown"] == "full" for i in _items(resp, "context") if i["kind"] != "context_section")
    ctx = next(i for i in _items(resp, "context") if i["kind"] == "context_section")
    assert ctx["omission"]["reason"] == "group_cap"  # 맥락은 자기 상한(6000자)으로만 줄었다
    for needle in ("ORDER_CONSTRAINT", "FOCUS_9", "LESSON_0", "LESSON_13", "NEXT_s0_5", "NEXT_s2_5"):
        assert needle in resp["text"], needle
    # 예산 때문에 내용을 못 넣은 항목도 위치 안내 줄은 본문에 남는다
    for item in budget_cut("recent"):
        om = next(o for o in resp["omissions"] if o["item"] == item["id"])
        assert f"L{om['lines'][0]}-L{om['lines'][1]}" in resp["text"] and om["critical"] is False
    assert resp["budget"]["budget_order"] == list(pb.BUDGET_ORDER)

    # 같은 vault에서 이전 구현의 순서(후속·결정·결과 다음에 맥락)였다면 맥락이 예산 때문에 사라진다 — 이 검사가 순서를 가른다
    monkeypatch.setattr(pb, "BUDGET_ORDER", ("constraint", "next_session", "project_open_loops", "decision",
                                             "session_result", "plan_goal", "context_section", "current_focus",
                                             "lessons", "common_open_loops"))
    old = _brief(tmp_path)
    assert [i for i in _items(old, "context") if i.get("omission", {}).get("reason") == "budget"]


def test_display_order_in_text_puts_follow_ups_after_recent_and_gaps_warnings_sources_last(tmp_path, monkeypatch):
    _order_vault(tmp_path)
    ok = _handoff(tmp_path, "proc-x", "process", "sx", "2026-11-13T10:00:00", _process("- 못 읽는 후속"))
    _deny_reads(monkeypatch, ok)
    resp = _brief(tmp_path)
    text = resp["text"]
    heads = [text.index(f"## {n}. {pb.SECTION_TITLES[k]}") for n, k in enumerate(pb.DISPLAY_ORDER, 1)]
    assert heads == sorted(heads)
    # 표시: 최근 결과·결정의 발췌가 후속 항목보다 앞, 후속 항목이 정보 부족·경고·근거보다 앞
    assert text.index("WC_s2_0") < text.index("## 4. 명시적 후속 항목") < text.index("NEXT_s2_0") < heads[4]
    tail = text[heads[4]:]
    assert resp["warnings"] and resp["partial"] is True
    assert tail.index("### 경고") < tail.index("read_failed 1") < tail.index("### 근거 출처")
    # 경고는 본문에 코드별 건수만 — 메시지·경로는 JSON warnings에만 있다
    assert all(w["path"] not in tail for w in resp["warnings"] if w.get("path"))
    for src in resp["sources"]:
        if "excluded" not in src:
            assert f"{src['path']} · {src['source_version']}" in tail


# ── 독립 리뷰 3차 지적의 회귀 ────────────────────────────────────────────────


def test_many_context_sections_do_not_crowd_out_constraints_with_location_lines(tmp_path):
    """맥락 절의 위치 안내 예약이 제약 발췌보다 먼저 예산을 가져가면 안 된다 (예산 순서: 제약 → 맥락)."""
    body = "\n# Devtrail\n\n## 제약\n\n" + "".join(f"- 제약 {i}: " + "가" * 80 + "\n" for i in range(60))
    body += "".join(f"\n## 배경 {i}\n\n- 맥락 {i} 짧은 줄\n" for i in range(80))
    _ctx(tmp_path, body)
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert resp["critical_omission"] is False and resp["requires_read"] == []
    assert [i["shown"] for i in _items(resp, "constraints")] == ["full"]
    assert resp["text"].count("- 제약 ") == 60
    assert "- 다음 일" in resp["text"]


def test_many_warnings_do_not_push_constraints_out_of_text(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + "".join(f"- 제약 {i}: " + "가" * 90 + "\n" for i in range(150)))
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
    for i in range(20):
        _w(tmp_path, f"60_Candidates/Decisions/Other-{i}-{'d' * 180}.md", "---\ntitle: [bad\n---\n")
    resp = _brief(tmp_path)
    shared = [w for w in resp["warnings"] if w["path"] == "60_Candidates/Decisions/"]
    assert [w["count"] for w in shared] == [20] and resp["partial"] is True
    assert resp["critical_omission"] is False and [i["shown"] for i in _items(resp, "constraints")] == ["full"]
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS


def test_other_project_file_paths_in_warnings_stay_out_of_text(tmp_path):
    _ctx(tmp_path, TEMPLATE_CONTEXT)
    _ctx(tmp_path, "\n# Other\n\n## 배경\n\n- x\n", project="Other")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
    rel = "60_Candidates/Decisions/Other-acquire-competitor-secretly.md"
    _w(tmp_path, rel, "---\nproject: Other\ntitle: [bad\n---\n# x\n")
    resp = _brief(tmp_path)
    # 소속을 확인하지 못한 공유 후보 파일은 JSON 어디에도 파일명을 싣지 않는다 — 폴더 경로와 건수로만 알린다(숨기지는 않는다)
    assert "acquire-competitor" not in json.dumps(resp, ensure_ascii=False)
    w = next(w for w in resp["warnings"] if w["code"] == "frontmatter_unparsed")
    assert w["path"] == "60_Candidates/Decisions/" and w["count"] == 1 and w["attribution"] == "unverified"
    assert resp["partial"] is True  # 이 프로젝트 것일 수도 있다 — 완전하다고 말하지 않는다
    assert "frontmatter_unparsed 1" in resp["text"]
    # 이 프로젝트 폴더의 해석 실패 파일은 이 프로젝트 소속 위치라 경로를 그대로 남긴다
    own = "30_Projects/Devtrail/Decisions/broken.md"
    _w(tmp_path, own, "---\ntitle: [bad\n---\n")
    resp = _brief(tmp_path)
    assert any(w["path"] == own for w in resp["warnings"])
    assert "frontmatter_unparsed 2" in resp["text"]


@pytest.mark.parametrize("mode", ["many_next_session_headings", "many_open_loops_blocks"])
def test_many_follow_up_items_do_not_displace_constraints(tmp_path, mode):
    """후속 항목 수는 창으로 묶이지 않는다(Next Session 절 반복, 패치마다 쌓이는 OpenLoops 블록) — 미리 예약하는 안내 줄이
    제약 발췌를 밀어내면 안 된다. 들어가는 제약(약 14000자)은 전부 실리고, 못 실은 후속 항목은 omissions와 건수로 드러난다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + "".join(f"- 제약 {i}: " + "가" * 90 + "\n" for i in range(140)))
    if mode == "many_next_session_headings":
        body = "# Process\n\n## What Changed\n\n- x\n\n" + "".join(f"## Next Session\n\n- 후속 {k}\n\n" for k in range(120))
        _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", body)
    else:
        _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
        mk = '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n'
        _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", "# Open Loops\n\n" + "".join(f"{mk}- 루프 {k}\n\n" for k in range(120)))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert resp["critical_omission"] is False and [i["shown"] for i in _items(resp, "constraints")] == ["full"]
    assert resp["text"].count("- 제약 ") == 140
    follow = _items(resp, "follow_ups")
    assert len(follow) >= 120 and _section(resp, "follow_ups")["state"] == "has_items"
    hidden = [i for i in follow if i["shown"] == "omitted"]
    assert all(any(o["item"] == i["id"] for o in resp["omissions"]) for i in hidden)
    if hidden and not all(i["path"] in resp["text"] for i in hidden):
        assert "안내도 못 낸 생략" in resp["text"]


@pytest.mark.parametrize("n_rules", [200, 230, 257])
def test_small_follow_up_keeps_location_without_taking_constraint_budget(tmp_path, n_rules):
    """제약이 예산을 다 써도 작은 후속 기록의 위치는 고정부에 남는다. 위치를 남기려고 발췌 자리를 미리 잡지 않는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + "".join(f"- c{i} " + "가" * 80 + "\n" for i in range(n_rules)))
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- a\n- b"))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    nxt = _items(resp, "follow_ups")[0]
    assert f"{nxt['path']} L{nxt['span'][0]}-L{nxt['span'][1]}" in resp["text"]
    cons = _items(resp, "constraints")[0]
    if cons["shown"] != "full":
        # 제약이 예산 때문에 잘렸다면 후속 발췌는 제약 다음 줄이 못 들어간 자투리에만 들어갈 수 있다
        assert nxt["shown"] != "full" or resp["budget"]["text_chars"] + 90 > pb.TEXT_MAX_CHARS
        sec = _section(resp, "follow_ups")
        if nxt["shown"] != "full":
            assert sec["complete"] is False and pb.FOLLOW_UP_UNKNOWN in sec["message"]


# ── 병합 리뷰 3차(BLOCK) 지적의 회귀 ─────────────────────────────────────────

_MK = '<!-- devtrail-memory-patch: {"scope": "project", "project": "%s"} -->\n'


def test_memory_rule_headings_are_constraints_with_scope_kept(tmp_path):
    _ctx(tmp_path, "## 제약\n\n- CTX_RULE 공식 영역 직접 쓰기 금지\n\n## 배경\n\nx\n")
    _w(tmp_path, "40_AgentMemory/01_CurrentFocus.md",
       "# Current Focus\n\n- 공통 초점\n\n## 규칙\n\n- COMMON_RULE 먼저 측정한다\n\n"
       + _MK % "Devtrail" + "## Devtrail\n\n- 지금 하는 일\n\n### 금지\n\n- PROJECT_RULE 운영 트리 직접 편집 금지\n\n"
       "### 메모\n\n- 그냥 메모\n\n" + _MK % "Other" + "## Other\n\n### 규칙\n\n- OTHER_RULE 다른 프로젝트 규칙\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", "# Lessons\n\n" + _MK % "Devtrail"
       + "- 교훈 하나\n\n#### Guardrails\n\n- LESSON_RULE 같은 실수 반복 금지\n")
    resp = _brief(tmp_path)
    rules = [i for i in _items(resp, "constraints") if i.get("memory_rule")]
    by_text = {seg["text"].splitlines()[-1]: i for i in rules for seg in i["segments"]}
    assert set(by_text) == {"- COMMON_RULE 먼저 측정한다", "- PROJECT_RULE 운영 트리 직접 편집 금지",
                            "- LESSON_RULE 같은 실수 반복 금지"}
    assert by_text["- COMMON_RULE 먼저 측정한다"]["scope"] == "common"
    assert by_text["- PROJECT_RULE 운영 트리 직접 편집 금지"]["scope"] == "project"
    assert by_text["- LESSON_RULE 같은 실수 반복 금지"]["scope"] == "project"
    assert all(i["kind"] == "constraint" for i in rules)
    assert _section(resp, "constraints")["memory_rule_items"] == 3
    # Context 제약은 그대로 있고, 둘을 합치거나 어느 쪽을 지우지 않는다
    assert any("CTX_RULE" in s["text"] for i in _items(resp, "constraints") for s in i["segments"])
    # 규칙이 아닌 부분은 맥락에 그대로 — '### 메모'처럼 규칙 뒤 같은 단계 제목부터는 맥락
    ctx_text = json.dumps(_items(resp, "context"), ensure_ascii=False)
    assert "그냥 메모" in ctx_text and "지금 하는 일" in ctx_text and "공통 초점" in ctx_text
    assert "PROJECT_RULE" not in ctx_text and "COMMON_RULE" not in ctx_text
    assert "OTHER_RULE" not in json.dumps(resp, ensure_ascii=False)
    for i in rules:
        lines = _file_lines(tmp_path, i["path"])
        for seg in i["segments"]:
            assert seg["text"] == "\n".join(lines[seg["start_line"] - 1:seg["end_line"]])


def test_cut_memory_rule_raises_critical_omission_and_requires_read(tmp_path, monkeypatch):
    _ctx(tmp_path, "## 배경\n\nx\n")
    rules = "".join(f"- 규칙 {i:03d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(250))
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", "# Lessons\n\n" + _MK % "Devtrail" + "## 원칙\n\n" + rules
       + "- MEMORY_RULE_TAIL 마지막 원칙\n")
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert resp["critical_omission"] is True and "MEMORY_RULE_TAIL" not in resp["text"]
    om = next(o for o in resp["omissions"] if o["critical"])
    assert om["path"] == "40_AgentMemory/06_Lessons.md" and om["kind"] == "constraint"
    assert any(r["item"] == om["item"] for r in resp["requires_read"])
    page = _mcp_read_note(monkeypatch, tmp_path, om["read"])
    assert page["ok"] and page["start_line"] == om["lines"][0]


def test_project_open_loops_explicit_none_is_scoped_like_next_session(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-03T10:00:00", _process("없음"))
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", "# OpenLoops\n\n" + _MK % "Devtrail" + "## Devtrail\n\n- 없음\n")
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "none_in_scope" and sec["complete"] is True
    assert sec["message"].startswith(pb.FOLLOW_UP_NONE)
    ol = next(i for i in sec["items"] if i["kind"] == "project_open_loops")
    assert ol["follow_up_state"] == "explicit_none" and ol["segments"][-1]["text"].endswith("- 없음")
    assert [s["state"] for s in sec["sources_checked"] if s["source"] == "project_open_loops"] == ["explicit_none"]
    assert resp["text"].count("명시적 없음 — 이 기록 범위 한정") == 2

    # 문장이 붙은 '없음'은 항목이다
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       "# OpenLoops\n\n" + _MK % "Devtrail" + "## Devtrail\n\n- 없음 — 단 운영 반영 실측은 남음\n")
    assert _section(_brief(tmp_path), "follow_ups")["state"] == "has_items"


def test_follow_up_items_cut_from_text_mark_state_incomplete(tmp_path):
    rules = "".join(f"- 규칙 {i:04d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(300))
    _ctx(tmp_path, "## 원칙\n\n" + rules)
    long_next = "".join(f"- 후속 {k}: " + "설명 " * 30 + "\n" for k in range(40))
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process(long_next))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert any(o["section"] == "follow_ups" for o in resp["omissions"])
    assert sec["state"] == "has_items" and sec["complete"] is False
    assert pb.FOLLOW_UP_UNKNOWN in sec["message"] and sec["unknown_reasons"]["omitted_from_text"] >= 1
    assert sec["message"] in resp["text"] and len(resp["text"]) <= pb.TEXT_MAX_CHARS


def test_explicit_none_records_cut_from_text_are_not_reported_as_none(tmp_path):
    rules = "".join(f"- 규칙 {i:04d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(300))
    _ctx(tmp_path, "## 원칙\n\n" + rules)
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("없음"))
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       "# OpenLoops\n\n" + "".join(_MK % "Devtrail" + "## Devtrail\n\n- 없음\n\n" for _ in range(120)))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert all(i["follow_up_state"] == "explicit_none" for i in sec["items"])
    assert any(o["section"] == "follow_ups" for o in resp["omissions"])
    assert sec["state"] == "unknown" and sec["complete"] is False
    assert sec["message"].startswith(pb.FOLLOW_UP_UNKNOWN) and pb.FOLLOW_UP_NONE not in sec["message"]
    assert sec["message"] in resp["text"] and len(resp["text"]) <= pb.TEXT_MAX_CHARS


def test_unclosed_fence_in_memory_block_is_reported(tmp_path):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", "# Lessons\n\n" + _MK % "Devtrail"
       + "- 교훈\n\n```bash\necho 열림\n\n## 규칙\n\n- HIDDEN_RULE\n")
    resp = _brief(tmp_path)
    gap = next(g for g in _section(resp, "gaps")["items"] if g["code"] == "unclosed_code_fence")
    assert gap["path"] == "40_AgentMemory/06_Lessons.md"
    assert not [i for i in _items(resp, "constraints") if i.get("memory_rule")]  # 판정하지 않고 알리기만 한다


def test_unreadable_shared_decisions_folder_keeps_its_reason(tmp_path, deny_access):
    _ctx(tmp_path, "## 제약\n\n- 제약\n")
    _w(tmp_path, "60_Candidates/Decisions/Other-secret-plan.md", "---\ntitle: x\nproject: Other\n---\n")
    deny_access.none("60_Candidates/Decisions")
    resp = _brief(tmp_path)
    assert deny_access.hits and resp["partial"] is True
    w = next(w for w in resp["warnings"] if w["path"] == "60_Candidates/Decisions/")
    assert w["code"] == "read_failed" and "폴더" in w["message"] and "count" not in w
    assert "secret-plan" not in json.dumps(resp, ensure_ascii=False)



# ── 병합 리뷰 4차(BLOCK) 지적의 회귀 ─────────────────────────────────────────


def test_constraint_that_fits_is_never_cut_for_later_stages(tmp_path, monkeypatch):
    """분리 재현: 고정부 뒤 남은 예산이 제약 전체 비용과 같을 때 제약은 전부 실리고, 후속·최근·맥락 발췌는 남은 예산이 없어 빠진다."""
    _ctx(tmp_path, "## 제약\n\n" + "".join(f"- 규칙 {i}: " + "가" * 90 + "\n" for i in range(10)) + "\n## 배경\n\n- 맥락 한 줄\n")
    for r in range(3):
        _handoff(tmp_path, f"p{r}", "process", f"s{r}", f"2026-11-1{r}T10:00:00", _process(f"- 후속 {r}", f"- 결과 {r}"))
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", "# OpenLoops\n\n" + "".join(
        _MK % "Devtrail" + f"## Devtrail\n\n- 루프 {k}\n\n" for k in range(5)))
    captured: dict = {}
    real = pb._allocate

    def spy(b, remaining):
        captured["b"] = b
        return real(b, remaining)

    monkeypatch.setattr(pb, "_allocate", spy)
    _brief(tmp_path)
    b = captured["b"]
    cons = [i for i in b.items if i.group == "constraint"]
    assert len(cons) == 1 and len(cons[0].candidates) >= 11
    for budget in (pb._full_cost(cons[0]), pb._full_cost(cons[0]) + 30):
        for i in b.items:
            i.shown, i.omission, i.stub, i.tail, i.skipped = [], None, False, False, []
        real(b, budget)
        assert cons[0].shown == cons[0].candidates and cons[0].omission is None, budget
        assert all(not i.shown for i in b.items if i.group != "constraint"), budget


@pytest.mark.parametrize("width", [16001, 17000, 19000])
def test_line_over_read_limit_is_never_excerpted(tmp_path, monkeypatch, width):
    long_rule = "- " + "가" * (width - 2)
    _ctx(tmp_path, "## 제약\n\n- 짧은 제약\n" + long_rule + "\n- 뒤 제약\n")
    _handoff(tmp_path, "p", "process", "s", "2026-11-10T10:00:00", _process("- 다음 " + "나" * (width - 5)))
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    assert "가" * 100 not in resp["text"] and "나" * 100 not in resp["text"]
    cons = _items(resp, "constraints")[0]
    # 긴 줄 하나만 건너뛰고 앞뒤 제약은 실린다(비연속 구간) — 긴 줄 때문에 뒤 제약까지 잃지 않는다
    assert cons["shown"] == "partial" and "- 짧은 제약" in resp["text"] and "- 뒤 제약" in resp["text"]
    lines = _file_lines(tmp_path, cons["path"])
    long_no = lines.index(long_rule) + 1
    assert cons["unreadable_lines"] == [long_no] and cons["contiguous"] is False and "omission" not in cons
    assert [(s_["start_line"], s_["end_line"]) for s_ in cons["segments"]][-1][0] == long_no + 1
    om = next(o for o in resp["omissions"] if o["item"] == cons["id"])
    assert om["lines"] == [long_no, long_no] and om["line_chars"] == len(long_rule)
    assert f"생략 L{long_no}-L{long_no} (line_too_long) → read_note(\"{cons['path']}\")" in resp["text"]
    assert om["reason"] == "line_too_long" and om["critical"] and om["structured_readable"] is False
    assert om["read"] == {"rel_path": om["path"]}
    assert resp["critical_omission"] is True and any(r["item"] == cons["id"] for r in resp["requires_read"])
    gaps = [g for g in _section(resp, "gaps")["items"] if g["code"] == "line_exceeds_read_limit"]
    assert {g["path"] for g in gaps} == {cons["path"], _items(resp, "follow_ups")[0]["path"]}
    # 모든 발췌 줄은 실제로 structured read_note로 회수된다
    for item in _all_items(resp):
        for seg in item["segments"]:
            page = _mcp_read_note(monkeypatch, tmp_path, {"rel_path": item["path"], "structured": True,
                                                          "start_line": seg["start_line"],
                                                          "max_lines": seg["end_line"] - seg["start_line"] + 1,
                                                          "expected_version": item["source_version"]})
            assert page["ok"] and page["content"] == seg["text"]
    full = _mcp_read_note(monkeypatch, tmp_path, om["read"])
    assert long_rule in full


def _check_resume_info_matches_read_note(monkeypatch, vault, resp) -> int:
    checked = 0
    for om in resp["omissions"]:
        if not om["structured_readable"]:
            continue
        page = _mcp_read_note(monkeypatch, vault, om["read"])
        assert page["ok"], page
        assert page["start_line"] == om["lines"][0]
        assert page["end_line"] == om["first_read_end_line"]
        assert om["read_continues"] == (page["end_line"] < om["lines"][1])
        if om["read_continues"]:
            assert page["next"]["start_line"] == page["end_line"] + 1
        checked += 1
    return checked


@pytest.mark.parametrize("n_lines,width", [(100, 200), (30, 600), (900, 10), (90, 179)])
def test_read_continues_matches_actual_read_note_paging(tmp_path, monkeypatch, n_lines, width):
    """이어읽기 정보는 400줄 상한뿐 아니라 16000자 상한도 반영해 실제 read_note의 end_line·next와 같다."""
    rows = "".join(f"- 규칙 {i:03d} " + "가" * (width - 10) + "\n" for i in range(n_lines))
    _ctx(tmp_path, "## 원칙\n\n" + rows * 2 + "\n## 배경\n\n" + rows)  # 제약 초과 + 맥락 상한 초과
    resp = _brief(tmp_path)
    assert _check_resume_info_matches_read_note(monkeypatch, tmp_path, resp) >= 1
    if n_lines * width > 16100:
        assert any(o["read_continues"] for o in resp["omissions"])


def test_over_limit_line_does_not_hide_later_constraints_or_widen_their_read(tmp_path):
    """긴 줄 뒤의 읽을 수 있는 제약 줄은 예산이 남으면 실리고, 그 줄들의 생략이 전문 읽기로 뭉개지지 않는다."""
    _ctx(tmp_path, "## 제약\n\n- 짧은 제약\n- " + "가" * 16000 + "\n- 뒤 제약\n\n## 배경\n\n- 배경 줄\n")
    resp = _brief(tmp_path)
    assert "- 뒤 제약" in resp["text"] and "- 배경 줄" in resp["text"]
    oms = [o for o in resp["omissions"] if o["critical"]]
    assert len(oms) == 1 and oms[0]["lines"][0] == oms[0]["lines"][1]  # 긴 줄 한 줄만
    assert oms[0]["read"] == {"rel_path": oms[0]["path"]}


def test_budget_cut_uses_exact_omission_note_length(tmp_path, monkeypatch):
    """예산 판정은 실제로 붙을 생략 줄 길이를 쓴다 — 최악 길이(구조화 인자) 때문에 들어갈 제약 줄을 자르지 않는다.
    남는 보수 오차는 구간 표시 줄을 최대 자릿수로 잡은 몫뿐이다."""
    _ctx(tmp_path, "## 제약\n\n- 짧은 제약\n- " + "다" * 15990 + "\n- " + "가" * 16500 + "\n- 끝 제약\n")
    captured: dict = {}
    real = pb._allocate

    def spy(b, remaining):
        captured["b"] = b
        return real(b, remaining)

    monkeypatch.setattr(pb, "_allocate", spy)
    _brief(tmp_path)
    b = captured["b"]
    item = next(i for i in b.items if i.group == "constraint")
    # 경계: 앞 두 줄(짧은 제약·약 16000자 줄)까지 넣는 비용 근처를 1자 단위로 훑는다
    first_two = sum(len(item.lines[n - 1]) + 1 for n in item.candidates if len(item.lines[n - 1]) <= pb.READ_MAX_CHARS)
    lo = first_two - 300
    hits = 0
    for budget in range(lo, lo + 900):
        for i in b.items:
            i.shown, i.omission, i.stub, i.tail, i.skipped = [], None, False, False, []
        real(b, budget)
        if not (item.omission and item.omission["reason"] == "budget") or item.omission["lines"][0] in item.skipped:
            continue
        k = item.omission["lines"][0]
        if len(item.lines[k - 1]) > pb.READ_MAX_CHARS:
            continue
        # k를 더 넣은 가상 렌더 — 뒤에 남는 줄이 있으면 실제 생략 줄까지 포함
        rest = [n for n in item.candidates if n > k]
        trial = pb._Item(**{**item.__dict__, "shown": sorted(item.shown + [k]),
                            "omission": pb._omission(item.doc, [rest[0], rest[-1]], "budget") if rest else None})
        # 허용 오차: 구간 표시 줄을 최대 자릿수로 잡은 몫(구간마다)
        t = item.doc.source.total_lines
        label_slack = sum(len(pb._seg_label(t, t)) - len(pb._seg_label(a_, b_)) for a_, b_ in pb._segments(trial.shown))
        assert len(pb._render_item(trial)) + 3 + label_slack > budget, budget
        hits += 1
    assert hits > 0  # 예산 때문에 잘리는 경계를 실제로 지나갔다


# ── 독립 리뷰 7차 지적 회귀 — 제목으로 쓴 규칙·할 일, 들여쓴 제목, 결정 고정부 목록 줄 ─────────────────


def test_heading_only_rules_are_constraints_not_empty_scaffold(tmp_path):
    """본문 없이 제목만 있는 규칙(`### …금지`)은 내용이다 — 빈 틀(heading_empty)로 지우지 않는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 배경\n\n- 배경 내용\n\n## 제약 / 원칙\n\n"
                   "### main 브랜치에 직접 push 금지\n\n### 운영 DB 스키마 변경은 사용자 승인 후에만\n\n## 관련 문서\n\n- 링크\n")
    resp = _brief(tmp_path)
    cons = _section(resp, "constraints")
    assert cons["state"] == "items"
    assert "constraint_section_empty" not in {g["code"] for g in _items(resp, "gaps")}
    shown = [seg["text"] for it in cons["items"] for seg in it["segments"]]
    assert "### main 브랜치에 직접 push 금지" in shown
    assert "### 운영 DB 스키마 변경은 사용자 승인 후에만" in shown
    assert "main 브랜치에 직접 push 금지" in resp["text"] and "운영 DB 스키마 변경" in resp["text"]
    # 하위 절만 거느린 상위 제목은 따로 보여줄 내용이 없어 정리 목록에 남는다
    assert {"제약 / 원칙"} <= {c["heading"] for c in _section(resp, "context")["cleaned_sections"]}


def test_scaffold_emptied_constraint_heading_stays_heading_empty(tmp_path):
    """알려진 빈 틀(빈 불릿)만 있던 제약 절은 여전히 heading_empty — 정리 규칙을 좁혔지 없앤 게 아니다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 배경\n\n- 배경 내용\n\n## 제약 / 원칙\n\n- \n\n### 세부\n\n- \n")
    resp = _brief(tmp_path)
    assert _section(resp, "constraints")["state"] == "heading_empty"
    assert "constraint_section_empty" in {g["code"] for g in _items(resp, "gaps")}


def test_heading_only_follow_ups_are_not_reported_as_none(tmp_path):
    """할 일을 제목으로 적은 Next Session·OpenLoops 블록을 '명시된 후속 작업 없음'으로 판정하지 않는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00",
             "# Process\n\n## What Changed\n\n- x\n\n## Next Session\n\n없음\n\n### 배포 스크립트 롤백 확인 필요\n")
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", _fm(type="agent_memory", scope="global", updated_at=TODAY)
       + "# OpenLoops\n\n" + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n### 결제 웹훅 재시도 미해결\n")
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert fu["state"] == "has_items"
    states = {s["source"]: s["state"] for s in fu["sources_checked"]}
    # Next Session은 자유 서식이라 '없음' 아래 제목도 내용이다. OpenLoops는 불릿이 항목이고 제목은 분류라, 제목만 남은 블록은
    # 할 일인지 비운 분류인지 판정하지 않는다(확인 불가) — '없음'으로 보지 않고, 위치·제목은 본문 gap에 남긴다.
    assert states == {"next_session": "items", "project_open_loops": "headings_only"}
    assert fu["complete"] is False and FOLLOW_UP_UNKNOWN_TEXT in fu["message"]
    assert "### 배포 스크립트 롤백 확인 필요" in resp["text"] and "### 결제 웹훅 재시도 미해결" in resp["text"]
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")
    ol = _file_lines(tmp_path, "40_AgentMemory/05_OpenLoops.md")
    n = ol.index("### 결제 웹훅 재시도 미해결") + 1
    assert gap["lines"][0] <= n <= gap["lines"][1] and f"L{n} ### 결제 웹훅 재시도 미해결" in gap["message"]


def test_heading_over_explicit_none_keeps_explicit_none(tmp_path):
    """내용을 거느린 하위 제목은 내용 줄로 세지 않는다 — `### 기타` 아래 '없음' 한 줄은 그대로 명시적 없음이다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("### 기타\n\n- 없음"))
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert [s["state"] for s in fu["sources_checked"] if s["source"] == "next_session"] == ["explicit_none"]


def test_indented_constraint_heading_is_recognised_late_in_long_context(tmp_path):
    """CommonMark처럼 0~3칸 들여쓴 제목도 제목이다 — 긴 Context 뒤의 들여쓴 제약 절이 맥락 상한에 잘려 사라지지 않는다."""
    filler = "".join(f"- 배경 {i:03d} " + "가" * 60 + "\n" for i in range(110))
    _ctx(tmp_path, "\n# Devtrail\n\n## 배경\n\n" + filler + "\n   ## 제약 / 원칙\n\n- main 브랜치에 직접 push 금지\n")
    resp = _brief(tmp_path)
    cons = _section(resp, "constraints")
    assert cons["state"] == "items"
    assert "- main 브랜치에 직접 push 금지" in resp["text"]
    lines = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md")
    for seg in (s for it in cons["items"] for s in it["segments"]):
        assert seg["text"] == "\n".join(lines[seg["start_line"] - 1:seg["end_line"]])
    # 4칸 이상 들여쓴 '#' 줄은 제목이 아니다
    assert pb._heading("    ## 코드") is None and pb._heading("   ## 제목") == (2, "제목")


def test_decisions_keep_fixed_list_line_when_excerpt_is_cut(tmp_path):
    """제약이 예산을 다 써서 결정 발췌가 빠져도 결정 제목·상태·경로는 고정부 목록 줄로 본문에 남는다."""
    rules = "".join(f"- 규칙 {i:04d} " + "나" * 80 + "\n" for i in range(260))
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + rules)
    for i in range(2):
        _w(tmp_path, f"60_Candidates/Decisions/dec{i}.md",
           _fm(type="candidate", candidate_type="decision", title=f"결정제목{i}", project="Devtrail",
               status="candidate", created_at=f"2026-11-0{i + 1}") + f"# 결정제목{i}\n\n## 결정\n\n- 결정 내용 {i}\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 다음 일"))
    resp = _brief(tmp_path)
    assert resp["critical_omission"] is True and len(resp["text"]) <= pb.TEXT_MAX_CHARS
    decisions = _section(resp, "recent")["decisions"]
    assert [d["state"] for d in decisions] == ["excerpt", "excerpt"]
    block = resp["text"][resp["text"].index("### 결정"):resp["text"].index("### 세션 결과")]
    for d in decisions:
        assert f"- {d['item']}: {d['title']} · candidate · {d['date']} · {d['path']}" in block
    assert "- 결정 내용" not in resp["text"]  # 발췌 자체는 예산 순서대로 빠졌다


# ── 병합 리뷰 지적 회귀 — 상위 제목이 담은 적용 범위 보존 ─────────────────────────────────────────────


def test_parent_heading_scope_stays_with_constraints(tmp_path):
    """하위 절만 거느린 상위 제목('운영 서버에서만 적용')은 따로 항목이 되지 않아도 하위 제약의 적용 범위로 남는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 운영 서버에서만 적용\n### 제약\n- 재시작 금지\n## 로컬 환경\n### 제약\n"
                   "- 자유롭게 재시작 가능\n")
    resp = _brief(tmp_path)
    items = _items(resp, "constraints")
    assert [(i["span"], i["heading_path"]) for i in items] == [
        ([11, 12], [{"line": 10, "level": 2, "text": "운영 서버에서만 적용"}]),
        ([14, 15], [{"line": 13, "level": 2, "text": "로컬 환경"}]),
    ]
    lines = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md")
    for i in items:
        for h in i["heading_path"]:  # 원문 줄 번호·단계·제목 그대로
            assert lines[h["line"] - 1] == "#" * h["level"] + " " + h["text"]
    text = resp["text"]
    first, second = text.index("- 재시작 금지"), text.index("- 자유롭게 재시작 가능")
    assert text.rindex("상위 제목: L10 ## 운영 서버에서만 적용", 0, first) < first
    assert text.rindex("상위 제목: L13 ## 로컬 환경", 0, second) > first  # 두 번째 제약 바로 위는 자기 범위다
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons["운영 서버에서만 적용"] == reasons["로컬 환경"] == "parent_heading"


def test_heading_path_lists_every_enclosing_level_but_not_doc_title(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 운영\n\n- 운영 설명\n\n### 서울 리전\n\n#### 금지\n\n- 평일 배포 금지\n\n"
                   "### 도쿄 리전\n\n- 도쿄 설명\n")
    resp = _brief(tmp_path)
    (rule,) = _items(resp, "constraints")
    assert [(h["line"], h["level"], h["text"]) for h in rule["heading_path"]] == [(10, 2, "운영"), (14, 3, "서울 리전")]
    assert "상위 제목: L10 ## 운영 › L14 ### 서울 리전" in resp["text"]
    tokyo = next(i for i in _items(resp, "context") if i["label"] == "도쿄 리전")
    assert [h["text"] for h in tokyo["heading_path"]] == ["운영"]  # 형제 절(서울 리전)은 상위가 아니다


def test_memory_rule_keeps_parent_heading_inside_its_block_only(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", _fm(type="agent_memory", scope="global", updated_at=TODAY)
       + "# Lessons\n\n## 다른 블록 밖 제목\n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n### 배포 작업 때만\n\n#### 규칙\n\n- 배포 전 백업 확인\n")
    resp = _brief(tmp_path)
    rule = next(i for i in _items(resp, "constraints") if i.get("memory_rule"))
    # 블록 제목(## Devtrail)·블록 밖 제목은 넣지 않는다 — 블록 귀속 경계를 넘지 않는다
    assert [h["text"] for h in rule["heading_path"]] == ["배포 작업 때만"]
    path_lines = [l for l in resp["text"].splitlines() if "상위 제목:" in l]
    assert any("### 배포 작업 때만" in l for l in path_lines)
    assert not any("다른 블록 밖 제목" in l for l in path_lines)  # 마커 앞(공통 블록) 제목은 이 블록의 상위가 아니다


def test_heading_path_line_is_counted_in_text_budget(tmp_path):
    """상위 제목 줄은 머리줄 비용에 함께 잡힌다 — 길어도 text 상한·완전한 줄·예산 순서가 그대로다."""
    long_scope = "범위 " + "가" * 190
    rules = "".join(f"- 규칙 {i:04d} " + "나" * 80 + "\n" for i in range(60))
    body = "\n# Devtrail\n\n" + "".join(f"## {long_scope} {k}\n### 제약\n{rules}" for k in range(5))
    _ctx(tmp_path, body)
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS and resp["budget"]["text_chars"] == len(resp["text"])
    lines = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md")
    for item in _items(resp, "constraints"):
        assert item["heading_path"] and item["heading_path"][0]["text"].startswith("범위 ")
        for seg in item["segments"]:
            assert seg["text"] == "\n".join(lines[seg["start_line"] - 1:seg["end_line"]])
            assert seg["text"] in resp["text"]



def test_open_loops_category_left_after_resolve_is_not_reported_as_open_work(tmp_path):
    """update_open_loops(section=)로 쓰고 resolve로 다 지운 뒤 남은 `### 분류` 제목을 후속 항목으로 보고하지 않는다.
    제목으로 적은 할 일과 구분할 근거가 없어 '없음'으로도 단정하지 않는다(확인 불가)."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
    s = _settings(tmp_path)
    vault_tools.update_open_loops("Devtrail", add=["결제 웹훅 재시도 확인"], section="결제", settings=s)
    assert vault_tools.update_open_loops("Devtrail", resolve=["결제 웹훅"], settings=s).resolved
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert fu["state"] == "unknown" and fu["state"] != "has_items"
    assert [x["state"] for x in fu["sources_checked"] if x["source"] == "project_open_loops"] == ["headings_only"]
    assert not [i for i in fu["items"] if i["kind"] == "project_open_loops"]
    assert "명시된 후속 항목이다" not in resp["text"]
    assert "follow_up_headings_only" in {g["code"] for g in _items(resp, "gaps")}
    # 같은 블록에 불릿 할 일이 하나라도 남아 있으면 항목이다 (빈 분류 제목은 발췌 안에 그대로 보인다)
    vault_tools.update_open_loops("Devtrail", add=["배포 롤백 점검"], section="배포", settings=s)
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert [x["state"] for x in fu["sources_checked"] if x["source"] == "project_open_loops"] == ["items"]
    assert fu["state"] == "has_items" and "배포 롤백 점검" in resp["text"]


def test_constraint_heading_over_empty_bullet_is_named_in_gap(tmp_path):
    """제목으로 쓴 규칙 아래 빈 불릿만 있으면 정리 규칙대로 항목은 만들지 않되, 그 제목·줄은 본문 gap에 남는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n### main 브랜치에 직접 push 금지\n\n- \n\n## 배경\n\n- 설명\n")
    resp = _brief(tmp_path)
    assert _section(resp, "constraints")["state"] == "heading_empty"
    lines = [l for l in resp["text"].splitlines() if l.startswith("- [constraint_section_empty]")]
    n = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md").index("### main 브랜치에 직접 push 금지") + 1
    assert len(lines) == 1 and f"L{n} ### main 브랜치에 직접 push 금지" in lines[0]


def _open_loops_block(vault: Path, body: str) -> None:
    _w(vault, "40_AgentMemory/05_OpenLoops.md", _fm(type="agent_memory", scope="global", updated_at=TODAY)
       + "# OpenLoops\n\n" + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n" + body)


def test_four_space_indented_hash_line_in_open_loops_is_content_not_heading(tmp_path):
    """4칸 들여쓴 '#' 줄은 제목이 아니다(CommonMark) — headings_only로 빠지지 않고 항목으로 본문에 남는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
    _open_loops_block(tmp_path, "    # 마이그레이션 재실행 필요\n")
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert [x["state"] for x in fu["sources_checked"] if x["source"] == "project_open_loops"] == ["items"]
    assert "    # 마이그레이션 재실행 필요" in resp["text"]


def test_heading_gaps_keep_count_in_text_and_full_list_in_json(tmp_path):
    """제목 목록 gap은 건수를 먼저 적어 본문 400자 자름에도 건수가 남고, JSON headings에는 전체 목록이 있다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
    names = [f"### 분류 {k} " + "가" * 120 for k in range(8)]
    _open_loops_block(tmp_path, "\n\n".join(names) + "\n")
    resp = _brief(tmp_path)
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")
    ol = _file_lines(tmp_path, "40_AgentMemory/05_OpenLoops.md")
    assert [h["line"] for h in gap["headings"]] == [ol.index(n) + 1 for n in names]
    assert all(h["text"] == ol[h["line"] - 1] for h in gap["headings"])
    line = next(l for l in resp["text"].splitlines() if l.startswith("- [follow_up_headings_only]"))
    assert "제목 8개만 남았다" in line and "외 3개" in line


# ── 병합 리뷰 지적 회귀 — 다른 제약이 있어도 빈 틀 아래 규칙 제목이 사라지지 않는다 ─────────────────────


def _rule_texts(resp: dict) -> list[str]:
    return [seg["text"] for it in _items(resp, "constraints") for seg in it["segments"]]


def test_scaffold_only_rule_heading_kept_beside_real_constraints_in_context(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n- 실제 규칙 A\n### main 브랜치 직접 push 금지\n-\n## 배경\n설명\n")
    resp = _brief(tmp_path)
    cons = _section(resp, "constraints")
    assert cons["state"] == "items"
    kept = [i for i in cons["items"] if i.get("scaffold_only")]
    assert len(kept) == 1 and [s["text"] for s in kept[0]["segments"]] == ["### main 브랜치 직접 push 금지"]
    lines = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md")
    seg = kept[0]["segments"][0]
    assert lines[seg["start_line"] - 1] == seg["text"]
    assert {"lines": [seg["start_line"] + 1, seg["start_line"] + 1], "reason": "empty_scaffolding"} in kept[0]["cleaned"]
    assert "### main 브랜치 직접 push 금지" in resp["text"] and "본문은 빈 틀뿐" in resp["text"]
    assert "- 실제 규칙 A" in resp["text"]


@pytest.mark.parametrize("rel", ["40_AgentMemory/01_CurrentFocus.md", "40_AgentMemory/06_Lessons.md"])
def test_scaffold_only_memory_rule_heading_kept_beside_real_rules(tmp_path, rel):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, rel, _fm(type="agent_memory", scope="global", updated_at=TODAY) + "# Memory\n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n### 규칙\n- 실제 기억 규칙\n### 운영 DB 직접 수정 금지\n- \n")
    resp = _brief(tmp_path)
    rules = [i for i in _items(resp, "constraints") if i.get("memory_rule")]
    assert [i.get("scaffold_only", False) for i in rules] == [False, True]
    assert [s["text"] for s in rules[1]["segments"]] == ["### 운영 DB 직접 수정 금지"]
    assert rules[1]["scope"] == "project" and rules[1]["path"] == rel
    assert "### 운영 DB 직접 수정 금지" in resp["text"] and "- 실제 기억 규칙" in resp["text"]


def test_scaffold_only_rule_heading_cut_by_budget_is_critical(tmp_path):
    """제목만 남긴 규칙도 제약 예산을 받고, 예산에 밀려 빠지면 critical_omission·requires_read로 드러난다."""
    rules = "".join(f"- 규칙 {i:04d} " + "나" * 80 + "\n" for i in range(260))
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + rules + "\n### 마지막 금지 제목\n\n- \n")
    resp = _brief(tmp_path)
    item = next(i for i in _items(resp, "constraints") if i.get("scaffold_only"))
    assert item["shown"] == "omitted" and resp["critical_omission"] is True
    assert any(r.get("item") == item["id"] for r in resp["requires_read"])


def test_parent_constraint_heading_without_scaffold_is_not_a_scaffold_item(tmp_path):
    """빈 틀 없이 하위 절만 거느린 제약 상위 제목은 항목이 아니라 하위 항목의 heading_path다 (이전 동작 유지)."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n### 운영\n- 재시작 금지\n")
    resp = _brief(tmp_path)
    items = _items(resp, "constraints")
    assert not [i for i in items if i.get("scaffold_only")]
    assert [h["text"] for h in items[0]["heading_path"]] == ["제약"]


# ── 독립 리뷰 지적 회귀 — 내용 있는 항목 안의 깊은 제목은 빈 틀 아래여도 남는다 ─────────────────────────


def test_deep_rule_heading_over_empty_bullet_inside_constraint_item_is_shown(tmp_path):
    """4단계 이하 제목은 상위 항목 안에 남는다 — 빈 불릿 줄만 빼고 제목은 지우지 않는다(3단계 scaffold_only와 같은 결과)."""
    _ctx(tmp_path, "# Devtrail\n\n## 제약\n\n- 공식 영역 직접 쓰기 금지\n\n#### main 브랜치에 직접 push 금지\n\n- \n\n"
                   "#### 배포 규칙\n\n- 태그로만 배포\n")
    resp = _brief(tmp_path)
    (item,) = _items(resp, "constraints")
    lines = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md")
    n = lines.index("#### main 브랜치에 직접 push 금지") + 1
    assert any(s["start_line"] <= n <= s["end_line"] for s in item["segments"])
    assert {"lines": [n + 2, n + 2], "reason": "empty_scaffolding"} in item["cleaned"]
    assert not any(c["reason"] == "empty_section" for c in item.get("cleaned", []))
    assert "#### main 브랜치에 직접 push 금지" in resp["text"] and "- 태그로만 배포" in resp["text"]


@pytest.mark.parametrize("rel", ["40_AgentMemory/01_CurrentFocus.md", "40_AgentMemory/06_Lessons.md"])
def test_deep_memory_rule_heading_over_empty_bullet_is_shown(tmp_path, rel):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, rel, _fm(type="agent_memory", scope="global", updated_at=TODAY) + "# Memory\n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n### 규칙\n- 실제 기억 규칙\n#### 운영 DB 직접 수정 금지\n- \n#### 기타\n- 다른 규칙\n")
    resp = _brief(tmp_path)
    (rule,) = [i for i in _items(resp, "constraints") if i.get("memory_rule")]
    shown = "\n".join(s["text"] for s in rule["segments"])
    assert "#### 운영 DB 직접 수정 금지" in shown and "- 다른 규칙" in shown
    assert "#### 운영 DB 직접 수정 금지" in resp["text"]


def test_todo_heading_over_empty_bullet_beside_real_items_is_shown_in_follow_ups(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00",
             _process("- 다음 일\n\n### 운영 DB 마이그레이션 롤백 확인\n\n- "))
    _open_loops_block(tmp_path, "- (2026-11-10) 실제 할 일\n\n### 결제 웹훅 재시도 미해결\n\n- \n")
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert fu["state"] == "has_items"
    shown = "\n".join(s["text"] for i in fu["items"] for s in i["segments"])
    for heading in ("### 운영 DB 마이그레이션 롤백 확인", "### 결제 웹훅 재시도 미해결"):
        assert heading in shown and heading in resp["text"]


def test_exact_template_sections_are_cleaned_but_heading_over_empty_bullet_is_not_a_follow_up(tmp_path):
    """템플릿과 정확히 같은 빈 절(`## 배경`·`## 목표`)만 지운다. 빈 불릿 위 `### 기타`는 지우지 않지만 할 일로도 보지 않는다."""
    _ctx(tmp_path, TEMPLATE_CONTEXT)
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("### 기타\n\n- "))
    resp = _brief(tmp_path)
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons["배경"] == reasons["목표"] == "template_section"
    assert "## 목표" not in resp["text"]
    fu = _section(resp, "follow_ups")
    assert [s["state"] for s in fu["sources_checked"] if s["source"] == "next_session"] == ["headings_only"]
    assert fu["state"] == "unknown"
    assert "### 기타" in resp["text"]


@pytest.mark.parametrize("where", ["open_loops", "next_session"])
def test_heading_over_empty_bullet_in_follow_up_record_is_named_in_gap(tmp_path, where):
    """빈 불릿을 거느린 후속 기록 안의 제목(할 일일 수 있다)은 지우지 않고, 확인 불가 gap에 건수·줄과 함께 본문에 남는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    if where == "open_loops":
        _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
        _open_loops_block(tmp_path, "### 결제 웹훅 재시도 미해결\n\n- \n")
        rel, heading = "40_AgentMemory/05_OpenLoops.md", "### 결제 웹훅 재시도 미해결"
    else:
        _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("### 운영 DB 롤백 확인\n\n- "))
        rel, heading = "60_Candidates/SessionHandoffs/Devtrail/p1.md", "### 운영 DB 롤백 확인"
    resp = _brief(tmp_path)
    assert _section(resp, "follow_ups")["state"] == "unknown"
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")
    n = _file_lines(tmp_path, rel).index(heading) + 1
    assert gap["headings"] == [{"line": n, "text": heading}]
    assert "제목 1개만 남았다" in gap["message"] and f"L{n} {heading}" in resp["text"]
    assert "follow_up_section_empty" not in {g["code"] for g in _items(resp, "gaps")}


# ── 사용자 변경 지시: 템플릿과 정확히 같은 빈 틀만 지우고 나머지 제목은 남겨 적용 범위를 보존한다 ──────────────────


def _template_sections(text: str) -> dict[str, tuple[str, ...]]:
    """렌더된 템플릿에서 '자리표시 줄만 거느린 절' — 제목 줄 → 본문(빈 줄 뺀, 끝 공백 무시) 목록."""
    lines = text.splitlines()
    out: dict[str, tuple[str, ...]] = {}
    for i, line in enumerate(lines):
        h = pb._heading(line)
        if not h:
            continue
        body: list[str] = []
        for nxt in lines[i + 1:]:
            nh = pb._heading(nxt)
            if nh and nh[0] <= h[0]:
                break
            if nxt.strip():
                body.append(nxt.rstrip())
        if body and all(b.strip() in pb._SCAFFOLD_LINES or pb._EMPTY_BULLET_RE.match(b.strip()) for b in body):
            out[line.rstrip()] = tuple(body)
    return out


def test_template_catalog_matches_real_repository_templates(tmp_path):
    """비교 기준은 저장소의 실제 템플릿 출력이다 — 목록이 템플릿과 어긋나면 이 테스트가 깨진다."""
    from app.services.wiki_service import WikiService

    ws = WikiService(tmp_path)
    context = ws._default_project_context("Devtrail")
    assert _template_sections(context) == pb._CONTEXT_TEMPLATE_SECTIONS
    memory = ws._default_agent_memory("Lessons")
    # 메모리 템플릿의 빈 절은 문서 제목(1단계, 하나뿐) + 자리표시 한 줄 — 문서 제목 줄(위치)과 자리표시 줄(문자열)로 빠진다
    assert _template_sections(memory) == {"# Lessons": ("_Fill this note with durable context that future agents should know._",)}
    template_lines = {l.strip() for l in (context + memory).splitlines()}
    assert pb._SCAFFOLD_LINES <= template_lines  # 자리표시 줄은 모두 실제 템플릿에 있는 문자열이다


def test_real_init_project_template_is_cleaned_to_its_one_real_constraint(tmp_path):
    """제품 함수(init-project)가 만든 Context.md 그대로 — 템플릿 빈 절은 지우고 실제 문장이 든 절은 남긴다."""
    from app.services.wiki_service import WikiService

    WikiService(tmp_path).init_project("Devtrail")
    resp = _brief(tmp_path)
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons["배경"] == reasons["목표"] == "template_section"
    assert reasons["Devtrail — Project Context"] == "repeated_title"
    (cons,) = _items(resp, "constraints")
    assert "- 사용자의 결정이 필요한 부분은 진행하지 말고 질문한다" in cons["segments"][0]["text"]
    assert "## 관련 문서" in resp["text"]


@pytest.mark.parametrize("section, why", [
    ("## 목표\n\n- \n- \n", "빈 불릿 둘 — 템플릿은 하나"),
    ("## 목표\n\n* \n", "다른 불릿 기호"),
    ("### 목표\n\n- \n", "다른 제목 단계"),
    ("##  목표\n\n- \n", "제목 띄어쓰기 다름"),
    ("## 목표들\n\n- \n", "비슷한 제목"),
    ("## 배경\n\n_(이 프로젝트가 왜 존재하는지)_\n", "자리표시와 비슷한 사용자 문장"),
    ("## 배경\n\n_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_\n- \n", "자리표시 + 빈 불릿"),
    ("## 목표\n\n```\n- \n```\n", "코드 블록 안 빈 불릿"),
    ("## 운영 서버에서만 적용\n\n- \n", "템플릿에 없는 제목"),
])
def test_near_template_sections_keep_their_heading(tmp_path, section, why):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n\n" + section)
    resp = _brief(tmp_path)
    heading = section.split("\n", 1)[0]
    assert heading in resp["text"], why
    n = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md").index(heading) + 1
    (item,) = [i for i in _all_items(resp) if i["span"][0] == n]  # `### 목표`는 `## 제약` 아래라 제약 항목이다
    assert any(s["start_line"] <= n <= s["end_line"] for s in item["segments"])
    assert [c["reason"] for c in _section(resp, "context").get("cleaned_sections", [])] == ["repeated_title"]  # `# Devtrail`만


def test_exact_template_section_with_trailing_whitespace_or_crlf_is_still_template(tmp_path):
    """비교는 끝 공백만 무시한다 — 편집기가 `- `의 끝 공백을 지우거나 CRLF로 저장해도 같은 템플릿 절이다."""
    body = "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n\n## 목표\n\n-\n\n## 배경 \n\n_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_  \n"
    _ctx(tmp_path, body.replace("\n", "\r\n"))
    resp = _brief(tmp_path)
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons == {"Devtrail": "repeated_title", "목표": "template_section", "배경": "template_section"}


def test_non_template_context_heading_over_empty_bullet_is_kept_as_scaffold_only_item(tmp_path):
    """예전에는 맥락 절 전체가 빈 불릿이면 제목째 정리했다 — 이제 제목은 남기고 빈 틀 줄만 뺀다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n\n## 운영 서버에서만 적용\n\n- \n\n## 메모\n\n- 실제 메모\n")
    resp = _brief(tmp_path)
    ctx = _items(resp, "context")
    item = next(i for i in ctx if i["label"] == "운영 서버에서만 적용")
    assert item["scaffold_only"] is True and item["segments"][0]["text"] == "## 운영 서버에서만 적용"
    assert item["cleaned"] == [{"lines": [item["span"][0] + 2] * 2, "reason": "empty_scaffolding"}]
    assert "본문은 빈 틀뿐 — 제목만 남김" in resp["text"]
    assert _section(resp, "constraints")["state"] == "items"


def test_template_heading_with_real_subsection_keeps_scope(tmp_path):
    """`## 목표` 아래 빈 불릿 + 실제 하위 절 — 절 전체가 템플릿과 다르므로 `## 목표`는 하위 항목의 상위 제목으로 남는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n\n## 목표\n\n- \n\n### 분기 목표\n\n- 실제 목표\n")
    resp = _brief(tmp_path)
    item = next(i for i in _items(resp, "context") if i["label"] == "분기 목표")
    assert [h["text"] for h in item["heading_path"]] == ["목표"]
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons["목표"] == "parent_heading"
    assert "⤷ 상위 제목: L" in resp["text"] and "## 목표" in resp["text"]


def test_template_and_real_content_mixed_keeps_heading_and_content(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n\n## 목표\n\n- \n- 실제 목표\n")
    resp = _brief(tmp_path)
    item = next(i for i in _items(resp, "context") if i["label"] == "목표")
    assert item["segments"][0]["text"].startswith("## 목표") and "- 실제 목표" in item["segments"][-1]["text"]
    assert "scaffold_only" not in item


def test_heading_equal_to_project_name_is_not_removed_by_similarity(tmp_path):
    """예전에는 프로젝트 이름과 같은 제목을 어디서든 '반복 제목'으로 지웠다 — 이제 문서 제목 줄만 위치로 뺀다."""
    _ctx(tmp_path, "\n# Devtrail — Project Context\n\n## 제약\n\n- 공통 규칙\n\n### Devtrail\n\n- 이 저장소에서만 적용\n")
    resp = _brief(tmp_path)
    shown = "\n".join(s["text"] for i in _items(resp, "constraints") for s in i["segments"])
    assert "### Devtrail" in shown and "# Devtrail — Project Context" not in resp["text"]


def test_multiple_h1_headings_are_all_kept_as_scope(tmp_path):
    """1단계 제목이 여럿이면 어느 것도 문서 제목으로 보지 않는다 — 각각이 적용 범위일 수 있다."""
    _ctx(tmp_path, "\n# 운영\n\n## 제약\n\n- 재시작 금지\n\n# 로컬\n\n## 제약\n\n- 마음대로 재시작\n")
    resp = _brief(tmp_path)
    paths = [[h["text"] for h in i["heading_path"]] for i in _items(resp, "constraints")]
    assert paths == [["운영"], ["로컬"]]


def test_memory_block_keeps_template_like_heading_but_drops_block_heading(tmp_path):
    """메모리 파일에는 템플릿 빈 절이 없다 — `## 목표` + 빈 불릿도 남는다. 블록 머리 제목 `## Devtrail`만 뺀다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", _fm(type="agent_memory", scope="global", updated_at=TODAY) + "# Lessons\n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n### 목표\n\n- \n\n### Devtrail\n\n- 프로젝트 이름과 같은 하위 제목\n")
    resp = _brief(tmp_path)
    (item,) = [i for i in _items(resp, "context") if i["kind"] == "lessons"]
    text = "\n".join(s["text"] for s in item["segments"])
    assert "### 목표" in text and "### Devtrail" in text
    assert not any(l == "## Devtrail" for l in text.splitlines())
    assert {"lines": [item["span"][0] + 1] * 2, "reason": "repeated_title"} in item["cleaned"]


def test_other_project_block_headings_never_leak_and_limit_stops_at_block_end(tmp_path):
    """다른 프로젝트 블록의 제목(빈 불릿을 거느린 것 포함)은 싣지 않고, 우리 블록 끝 제목의 상위 판정이 그 블록을 보지 않는다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, "40_AgentMemory/01_CurrentFocus.md", _fm(type="agent_memory", scope="global", updated_at=TODAY)
       + "# Current Focus\n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n- 지금 하는 일\n\n### 운영 서버 범위\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Other"} -->\n'
       + "## Other\n\n#### 비밀 프로젝트 제목\n\n- \n")
    resp = _brief(tmp_path)
    assert "비밀 프로젝트 제목" not in json.dumps(resp, ensure_ascii=False)
    (item,) = [i for i in _items(resp, "context") if i["kind"] == "current_focus"]
    assert "### 운영 서버 범위" in item["segments"][-1]["text"]


def test_scaffold_only_heading_cut_by_budget_keeps_exact_omission(tmp_path, monkeypatch):
    """제약이 예산을 다 쓰면 제목만 남은 맥락 절도 조용히 사라지지 않고 정확한 줄 범위·이어읽기 인자로 남는다."""
    filler = "".join(f"- 긴 규칙 {i} " + "가" * 180 + "\n" for i in range(130))
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + filler + "\n## 운영 서버 범위\n\n- \n")
    resp = _brief(tmp_path)
    n = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md").index("## 운영 서버 범위") + 1
    item = next(i for i in _items(resp, "context") if i["label"] == "운영 서버 범위")
    assert item["shown"] == "omitted" and item["scaffold_only"] is True
    om = next(o for o in resp["omissions"] if o["item"] == item["id"])
    assert om["lines"] == [n, n] and om["read"]["start_line"] == n
    assert om["read"]["expected_version"] == item["source_version"]
    page = _mcp_read_note(monkeypatch, tmp_path, om["read"])  # 반환된 인자 그대로 회수한다
    assert page["ok"] and page["content"].splitlines()[0] == "## 운영 서버 범위"
    assert resp["critical_omission"] is True  # 제약 일부도 잘렸다
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS


def test_parent_heading_whose_children_are_all_template_sections_is_kept(tmp_path):
    """하위 절이 모두 템플릿 빈 절로 지워지면 상위 제목을 실을 하위 항목이 없다 — 상위 제목을 제 항목으로 남긴다(퍼즈 재현)."""
    _ctx(tmp_path, "\n# 운영\n\n## 배경\n\n_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_\n\n## 목표\n\n- \n\n"
                   "# 로컬\n\n## 제약\n\n- 마음대로 재시작\n")
    resp = _brief(tmp_path)
    n = _file_lines(tmp_path, "30_Projects/Devtrail/Context.md").index("# 운영") + 1
    item = next(i for i in _items(resp, "context") if i["span"][0] == n)
    assert item["segments"][0]["text"] == "# 운영" and "# 운영" in resp["text"]
    reasons = {c["heading"]: c["reason"] for c in _section(resp, "context")["cleaned_sections"]}
    assert reasons == {"배경": "template_section", "목표": "template_section", "로컬": "parent_heading"}
    (cons,) = _items(resp, "constraints")
    assert [h["text"] for h in cons["heading_path"]] == ["로컬"]


# ── 독립 리뷰 지적 회귀 — 문서 제목 판정, 빈 틀 아래 제목과 후속 상태 ─────────────────────────────────────────


@pytest.mark.parametrize("body, meta_title", [
    ("\n# 운영 서버에서만 적용\n\n## 제약\n\n- 직접 재시작 금지\n", "Devtrail 컨텍스트"),  # 응답 제목은 frontmatter에서
    ("\n```bash\n# 예시 주석\n```\n\n# 운영 서버에서만 적용\n\n## 제약\n\n- 직접 재시작 금지\n", None),  # 코드 블록 안 '# ' 줄이 제목
    ("\n#\t운영 서버에서만 적용\n\n## 제약\n\n- 직접 재시작 금지\n", None),  # 탭 구분 — 응답 제목은 파일명
])
def test_lone_h1_is_kept_unless_it_is_the_response_title(tmp_path, body, meta_title):
    """1단계 제목 하나가 응답의 문서 제목(sources[].title)으로 실리지 않으면 그 제목은 적용 범위로 남는다."""
    meta = dict(type="project_context", project="Devtrail", status="active", updated_at=TODAY)
    if meta_title:
        meta["title"] = meta_title
    _w(tmp_path, "30_Projects/Devtrail/Context.md", _fm(**meta) + body)
    resp = _brief(tmp_path)
    (cons,) = _items(resp, "constraints")
    assert [h["text"] for h in cons["heading_path"]] == ["운영 서버에서만 적용"]
    assert "운영 서버에서만 적용" in resp["text"]
    src = next(s for s in resp["sources"] if s["path"].endswith("Context.md"))
    assert src["title"] != "운영 서버에서만 적용"


def test_lone_h1_that_is_the_response_title_is_not_repeated(tmp_path):
    _ctx(tmp_path, "\n# 운영 서버에서만 적용\n\n## 제약\n\n- 직접 재시작 금지\n")
    resp = _brief(tmp_path)
    (cons,) = _items(resp, "constraints")
    assert "heading_path" not in cons
    assert next(s for s in resp["sources"] if s["path"].endswith("Context.md"))["title"] == "운영 서버에서만 적용"


def test_memory_block_h1_is_kept_when_file_title_comes_from_frontmatter(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _w(tmp_path, "40_AgentMemory/01_CurrentFocus.md", _fm(type="agent_memory", scope="global", title="CurrentFocus",
                                                         updated_at=TODAY)
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "# 운영 서버에서만 적용\n### 금지\n- 직접 재시작\n")
    resp = _brief(tmp_path)
    (rule,) = [i for i in _items(resp, "constraints") if i.get("memory_rule")]
    assert [h["text"] for h in rule["heading_path"]] == ["운영 서버에서만 적용"]


@pytest.mark.parametrize("next_session, state", [
    ("- 없음\n\n### 기타\n\n- ", "headings_only"),  # '없음' + 빈 틀 아래 제목 — 있음도 없음도 아니다
    ("### A\n\n- \n\n### B", "items"),  # 빈 틀 없이 적은 제목 B는 내용이다
    ("### 배포\n- \n#### 확인\n- ", "headings_only"),  # 중첩된 빈 틀 아래 제목뿐
    ("- 실제 할 일\n\n### 기타\n\n- ", "items"),
    ("- 없음", "explicit_none"),
    ("### 기타\n\n- 없음", "explicit_none"),
])
def test_next_session_state_ignores_headings_that_only_hold_scaffolding(tmp_path, next_session, state):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process(next_session))
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert [s["state"] for s in fu["sources_checked"] if s["source"] == "next_session"] == [state]
    for line in next_session.splitlines():
        if line.startswith("#"):
            assert line in resp["text"]  # 어느 경우든 제목은 본문(발췌 또는 gap)에 남는다


def test_constraint_with_scaffold_heading_and_bare_heading_counts_as_items(tmp_path):
    """빈 틀 아래 제목과 빈 틀 없이 적은 제목이 한 항목에 있으면 내용 있는 제약이다(scaffold_only 아님)."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n#### A\n\n- \n\n#### main 브랜치 직접 push 금지\n")
    resp = _brief(tmp_path)
    assert _section(resp, "constraints")["state"] == "items"
    assert not [i for i in _items(resp, "constraints") if i.get("scaffold_only")]


def test_open_loops_none_plus_scaffold_heading_is_unknown_like_next_session(tmp_path):
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
    _open_loops_block(tmp_path, "- 없음\n\n### 기타\n\n- \n")
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert {s["source"]: s["state"] for s in fu["sources_checked"]}["project_open_loops"] == "headings_only"
    assert fu["state"] == "unknown" and "### 기타" in resp["text"]


# ── 독립 리뷰 잔존 지적: 제목만 남은 기록의 긴 제목이 JSON에서 조용히 잘리고 회수 수단도 없었다 ──────────────────


def _headings_only_record(vault: Path, where: str, heading: str, *, crlf_bom: bool = False) -> tuple[str, int]:
    """where의 후속 기록에 '긴 제목 + 빈 불릿'만 둔다(headings_only). (원문 경로, 제목 줄 번호)."""
    _ctx(vault, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    if where == "open_loops":
        _handoff(vault, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
        _open_loops_block(vault, heading + "\n\n- \n")
        rel = "40_AgentMemory/05_OpenLoops.md"
    else:
        _handoff(vault, "p1", "process", "s1", "2026-11-10T10:00:00", _process(heading + "\n\n- "))
        rel = "60_Candidates/SessionHandoffs/Devtrail/p1.md"
    if crlf_bom:
        path = vault / rel
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
    return rel, _file_lines(vault, rel).index(heading) + 1


@pytest.mark.parametrize("crlf_bom", [False, True])
@pytest.mark.parametrize("where", ["next_session", "open_loops"])
def test_long_heading_only_follow_up_heading_is_marked_clipped_and_recoverable(tmp_path, monkeypatch, where, crlf_bom):
    """리뷰 재현: 364자 제목 + 빈 불릿. JSON 제목이 잘린 사실을 표시하고, 반환된 read를 그대로 넘기면 같은 원문 줄이 온다."""
    heading = "### " + "가나다 " * 90  # 364자, 비ASCII
    assert len(heading) == 364
    rel, n = _headings_only_record(tmp_path, where, heading, crlf_bom=crlf_bom)
    resp = _brief(tmp_path)
    fu = _section(resp, "follow_ups")
    assert fu["state"] == "unknown" and FOLLOW_UP_UNKNOWN_TEXT in fu["message"]
    assert not [i for i in _items(resp, "follow_ups") if i["path"] == rel]  # 제목만으로 후속 항목·상태를 만들지 않는다
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")
    version = content_version((tmp_path / rel).read_bytes())
    assert gap["path"] == rel and gap["source_version"] == version
    [h] = gap["headings"]
    assert h["line"] == n and h["text_complete"] is False and h["line_chars"] == 364
    assert len(h["text"]) == pb._FIELD_CHARS and h["text"].endswith("…") and heading.startswith(h["text"][:-1])
    assert h["structured_readable"] is True
    assert h["read"] == {"rel_path": rel, "structured": True, "start_line": n, "max_lines": 1, "expected_version": version}
    page = _mcp_read_note(monkeypatch, tmp_path, h["read"])
    assert page["ok"] and page["start_line"] == page["end_line"] == n and page["content"] == heading
    # 같은 생략이 omissions에도 있다 — 항목이 아니라 gap을 가리키고, 제약이 아니라 critical이 아니다
    [om] = [o for o in resp["omissions"] if o["reason"] == "heading_clipped"]
    assert om["item"] is None and om["gap"] == "follow_up_headings_only" and om["section"] == "gaps"
    assert om["path"] == rel and om["lines"] == [n, n] and om["read"] == h["read"] and om["critical"] is False
    assert om["line_chars"] == 364 and om["first_read_end_line"] == n and om["read_continues"] is False
    assert resp["critical_omission"] is False
    # 본문 gap 줄은 잘렸다는 사실과 회수 위치를 알린다(제목 목록 자체는 원래대로 40자 약식)
    line = next(l for l in resp["text"].splitlines() if l.startswith("- [follow_up_headings_only]"))
    assert "앞부분만 실었다" in line and f"L{n} " in line
    # 원문이 바뀌면 같은 인자의 다시 읽기는 버전 불일치로 거절된다
    path = tmp_path / rel
    path.write_bytes(path.read_bytes() + "- 새 줄\n".encode())
    page = _mcp_read_note(monkeypatch, tmp_path, h["read"])
    assert not page["ok"] and page["error"]["code"] == "version_mismatch"


@pytest.mark.parametrize("width,clipped", [(pb._FIELD_CHARS - 1, False), (pb._FIELD_CHARS, False),
                                           (pb._FIELD_CHARS + 1, True)])
def test_heading_clip_boundary(tmp_path, width, clipped):
    heading = "### " + "나" * (width - 4)
    rel, n = _headings_only_record(tmp_path, "next_session", heading)
    resp = _brief(tmp_path)
    [h] = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")["headings"]
    heading_oms = [o for o in resp["omissions"] if o["reason"] == "heading_clipped"]
    if clipped:
        assert h["text_complete"] is False and h["line_chars"] == width and len(heading_oms) == 1
    else:
        assert h == {"line": n, "text": heading} and not heading_oms


def test_heading_over_read_line_limit_gives_full_read_and_version(tmp_path, monkeypatch):
    """structured 한 줄 상한(16000자)을 넘는 제목은 structured로 못 읽는다 — 전문 읽기 인자와 비교할 버전을 준다."""
    heading = "### " + "다" * (pb.READ_MAX_CHARS + 10)
    rel, n = _headings_only_record(tmp_path, "open_loops", heading)
    resp = _brief(tmp_path)
    assert len(resp["text"]) <= pb.TEXT_MAX_CHARS
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "follow_up_headings_only")
    [h] = gap["headings"]
    assert h["text_complete"] is False and h["structured_readable"] is False and h["read"] == {"rel_path": rel}
    assert gap["source_version"] == content_version((tmp_path / rel).read_bytes())
    assert "16000자를 넘는 한 줄" in gap["message"]
    [om] = [o for o in resp["omissions"] if o["reason"] == "heading_clipped"]
    assert om["structured_readable"] is False and om["first_read_end_line"] == n - 1
    full = _mcp_read_note(monkeypatch, tmp_path, h["read"])
    assert heading in (full if isinstance(full, str) else json.dumps(full, ensure_ascii=False))


def test_long_heading_in_other_project_block_is_never_listed(tmp_path):
    """긴 제목 처리도 블록 경계 안에서만 — 다른 프로젝트 블록의 제목·줄은 gap·omissions 어디에도 없다."""
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n- 규칙 하나\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-10T10:00:00", _process("- 없음"))
    own = "### " + "우리 " * 120
    other = "### OTHER_SECRET " + "남의 " * 120
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md", _fm(type="agent_memory", scope="global", updated_at=TODAY)
       + "# OpenLoops\n\n" + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
       + "## Devtrail\n\n" + own + "\n\n- \n\n"
       + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Other"} -->\n## Other\n\n' + other + "\n\n- \n")
    resp = _brief(tmp_path)
    dump = json.dumps(resp, ensure_ascii=False)
    assert "OTHER_SECRET" not in dump and "남의" not in dump
    ol = _file_lines(tmp_path, "40_AgentMemory/05_OpenLoops.md")
    [om] = [o for o in resp["omissions"] if o["reason"] == "heading_clipped"]
    assert om["lines"] == [ol.index(own) + 1] * 2


def test_long_empty_constraint_heading_in_context_gap_is_recoverable(tmp_path, monkeypatch):
    """Context 제약 빈 틀 gap의 제목 목록도 같은 처리 — 잘린 제목은 표시·회수 인자를 갖는다."""
    heading = "### " + "금지 규칙 " * 50
    _ctx(tmp_path, "\n# Devtrail\n\n## 제약\n\n" + heading + "\n\n- \n")
    resp = _brief(tmp_path)
    gap = next(g for g in _items(resp, "gaps") if g["code"] == "constraint_section_empty")
    [h] = gap["headings"]
    assert h["text_complete"] is False
    page = _mcp_read_note(monkeypatch, tmp_path, h["read"])
    assert page["ok"] and page["content"] == heading
