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
    # 깨진 marker 블록은 "소속 근거 없음"과 구분해 센다
    assert resp["filtered"]["blocks"] == {"other_project": 1, "common": 2, "invalid_marker": 1}  # common: marker 앞 + global


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
        assert all(e["text"] is None or len(e["text"]) <= 800 for e in r["excerpts"])
    long = next(r for r in resp["results"] if r["path"].endswith("longline.md"))["excerpts"][0]
    # 800자보다 긴 줄은 잘라 내지 않는다 — 줄 위치·길이만 알리고 text는 없다
    assert long["truncated"] and long["text"] is None and "line_clip" not in long
    assert long["line_too_long"] == {"line": 1, "line_chars": 6006} and long["matched_terms"] == ["발췌토큰"]


def test_excerpt_text_is_always_whole_source_lines(tmp_path):
    from app.services.source_reader import read_range

    # 3행·9행은 800자보다 긴 일치 줄 — 첫 발췌는 긴 줄, 둘째 발췌는 뒤에 긴 줄이 붙은 창이다
    body = "\n".join(
        (f"줄{i} 완전토큰 " + "나" * (820 if i in (3, 9) else 30)) if i % 3 == 0 else f"채움 {i}" for i in range(1, 40)
    )
    _w(tmp_path, "10_Worklog/Sessions/w.md", body + "\n")
    lines = (tmp_path / "10_Worklog/Sessions/w.md").read_text(encoding="utf-8").split("\n")
    r = _search(tmp_path, "완전토큰")["results"][0]
    assert [(e["start_line"], e["end_line"]) for e in r["excerpts"]] == [(3, 3), (6, 8)]
    assert r["excerpts"][0]["omitted_lines"] == [4, 6] and r["excerpts"][1]["omitted_lines"] == [9, 9]
    for e in r["excerpts"]:
        if e["text"] is None:
            assert e["line_too_long"]["line_chars"] == len(lines[e["start_line"] - 1]) > 800
            continue
        assert e["text"] == "\n".join(lines[e["start_line"] - 1:e["end_line"]])
        page = read_range(tmp_path, r["path"], start_line=e["start_line"], max_lines=e["end_line"] - e["start_line"] + 1)
        assert page["content"] == e["text"]


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
    # 승격 사본 — curator는 파일명을 유지한다
    _w(tmp_path, "60_Candidates/Decisions/copy.md", _fm(project="Alpha", status="candidate") + "같은 본문 중복토큰\n")
    _w(tmp_path, "30_Projects/Alpha/Decisions/copy.md", _fm(status="accepted") + "같은 본문 중복토큰\n")
    resp = _search(tmp_path, "중복토큰", project="Alpha", limit=20)
    paths = _paths(resp)
    assert "60_Candidates/SessionHandoffs/Alpha/plan.md" in paths  # Plan은 내용이 달라 묶지 않는다
    proc = next(r for r in resp["results"] if r["path"].endswith("proc.md"))
    dup = proc["duplicates"][0]
    assert len(proc["duplicates"]) == 1 and dup["path"] == "10_Worklog/Sessions/sess.md" and dup["reason"] == "same_session_id"
    # 묶인 사본도 자기 근거(줄 위치·등급·상태·소속·버전)를 잃지 않는다
    assert dup["excerpt_lines"] == [[8, 8]] and dup["record_tier"] == "raw"
    assert dup["attribution"] == {"scope": "project", "project": "Alpha"} and dup["source_version"].startswith("sha256:")
    assert "10_Worklog/Sessions/sess.md" not in paths
    copies = [p for p in paths if p.endswith("copy.md")]
    assert copies == ["30_Projects/Alpha/Decisions/copy.md"]  # 같은 그룹이면 정본이 대표
    rep = next(r for r in resp["results"] if r["path"] in copies)
    assert rep["duplicates"][0]["reason"] == "same_content"
    assert rep["duplicates"][0]["status"] == {"declared": "candidate", "class": "known"}
    assert resp["total_matches"] == len(paths)


def test_identical_bodies_of_different_decisions_are_not_hidden(tmp_path):
    """본문(템플릿)만 같은 서로 다른 결정·다른 프로젝트 문서는 묶지 않는다."""
    _projects(tmp_path, "Alpha", "Beta")
    template = "## 결정\n\n결정토큰 (작성 예정)\n"
    _w(tmp_path, "30_Projects/Alpha/Decisions/2026-10-01 캐시 도입.md", _fm(title="캐시 도입") + template)
    _w(tmp_path, "30_Projects/Alpha/Decisions/2026-10-02 캐시 제거.md", _fm(title="캐시 제거") + template)
    _w(tmp_path, "30_Projects/Beta/Decisions/2026-10-01 캐시 도입.md", _fm(title="캐시 도입") + template)
    alpha = _search(tmp_path, "결정토큰", project="Alpha")
    assert len(alpha["results"]) == 2 and all("duplicates" not in r for r in alpha["results"])
    whole = _search(tmp_path, "결정토큰")
    assert whole["total_matches"] == 3 and all("duplicates" not in r for r in whole["results"])


def test_session_rule_does_not_merge_across_projects(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/p.md",
       _fm(project="Alpha", handoff_type="process", session_id="same") + "세션토큰 알파\n")
    _w(tmp_path, "10_Worklog/Sessions/b.md", _fm(project="Beta", session_id="same") + "세션토큰 베타\n")
    assert _search(tmp_path, "세션토큰")["total_matches"] == 2


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


def test_cursor_survives_change_outside_scope(tmp_path):
    _projects(tmp_path, "Alpha", "Beta")
    for i in range(6):
        _w(tmp_path, f"30_Projects/Alpha/Plans/p{i}.md", f"커서토큰 {i}\n")
    first = _search(tmp_path, "커서토큰", project="Alpha", limit=3)
    _w(tmp_path, "30_Projects/Beta/Plans/x.md", "커서토큰 다른 프로젝트\n")
    _w(tmp_path, "00_Inbox/x.md", "커서토큰 범위 밖\n")
    nxt = _search(tmp_path, "커서토큰", project="Alpha", limit=3, cursor=first["next_cursor"])
    assert nxt["ok"] and nxt["offset"] == 3


def test_cursor_stale_when_scanned_set_changes_even_without_new_match(tmp_path):
    """범위 안 스캔 대상 집합이 바뀌면 이어 주지 않는다 — 일치하지 않는 문서가 늘어도 마찬가지."""
    first = _two_pages(tmp_path)
    _w(tmp_path, "20_Knowledge/unrelated.md", "관계없는 내용\n")
    assert _search(tmp_path, "커서토큰", limit=3, cursor=first["next_cursor"])["error"]["code"] == "cursor_stale"


def test_cursor_stale_when_attribution_changes_without_content_change(tmp_path):
    """내용은 그대로인데 소속 등록부가 바뀌어 문서 소속이 달라지면 cursor_stale."""
    for i in range(4):
        _w(tmp_path, f"20_Knowledge/Gamma/g{i}.md", f"소속토큰 {i}\n")
    first = _search(tmp_path, "소속토큰", limit=2)
    assert first["results"][0]["attribution"]["scope"] == "unknown"
    (tmp_path / "60_Candidates/SessionHandoffs/Gamma").mkdir(parents=True)  # 빈 폴더 — 문서는 늘지 않는다
    again = _search(tmp_path, "소속토큰", limit=2)
    assert again["results"][0]["attribution"]["project"] == "Gamma"
    assert _search(tmp_path, "소속토큰", limit=2, cursor=first["next_cursor"])["error"]["code"] == "cursor_stale"


def test_cursor_stale_when_partial_scan_recovers(tmp_path, monkeypatch):
    for i in range(4):
        _w(tmp_path, f"20_Knowledge/k{i}.md", f"회복토큰 {i}\n")
    _w(tmp_path, "20_Knowledge/z-broken.md", "다른 내용\n")
    real = evidence_search.read_source_text

    def flaky(path):
        if path.name == "z-broken.md":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(evidence_search, "read_source_text", flaky)
    first = _search(tmp_path, "회복토큰", limit=2)
    assert first["partial"] and first["total_matches"] is None and first["next_cursor"]
    monkeypatch.setattr(evidence_search, "read_source_text", real)
    assert _search(tmp_path, "회복토큰", limit=2, cursor=first["next_cursor"])["error"]["code"] == "cursor_stale"


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
    {"limit": 0}, {"limit": 21}, {"max_chars": 12001}, {"max_chars": 2999}, {"kinds": ["nope"]},
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
    resp = _search(tmp_path, "예산경계", max_chars=3000)
    assert resp["ok"] and len(json.dumps(resp, ensure_ascii=False)) <= 3000
    assert len(resp["results"][0]["title"]) <= 200
    # 같은 영역의 같은 본문 200개 — 사본 흐름이 아니라 묶지 않는다. 결과가 많아도 예산은 지킨다
    for i in range(200):
        _w(tmp_path, f"20_Knowledge/d{i:03d}/dup.md", "중복예산 같은 본문\n")
    resp = _search(tmp_path, "중복예산", limit=20)
    assert resp["ok"] and len(json.dumps(resp, ensure_ascii=False)) <= 12000
    assert resp["total_matches"] == 200 and all("duplicates" not in r for r in resp["results"])


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


