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
