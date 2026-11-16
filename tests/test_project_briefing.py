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
        < text.index("## 4. 명시적 후속 항목") < text.index("## 5. 정보 부족·판단 한계")


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
    assert "검토한 범위" in sec["message"] and "범위 밖" in sec["message"]
    item = sec["items"][0]
    assert item["follow_up_state"] == "explicit_none" and item["segments"][0]["text"] == "없음"
    assert "명시적 없음 — 이 기록 범위 한정" in resp["text"]

    # 빈 틀("- ")은 '없음'이 아니라 확인 불가다
    _handoff(tmp_path, "p0", "process", "s0", "2026-11-02T10:00:00", _process("- "))
    resp = _brief(tmp_path)
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and "확인 불가" in sec["message"]
    assert any(s["state"] == "empty" for s in sec["sources_checked"])

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
    assert sec["state"] == "unknown"
    assert [s["state"] for s in sec["sources_checked"] if s["source"] == "next_session"] == ["missing"]


def test_partial_read_failure_makes_follow_ups_unknown_not_none(tmp_path, monkeypatch):
    _ctx(tmp_path, "## 배경\n\nx\n")
    _handoff(tmp_path, "p1", "process", "s1", "2026-11-03T10:00:00", _process("없음"))
    _handoff(tmp_path, "p2", "process", "s2", "2026-11-04T10:00:00", _process("- 숨은 후속"))
    _deny_reads(monkeypatch, tmp_path / "60_Candidates/SessionHandoffs/Devtrail/p2.md")
    resp = _brief(tmp_path)
    assert resp["partial"] is True
    sec = _section(resp, "follow_ups")
    assert sec["state"] == "unknown" and sec["complete"] is False
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
    # 내용 일부 또는 위치 안내 줄 중 하나는 반드시 본문에 있다
    assert nxt["path"] in resp["text"]
    om = next(o for o in resp["omissions"] if o["item"] == nxt["id"])
    assert f"생략 L{om['lines'][0]}-L{om['lines'][1]}" in resp["text"]


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
    assert skipped == set(links)
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