def test_budget_holds_for_document_with_hundreds_of_marker_blocks(tmp_path):
    """marker 200개 문서 — 블록 목록도 예산 안으로 줄이고 생략 개수·줄 범위를 남긴다."""
    _projects(tmp_path, "Alpha")
    body = "".join(
        f'<!-- devtrail-memory-patch: {{"scope": "project", "project": "Alpha"}} -->\n- 블록예산 교훈 {i}\n'
        for i in range(200)
    )
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", body)
    resp = _search(tmp_path, "블록예산", project="Alpha")
    assert resp["ok"] and len(json.dumps(resp, ensure_ascii=False)) <= 12000
    att = resp["results"][0]["attribution"]
    assert len(att["blocks"]) <= 10
    assert att["blocks_omitted"]["count"] == 200 - len(att["blocks"]) and att["blocks_omitted"]["last_line"] == 400
    small = _search(tmp_path, "블록예산", project="Alpha", max_chars=3000)
    assert small["ok"] and len(json.dumps(small, ensure_ascii=False)) <= 3000 and small["returned"] == 1


# macOS의 절대 경로 상한(PATH_MAX 1024바이트)·이름 상한(NAME_MAX 255바이트). Linux(4096)에서만 통과하는 경로를 만들지 않는다
_PORTABLE_PATH_BYTES = 1024
_PORTABLE_NAME_BYTES = 255


def _portable_w(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    raw = os.fsencode(path)
    assert len(raw) < _PORTABLE_PATH_BYTES, f"절대 경로 {len(raw)}바이트 — macOS PATH_MAX를 넘는다"
    assert all(len(os.fsencode(part)) <= _PORTABLE_NAME_BYTES for part in path.parts)
    return _w(vault, rel, text)


def test_budget_never_returns_oversized_success(tmp_path):
    """압축형 1건 + 고정부도 max_chars에 안 들어가면 넘는 응답을 성공으로 내지 않는다 (budget_too_small).

    전에는 상대 경로만 2천 자를 넘겨 이 상황을 만들었는데, macOS 절대 경로 상한(1024바이트)을 넘어 파일을 만들지
    못했다. 경로 대신 응답 고정부를 문서화된 입력 상한까지 채운다 — project 300자(선언명)·질의 단어 32개. 그러면
    tmp_path를 더해도 상한 안인 경로(상대 약 430자)로 같은 분기를 탄다. 짧은 경로 대조군으로 경계 양쪽을 함께 본다.
    """
    name = "Budget" + "P" * (evidence_search.MAX_QUERY_CHARS - 6)
    query = " ".join(f"경로예산{i:02d}" for i in range(evidence_search.MAX_QUERY_TOKENS))
    assert len(name) <= evidence_search.MAX_QUERY_CHARS and len(query) <= evidence_search.MAX_QUERY_CHARS

    def vault(sub: str, rel: str) -> Path:
        v = tmp_path / sub
        _portable_w(v, "30_Projects/B/Context.md", _fm(project=name) + "# B\n")
        _portable_w(v, rel, query + "\n")
        return v

    # 대조군: 짧은 경로는 압축형으로 줄여서라도 성공하고, 그 응답도 상한 안이다
    short = _search(vault("s", "30_Projects/B/Plans/n.md"), query, project=name, max_chars=3000)
    assert short["ok"] and short["results"][0].get("compacted") and short["budget"]["used_chars"] <= 3000
    assert len(json.dumps(short, ensure_ascii=False)) <= 3000

    long_rel = "30_Projects/B/Plans/" + "a" * 200 + "/" + "b" * 200 + "/n.md"  # 상대 426자
    tight = _search(vault("l", long_rel), query, project=name, max_chars=3000)
    assert not tight["ok"] and tight["error"]["code"] == "budget_too_small"  # 넘는 응답을 성공으로 내지 않는다
    assert tight["error"]["needed_chars"] > 3000
    assert len(json.dumps(tight, ensure_ascii=False)) <= 3000

    roomy_vault = tmp_path / "r"
    _projects(roomy_vault, "Alpha")
    for i in range(30):
        _portable_w(roomy_vault, f"30_Projects/Alpha/Plans/{'b' * 200}{i:02d}/x/{'c' * 200}.md", f"경로예산 {i}\n")
    roomy = _search(roomy_vault, "경로예산", project="Alpha", limit=20)
    assert roomy["ok"] and len(json.dumps(roomy, ensure_ascii=False)) <= 12000 and roomy["has_more"]
    assert roomy["budget"]["stopped_by"] == "budget"


def test_long_query_is_rejected(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "본문\n")
    assert _search(tmp_path, "가나" * 200)["error"]["code"] == "invalid_argument"
    assert _search(tmp_path, " ".join(f"단어{i}" for i in range(40)))["error"]["code"] == "invalid_argument"


def test_long_first_line_keeps_following_evidence(tmp_path):
    """긴 첫 줄(800자 초과)은 text 없이 line_too_long으로 알리고, 같은 창의 뒷줄 근거는 생략 범위로 남겨 두 번째 발췌로 보존한다."""
    _w(tmp_path, "10_Worklog/Sessions/s.md", "앞" * 2000 + " 긴줄토큰 " + "뒤" * 2000 + "\n두번째 줄 후속토큰 근거\n")
    r = _search(tmp_path, "긴줄토큰 후속토큰")["results"][0]
    first, second = r["excerpts"]
    assert first["start_line"] == 1 and first["text"] is None and first["omitted_lines"] == [2, 2]
    assert first["line_too_long"] == {"line": 1, "line_chars": 4006}
    assert (second["start_line"], second["end_line"]) == (2, 2) and "후속토큰" in second["text"]


def test_legacy_search_never_opens_forbidden_link_targets(tmp_path, monkeypatch):
    """금지 prefix·vault 밖 링크는 결과 노출뿐 아니라 파일 읽기 자체가 일어나지 않아야 한다."""
    from app.services import wiki_service

    vault = tmp_path / "vault"
    _w(vault, "00_Inbox/secret.md", "열기토큰 비밀\n")
    _w(tmp_path, "outside/out.md", "열기토큰 밖\n")
    _w(vault, "20_Knowledge/real.md", "열기토큰 정상\n")
    os.symlink(vault / "00_Inbox" / "secret.md", vault / "20_Knowledge" / "to-inbox.md")
    os.symlink(tmp_path / "outside", vault / "20_Knowledge" / "outdir")
    os.symlink(vault / "20_Knowledge" / "missing.md", vault / "20_Knowledge" / "dangling.md")
    opened: list[str] = []
    real_parse = wiki_service.WikiService._parse_note

    def spy(self, path):
        opened.append(path.relative_to(vault).as_posix())
        return real_parse(self, path)

    monkeypatch.setattr(wiki_service.WikiService, "_parse_note", spy)
    hits = vault_tools.search_vault("열기토큰", settings=_settings(vault))
    assert [h.path for h in hits] == ["20_Knowledge/real.md"]
    assert not any(p.startswith(("00_Inbox/", "20_Knowledge/to-inbox", "20_Knowledge/outdir")) for p in opened)


# ── 최종 리뷰 반영 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fm_block", ["key: [닫히지 않음", "그냥 문장 한 줄"])
def test_unparseable_frontmatter_lines_stay_searchable(tmp_path, fm_block):
    """'---' 사이가 YAML 매핑이 아니면 그 줄도 본문이다 — 수평선으로 시작하는 노트의 앞줄이 사라지지 않게."""
    _w(tmp_path, "20_Knowledge/hr.md", f"---\n{fm_block} 앞줄토큰\n---\n뒷부분\n")
    r = _search(tmp_path, "앞줄토큰")["results"][0]
    assert r["excerpts"][0]["start_line"] == 2 and "앞줄토큰" in r["excerpts"][0]["text"]
    assert any("frontmatter를 해석하지 못해" in w for w in r["warnings"])


def test_alias_and_folder_names_in_documents_attribute_like_identification(tmp_path):
    """문서가 별칭·폴더명으로 프로젝트를 적어도 식별과 같은 근거로 소속을 정한다."""
    _w(tmp_path, "30_Projects/devtrail-dir/Context.md", _fm(project="Devtrail") + "# Devtrail\n")
    _projects(tmp_path, "Other")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"projects": {"Devtrail": {"aliases": ["dt"]}, "Other": {"aliases": ["shared"]},
                                                "Third": {"aliases": ["shared"]}}}), encoding="utf-8")
    _w(tmp_path, "10_Worklog/Sessions/a.md", _fm(project="dt") + "별칭토큰 세션\n")
    _w(tmp_path, "10_Worklog/Sessions/b.md", _fm(project="devtrail-dir") + "별칭토큰 폴더명\n")
    _w(tmp_path, "30_Projects/devtrail-dir/Plans/p.md", _fm(project="dt") + "별칭토큰 계획\n")
    _w(tmp_path, "10_Worklog/Sessions/c.md", _fm(project="shared") + "별칭토큰 모호\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md", '<!-- devtrail-memory-patch: {"scope": "project", "project": "dt"} -->\n별칭토큰 교훈\n')
    resp = vault_tools.search_evidence("별칭토큰", project="Devtrail", limit=20,
                                       settings=_settings(tmp_path, str(mapping)))
    by = {r["path"]: r for r in resp["results"]}
    # b.md의 'devtrail-dir'은 식별이 인정하지 않는 이름(폴더명≠선언명)이라 소속을 정하지 않는다
    assert set(by) == {"10_Worklog/Sessions/a.md", "30_Projects/devtrail-dir/Plans/p.md", "40_AgentMemory/06_Lessons.md"}
    assert by["10_Worklog/Sessions/a.md"]["attribution"]["evidence"] == ["meta:project=dt→Devtrail"]
    assert by["30_Projects/devtrail-dir/Plans/p.md"]["attribution"]["scope"] == "project"  # 충돌 아님
    assert by["40_AgentMemory/06_Lessons.md"]["attribution"]["blocks"][0]["project"] == "Devtrail"
    # 두 프로젝트를 가리키는 별칭은 소속을 정하지 않는다
    assert resp["filtered"]["documents"]["other_project"] >= 1


