"""structured 근거 검색 (app/services/evidence_search.py, vault_tools.search_evidence)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import vault_tools
from app.services import evidence_search


def _settings(vault: Path, project_map: str = ""):
    return SimpleNamespace(obsidian_vault_root=str(vault), devtrail_project_map=project_map)


def _w(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fm(**meta) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---"]
    return "\n".join(lines) + "\n"


def _projects(vault: Path, *names: str) -> None:
    for name in names:
        _w(vault, f"30_Projects/{name}/Context.md", _fm(project=name) + f"# {name}\n\n## 배경\n\n{name} 배경\n")


def _search(vault: Path, query: str, **kwargs) -> dict:
    return vault_tools.search_evidence(query, settings=_settings(vault), **kwargs)


def _paths(resp: dict) -> list[str]:
    assert resp["ok"], resp
    return [r["path"] for r in resp["results"]]


_LESSONS = (
    "---\nupdated_at: 2026-10-01\n---\n# Lessons\n\n전역 교훈: 고유토큰 확인\n\n"
    '<!-- devtrail-memory-patch: {"scope": "project", "project": "Beta"} -->\n'
    "Beta 교훈: 고유토큰 비밀베타\n\n"
    '<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n'
    "Alpha 교훈: 고유토큰 알파\n\n"
    '<!-- devtrail-memory-patch: {"scope": "global", "project": ""} -->\n'
    "전역 패치: 고유토큰 공통\n\n"
    "<!-- devtrail-memory-patch: {broken -->\n"
    "깨진 marker: 고유토큰 불명\n"
)


# ── 범위 (AC-3) ──────────────────────────────────────────────────────────────


@pytest.fixture()
def scoped_vault(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    _w(tmp_path, "30_Projects/Alpha/Decisions/d1.md", _fm(title="알파 결정", status="accepted") + "고유토큰 알파 결정\n")
    _w(tmp_path, "30_Projects/Beta/Decisions/d1.md", _fm(title="베타 결정", status="accepted") + "고유토큰 베타 결정\n")
    _w(tmp_path, "10_Worklog/Sessions/s-alpha.md", _fm(project="Alpha", status="raw") + "고유토큰 세션 알파\n")
    _w(tmp_path, "10_Worklog/Sessions/s-beta.md", _fm(project="Beta", status="raw") + "고유토큰 세션 베타\n")
    _w(tmp_path, "50_Outputs/Digest/d.md", _fm(type="digest", status="generated") + "고유토큰 다이제스트\n")
    _w(tmp_path, "20_Knowledge/general.md", _fm(title="일반 지식", scope="global") + "고유토큰 공통 지식\n")
    _w(tmp_path, "30_Projects/Alpha/Plans/mislabeled.md", _fm(project="Beta") + "고유토큰 충돌 문서\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", _LESSONS)
    return tmp_path


def test_project_search_excludes_common_other_and_unknown(scoped_vault):
    resp = _search(scoped_vault, "고유토큰", project="alpha", limit=20)
    paths = _paths(resp)
    assert set(paths) == {"30_Projects/Alpha/Decisions/d1.md", "10_Worklog/Sessions/s-alpha.md", "40_AgentMemory/06_Lessons.md"}
    assert resp["scope"]["project"] == "Alpha"
    lessons = next(r for r in resp["results"] if r["path"].endswith("06_Lessons.md"))
    blocks = lessons["attribution"]["blocks"]
    assert [b["project"] for b in blocks] == ["Alpha"] and lessons["attribution"]["blocks_excluded"] == 4
    # 제외된 블록(Beta·전역·불명)은 발췌에도 점수에도 들어오지 않는다
    text = "\n".join(e["text"] for e in lessons["excerpts"])
    assert "알파" in text and "베타" not in text and "공통" not in text and "불명" not in text
    filtered = resp["filtered"]["documents"]
    assert filtered["other_project"] >= 3 and filtered["common"] == 1 and filtered["unknown"] == 1
    assert filtered["conflict"] == 1


def test_include_common_adds_common_but_never_other_projects(scoped_vault):
    resp = _search(scoped_vault, "고유토큰", project="Alpha", include_common=True, limit=20)
    paths = _paths(resp)
    assert "20_Knowledge/general.md" in paths
    assert not any("Beta" in p or "beta" in p for p in paths)
    lessons = next(r for r in resp["results"] if r["path"].endswith("06_Lessons.md"))
    scopes = sorted((b["scope"], b["project"]) for b in lessons["attribution"]["blocks"])
    assert scopes == [("common", ""), ("common", ""), ("project", "Alpha")]
    text = "\n".join(e["text"] for e in lessons["excerpts"])
    assert "베타" not in text and "불명" not in text


def test_include_unattributed_adds_unknown_and_own_conflicts(scoped_vault):
    resp = _search(scoped_vault, "고유토큰", project="Alpha", include_unattributed=True, limit=20)
    paths = _paths(resp)
    assert "50_Outputs/Digest/d.md" in paths and "30_Projects/Alpha/Plans/mislabeled.md" in paths
    conflict = next(r for r in resp["results"] if r["path"].endswith("mislabeled.md"))
    assert conflict["attribution"]["scope"] == "conflict"
    assert conflict["attribution"]["conflict_with"] == ["Alpha", "Beta"]
    # 깨진 marker 블록은 unknown 블록으로 포함되고, 경고가 붙는다
    lessons = next(r for r in resp["results"] if r["path"].endswith("06_Lessons.md"))
    assert ("unknown", "") in {(b["scope"], b["project"]) for b in lessons["attribution"]["blocks"]}
    assert any("marker" in w for w in lessons["warnings"])


def test_no_project_searches_whole_vault_and_reports_attribution(scoped_vault):
    resp = _search(scoped_vault, "고유토큰", limit=20)
    by_path = {r["path"]: r for r in resp["results"]}
    assert by_path["50_Outputs/Digest/d.md"]["attribution"]["scope"] == "unknown"
    assert by_path["20_Knowledge/general.md"]["attribution"]["scope"] == "common"
    assert by_path["10_Worklog/Sessions/s-beta.md"]["attribution"] == {
        "scope": "project", "project": "Beta", "evidence": ["meta:project=Beta"],
    }


def test_project_name_in_body_is_not_attribution(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "50_Outputs/Digest/x.md", "# Digest\n\nAlpha 프로젝트 고유토큰 언급\n")
    resp = _search(tmp_path, "고유토큰", project="Alpha")
    assert resp["results"] == [] and resp["filtered"]["documents"] == {"unknown": 1}


def test_zero_results_do_not_widen_scope(scoped_vault):
    resp = _search(scoped_vault, "비밀베타", project="Alpha")
    assert resp["ok"] and resp["results"] == [] and resp["total_matches"] == 0
    assert resp["scope"]["include_common"] is False
    assert any(w["code"] == "no_match_in_scope" for w in resp["warnings"])


def test_kind_filter_applies_before_cut(tmp_path):
    _projects(tmp_path, "Alpha")
    for i in range(10):
        _w(tmp_path, f"30_Projects/Alpha/Plans/p{i}.md", "고유토큰 " * 3 + "\n")
    _w(tmp_path, "60_Candidates/Problems/prob.md", _fm(project="Alpha", status="candidate") + "고유토큰\n")
    resp = _search(tmp_path, "고유토큰", project="Alpha", kinds=["problem"], limit=1)
    assert _paths(resp) == ["60_Candidates/Problems/prob.md"] and resp["total_matches"] == 1


def test_unresolved_project_is_error_not_whole_vault(scoped_vault):
    resp = _search(scoped_vault, "고유토큰", project="Gamma")
    assert not resp["ok"] and resp["error"]["code"] == "project_unresolved"
    assert "results" not in resp


def test_repo_basename_is_not_used_for_project(scoped_vault, tmp_path_factory):
    repo = tmp_path_factory.mktemp("repos") / "alpha"
    (repo / ".git").mkdir(parents=True)
    resp = _search(scoped_vault, "고유토큰", project=str(repo))
    assert not resp["ok"] and resp["error"]["code"] == "project_unresolved"
    assert "확정하지 않습니다" in resp["error"]["project_resolution"]["hint"]


def test_alias_mapping_resolves_project(scoped_vault, tmp_path_factory):
    map_path = tmp_path_factory.mktemp("cfg") / "map.json"
    map_path.write_text(json.dumps({"projects": {"Alpha": {"aliases": ["al"]}}}), encoding="utf-8")
    resp = vault_tools.search_evidence("고유토큰", project="al", settings=_settings(scoped_vault, str(map_path)))
    assert resp["ok"] and resp["scope"]["project"] == "Alpha"
    assert resp["scope"]["project_resolution"]["method"] == "alias"


# ── 순위 (AC-4) ──────────────────────────────────────────────────────────────


def test_exact_session_evidence_beats_single_word_canonical(tmp_path):
    _projects(tmp_path, "Alpha")
    for i in range(6):
        _w(tmp_path, f"30_Projects/Alpha/Decisions/mcp-{i}.md", _fm(title=f"FastMCP 결정 {i}", status="accepted") + f"FastMCP 도입 {i}\n" + "FastMCP\n" * 20)
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/proc.md",
       _fm(project="Alpha", handoff_type="process", session_id="s1", status="candidate")
       + "# Process\n\n" + "기타 기록\n" * 30 + "- FastMCP 개명으로 mcp import 깨짐 → pin 고정\n")
    resp = _search(tmp_path, "FastMCP 개명 pin", project="Alpha")
    assert resp["results"][0]["path"] == "60_Candidates/SessionHandoffs/Alpha/proc.md"
    top = resp["results"][0]
    assert top["relevance"]["token_coverage"] == "3/3" and top["relevance"]["window_coverage"] == "3/3"
    # 정답 줄이 문서 후반(34행)이어도 발췌가 그 줄을 가리킨다
    assert top["excerpts"][0]["start_line"] == top["total_lines"]
    assert "FastMCP" in top["excerpts"][0]["text"]
    # legacy는 같은 질의에서 stable을 무조건 앞에 둔다 — 비교 기록용
    legacy = vault_tools.search_vault("FastMCP 개명 pin", limit=5, settings=_settings(tmp_path))
    assert legacy[0].status == "stable"


def test_same_group_prefers_canonical(tmp_path):
    _w(tmp_path, "10_Worklog/Sessions/a.md", "알파토큰 베타토큰 원문\n")
    _w(tmp_path, "60_Candidates/Knowledge/b.md", "알파토큰 베타토큰 후보\n")
    _w(tmp_path, "20_Knowledge/c.md", "알파토큰 베타토큰 정본\n")
    resp = _search(tmp_path, "알파토큰 베타토큰")
    assert [r["record_tier"] for r in resp["results"]] == ["stable", "candidate", "raw"]


def test_window_coverage_beats_scattered_large_raw(tmp_path):
    scattered = "가나다토큰\n" + "채움 줄\n" * 200 + "라마바토큰\n" + "채움 줄\n" * 200 + "사아자토큰\n"
    _w(tmp_path, "20_Knowledge/big.md", scattered)
    _w(tmp_path, "10_Worklog/Sessions/exact.md", "결론: 가나다토큰 라마바토큰 사아자토큰 함께 확인\n")
    resp = _search(tmp_path, "가나다토큰 라마바토큰 사아자토큰")
    assert _paths(resp)[0] == "10_Worklog/Sessions/exact.md"
    assert resp["results"][1]["relevance"]["window_coverage"] == "1/3"


def test_repetition_is_capped(tmp_path):
    _w(tmp_path, "10_Worklog/Sessions/spam.md", "반복토큰 " * 500 + "\n")
    _w(tmp_path, "10_Worklog/Sessions/exact.md", "반복토큰 한 번과 정답토큰\n")
    resp = _search(tmp_path, "반복토큰 정답토큰")
    assert _paths(resp)[0] == "10_Worklog/Sessions/exact.md"


def test_phrase_match_breaks_tie_in_same_coverage(tmp_path):
    _w(tmp_path, "20_Knowledge/split.md", "nightly 그리고 auto 그리고 promote\n")
    _w(tmp_path, "10_Worklog/Sessions/phrase.md", "nightly auto promote 실패\n")
    resp = _search(tmp_path, "nightly auto promote")
    assert _paths(resp)[0] == "10_Worklog/Sessions/phrase.md"
    assert resp["results"][0]["relevance"]["phrase"] and not resp["results"][1]["relevance"]["phrase"]


def test_ranking_is_deterministic(scoped_vault):
    a = _search(scoped_vault, "고유토큰 알파", limit=20)
    b = _search(scoped_vault, "고유토큰 알파", limit=20)
    assert _paths(a) == _paths(b)


def test_superseded_and_archive_are_history(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/Alpha/Decisions/old.md", _fm(title="옛 결정", status="superseded") + "결정토큰 옛\n")
    _w(tmp_path, "60_Candidates/_Archive/Decisions/arch.md", _fm(project="Alpha", status="candidate") + "결정토큰 보관\n")
    _w(tmp_path, "30_Projects/Alpha/Decisions/new.md", _fm(title="새 결정", status="accepted") + "결정토큰 새\n")
    resp = _search(tmp_path, "결정토큰", project="Alpha")
    assert _paths(resp) == ["30_Projects/Alpha/Decisions/new.md"] and resp["filtered"]["documents"]["history"] == 2
    hist = _search(tmp_path, "결정토큰", project="Alpha", include_history=True)
    classes = {r["path"]: r["status"]["class"] for r in hist["results"]}
    assert classes == {
        "30_Projects/Alpha/Decisions/new.md": "known",
        "30_Projects/Alpha/Decisions/old.md": "history",
        "60_Candidates/_Archive/Decisions/arch.md": "history",
    }
    assert _paths(hist)[0] == "30_Projects/Alpha/Decisions/new.md"  # 같은 그룹이면 이력은 뒤


def test_unknown_status_is_not_certified(tmp_path):
    _w(tmp_path, "20_Knowledge/x.md", _fm(status="wip-maybe") + "상태토큰\n")
    _w(tmp_path, "20_Knowledge/y.md", "상태토큰 없음\n")
    resp = _search(tmp_path, "상태토큰")
    by = {r["path"]: r for r in resp["results"]}
    assert by["20_Knowledge/x.md"]["status"]["class"] == "unknown"
    assert any("인증하지 않습니다" in w for w in by["20_Knowledge/x.md"]["warnings"])
    assert by["20_Knowledge/y.md"]["status"] == {"declared": None, "class": "absent", "reason": "status 없음"}
    assert "valid" not in json.dumps(resp)


# ── 결과 계약 (AC-5) ─────────────────────────────────────────────────────────


def test_result_fields_and_source_version(tmp_path):
    _projects(tmp_path, "Alpha")
    path = _w(tmp_path, "30_Projects/Alpha/Problems/p.md",
              _fm(title="문제", status="accepted", updated_at="2026-10-02", type="problem") + "# 문제\n\n원인토큰 설명\n")
    resp = _search(tmp_path, "원인토큰", project="Alpha")
    r = resp["results"][0]
    assert r["kind"] == "problem" and r["kind_source"] == "path" and r["declared_type"] == "problem"
    assert r["record_tier"] == "stable" and r["status"]["declared"] == "accepted"
    assert r["time"] == {"value": "2026-10-02", "source": "meta:updated_at"}
    assert r["attribution"]["evidence"] == ["path:30_Projects/Alpha/"]
    assert r["matched_fields"] == {"원인토큰": ["body"]}
    assert r["excerpts"] == [{"start_line": 9, "end_line": 9, "text": "원인토큰 설명", "matched_terms": ["원인토큰"], "truncated": False}]
    assert r["source_version"] == evidence_search.read_source_text(path).version
    assert (resp["returned"], resp["total_matches"], resp["has_more"], resp["next_cursor"], resp["partial"]) == (1, 1, False, None, False)


def test_excerpt_line_numbers_match_read_source(tmp_path):
    body = "\n".join(f"줄 {i}" for i in range(1, 60)) + "\n결정적 근거토큰 여기\n" + "\n".join(f"뒤 {i}" for i in range(20))
    _w(tmp_path, "10_Worklog/Sessions/long.md", _fm(status="raw") + body + "\n")
    r = _search(tmp_path, "근거토큰")["results"][0]
    e = r["excerpts"][0]
    page = vault_tools.read_source(r["path"], start_line=e["start_line"], max_lines=e["end_line"] - e["start_line"] + 1,
                                   expected_version=r["source_version"], settings=_settings(tmp_path))
    assert page["ok"] and page["content"] == e["text"]


def test_at_most_two_excerpts_of_800_chars(tmp_path):
    lines = []
    for i in range(5):
        lines += ["발췌토큰 " + "가" * 100] + ["채움"] * 10
    _w(tmp_path, "20_Knowledge/many.md", "\n".join(lines) + "\n")
    _w(tmp_path, "20_Knowledge/longline.md", "앞" * 3000 + " 발췌토큰 " + "뒤" * 3000 + "\n")
    resp = _search(tmp_path, "발췌토큰")
    for r in resp["results"]:
        assert len(r["excerpts"]) <= 2
        assert all(len(e["text"]) <= 800 for e in r["excerpts"])
    clip = next(r for r in resp["results"] if r["path"].endswith("longline.md"))["excerpts"][0]
    assert clip["truncated"] and "발췌토큰" in clip["text"]
    assert clip["line_clip"]["line_chars"] == 6006 and clip["line_clip"]["char_start"] > 0


def test_limit_defaults_and_cursor_paging(tmp_path):
    for i in range(12):
        _w(tmp_path, f"20_Knowledge/k{i:02d}.md", f"페이지토큰 {i}\n")
    first = _search(tmp_path, "페이지토큰")
    assert first["returned"] == 5 and first["total_matches"] == 12 and first["has_more"]
    seen = _paths(first)
    cursor = first["next_cursor"]
    while cursor:
        page = _search(tmp_path, "페이지토큰", cursor=cursor)
        assert page["ok"] and page["offset"] == len(seen)
        seen += _paths(page)
        cursor = page["next_cursor"]
    assert seen == sorted(seen) and len(seen) == 12 and len(set(seen)) == 12


def test_response_budget_is_respected(tmp_path):
    for i in range(20):
        _w(tmp_path, f"20_Knowledge/b{i:02d}.md", (f"예산토큰 {i} " + "가" * 700 + "\n" + "채움\n" * 10) * 2)
    resp = _search(tmp_path, "예산토큰", limit=20)
    assert resp["budget"]["used_chars"] <= 12000
    assert len(json.dumps(resp, ensure_ascii=False)) == resp["budget"]["used_chars"]
    assert resp["returned"] < 20 and resp["has_more"] and resp["budget"]["stopped_by"] == "budget"
    small = _search(tmp_path, "예산토큰", limit=20, max_chars=3000)
    assert len(json.dumps(small, ensure_ascii=False)) <= 3000 and small["returned"] >= 1


def test_duplicate_sources_are_collapsed_explicitly(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/proc.md",
       _fm(project="Alpha", handoff_type="process", session_id="sess-9") + "중복토큰 Process 본문\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/plan.md",
       _fm(project="Alpha", handoff_type="plan", session_id="sess-9") + "중복토큰 Plan 본문\n")
    _w(tmp_path, "10_Worklog/Sessions/sess.md", _fm(project="Alpha", session_id="sess-9", type="session") + "# 세션\n\n중복토큰 Process 본문\n")
    _w(tmp_path, "20_Knowledge/Alpha/copy-a.md", "같은 본문 중복토큰\n")
    _w(tmp_path, "30_Projects/Alpha/Plans/copy-b.md", "같은 본문 중복토큰\n")
    resp = _search(tmp_path, "중복토큰", project="Alpha", limit=20)
    paths = _paths(resp)
    assert "60_Candidates/SessionHandoffs/Alpha/plan.md" in paths  # Plan은 내용이 달라 묶지 않는다
    proc = next(r for r in resp["results"] if r["path"].endswith("proc.md"))
    assert proc["duplicates"] == [{"path": "10_Worklog/Sessions/sess.md", "reason": "same_session_id",
                                   "source_version": proc["duplicates"][0]["source_version"]}]
    assert "10_Worklog/Sessions/sess.md" not in paths
    copies = [p for p in paths if "copy-" in p]
    assert len(copies) == 1
    rep = next(r for r in resp["results"] if r["path"] in copies)
    assert rep["duplicates"][0]["reason"] == "same_content"
    assert resp["total_matches"] == len(paths)


# ── 커서·부분 실패·경로 (AC-7) ────────────────────────────────────────────────


def _two_pages(tmp_path: Path) -> dict:
    for i in range(8):
        _w(tmp_path, f"20_Knowledge/c{i}.md", f"커서토큰 {i}\n")
    return _search(tmp_path, "커서토큰", limit=3)


def test_cursor_rejected_when_conditions_change(tmp_path):
    first = _two_pages(tmp_path)
    other = _search(tmp_path, "커서토큰 다른", cursor=first["next_cursor"])
    assert not other["ok"] and other["error"]["code"] == "cursor_mismatch"
    hist = _search(tmp_path, "커서토큰", include_history=True, cursor=first["next_cursor"])
    assert hist["error"]["code"] == "cursor_mismatch"
    # limit은 페이지 크기라 바꿔도 된다
    assert _search(tmp_path, "커서토큰", limit=5, cursor=first["next_cursor"])["ok"]


def test_cursor_rejected_when_documents_change(tmp_path):
    first = _two_pages(tmp_path)
    _w(tmp_path, "20_Knowledge/c3.md", "커서토큰 바뀐 내용\n")
    stale = _search(tmp_path, "커서토큰", limit=3, cursor=first["next_cursor"])
    assert not stale["ok"] and stale["error"]["code"] == "cursor_stale"
    first = _search(tmp_path, "커서토큰", limit=3)
    _w(tmp_path, "20_Knowledge/new.md", "커서토큰 새 문서\n")
    assert _search(tmp_path, "커서토큰", limit=3, cursor=first["next_cursor"])["error"]["code"] == "cursor_stale"


def test_cursor_survives_unrelated_change(tmp_path):
    first = _two_pages(tmp_path)
    _w(tmp_path, "20_Knowledge/unrelated.md", "관계없는 내용\n")
    assert _search(tmp_path, "커서토큰", limit=3, cursor=first["next_cursor"])["ok"]


@pytest.mark.parametrize("cursor", ["!!!", "eyJ2Ijo5fQ"])
def test_garbage_cursor(tmp_path, cursor):
    _w(tmp_path, "20_Knowledge/a.md", "토큰들\n")
    resp = _search(tmp_path, "토큰들", cursor=cursor)
    assert not resp["ok"] and resp["error"]["code"] == "cursor_invalid"


def test_read_failure_is_partial_with_warning(tmp_path, monkeypatch):
    _w(tmp_path, "20_Knowledge/ok.md", "부분토큰\n")
    _w(tmp_path, "20_Knowledge/broken.md", "부분토큰\n")
    real = evidence_search.read_source_text

    def flaky(path):
        if path.name == "broken.md":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(evidence_search, "read_source_text", flaky)
    resp = _search(tmp_path, "부분토큰")
    assert resp["ok"] and resp["partial"] is True and resp["total_matches"] is None
    assert _paths(resp) == ["20_Knowledge/ok.md"]
    assert {"code": "read_failed", "path": "20_Knowledge/broken.md"}.items() <= resp["warnings"][0].items()


def test_symlinks_out_of_scope_are_not_searched(tmp_path):
    vault = tmp_path / "vault"
    _w(vault, "00_Inbox/secret.md", "링크토큰 비밀\n")
    _w(tmp_path, "outside/out.md", "링크토큰 밖\n")
    _w(vault, "20_Knowledge/real.md", "링크토큰 정상\n")
    os.symlink(vault / "00_Inbox" / "secret.md", vault / "20_Knowledge" / "to-inbox.md")
    os.symlink(tmp_path / "outside", vault / "20_Knowledge" / "outdir")
    os.symlink(tmp_path / "outside", vault / "70_Tasks")
    resp = vault_tools.search_evidence("링크토큰", settings=_settings(vault))
    assert _paths(resp) == ["20_Knowledge/real.md"]
    codes = {(w["code"], w["path"]) for w in resp["warnings"]}
    assert ("outside_scope_link", "20_Knowledge/to-inbox.md") in codes
    assert ("symlink_dir_skipped", "20_Knowledge/outdir/") in codes
    assert ("outside_scope_link", "70_Tasks/") in codes
    assert "비밀" not in json.dumps(resp, ensure_ascii=False)


def test_legacy_search_and_read_reject_symlink_bypass(tmp_path):
    _w(tmp_path, "00_Inbox/secret.md", "링크토큰 비밀\n")
    (tmp_path / "20_Knowledge").mkdir(parents=True, exist_ok=True)
    os.symlink(tmp_path / "00_Inbox" / "secret.md", tmp_path / "20_Knowledge" / "to-inbox.md")
    _w(tmp_path, "20_Knowledge/real.md", "링크토큰 정상\n")
    hits = vault_tools.search_vault("링크토큰", settings=_settings(tmp_path))
    assert [h.path for h in hits] == ["20_Knowledge/real.md"]
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note("20_Knowledge/to-inbox.md", settings=_settings(tmp_path))


# ── 인자 검증 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": 21}, {"max_chars": 12001}, {"max_chars": 1999}, {"kinds": ["nope"]},
    {"include_common": True}, {"include_unattributed": True},
])
def test_invalid_arguments(tmp_path, kwargs):
    _w(tmp_path, "20_Knowledge/a.md", "인자토큰\n")
    resp = _search(tmp_path, "인자토큰", **kwargs)
    assert not resp["ok"] and resp["error"]["code"] == "invalid_argument"


def test_query_without_tokens_is_invalid(tmp_path):
    resp = _search(tmp_path, "a ? 가")
    assert not resp["ok"] and resp["error"]["code"] == "invalid_argument"


# ── 리뷰에서 재현된 경계 사례 ─────────────────────────────────────────────────


def test_excluded_block_tags_and_heading_do_not_leak(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    _w(tmp_path, "40_AgentMemory/05_OpenLoops.md",
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Beta"} -->\n'
       "# 베타비밀제목\n- 할 일 #kafkasecret\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n'
       "- 알파 할 일\n")
    assert _search(tmp_path, "kafkasecret", project="Alpha")["results"] == []
    assert _search(tmp_path, "베타비밀제목", project="Alpha")["results"] == []
    resp = _search(tmp_path, "알파", project="Alpha")
    assert resp["results"][0]["title"] == "05_OpenLoops"  # 범위 밖 블록의 제목 줄을 내지 않는다
    beta = _search(tmp_path, "kafkasecret", project="Beta")
    assert beta["results"][0]["matched_fields"]["kafkasecret"] == ["tags", "body"]


def test_budget_holds_with_huge_title_and_many_duplicates(tmp_path):
    _w(tmp_path, "20_Knowledge/big.md", _fm(title="큰제목 " + "가" * 3000) + "예산경계 본문\n")
    resp = _search(tmp_path, "예산경계", max_chars=2000)
    assert len(json.dumps(resp, ensure_ascii=False)) <= 2000 and not resp["budget"]["exceeded"]
    assert len(resp["results"][0]["title"]) <= 200
    for i in range(200):
        _w(tmp_path, f"20_Knowledge/dup{i:03d}.md", "중복예산 같은 본문\n")
    resp = _search(tmp_path, "중복예산")
    assert len(json.dumps(resp, ensure_ascii=False)) <= 12000 and not resp["budget"]["exceeded"]
    assert len(resp["results"][0]["duplicates"]) == 10 and resp["results"][0]["duplicates_omitted"] == 189


def test_four_dash_frontmatter_matches_parser(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    _w(tmp_path, "30_Projects/Alpha/Plans/x.md", "----\nproject: Beta\n----\n경계토큰 본문\n")
    resp = _search(tmp_path, "경계토큰", project="Alpha", include_unattributed=True)
    assert resp["results"][0]["attribution"]["scope"] == "conflict"
    # frontmatter 줄은 본문으로 점수화되지 않는다
    assert "30_Projects/Alpha/Plans/x.md" not in _paths(_search(tmp_path, "beta", project="Alpha", include_unattributed=True))


def test_marker_without_closing_is_a_block_boundary(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n'
       "- 알파 교훈 경계토큰\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Beta"}\n'
       "- 베타 비밀 경계토큰\n")
    resp = _search(tmp_path, "경계토큰", project="Alpha")
    lessons = resp["results"][0]
    assert "베타" not in json.dumps(lessons["excerpts"], ensure_ascii=False)
    assert lessons["attribution"]["blocks"] == [
        {"lines": [1, 3], "scope": "project", "project": "Alpha", "evidence": ["marker:1행 project=Alpha"]}]
    assert any("4행 marker" in w for w in lessons["warnings"])
    beta = _search(tmp_path, "비밀", project="Beta")
    assert beta["results"] == []  # 깨진 marker 블록은 Beta로도 확정하지 않는다
    unk = _search(tmp_path, "비밀", project="Alpha", include_unattributed=True)["results"][0]
    assert ("unknown", "") in {(b["scope"], b["project"]) for b in unk["attribution"]["blocks"]}
    assert "베타 비밀" in unk["excerpts"][0]["text"]


def test_cursor_stale_when_duplicate_copy_changes(tmp_path):
    _projects(tmp_path, "Alpha")
    for i in range(4):
        _w(tmp_path, f"30_Projects/Alpha/Plans/p{i}.md", f"사본토큰 계획 {i}\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/proc.md",
       _fm(project="Alpha", handoff_type="process", session_id="s-dup") + "사본토큰 사본토큰 사본토큰 Process\n")
    log = _w(tmp_path, "10_Worklog/Sessions/s.md", _fm(project="Alpha", session_id="s-dup") + "사본토큰 세션 원문\n")
    whole = _search(tmp_path, "사본토큰", project="Alpha", limit=20)
    proc = next(r for r in whole["results"] if r["path"].endswith("proc.md"))
    assert proc["duplicates"][0]["path"] == "10_Worklog/Sessions/s.md"
    first = _search(tmp_path, "사본토큰", project="Alpha", limit=2)
    assert first["next_cursor"]
    log.write_text(_fm(project="Alpha", session_id="s-dup") + "사본토큰 세션 원문 수정\n", encoding="utf-8")
    again = _search(tmp_path, "사본토큰", project="Alpha", limit=2, cursor=first["next_cursor"])
    assert not again["ok"] and again["error"]["code"] == "cursor_stale"


def test_legacy_search_keeps_link_to_hidden_target_in_scope(tmp_path):
    """허용 prefix 안 숨김 파일을 가리키는 링크는 기존처럼 legacy 검색에 남는다 (금지 prefix만 막는다)."""
    _w(tmp_path, "20_Knowledge/.drafts/hidden.md", "숨김대상토큰 초안\n")
    os.symlink(tmp_path / "20_Knowledge" / ".drafts" / "hidden.md", tmp_path / "20_Knowledge" / "visible.md")
    hits = vault_tools.search_vault("숨김대상토큰", settings=_settings(tmp_path))
    assert [h.path for h in hits] == ["20_Knowledge/visible.md"]
    assert "숨김대상토큰" in vault_tools.read_note("20_Knowledge/visible.md", settings=_settings(tmp_path))
