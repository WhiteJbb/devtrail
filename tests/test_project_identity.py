"""app/services/project_identity.py — 명시적 근거로만 프로젝트를 확정한다."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.project_identity import repo_remotes, resolve_project


def _ctx(vault: Path, folder: str, project: str | None = None) -> None:
    path = vault / "30_Projects" / folder / "Context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = f"project: {project}\n" if project else ""
    path.write_text(f"---\n{meta}---\n# {folder}\n\n본문\n", encoding="utf-8")


def _map(tmp_path: Path, projects: dict) -> str:
    path = tmp_path / "project-map.json"
    path.write_text(json.dumps({"version": 1, "projects": projects}), encoding="utf-8")
    return str(path)


def _repo(tmp_path: Path, name: str, *, vault_json: str | None = None, remote: str | None = None) -> Path:
    repo = tmp_path / "repos" / name
    (repo / ".git").mkdir(parents=True)
    config = "[core]\n\tbare = false\n"
    if remote:
        config += f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
    (repo / ".git" / "config").write_text(config, encoding="utf-8")
    if vault_json is not None:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "vault.json").write_text(json.dumps({"project": vault_json}), encoding="utf-8")
    return repo


def test_canonical_name_is_case_insensitive(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    res = resolve_project(vault, "devtrail")
    assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "canonical")
    assert res.evidence == ["context:30_Projects/Devtrail/Context.md"]


def test_context_project_metadata_wins_over_folder_name(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "dt-folder", "Devtrail")
    assert resolve_project(vault, "Devtrail").project == "Devtrail"
    assert resolve_project(vault, "dt-folder").status == "unresolved"


def test_handoff_folder_only_project_resolves(tmp_path):
    vault = tmp_path / "vault"
    (vault / "60_Candidates" / "SessionHandoffs" / "rpg-game").mkdir(parents=True)
    res = resolve_project(vault, "RPG-GAME")
    assert (res.status, res.project, res.method) == ("resolved", "rpg-game", "handoff_folder")


def test_alias_from_map_file(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    project_map = _map(tmp_path, {"Devtrail": {"aliases": ["dt", "devtrail-cli"]}})
    res = resolve_project(vault, "DT", project_map)
    assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "alias")


def test_owner_repo_and_remote_url_forms(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    project_map = _map(tmp_path, {"Devtrail": {"repos": ["WhiteJbb/devtrail"]}})
    for ident in ("WhiteJbb/devtrail", "whitejbb/DEVTRAIL"):
        res = resolve_project(vault, ident, project_map)
        assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "repo_mapping"), ident


def test_unknown_owner_repo_is_unresolved_not_guessed(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "devtrail", "devtrail")
    res = resolve_project(vault, "someone/devtrail")
    assert res.status == "unresolved" and res.project == ""


def test_unregistered_name_is_unresolved_with_candidates(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    res = resolve_project(vault, "Gamma")
    assert res.status == "unresolved" and res.project == "" and res.candidates == ["Alpha"]


def test_same_name_declared_twice_is_ambiguous(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    _ctx(vault, "devtrail-old", "devtrail")
    res = resolve_project(vault, "Devtrail")
    assert res.status == "ambiguous" and res.project == ""
    assert len(res.candidates) == 2


def test_alias_colliding_with_other_canonical_is_ambiguous(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    _ctx(vault, "Beta", "Beta")
    project_map = _map(tmp_path, {"Beta": {"aliases": ["alpha"]}})
    res = resolve_project(vault, "alpha", project_map)
    assert res.status == "ambiguous" and res.candidates == ["Alpha", "Beta"]


def test_repo_mapped_to_two_projects_is_conflict(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    _ctx(vault, "Beta", "Beta")
    project_map = _map(tmp_path, {"Alpha": {"repos": ["org/app"]}, "Beta": {"repos": ["org/app"]}})
    res = resolve_project(vault, "org/app", project_map)
    assert res.status == "conflict" and res.project == ""


def test_repo_dir_local_mapping(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    repo = _repo(tmp_path, "anything", vault_json="devtrail")
    res = resolve_project(vault, str(repo))
    assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "local_mapping")


def test_repo_dir_remote_mapping_without_vault_json(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    project_map = _map(tmp_path, {"Devtrail": {"repos": ["WhiteJbb/devtrail"]}})
    repo = _repo(tmp_path, "checkout", remote="git@github.com:WhiteJbb/devtrail.git")
    assert repo_remotes(repo) == ["whitejbb/devtrail"]
    res = resolve_project(vault, str(repo), project_map)
    assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "repo_mapping")


def test_repo_dir_mapping_conflict_is_reported(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    _ctx(vault, "Beta", "Beta")
    project_map = _map(tmp_path, {"Beta": {"repos": ["org/app"]}})
    repo = _repo(tmp_path, "app", vault_json="Alpha", remote="https://github.com/org/app.git")
    res = resolve_project(vault, str(repo), project_map)
    assert res.status == "conflict" and res.candidates == ["Alpha", "Beta"] and res.project == ""


def test_repo_basename_alone_never_resolves(tmp_path):
    """디렉터리 이름이 프로젝트명과 같아도 근거가 아니다 — hint로만 알린다."""
    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    repo = _repo(tmp_path, "devtrail")
    res = resolve_project(vault, str(repo))
    assert res.status == "unresolved" and res.project == ""
    assert "확정하지 않습니다" in res.hint


def test_local_mapping_to_unregistered_project(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    repo = _repo(tmp_path, "x", vault_json="Nowhere")
    res = resolve_project(vault, str(repo))
    assert res.status == "unregistered" and res.project == "Nowhere"


def test_broken_map_file_degrades_to_warning(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    res = resolve_project(vault, "Alpha", str(bad))
    assert res.status == "resolved" and any("매핑 파일" in w for w in res.warnings)


def test_empty_identifier_is_invalid(tmp_path):
    assert resolve_project(tmp_path, "  ").status == "invalid"


def test_badly_typed_map_entries_are_ignored_with_warning(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    project_map = _map(tmp_path, {"Alpha": {"aliases": 5, "repos": True}, "Beta": {"aliases": "ab"}})
    res = resolve_project(vault, "Alpha", project_map)
    assert res.status == "resolved"
    assert sum("문자열 목록" in w for w in res.warnings) == 3
    assert resolve_project(vault, "a", project_map).status == "unresolved"


def test_alias_to_project_missing_from_vault_is_unregistered(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    project_map = _map(tmp_path, {"Ghost": {"aliases": ["gh"]}})
    res = resolve_project(vault, "gh", project_map)
    assert res.status == "unregistered" and res.project == "Ghost"


def test_bare_name_is_not_a_cwd_relative_path(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    work = tmp_path / "cwd"
    (work / "Alpha" / ".claude").mkdir(parents=True)
    (work / "Alpha" / ".claude" / "vault.json").write_text('{"project": "Other"}', encoding="utf-8")
    monkeypatch.chdir(work)
    res = resolve_project(vault, "Alpha")
    assert (res.status, res.project, res.method) == ("resolved", "Alpha", "canonical")
    assert resolve_project(vault, "./Alpha").status == "unregistered"


def test_registry_does_not_read_context_through_links(tmp_path):
    """Context.md나 프로젝트 폴더가 금지 prefix·vault 밖으로 연결돼 있으면 읽지도 노출하지도 않는다."""
    import os

    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    inbox = vault / "00_Inbox" / "Context.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("---\nproject: 비밀인박스\n---\n# x\n", encoding="utf-8")
    (vault / "30_Projects" / "Linked").mkdir()
    os.symlink(inbox, vault / "30_Projects" / "Linked" / "Context.md")
    outside = tmp_path / "outside" / "Escaped"
    outside.mkdir(parents=True)
    (outside / "Context.md").write_text("---\nproject: 바깥비밀\n---\n# y\n", encoding="utf-8")
    os.symlink(outside, vault / "30_Projects" / "Escaped")
    (tmp_path / "outside" / "Handoff").mkdir()
    (vault / "60_Candidates" / "SessionHandoffs").mkdir(parents=True)
    os.symlink(tmp_path / "outside" / "Handoff", vault / "60_Candidates" / "SessionHandoffs" / "Handoff")
    for name in ("비밀인박스", "바깥비밀", "Handoff"):
        res = resolve_project(vault, name)
        assert res.status == "unresolved" and res.candidates == ["Alpha"], name
    res = resolve_project(vault, "Alpha")
    assert "비밀인박스" not in repr(res) and "바깥비밀" not in repr(res)
    assert sum("링크" in w for w in res.warnings) == 3


def test_alias_and_repo_to_duplicated_name_are_ambiguous(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    _ctx(vault, "alpha-copy", "Alpha")
    project_map = _map(tmp_path, {"Alpha": {"aliases": ["al"], "repos": ["org/alpha"]}})
    for ident in ("Alpha", "al", "org/alpha"):
        res = resolve_project(vault, ident, project_map)
        assert res.status == "ambiguous" and res.project == "", ident
        assert len(res.candidates) == 2, ident
    repo = _repo(tmp_path, "checkout", vault_json="al")
    assert resolve_project(vault, str(repo), project_map).status == "ambiguous"
    remote_only = _repo(tmp_path, "remote-only", remote="https://github.com/org/alpha.git")
    assert resolve_project(vault, str(remote_only), project_map).status == "ambiguous"


def test_resolve_project_identity_uses_settings_map(tmp_path):
    from types import SimpleNamespace

    from app import vault_tools

    vault = tmp_path / "vault"
    _ctx(vault, "Devtrail", "Devtrail")
    settings = SimpleNamespace(obsidian_vault_root=str(vault),
                               devtrail_project_map=_map(tmp_path, {"Devtrail": {"repos": ["WhiteJbb/devtrail"]}}))
    res = vault_tools.resolve_project_identity("WhiteJbb/devtrail", settings=settings)
    assert (res.status, res.project, res.method) == ("resolved", "Devtrail", "repo_mapping")


def test_non_string_context_project_falls_back_to_folder(tmp_path):
    vault = tmp_path / "vault"
    path = vault / "30_Projects" / "Alpha" / "Context.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nproject: [a, b]\n---\n# Alpha\n", encoding="utf-8")
    res = resolve_project(vault, "Alpha")
    assert res.status == "resolved" and res.project == "Alpha"
    assert any("문자열이 아니라" in w for w in res.warnings)


def test_non_string_vault_json_project_is_not_evidence(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "123", "'123'")
    repo = tmp_path / "repos" / "r"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "vault.json").write_text('{"project": 123}', encoding="utf-8")
    res = resolve_project(vault, str(repo))
    assert res.status == "unresolved" and any("문자열이 아니라" in w for w in res.warnings)


def test_project_field_rule():
    from datetime import date

    from app.services.project_identity import project_field

    assert project_field({"project": " Alpha "}) == ("Alpha", False)
    assert project_field({}) == ("", False) and project_field({"project": None}) == ("", False)
    assert project_field({"project": ""}) == ("", False) and project_field("x") == ("", False)
    for value in (123, 1.5, True, date(2026, 10, 1), ["a"], {"a": 1}):
        assert project_field({"project": value}) == ("", True)


# ── 권한·인코딩·손상 문자열 회귀 (2026-11-06) ──────────────────────────────────


def test_project_field_rejects_lone_surrogates_but_keeps_unicode():
    from app.services.project_identity import project_field, project_field_issue

    assert project_field({"project": "\ud800"}) == ("", True)
    assert project_field({"project": "Alpha\udfff"}) == ("", True)
    assert project_field({"project": " 한글팀 "}) == ("한글팀", False)
    assert project_field({"project": "😀 팀"}) == ("😀 팀", False)  # 짝이 맞는 비BMP 문자는 정상이다
    assert "유효하지 않은 문자" in project_field_issue({"project": "\ud800"})
    assert project_field_issue({"project": 123}) == "문자열이 아니라"


def test_non_utf8_map_file_is_ignored_with_warning(tmp_path):
    """UTF-8이 아닌 매핑은 다른 인코딩으로 추정해 읽지 않는다 — 경고 후 무시하고 canonical 식별은 계속한다."""
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    bad = tmp_path / "map-cp949.json"
    bad.write_bytes(json.dumps({"projects": {"Alpha": {"aliases": ["알파"], "repos": ["o/alpha"]}}},
                               ensure_ascii=False).encode("cp949"))
    res = resolve_project(vault, "Alpha", str(bad))
    assert (res.status, res.project, res.method) == ("resolved", "Alpha", "canonical")
    assert any("UTF-8이 아니라 무시합니다" in w for w in res.warnings)
    assert resolve_project(vault, "알파", str(bad)).status == "unresolved"
    assert resolve_project(vault, "o/alpha", str(bad)).status == "unresolved"


def test_non_utf8_vault_json_is_ignored_with_warning(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    repo = _repo(tmp_path, "r", remote="git@github.com:o/alpha.git")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "vault.json").write_bytes('{"project": "알파"}'.encode("cp949"))
    res = resolve_project(vault, str(repo), _map(tmp_path, {"Alpha": {"repos": ["o/alpha"]}}))
    assert (res.status, res.project, res.method) == ("resolved", "Alpha", "repo_mapping")  # remote 근거는 계속 쓴다
    assert any(".claude/vault.json이 UTF-8이 아니라" in w for w in res.warnings)


def test_vault_json_with_lone_surrogate_is_not_evidence(tmp_path):
    vault = tmp_path / "vault"
    _ctx(vault, "Alpha", "Alpha")
    repo = tmp_path / "repos" / "r"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "vault.json").write_text('{"project": "\\ud800"}', encoding="utf-8")
    res = resolve_project(vault, str(repo))
    assert res.status == "unresolved" and any("유효하지 않은 문자" in w for w in res.warnings)


def test_registry_permission_errors_are_warnings_not_exceptions(tmp_path, deny_access):
    """등록부 순회의 PermissionError는 그 경로만 미확인으로 남긴다. 나머지 등록·식별은 계속된다."""
    from app.services.project_identity import load_registry

    _ctx(tmp_path, "Alpha", "Alpha")
    _ctx(tmp_path, "Secret", "Hidden")
    (tmp_path / "60_Candidates/SessionHandoffs/Beta").mkdir(parents=True)
    deny_access.none("30_Projects/Secret")
    deny_access.none("60_Candidates/SessionHandoffs")
    reg = load_registry(tmp_path)
    assert deny_access.hits
    assert set(reg.unreadable) == {"30_Projects/Secret/", "60_Candidates/SessionHandoffs/"}
    assert reg.known_projects() == ["Alpha"]
    assert reg.unreadable_prefix("30_Projects/Secret/Plans/p.md") == "30_Projects/Secret/"
    assert reg.unreadable_prefix("30_Projects/SecretOther/p.md") == ""
    res = resolve_project(tmp_path, "Alpha")
    assert res.status == "resolved" and any("30_Projects/Secret/" in w for w in res.warnings)
    assert resolve_project(tmp_path, "Hidden").status == "unresolved"  # 못 읽은 선언을 추측하지 않는다


def test_unreadable_context_file_is_not_registered_by_folder_name(tmp_path, monkeypatch):
    """Context.md 자체를 못 읽으면 폴더명으로 등록하지 않는다 — 선언명이 폴더명과 다를 수 있다.
    (frontmatter 형식 오류는 전처럼 폴더명으로 식별한다.)"""
    from app.services import project_identity

    _ctx(tmp_path, "Secret", "Hidden")
    _ctx(tmp_path, "Broken", None)
    (tmp_path / "30_Projects/Broken/Context.md").write_text("---\nproject: [닫히지\n---\n", encoding="utf-8")
    real = Path.read_text

    def guarded(self, *args, **kwargs):
        if self.parent.name == "Secret" and self.name == "Context.md":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(project_identity.Path, "read_text", guarded)
    reg = project_identity.load_registry(tmp_path)
    assert "30_Projects/Secret/" in reg.unreadable and not reg.is_known("Secret") and not reg.is_known("Hidden")
    assert reg.is_known("Broken")


def test_context_path_that_is_not_readable_as_file_keeps_folder_fallback(tmp_path):
    """권한 오류가 아닌 읽기 실패(Context.md가 폴더)는 전처럼 폴더명으로 식별한다 — 등록부 미확인(partial)으로 만들지 않는다."""
    from app.services.project_identity import load_registry

    (tmp_path / "30_Projects/Odd/Context.md").mkdir(parents=True)
    reg = load_registry(tmp_path)
    assert reg.is_known("Odd") and not reg.unreadable
    assert any("폴더명으로 식별합니다" in w for w in reg.warnings)


def test_alias_only_name_is_not_confirmed_while_registry_may_hide_it(tmp_path, deny_access):
    """별칭만 남은 이름은 못 읽은 등록부가 그 이름을 가렸을 수 있으면 확정하지 않는다(식별 ambiguous, 소속 후보 둘).
    SessionHandoffs 폴더는 이름이 곧 폴더명이라 그 이름만, 30_Projects 아래 폴더는 선언명을 몰라 모든 별칭이 해당한다."""
    from app.services.project_identity import load_registry

    _ctx(tmp_path, "Alpha", "Alpha")
    _ctx(tmp_path, "Gamma", "Gamma")
    (tmp_path / "60_Candidates/SessionHandoffs/Beta").mkdir(parents=True)
    map_path = _map(tmp_path, {"Alpha": {"aliases": ["Beta", "al"]}})

    deny_access.none("60_Candidates/SessionHandoffs/Beta")
    deny_access.no_exec("60_Candidates/SessionHandoffs")
    reg = load_registry(tmp_path, map_path)
    assert reg.attribution_targets("Beta") == ["Alpha", "Beta"]
    assert resolve_project(tmp_path, "Beta", map_path).status == "ambiguous"
    assert resolve_project(tmp_path, "al", map_path).project == "Alpha"  # 가려질 수 없는 별칭은 그대로 확정
    assert resolve_project(tmp_path, "Alpha", map_path).status == "resolved"

    deny_access.clear()
    deny_access.none("30_Projects/Gamma")
    reg = load_registry(tmp_path, map_path)
    # Gamma의 선언명이 al일 수도, Alpha일 수도 있다
    assert reg.attribution_targets("al") == ["al", "Alpha", "Alpha (30_Projects/Gamma/ 미확인)"]
    assert resolve_project(tmp_path, "al", map_path).status == "ambiguous"
    assert resolve_project(tmp_path, "Alpha", map_path).status == "resolved"  # canonical 이름은 계속 확정


def test_may_shadow_rule(tmp_path, deny_access):
    """등록된 이름이 못 읽은 등록부 때문에 하나로 보이는 것일 수 있는가 — 식별은 계속 확정(경고), 소속 후보에는 가려진 쪽을 더한다."""
    from app.services.project_identity import load_registry

    _ctx(tmp_path, "Alpha", "Alpha")
    _ctx(tmp_path, "Old", "Alpha")
    _ctx(tmp_path, "Other", "Other")
    (tmp_path / "60_Candidates/SessionHandoffs/Gamma").mkdir(parents=True)
    assert resolve_project(tmp_path, "Alpha").status == "ambiguous"

    deny_access.none("30_Projects/Old")
    reg = load_registry(tmp_path)
    assert reg.may_shadow("alpha") == "30_Projects/Old/" and reg.may_shadow("Other") == "30_Projects/Old/"
    assert reg.may_shadow("Gamma") == ""  # handoff 이름 — 못 읽은 폴더 하나로는 모호해지지 않는다
    assert reg.may_shadow("Nobody") == ""  # 등록되지 않은 이름은 may_hide가 다룬다
    assert reg.attribution_targets("Alpha") == ["Alpha", "Alpha (30_Projects/Old/ 미확인)"]
    assert reg.attribution_targets("Gamma") == ["Gamma"]
    res = resolve_project(tmp_path, "Alpha")
    assert res.status == "resolved" and any("같은 이름을 선언한 다른 Context.md" in w for w in res.warnings)

    deny_access.clear()
    reg = load_registry(tmp_path)
    assert not reg.unreadable and reg.may_shadow("Other") == "" and reg.attribution_targets("Other") == ["Other"]