def test_project_keeps_own_documents_when_folder_name_differs_from_declared_name(tmp_path):
    """식별로 확정한 프로젝트는 소속 판정에서도 같은 이름이어야 한다 — 폴더명≠선언명인 Context.md가 있어도."""
    _w(tmp_path, "30_Projects/Alpha/Context.md", _fm(project="Beta") + "# ctx\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/p.md",
       _fm(project="Alpha", session_id="s1", handoff_type="process") + "폴더토큰 handoff\n")
    _w(tmp_path, "10_Worklog/Sessions/s.md", _fm(project="Alpha", session_id="s1") + "폴더토큰 session\n")
    resp = _search(tmp_path, "폴더토큰", project="Alpha")
    assert resp["scope"]["project"] == "Alpha" and _paths(resp) == ["60_Candidates/SessionHandoffs/Alpha/p.md"]
    hit = resp["results"][0]
    assert hit["attribution"]["scope"] == "project" and hit["duplicates"][0]["path"] == "10_Worklog/Sessions/s.md"


@pytest.mark.parametrize("fm_block", ["# 초안 주석토큰", "{}", ""])
def test_valid_empty_or_comment_frontmatter_is_not_a_parse_failure(tmp_path, fm_block):
    _w(tmp_path, "20_Knowledge/c.md", f"---\n{fm_block}\n---\n주석토큰 본문\n")
    r = _search(tmp_path, "주석토큰")["results"][0]
    assert r["title"] == "c" and "warnings" not in r
    assert [(e["start_line"], e["end_line"]) for e in r["excerpts"]] == [(4, 4)]


def test_registry_is_loaded_once_per_search(tmp_path, monkeypatch):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/Alpha/Plans/p.md", "한번토큰\n")
    calls = []
    real = evidence_search.load_registry
    monkeypatch.setattr(evidence_search, "load_registry", lambda *a, **k: calls.append(1) or real(*a, **k))
    import app.services.project_identity as pi
    monkeypatch.setattr(pi, "load_registry", lambda *a, **k: calls.append(2) or real(*a, **k))
    assert _search(tmp_path, "한번토큰", project="Alpha")["returned"] == 1
    assert calls == [1]


def test_hidden_project_folder_is_not_reported_as_link(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/.trash/Old/Context.md", _fm(project="Old") + "# Old\n")
    _w(tmp_path, "30_Projects/.trash/Context.md", _fm(project="Old") + "# Old\n")
    _w(tmp_path, "30_Projects/Alpha/Plans/p.md", "숨김토큰\n")
    resp = _search(tmp_path, "숨김토큰", project="Alpha")
    assert resp["ok"] and not [w for w in resp["warnings"] if "링크" in w["message"]]


# ── 병합 차단 리뷰 반영 ───────────────────────────────────────────────────────


def test_ambiguous_names_stay_conflict_in_attribution_like_identification(tmp_path):
    """식별에서 모호한 이름(별칭이 다른 canonical과 겹침)은 소속 판정에서도 하나로 확정하지 않는다."""
    _projects(tmp_path, "Alpha", "Beta")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"projects": {"Alpha": {"repos": ["owner/alpha"]}, "Beta": {"aliases": ["Alpha"]}}}),
                       encoding="utf-8")
    settings = _settings(tmp_path, str(mapping))
    assert vault_tools.resolve_project_identity("Alpha", settings=settings).status == "ambiguous"
    _w(tmp_path, "30_Projects/Alpha/Plans/p.md", "모호토큰 경로로 확정\n")
    _w(tmp_path, "30_Projects/Alpha/Plans/q.md", _fm(project="Alpha") + "모호토큰 경로가 좁힌 선언\n")
    _w(tmp_path, "10_Worklog/Sessions/x.md", _fm(project="Alpha") + "모호토큰 선언만\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Alpha/h.md", _fm(handoff_type="process") + "모호토큰 폴더\n")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n모호토큰 블록\n')
    resp = vault_tools.search_evidence("모호토큰", project="owner/alpha", limit=20, settings=settings)
    assert resp["ok"] and resp["scope"]["project"] == "Alpha"
    # Alpha 폴더 안의 `project: Alpha`(q.md, Context.md)는 경로가 모호함을 좁혀 Alpha 소속이다 — conflict가 아니다
    assert sorted(_paths(resp)) == ["30_Projects/Alpha/Plans/p.md", "30_Projects/Alpha/Plans/q.md"]
    assert resp["filtered"]["documents"]["conflict"] == 3  # 세션·handoff·Lessons(블록이 전부 conflict)
    whole = vault_tools.search_evidence("모호토큰", limit=20, settings=settings)
    by = {r["path"]: r["attribution"] for r in whole["results"]}
    assert by["10_Worklog/Sessions/x.md"]["scope"] == "conflict"
    assert by["10_Worklog/Sessions/x.md"]["conflict_with"] == ["Alpha", "Beta"]
    assert "모호" in by["10_Worklog/Sessions/x.md"]["evidence"][0]
    assert by["40_AgentMemory/06_Lessons.md"]["blocks"][0]["conflict_with"] == ["Alpha", "Beta"]
    # 명시적으로 소속 불명·충돌을 포함하면 이 프로젝트가 한쪽인 충돌 문서만 더해진다
    wide = vault_tools.search_evidence("모호토큰", project="owner/alpha", include_unattributed=True, limit=20,
                                       settings=settings)
    assert set(_paths(wide)) == set(by)


def test_same_name_and_body_with_different_metadata_are_different_decisions(tmp_path):
    """리뷰 재현: 같은 파일명·같은 템플릿 본문이라도 제목이 다른 두 결정은 각각 나온다."""
    _projects(tmp_path, "Alpha")
    template = "## 결정\n\n템플릿토큰 (작성 예정)\n"
    _w(tmp_path, "30_Projects/Alpha/Decisions/backend/decision.md", _fm(title="캐시 도입") + template)
    _w(tmp_path, "30_Projects/Alpha/Decisions/frontend/decision.md", _fm(title="캐시 제거") + template)
    resp = _search(tmp_path, "템플릿토큰", project="Alpha")
    assert len(resp["results"]) == 2 and all("duplicates" not in r for r in resp["results"])


def test_same_area_identical_files_are_not_copies(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/Alpha/Decisions/a/decision.md", "같은영역토큰\n")
    _w(tmp_path, "30_Projects/Alpha/Decisions/b/decision.md", "같은영역토큰\n")
    assert _search(tmp_path, "같은영역토큰", project="Alpha")["total_matches"] == 2


def test_candidate_and_promoted_copy_with_conflicting_title_are_not_merged(tmp_path):
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "60_Candidates/Decisions/d.md", _fm(project="Alpha", title="캐시 도입", candidate_type="decision") + "제목토큰\n")
    _w(tmp_path, "30_Projects/Alpha/Decisions/d.md", _fm(project="Alpha", title="캐시 제거", type="decision") + "제목토큰\n")
    assert _search(tmp_path, "제목토큰", project="Alpha")["total_matches"] == 2


def test_promotion_and_archive_copies_are_merged_with_their_evidence(tmp_path):
    """승격·보관 흐름의 사본(영역이 다르고 바뀌는 값은 status·type·promoted_at뿐)은 한 건으로 묶는다."""
    _projects(tmp_path, "Alpha")
    meta = {"project": "Alpha", "title": "캐시 도입", "created_at": "2026-10-01"}
    _w(tmp_path, "60_Candidates/Decisions/d.md", _fm(**meta, status="candidate", candidate_type="decision") + "사본토큰\n")
    _w(tmp_path, "30_Projects/Alpha/Decisions/d.md",
       _fm(**meta, status="accepted", type="decision", promoted_at="2026-10-02") + "사본토큰\n")
    _w(tmp_path, "60_Candidates/_Archive/Decisions/d.md", _fm(**meta, status="candidate", candidate_type="decision") + "사본토큰\n")
    resp = _search(tmp_path, "사본토큰", project="Alpha", include_history=True)
    assert _paths(resp) == ["30_Projects/Alpha/Decisions/d.md"]
    dups = {d["path"]: d for d in resp["results"][0]["duplicates"]}
    assert set(dups) == {"60_Candidates/Decisions/d.md", "60_Candidates/_Archive/Decisions/d.md"}
    assert dups["60_Candidates/_Archive/Decisions/d.md"]["status"]["class"] == "history"
    # 사본마다 frontmatter 길이가 달라 근거 줄도 자기 파일 기준이다 (대표는 9행)
    assert resp["results"][0]["excerpts"][0]["start_line"] == 9
    assert all(d["reason"] == "same_content" and d["excerpt_lines"] == [[8, 8]] for d in dups.values())


@pytest.mark.parametrize("raw_project", ["123", "2026-10-01", "[a, b]", "true", "1.5"])
def test_non_string_context_project_identifies_and_attributes_the_same(tmp_path, raw_project):
    """리뷰 재현: 숫자·날짜 등 문자열이 아닌 project는 식별(폴더명으로 등록)과 소속 판정(근거에서 뺌)이 같은 규칙이다 —
    project="Alpha" 검색에서 자기 Context.md가 'Alpha와 123의 conflict'로 빠지지 않는다."""
    _w(tmp_path, "30_Projects/Alpha/Context.md", f"---\nproject: {raw_project}\n---\n# Alpha\n\n타입토큰 배경\n")
    _w(tmp_path, "30_Projects/Alpha/Plans/p.md", f"---\nproject: {raw_project}\n---\n타입토큰 계획\n")
    res = vault_tools.resolve_project_identity("Alpha", settings=_settings(tmp_path))
    assert (res.status, res.project, res.method) == ("resolved", "Alpha", "canonical")
    assert any("문자열이 아니라" in w for w in res.warnings)
    resp = _search(tmp_path, "타입토큰", project="Alpha")
    assert sorted(_paths(resp)) == ["30_Projects/Alpha/Context.md", "30_Projects/Alpha/Plans/p.md"]
    assert "conflict" not in resp["filtered"]["documents"]
    for r in resp["results"]:
        assert r["attribution"] == {"scope": "project", "project": "Alpha", "evidence": ["path:30_Projects/Alpha/"]}
        assert any("문자열이 아니라 소속 근거로 쓰지 않았습니다" in w for w in r["warnings"])


def test_non_string_project_alone_is_not_an_attribution(tmp_path):
    """경로 근거 없이 숫자 project만 있으면 '123' 프로젝트로 귀속하지 않는다 — 소속 불명이다."""
    _w(tmp_path, "30_Projects/123/Context.md", "---\nproject: '123'\n---\n# 123\n")
    _w(tmp_path, "10_Worklog/Sessions/x.md", "---\nproject: 123\n---\n숫자토큰 세션\n")
    whole = _search(tmp_path, "숫자토큰")
    assert whole["results"][0]["attribution"]["scope"] == "unknown"
    scoped = _search(tmp_path, "숫자토큰", project="123")
    assert scoped["ok"] and scoped["results"] == [] and scoped["filtered"]["documents"] == {"unknown": 1}


# ── 권한·인코딩·손상 marker 회귀 (2026-11-06) ──────────────────────────────────


def _perm_vault(vault: Path) -> None:
    _projects(vault, "Alpha")
    _w(vault, "30_Projects/Alpha/Decisions/d.md", _fm(status="accepted") + "권한토큰 알파 결정\n")
    # 폴더명(Secret)과 선언명(Hidden)이 다르다 — 등록부가 못 읽으면 어느 이름인지 모른다
    _w(vault, "30_Projects/Secret/Context.md", _fm(project="Hidden") + "# Secret\n\n권한토큰 비밀\n")
    _w(vault, "30_Projects/Secret/Plans/p.md", _fm(project="Alpha") + "권한토큰 비밀 계획\n")
    _w(vault, "60_Candidates/SessionHandoffs/Alpha/h.md", _fm(project="Alpha") + "권한토큰 알파 세션\n")
    _w(vault, "60_Candidates/SessionHandoffs/Beta/h.md", _fm(project="Beta") + "권한토큰 베타 세션\n")


_ALPHA_OWN = {"30_Projects/Alpha/Decisions/d.md"}
_ALPHA_HANDOFF = "60_Candidates/SessionHandoffs/Alpha/h.md"


@pytest.mark.parametrize(("mode", "rel", "unreadable", "hidden_project"), [
    ("none", "60_Candidates/SessionHandoffs", ["60_Candidates/SessionHandoffs/"], "Beta"),
    ("no_exec", "60_Candidates/SessionHandoffs",
     ["60_Candidates/SessionHandoffs/Alpha/", "60_Candidates/SessionHandoffs/Beta/"], "Beta"),
    ("none", "30_Projects/Secret", ["30_Projects/Secret/"], "Hidden"),
    ("no_exec", "30_Projects/Secret", ["30_Projects/Secret/"], "Hidden"),
])
def test_registry_folder_permission_error_does_not_abort_search(tmp_path, deny_access, mode, rel, unreadable, hidden_project):
    """등록부 폴더(30_Projects/<P>, SessionHandoffs와 그 하위)의 순회가 PermissionError를 내도 검색 전체가 멈추지 않는다.

    수정 전: SessionHandoffs의 iterdir/is_dir와 스캔의 is_symlink가 PermissionError를 그대로 올려 검색이 예외로 끝났고,
    30_Projects/<P>는 glob이 경고 없이 등록부에서 빼 소속 불완전성이 드러나지 않았다.
    """
    _perm_vault(tmp_path)
    getattr(deny_access, mode)(rel)
    resp = _search(tmp_path, "권한토큰", project="Alpha", limit=20)
    assert deny_access.hits, "PermissionError가 실제로 재현되지 않았다"
    assert resp["ok"], resp
    # 정상 프로젝트의 경로 근거 문서(30_Projects/Alpha/)는 계속 검색된다. SessionHandoffs/Alpha/는 폴더 **이름**으로 소속이
    # 정해지는데, 30_Projects 폴더를 못 읽으면 그 폴더도 Alpha를 선언했을 수 있어(정상이면 모호) conflict로 빠진다
    assert set(_paths(resp)) == _ALPHA_OWN
    if rel.startswith("30_Projects/"):
        whole_attr = {r["path"]: r["attribution"] for r in _search(tmp_path, "권한토큰", limit=20)["results"]}
        assert whole_attr[_ALPHA_HANDOFF]["scope"] == "conflict"
        assert whole_attr[_ALPHA_HANDOFF]["conflict_with"] == ["Alpha", "Alpha (30_Projects/Secret/ 미확인)"]
    assert resp["partial"] is True and resp["total_matches"] is None
    flagged = [w for w in resp["warnings"] if w["code"] == "registry_unreadable"]
    assert [w["path"] for w in flagged] == unreadable
    json.dumps(resp, ensure_ascii=False).encode("utf-8")
    # 못 읽은 등록부의 프로젝트는 확정하지 않는다 — 범위를 넓혀 대신 검색하지도 않는다
    hidden = _search(tmp_path, "권한토큰", project=hidden_project)
    assert not hidden["ok"] and hidden["error"]["code"] == "project_unresolved"
    whole = _search(tmp_path, "권한토큰", limit=20)
    assert whole["ok"] and whole["partial"] is True


def test_docs_under_unconfirmed_registry_folder_are_not_attributed(tmp_path, deny_access):
    """등록부가 Context.md를 확인하지 못한 폴더의 문서는 폴더명·frontmatter로 소속을 추측하지 않는다(unknown)."""
    _perm_vault(tmp_path)
    deny_access.stat("30_Projects/Secret/Context.md")
    whole = _search(tmp_path, "권한토큰", limit=20)
    assert deny_access.hits and whole["ok"]
    by_path = {r["path"]: r for r in whole["results"]}
    plan = by_path["30_Projects/Secret/Plans/p.md"]  # 문서 자체는 읽힌다
    assert plan["attribution"] == {"scope": "unknown", "project": "", "evidence": ["registry_unreadable:30_Projects/Secret/"]}
    assert any("소속을 확정하지 않습니다" in w for w in plan["warnings"])
    assert {"code": "read_failed", "path": "30_Projects/Secret/Context.md"}.items() <= next(
        w for w in whole["warnings"] if w.get("path") == "30_Projects/Secret/Context.md").items()
    scoped = _search(tmp_path, "권한토큰", project="Alpha", limit=20)
    assert "30_Projects/Secret/Plans/p.md" not in _paths(scoped)  # frontmatter project=Alpha여도 Alpha로 넣지 않는다
    assert scoped["filtered"]["documents"].get("registry_unreadable") == 1  # 근거 없음(unknown)과 구분해 센다
    # include_unattributed로도 넣지 않는다 — 같은 폴더에 project: Hidden 문서가 있으면 정상일 때 다른 프로젝트로 걸러졌을 수 있다
    opted = _search(tmp_path, "권한토큰", project="Alpha", include_unattributed=True, limit=20)
    assert "30_Projects/Secret/Plans/p.md" not in _paths(opted) and opted["partial"] is True
    assert opted["filtered"]["documents"].get("registry_unreadable") == 1


def test_cursor_stale_when_registry_folder_recovers(tmp_path, deny_access):
    _perm_vault(tmp_path)
    _w(tmp_path, "30_Projects/Alpha/Plans/p2.md", "권한토큰 알파 계획\n")  # 경로 근거 문서 2건 — 첫 페이지 뒤에 cursor가 남게
    deny_access.no_exec("30_Projects/Secret")
    first = _search(tmp_path, "권한토큰", project="Alpha", limit=1)
    assert first["ok"] and first["next_cursor"]
    deny_access.clear()
    again = _search(tmp_path, "권한토큰", project="Alpha", limit=1, cursor=first["next_cursor"])
    assert again["error"]["code"] == "cursor_stale"


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 디렉터리 권한을 무시한다 — 결정적 재현은 DenyAccess 테스트가 맡는다")
def test_real_chmod_registry_folders_do_not_abort_search(tmp_path):
    """실제 파일 권한으로도 같은지 — SessionHandoffs 000, 30_Projects/Secret r--(실행 권한 없음)."""
    _perm_vault(tmp_path)
    handoffs, secret = tmp_path / "60_Candidates/SessionHandoffs", tmp_path / "30_Projects/Secret"
    os.chmod(handoffs, 0)
    os.chmod(secret, 0o444)
    try:
        resp = _search(tmp_path, "권한토큰", project="Alpha", limit=20)
        whole = _search(tmp_path, "권한토큰", limit=20)
    finally:
        os.chmod(handoffs, 0o755)
        os.chmod(secret, 0o755)
    assert resp["ok"] and set(_paths(resp)) == _ALPHA_OWN and resp["partial"] is True
    assert {w["path"] for w in resp["warnings"] if w["code"] == "registry_unreadable"} == {
        "60_Candidates/SessionHandoffs/", "30_Projects/Secret/"}
    assert whole["ok"] and whole["partial"] is True


def test_non_utf8_project_map_is_ignored_and_search_continues(tmp_path):
    """UTF-8이 아닌 매핑 파일은 인코딩을 추정하지 않고 경고 후 무시한다 — canonical 식별·검색은 계속된다."""
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/Alpha/Plans/p.md", "매핑토큰 계획\n")
    map_path = tmp_path / "project-map.json"
    map_path.write_bytes(json.dumps({"projects": {"Alpha": {"aliases": ["알파"]}}}, ensure_ascii=False).encode("cp949"))
    settings = _settings(tmp_path, str(map_path))
    resp = vault_tools.search_evidence("매핑토큰", project="Alpha", settings=settings)
    assert resp["ok"] and _paths(resp) == ["30_Projects/Alpha/Plans/p.md"]
    assert resp["scope"]["project_resolution"]["method"] == "canonical"
    assert any(w["code"] == "registry" and "UTF-8이 아니라" in w["message"] for w in resp["warnings"])
    alias = vault_tools.search_evidence("매핑토큰", project="알파", settings=settings)  # 잘못 읽은 별칭을 쓰지 않는다
    assert not alias["ok"] and alias["error"]["code"] == "project_unresolved"


_SURROGATE_MARKERS = [
    '{"scope": "project", "project": "\\ud800"}',
    '{"scope": "project", "project": "Alpha\\ud800"}',  # 앞부분이 Alpha여도 Alpha로 보지 않는다
    '{"scope": "global", "project": "\\udfff"}',
    '{"scope": "\\ud800", "project": "Alpha"}',
]


@pytest.mark.parametrize("payload", _SURROGATE_MARKERS)
def test_marker_with_lone_surrogate_is_a_corrupt_marker(tmp_path, payload):
    """marker JSON의 이스케이프된 짝 없는 surrogate는 손상 marker(unknown, invalid_marker)다.

    수정 전: 그 값이 블록 소속 project가 되어 커서 지문(sha256)에서 UnicodeEncodeError로 검색 전체가 멈췄다.
    """
    _projects(tmp_path, "Alpha", "한글팀")
    _w(tmp_path, "40_AgentMemory/06_Lessons.md",
       "# Lessons\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n'
       "Alpha 교훈: 서로게이트토큰 알파\n\n"
       f"<!-- devtrail-memory-patch: {payload} -->\n"
       "손상 블록: 서로게이트토큰 손상\n\n"
       '<!-- devtrail-memory-patch: {"scope": "project", "project": "한글팀"} -->\n'
       "한글 교훈: 서로게이트토큰 한글\n")
    whole = _search(tmp_path, "서로게이트토큰", limit=1)
    assert whole["ok"], whole
    json.dumps(whole, ensure_ascii=False).encode("utf-8")  # MCP 응답 직렬화와 같은 UTF-8 인코딩
    blocks = whole["results"][0]["attribution"]["blocks"]
    assert [(b["scope"], b["project"], b.get("invalid_marker", False)) for b in blocks] == [
        ("common", "", False), ("project", "Alpha", False), ("unknown", "", True), ("project", "한글팀", False)]
    assert blocks[2]["evidence"] == ["marker:6행 유효하지 않은 문자"]
    assert any("유효하지 않은 문자" in w for w in whole["results"][0]["warnings"])
    if whole["next_cursor"]:
        page2 = _search(tmp_path, "서로게이트토큰", limit=1, cursor=whole["next_cursor"])
        assert page2["ok"], page2

    alpha = _search(tmp_path, "서로게이트토큰", project="Alpha")
    assert alpha["ok"] and _paths(alpha) == ["40_AgentMemory/06_Lessons.md"]
    texts = " ".join(e["text"] for e in alpha["results"][0]["excerpts"])
    assert "알파" in texts and "손상" not in texts and "한글" not in texts  # 손상·타 프로젝트 블록이 새지 않는다
    assert alpha["filtered"]["blocks"] == {"invalid_marker": 1, "other_project": 1, "common": 1}
    korean = _search(tmp_path, "서로게이트토큰", project="한글팀")
    assert korean["ok"] and "한글 교훈" in korean["results"][0]["excerpts"][0]["text"]  # 정상 한글 이름은 그대로
    opted = _search(tmp_path, "서로게이트토큰", project="Alpha", include_unattributed=True)
    assert opted["ok"]
    json.dumps(opted, ensure_ascii=False).encode("utf-8")
    opted_blocks = opted["results"][0]["attribution"]["blocks"]
    assert [b["scope"] for b in opted_blocks] == ["project", "unknown"]  # 손상 블록은 unknown으로만 포함된다


def test_frontmatter_project_with_lone_surrogate_is_not_evidence(tmp_path, monkeypatch):
    """YAML "\\ud800"도 같은 규칙(project_field) — 소속 근거로 쓰지 않고 경고, 직렬화도 멈추지 않는다.

    libyaml(CSafeLoader)은 이 이스케이프를 문법 오류로 거부하지만, libyaml 없이 설치된 PyYAML의 SafeLoader는 받아들인다.
    그 환경을 재현하려고 순수 Python 로더로 바꿔 본다.
    """
    import yaml

    monkeypatch.setattr(evidence_search, "_YAML_LOADER", yaml.SafeLoader)
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "10_Worklog/Sessions/s.md", '---\nproject: "\\ud800"\n---\n깨진이름토큰 세션\n')
    whole = _search(tmp_path, "깨진이름토큰")
    assert whole["ok"] and whole["results"][0]["attribution"]["scope"] == "unknown"
    assert any("유효하지 않은 문자" in w for w in whole["results"][0]["warnings"])
    json.dumps(whole, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize(("mode", "rel", "folder"), [
    ("none", "60_Candidates/SessionHandoffs", "Beta"),
    ("none", "30_Projects/Secret", "Hidden"),  # 못 읽은 Context.md가 어떤 이름을 선언했는지 모른다
])
def test_knowledge_folder_hidden_by_unreadable_registry_is_not_attributed(tmp_path, deny_access, mode, rel, folder):
    """리뷰 재현: 20_Knowledge/<P>/는 P가 등록돼 있어야 경로 근거다. 등록부를 못 읽어 P를 모르게 됐다고
    선언(project: Alpha)만으로 Alpha로 확정하면, 정상일 때 conflict로 빠지던 문서가 Alpha 검색에 들어온다."""
    _perm_vault(tmp_path)
    _w(tmp_path, f"20_Knowledge/{folder}/k.md", _fm(project="Alpha") + "권한토큰 지식\n")
    _w(tmp_path, "20_Knowledge/Topic/t.md", _fm(scope="global") + "권한토큰 주제\n")
    normal = _search(tmp_path, "권한토큰", project="Alpha", limit=20)
    assert f"20_Knowledge/{folder}/k.md" not in _paths(normal)
    getattr(deny_access, mode)(rel)
    resp = _search(tmp_path, "권한토큰", project="Alpha", limit=20)
    assert deny_access.hits and resp["ok"] and resp["partial"]
    assert f"20_Knowledge/{folder}/k.md" not in _paths(resp)  # 범위가 넓어지지 않는다
    whole = {r["path"]: r["attribution"] for r in _search(tmp_path, "권한토큰", limit=20)["results"]}
    assert whole[f"20_Knowledge/{folder}/k.md"]["scope"] == "unknown"
    assert whole["20_Knowledge/Topic/t.md"]["scope"] == "common"  # 선언 프로젝트가 없는 문서는 그대로


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 파일 권한을 무시한다")
def test_real_chmod_unreadable_context_file_does_not_attribute(tmp_path):
    _perm_vault(tmp_path)
    ctx = tmp_path / "30_Projects/Secret/Context.md"
    os.chmod(ctx, 0)
    try:
        whole = _search(tmp_path, "권한토큰", limit=20)
        hidden = _search(tmp_path, "권한토큰", project="Hidden")
        secret = _search(tmp_path, "권한토큰", project="Secret")
    finally:
        os.chmod(ctx, 0o644)
    assert whole["ok"] and whole["partial"]
    by_path = {r["path"]: r["attribution"] for r in whole["results"]}
    assert by_path["30_Projects/Secret/Plans/p.md"]["scope"] == "unknown"
    assert {"code": "read_failed", "path": "30_Projects/Secret/Context.md"}.items() <= next(
        w for w in whole["warnings"] if w.get("path") == "30_Projects/Secret/Context.md").items()
    assert hidden["error"]["code"] == "project_unresolved" and secret["error"]["code"] == "project_unresolved"


def test_map_with_lone_surrogates_is_ignored_without_encode_error(tmp_path):
    """리뷰 재현: UTF-8로는 정상인 매핑에 JSON 이스케이프로 짝 없는 surrogate가 든 이름·별칭이 있어도 검색이 멈추지 않는다."""
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "10_Worklog/Sessions/s.md", _fm(project="Beta") + "매핑토큰 세션\n")
    map_path = tmp_path / "project-map.json"
    map_path.write_text('{"projects": {"\\ud800": {"aliases": ["Beta"]}, "Alpha": {"aliases": ["al", "\\udfff"]}}}',
                        encoding="utf-8")
    settings = _settings(tmp_path, str(map_path))
    resp = vault_tools.search_evidence("매핑토큰", settings=settings)
    assert resp["ok"]
    json.dumps(resp, ensure_ascii=False).encode("utf-8")
    assert resp["results"][0]["attribution"]["project"] == "Beta"  # 손상 매핑의 별칭이 소속을 바꾸지 않는다
    assert sum("유효하지 않은 문자" in w["message"] for w in resp["warnings"] if w["code"] == "registry") == 2
    assert vault_tools.search_evidence("매핑토큰", project="al", settings=settings)["error"]["code"] == "project_unresolved"


# ── 병합 차단 리뷰 반영 (2026-11-06) ────────────────────────────────────────────


def _alias_vault(vault: Path, beta_where: str) -> str:
    """Alpha 정상 등록 + Beta 등록(handoff 폴더 또는 30_Projects) + 매핑이 Beta를 Alpha의 별칭으로 둔다 — 정상이면 Beta는 모호하다."""
    _projects(vault, "Alpha")
    if beta_where == "handoff":
        _w(vault, "60_Candidates/SessionHandoffs/Beta/x.md", _fm(project="Beta") + "별칭토큰 handoff\n")
    else:
        _w(vault, "30_Projects/Beta/Context.md", _fm(project="Beta") + "# Beta\n")
    _w(vault, "10_Worklog/Sessions/s.md", _fm(project="Beta") + "별칭토큰 세션\n")
    _w(vault, "60_Candidates/_Archive/SessionHandoffs/Beta/a.md", _fm(project="Beta") + "별칭토큰 보관\n")
    _w(vault, "40_AgentMemory/L.md",
       '# L\n<!-- devtrail-memory-patch: {"scope": "project", "project": "Beta"} -->\n별칭토큰 메모리\n')
    map_path = vault / "map.json"
    map_path.write_text(json.dumps({"projects": {"Alpha": {"aliases": ["Beta"]}}}), encoding="utf-8")
    return str(map_path)


_ALIAS_DOCS = ("10_Worklog/Sessions/s.md", "60_Candidates/_Archive/SessionHandoffs/Beta/a.md", "40_AgentMemory/L.md")


@pytest.mark.parametrize(("beta_where", "mode", "rel"), [
    ("handoff", "none", "60_Candidates/SessionHandoffs"),
    ("handoff", "no_exec", "60_Candidates/SessionHandoffs"),
    ("projects", "none", "30_Projects/Beta"),
])
def test_unreadable_registry_does_not_resolve_alias_conflict(tmp_path, deny_access, beta_where, mode, rel):
    """병합 차단 리뷰 재현: 정상이면 `project: Beta`(Beta 등록 + Alpha의 별칭 Beta)는 conflict(Alpha, Beta)다.
    Beta 등록부가 권한 오류로 빠져도 별칭만 남아 Alpha로 확정되면 안 된다 — 세션 frontmatter·메모리 marker·보관 handoff 모두."""
    settings = _settings(tmp_path, _alias_vault(tmp_path, beta_where))

    def alpha_paths() -> list[str]:
        resp = vault_tools.search_evidence("별칭토큰", project="Alpha", include_history=True, limit=20, settings=settings)
        assert resp["ok"], resp
        return [r["path"] for r in resp["results"]]

    def attributions() -> dict[str, dict]:
        resp = vault_tools.search_evidence("별칭토큰", include_history=True, limit=20, settings=settings)
        assert resp["ok"], resp
        json.dumps(resp, ensure_ascii=False).encode("utf-8")
        out = {r["path"]: r["attribution"] for r in resp["results"]}
        out["40_AgentMemory/L.md"] = out["40_AgentMemory/L.md"]["blocks"][-1]  # marker 블록
        return out

    assert not set(_ALIAS_DOCS) & set(alpha_paths())
    assert vault_tools.resolve_project_identity("Beta", settings=settings).status == "ambiguous"
    getattr(deny_access, mode)(rel)
    assert not set(_ALIAS_DOCS) & set(alpha_paths())  # 범위가 넓어지지 않는다
    assert deny_access.hits
    after = attributions()
    # 못 읽은 30_Projects 폴더는 Alpha를 선언했을 수도 있다 — 그 가능성도 후보로 남는다(SessionHandoffs만 못 읽으면 없다)
    expected = ["Alpha", "Alpha (30_Projects/Beta/ 미확인)", "Beta"] if beta_where == "projects" else ["Alpha", "Beta"]
    for path in _ALIAS_DOCS:
        assert after[path]["scope"] == "conflict" and after[path]["conflict_with"] == expected, (path, after[path])
    res = vault_tools.resolve_project_identity("Beta", settings=settings)
    assert res.status == "ambiguous" and any(e.startswith("registry_unreadable:") for e in res.evidence)
    # 정상 등록 프로젝트 검색은 계속된다
    assert vault_tools.resolve_project_identity("Alpha", settings=settings).status == "resolved"
    opted = vault_tools.search_evidence("별칭토큰", project="Alpha", include_history=True, include_unattributed=True,
                                        limit=20, settings=settings)
    for r in opted["results"]:  # 확정 소속으로는 들어오지 않는다 (marker 문서는 포함된 블록 소속을 본다)
        units = r["attribution"].get("blocks") or [r["attribution"]]
        assert all(u["scope"] in ("conflict", "unknown") for u in units), (r["path"], r["attribution"])


def test_cursor_issued_before_this_change_still_continues(tmp_path):
    """등록부 미확인이 없으면 cursor 지문 구조가 변경 전과 같다 — 변경 전에 발급된 정상 cursor가 만료되지 않는다.
    아래 cursor는 변경 전 코드(88288b4)가 이 Vault에 대해 실제로 발급한 값이다(내용 버전·경로가 같으면 결정적)."""
    for i in range(3):
        _w(tmp_path, f"20_Knowledge/k{i}.md", f"호환토큰 {i}\n")
    legacy = "eyJ2IjoyLCJmIjoiODc4MjliMjMwNzE2YzY3YiIsImMiOiI1M2Y4NGRmMzk3NTdlN2I3IiwibyI6MX0"
    assert _search(tmp_path, "호환토큰", limit=1)["next_cursor"] == legacy
    page2 = _search(tmp_path, "호환토큰", limit=1, cursor=legacy)
    assert page2["ok"] and page2["offset"] == 1 and _paths(page2) == ["20_Knowledge/k1.md"]


# ── 2번째 병합 차단 리뷰 반영: 동명 Context 충돌 (2026-11-06) ─────────────────────


_DUP_NAME_ONLY = (
    "10_Worklog/Sessions/s.md",  # 세션 frontmatter
    "40_AgentMemory/L.md",  # 메모리 marker
    "60_Candidates/SessionHandoffs/Alpha/h.md",  # handoff 폴더 이름
    "60_Candidates/_Archive/SessionHandoffs/Alpha/a.md",  # 보관 handoff 폴더 이름
    "20_Knowledge/Alpha/k.md",  # knowledge 폴더 이름
)
_DUP_PATH = {"30_Projects/Alpha/Context.md", "30_Projects/Alpha/Plans/p.md"}


def _dup_vault(vault: Path) -> None:
    """30_Projects/Alpha와 30_Projects/AlphaOld가 둘 다 project: Alpha를 선언한다 — 정상이면 Alpha는 모호하다."""
    _w(vault, "30_Projects/Alpha/Context.md", _fm(project="Alpha") + "# Alpha\n동명토큰 배경\n")
    _w(vault, "30_Projects/Alpha/Plans/p.md", "동명토큰 계획\n")
    _w(vault, "30_Projects/AlphaOld/Context.md", _fm(project="Alpha") + "# Old\n")
    _w(vault, "10_Worklog/Sessions/s.md", _fm(project="Alpha") + "동명토큰 세션\n")
    _w(vault, "40_AgentMemory/L.md",
       '# L\n<!-- devtrail-memory-patch: {"scope": "project", "project": "Alpha"} -->\n동명토큰 메모리\n')
    _w(vault, "60_Candidates/SessionHandoffs/Alpha/h.md", "동명토큰 handoff\n")
    _w(vault, "60_Candidates/_Archive/SessionHandoffs/Alpha/a.md", "동명토큰 보관\n")
    _w(vault, "20_Knowledge/Alpha/k.md", "동명토큰 지식\n")


def _unit_scopes(resp: dict) -> dict[str, dict]:
    """문서별 소속 — marker 문서는 마지막(프로젝트) 블록."""
    return {r["path"]: (r["attribution"].get("blocks") or [r["attribution"]])[-1] for r in resp["results"]}


def _check_dup_denied(vault: Path) -> None:
    alpha = _search(vault, "동명토큰", project="Alpha", include_history=True, limit=20)
    assert alpha["ok"] and alpha["partial"] is True
    # 경로가 직접 소속을 정하는 문서는 계속 검색된다. 이름만으로 소속이 정해지는 문서는 들어오지 않는다
    assert set(_paths(alpha)) == _DUP_PATH
    assert any(w["code"] == "project_resolution" and "같은 이름을 선언한 다른 Context.md" in w["message"]
               for w in alpha["warnings"])
    whole = _unit_scopes(_search(vault, "동명토큰", include_history=True, limit=20))
    for path in _DUP_NAME_ONLY:
        assert whole[path]["scope"] == "conflict", (path, whole[path])
        assert whole[path]["conflict_with"] == ["Alpha", "Alpha (30_Projects/AlphaOld/ 미확인)"]
    opted = _search(vault, "동명토큰", project="Alpha", include_history=True, include_unattributed=True, limit=20)
    for path, unit in _unit_scopes(opted).items():  # 포함하더라도 conflict로만 들어온다
        assert unit["scope"] == ("project" if path in _DUP_PATH else "conflict"), (path, unit)


@pytest.mark.parametrize("mode", ["none", "no_exec"])
def test_unreadable_context_does_not_dissolve_duplicate_name_conflict(tmp_path, deny_access, mode):
    """2번째 병합 차단 리뷰 재현: 두 Context가 Alpha를 선언하면 정상일 때 Alpha 식별은 ambiguous, 이름만 선언한 문서는 conflict다.
    하나를 못 읽어도 그 문서들(세션·marker·handoff·보관 handoff·knowledge 폴더)이 Alpha 확정 소속으로 바뀌면 안 된다."""
    _dup_vault(tmp_path)
    normal = _search(tmp_path, "동명토큰", project="Alpha")
    assert not normal["ok"] and normal["error"]["code"] == "project_ambiguous"
    assert all(u["scope"] == "conflict" for p, u in _unit_scopes(_search(tmp_path, "동명토큰", include_history=True,
                                                                          limit=20)).items() if p in _DUP_NAME_ONLY)
    getattr(deny_access, mode)("30_Projects/AlphaOld")
    _check_dup_denied(tmp_path)
    assert deny_access.hits


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 디렉터리 권한을 무시한다")
def test_real_chmod_unreadable_context_does_not_dissolve_duplicate_name_conflict(tmp_path):
    _dup_vault(tmp_path)
    old = tmp_path / "30_Projects/AlphaOld"
    os.chmod(old, 0)
    try:
        _check_dup_denied(tmp_path)
    finally:
        os.chmod(old, 0o755)


def test_handoff_only_name_is_not_shadowed_by_one_unreadable_project_folder(tmp_path, deny_access):
    """보수 판정이 넘치지 않는지: SessionHandoffs로만 등록된 이름(Gamma)은 못 읽은 30_Projects 폴더 하나가 Gamma를 선언해도
    같은 프로젝트다(등록 표기가 우선) — 그대로 확정한다. 30_Projects 전체를 못 읽으면 둘 이상이 선언했을 수 있어 conflict."""
    _projects(tmp_path, "Alpha")
    _w(tmp_path, "30_Projects/Secret/Context.md", _fm(project="Hidden") + "# S\n")
    _w(tmp_path, "60_Candidates/SessionHandoffs/Gamma/h.md", "감마토큰 handoff\n")
    _w(tmp_path, "10_Worklog/Sessions/g.md", _fm(project="Gamma") + "감마토큰 세션\n")
    deny_access.none("30_Projects/Secret")
    one = _search(tmp_path, "감마토큰", project="Gamma")
    assert one["ok"] and set(_paths(one)) == {"60_Candidates/SessionHandoffs/Gamma/h.md", "10_Worklog/Sessions/g.md"}
    deny_access.clear()
    deny_access.none("30_Projects")
    whole = _unit_scopes(_search(tmp_path, "감마토큰", limit=20))
    assert {p: u["scope"] for p, u in whole.items()} == {
        "60_Candidates/SessionHandoffs/Gamma/h.md": "conflict", "10_Worklog/Sessions/g.md": "conflict"}
    assert _search(tmp_path, "감마토큰", project="Gamma")["results"] == []


# ── 최종 재리뷰 반영 ──────────────────────────────────────────────────────────


def _intersect_vault(vault: Path) -> str:
    """Alpha·AlphaOld가 모두 Alpha를 선언(정상이면 Alpha는 모호) + 매핑이 Beta를 Alpha의 별칭으로, Beta handoff 폴더도 있다.
    경로 후보와 선언 후보의 교집합으로 소속을 정하는 문서 둘 — 정상이면 둘 다 conflict다."""
    _projects(vault, "Alpha")
    _w(vault, "30_Projects/Alpha/Plans/own.md", "교집합토큰 알파 경로\n")
    _w(vault, "30_Projects/AlphaOld/Context.md", _fm(project="Alpha") + "# AlphaOld\n")
    _w(vault, "60_Candidates/SessionHandoffs/Beta/h.md", _fm(project="Alpha") + "교집합토큰 베타 폴더\n")
    _w(vault, "20_Knowledge/Alpha/k.md", _fm(project="Beta") + "교집합토큰 지식\n")
    map_path = vault.parent / "intersect-map.json"
    map_path.write_text(json.dumps({"projects": {"Alpha": {"aliases": ["Beta"]}}}), encoding="utf-8")
    return str(map_path)


_INTERSECT_DOCS = {"60_Candidates/SessionHandoffs/Beta/h.md", "20_Knowledge/Alpha/k.md"}


def _check_intersect(settings) -> None:
    alpha = vault_tools.search_evidence("교집합토큰", project="Alpha", limit=20, settings=settings)
    assert alpha["ok"] and alpha["partial"] is True
    assert set(_paths(alpha)) == {"30_Projects/Alpha/Plans/own.md"}  # 경로가 직접 정하는 문서만
    whole = vault_tools.search_evidence("교집합토큰", limit=20, settings=settings)
    json.dumps(whole, ensure_ascii=False).encode("utf-8")
    by_path = {r["path"]: r["attribution"] for r in whole["results"]}
    for path in _INTERSECT_DOCS:
        unit = by_path[path]
        assert unit["scope"] == "conflict", (path, unit)
        assert {"Alpha", "Alpha (30_Projects/AlphaOld/ 미확인)"} <= set(unit["conflict_with"]), (path, unit)
    opted = vault_tools.search_evidence("교집합토큰", project="Alpha", include_unattributed=True, limit=20, settings=settings)
    for r in opted["results"]:
        assert r["attribution"]["scope"] == ("project" if r["path"] == "30_Projects/Alpha/Plans/own.md" else "conflict"), r


@pytest.mark.parametrize("mode", ["none", "no_exec"])
def test_unreadable_context_does_not_confirm_path_meta_intersection(tmp_path, deny_access, mode):
    """최종 재리뷰 재현: 경로 이름(Beta 폴더 → Alpha·Beta)이 이미 모호하면 가려진 후보가 한쪽에만 붙어, 교집합이 Alpha
    하나로 줄며 정상이면 conflict인 문서가 Alpha로 확정됐다. 가려진 후보는 후보 수와 무관하게 양쪽에 붙어야 한다."""
    vault = tmp_path / "v"
    settings = _settings(vault, _intersect_vault(vault))
    normal = vault_tools.search_evidence("교집합토큰", project="Alpha", settings=settings)
    assert not normal["ok"] and normal["error"]["code"] == "project_ambiguous"
    whole = {r["path"]: r["attribution"] for r in vault_tools.search_evidence("교집합토큰", limit=20, settings=settings)["results"]}
    assert all(whole[p]["scope"] == "conflict" for p in _INTERSECT_DOCS)
    getattr(deny_access, mode)("v/30_Projects/AlphaOld")
    _check_intersect(settings)
    assert deny_access.hits


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 파일 권한을 무시한다")
def test_real_chmod_unreadable_context_does_not_confirm_path_meta_intersection(tmp_path):
    vault = tmp_path / "v"
    settings = _settings(vault, _intersect_vault(vault))
    ctx = vault / "30_Projects/AlphaOld/Context.md"
    os.chmod(ctx, 0)
    try:
        _check_intersect(settings)
    finally:
        os.chmod(ctx, 0o644)


def test_folder_without_context_is_name_attribution_under_unreadable_registry(tmp_path, deny_access):
    """Context.md 없는 30_Projects/<이름>/은 폴더 이름으로 소속을 정한다 — 이름만으로 정하는 다른 근거와 같이, 등록부 일부를
    못 읽어 그 이름이 정말 하나인지 모르면 확정하지 않는다. 정상 등록부에서는 전처럼 폴더명 하나로 확정한다."""
    _w(tmp_path, "30_Projects/X/Context.md", _fm(project="Foo") + "# X\n")
    _w(tmp_path, "30_Projects/Y/Context.md", _fm(project="Foo") + "# Y\n")
    _w(tmp_path, "30_Projects/Foo/Plans/p.md", "폴더명토큰 계획\n")
    _w(tmp_path, "30_Projects/Bar/Plans/q.md", "폴더명토큰 미등록 폴더\n")
    assert _search(tmp_path, "폴더명토큰", project="Foo")["error"]["code"] == "project_ambiguous"
    normal = {r["path"]: r["attribution"] for r in _search(tmp_path, "폴더명토큰", limit=20)["results"]}
    assert normal["30_Projects/Foo/Plans/p.md"]["project"] == "Foo"  # 기존 동작 보존
    assert normal["30_Projects/Bar/Plans/q.md"]["project"] == "Bar"

    deny_access.none("30_Projects/X")
    foo = _search(tmp_path, "폴더명토큰", project="Foo", include_unattributed=True, limit=20)
    assert foo["ok"] and foo["partial"] is True and deny_access.hits
    assert all(r["attribution"]["scope"] == "conflict" for r in foo["results"])
    assert _search(tmp_path, "폴더명토큰", project="Foo")["results"] == []
    whole = {r["path"]: r["attribution"] for r in _search(tmp_path, "폴더명토큰", limit=20)["results"]}
    assert whole["30_Projects/Foo/Plans/p.md"]["scope"] == "conflict"
    assert whole["30_Projects/Foo/Plans/p.md"]["conflict_with"] == ["Foo", "Foo (30_Projects/X/ 미확인)"]
    assert whole["30_Projects/Bar/Plans/q.md"]["project"] == "Bar"  # 등록되지 않은 이름은 가려질 동명이 없다


def _link_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "v"
    _projects(vault, "Alpha")
    _w(vault, "60_Candidates/SessionHandoffs/Alpha/h.md", "링크토큰 알파 handoff\n")
    _w(tmp_path, "out/Context.md", _fm(project="Alpha") + "# 밖\n")
    os.symlink(tmp_path / "out", vault / "30_Projects" / "Ext")
    return vault


def _check_link_not_unreadable(vault: Path) -> None:
    resp = _search(vault, "링크토큰", project="Alpha")
    assert resp["ok"] and resp["partial"] is False
    assert _paths(resp) == ["60_Candidates/SessionHandoffs/Alpha/h.md"]
    assert not any(w["code"] == "registry_unreadable" for w in resp["warnings"])


def test_symlinked_project_folder_with_unenterable_target_is_not_unreadable_registry(tmp_path, deny_access):
    """최종 재리뷰 재현(과잉 보호): 등록부는 링크 폴더를 원래 등록하지 않는다. 대상에 못 들어가는 링크를 등록부 미확인으로
    만들면 정상 프로젝트 handoff까지 conflict가 되고 partial이 켜졌다 — 변경 전처럼 그 링크만 빼고 계속한다."""
    vault = _link_vault(tmp_path)
    _check_link_not_unreadable(vault)  # 정상
    deny_access.no_exec("v/30_Projects/Ext")  # 링크 자체는 보이지만 그 아래 stat이 거부된다
    _check_link_not_unreadable(vault)
    assert deny_access.hits


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 디렉터리 권한을 무시한다")
def test_real_chmod_symlinked_project_folder_target_is_not_unreadable_registry(tmp_path):
    vault = _link_vault(tmp_path)
    os.chmod(tmp_path / "out", 0o600)
    try:
        _check_link_not_unreadable(vault)
    finally:
        os.chmod(tmp_path / "out", 0o755)


def _check_unattributed_excludes_unreadable(resp: dict) -> None:
    assert resp["ok"] and resp["partial"] is True
    leaked = [r["path"] for r in resp["results"] if r["path"].startswith(("30_Projects/Secret/", "20_Knowledge/Hidden/"))]
    assert leaked == []
    assert resp["filtered"]["documents"].get("registry_unreadable", 0) >= 1


def test_include_unattributed_does_not_add_docs_under_unreadable_registry(tmp_path, deny_access):
    """최종 재리뷰 재현: include_unattributed는 근거 없는 문서를 더한다. 등록부를 못 읽어 판정을 못 한 문서(정상이면 다른 프로젝트로
    걸러졌을 수 있다)까지 프로젝트 검색에 들어오면 안 된다. 범위 없는 검색에서는 unknown으로 계속 보인다."""
    _perm_vault(tmp_path)
    _w(tmp_path, "30_Projects/Secret/Plans/q.md", _fm(project="Hidden") + "권한토큰 숨은 프로젝트 계획\n")
    _w(tmp_path, "20_Knowledge/Hidden/k.md", _fm(project="Beta") + "권한토큰 숨은 지식\n")
    deny_access.stat("30_Projects/Secret/Context.md")
    opted = _search(tmp_path, "권한토큰", project="Alpha", include_unattributed=True, include_history=True, limit=20)
    _check_unattributed_excludes_unreadable(opted)
    assert deny_access.hits
    whole = {r["path"]: r["attribution"] for r in _search(tmp_path, "권한토큰", limit=20)["results"]}
    assert whole["30_Projects/Secret/Plans/q.md"]["scope"] == "unknown"

    deny_access.clear()
    deny_access.none("30_Projects/Secret")  # 폴더 전체를 못 읽으면 20_Knowledge/Hidden/도 판정하지 못한다
    opted = _search(tmp_path, "권한토큰", project="Alpha", include_unattributed=True, include_history=True, limit=20)
    _check_unattributed_excludes_unreadable(opted)
    whole = {r["path"]: r["attribution"] for r in _search(tmp_path, "권한토큰", limit=20)["results"]}
    assert whole["20_Knowledge/Hidden/k.md"]["scope"] == "unknown"


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root는 파일 권한을 무시한다")
def test_real_chmod_include_unattributed_does_not_add_docs_under_unreadable_context(tmp_path):
    _perm_vault(tmp_path)
    _w(tmp_path, "30_Projects/Secret/Plans/q.md", _fm(project="Hidden") + "권한토큰 숨은 프로젝트 계획\n")
    ctx = tmp_path / "30_Projects/Secret/Context.md"
    os.chmod(ctx, 0)
    try:
        opted = _search(tmp_path, "권한토큰", project="Alpha", include_unattributed=True, include_history=True, limit=20)
    finally:
        os.chmod(ctx, 0o644)
    _check_unattributed_excludes_unreadable(opted)
