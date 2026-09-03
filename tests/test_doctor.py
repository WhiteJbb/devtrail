"""doctor 진단·수리 테스트.

실제 머신 상태에 의존하지 않도록 repo_dir·vault_root를 전부 tmp_path로 주입하고,
외부 CLI(claude) 호출은 monkeypatch로 대체한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services import doctor
from app.services.wiki_service import WikiService


def _make_repo(tmp_path: Path, *, settings: bool = False, vault_json: dict | None = None,
               example: bool = True, dispatcher: bool = True, venv_python: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    if example:
        (repo / ".claude" / "settings.example.json").write_text('{"hooks": {}}', encoding="utf-8")
    if settings:
        (repo / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    if vault_json is not None:
        (repo / ".claude" / "vault.json").write_text(json.dumps(vault_json), encoding="utf-8")
    if dispatcher:
        hooks = repo / "scripts" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "run-hook.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    if venv_python:
        scripts = repo / ".venv" / "Scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "python.exe").write_text("", encoding="utf-8")
    return repo


def _make_vault(tmp_path: Path, *, project: str = "", full: bool = False) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    if full:
        WikiService(vault).init_vault()
    if project:
        pdir = vault / "30_Projects" / project
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "Context.md").write_text("# Context\n", encoding="utf-8")
    return vault


# ── vault 경로 ───────────────────────────────────────────────────────────────


def test_vault_path_empty_is_fail():
    result = doctor.check_vault_path("")
    assert result.severity == doctor.FAIL
    assert "OBSIDIAN_VAULT_PATH" in result.hint


def test_vault_path_missing_dir_is_fail(tmp_path):
    result = doctor.check_vault_path(str(tmp_path / "nope"))
    assert result.severity == doctor.FAIL


def test_vault_path_ok(tmp_path):
    assert doctor.check_vault_path(str(tmp_path)).severity == doctor.OK


# ── 훅 설정 ─────────────────────────────────────────────────────────────────


def test_hook_settings_missing_is_warn_and_fixable(tmp_path):
    """FAIL이 아니라 WARN이다 — 봇 서버 전용 노드는 훅이 불필요하다(2026-07-08 결정)."""
    repo = _make_repo(tmp_path)
    result = doctor.check_hook_settings(repo)
    assert result.severity == doctor.WARN
    assert result.fixable


def test_hook_settings_present_is_ok(tmp_path):
    repo = _make_repo(tmp_path, settings=True)
    result = doctor.check_hook_settings(repo)
    assert result.severity == doctor.OK
    assert not result.fixable


def test_hook_settings_without_example_is_not_fixable(tmp_path):
    repo = _make_repo(tmp_path, example=False)
    result = doctor.check_hook_settings(repo)
    assert result.severity == doctor.WARN
    assert not result.fixable


# ── 프로젝트 매핑 ────────────────────────────────────────────────────────────


def test_project_mapping_missing_file_is_fail(tmp_path):
    repo = _make_repo(tmp_path)
    vault = _make_vault(tmp_path, project="Devtrail")
    result = doctor.check_project_mapping(repo, vault)
    assert result.severity == doctor.FAIL
    assert result.fixable


def test_project_mapping_ok(tmp_path):
    repo = _make_repo(tmp_path, vault_json={"project": "Devtrail"})
    vault = _make_vault(tmp_path, project="Devtrail")
    assert doctor.check_project_mapping(repo, vault).severity == doctor.OK


def test_project_mapping_pointing_to_missing_project_is_fail(tmp_path):
    """파일은 있는데 값이 실재하지 않는 상태 — 없는 것보다 찾기 어려운 조용한 실패."""
    repo = _make_repo(tmp_path, vault_json={"project": "Ghost"})
    vault = _make_vault(tmp_path, project="Devtrail")
    result = doctor.check_project_mapping(repo, vault)
    assert result.severity == doctor.FAIL
    assert "Ghost" in result.detail
    assert not result.fixable  # 이름이 틀린 것은 사람이 판단해야 한다


def test_project_mapping_without_context_is_warn(tmp_path):
    repo = _make_repo(tmp_path, vault_json={"project": "Devtrail"})
    vault = _make_vault(tmp_path)
    (vault / "30_Projects" / "Devtrail").mkdir(parents=True)
    result = doctor.check_project_mapping(repo, vault)
    assert result.severity == doctor.WARN
    assert "Context.md" in result.detail


def test_project_mapping_broken_json_is_fail(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / ".claude" / "vault.json").write_text("{not json", encoding="utf-8")
    result = doctor.check_project_mapping(repo, _make_vault(tmp_path))
    assert result.severity == doctor.FAIL


def test_project_mapping_without_vault_is_unknown(tmp_path):
    repo = _make_repo(tmp_path, vault_json={"project": "Devtrail"})
    assert doctor.check_project_mapping(repo, None).severity == doctor.UNKNOWN


# ── vault 구조 ──────────────────────────────────────────────────────────────


def test_vault_structure_empty_is_warn_because_handoffs_missing(tmp_path):
    """빈 Vault는 SessionHandoffs가 없어 briefing 폴백이 실패한다 — 실제 기능 저하."""
    result = doctor.check_vault_structure(_make_vault(tmp_path))
    assert result.severity == doctor.WARN
    assert "SessionHandoffs" in result.detail
    assert result.fixable


def test_vault_structure_initialized_is_ok(tmp_path):
    result = doctor.check_vault_structure(_make_vault(tmp_path, full=True))
    assert result.severity == doctor.OK


def test_vault_structure_auto_created_gaps_are_not_warned(tmp_path):
    """TTL이 지운 후보 폴더처럼 쓰기 시점에 자동 생성되는 결손은 경고하지 않는다.

    무해한 것을 WARN으로 올리면 진단 자체를 안 믿게 된다 — 이 커맨드를 실제 머신에서
    처음 돌렸을 때 나온 거짓 경보를 고정한다.
    """
    vault = _make_vault(tmp_path, full=True)
    for rel in ("60_Candidates/Knowledge", "60_Candidates/BlogIdeas", "60_Candidates/CareerBullets"):
        (vault / rel).rmdir()

    result = doctor.check_vault_structure(vault)
    assert result.severity == doctor.OK
    assert "기능 영향 없음" in result.detail
    assert result.fixable  # 정리하고 싶으면 --fix로 가능


def test_vault_structure_missing_agent_memory_file_is_not_warned(tmp_path):
    """apply_memory_patch가 대상 파일을 생성하므로 06_Lessons.md 부재도 치명적이지 않다."""
    vault = _make_vault(tmp_path, full=True)
    (vault / "40_AgentMemory" / "06_Lessons.md").unlink()

    result = doctor.check_vault_structure(vault)
    assert result.severity == doctor.OK


# ── 훅 실행 전제 ─────────────────────────────────────────────────────────────


def test_hook_runtime_missing_dispatcher_is_fail(tmp_path):
    repo = _make_repo(tmp_path, dispatcher=False)
    assert doctor.check_hook_runtime(repo).severity == doctor.FAIL


def test_hook_runtime_with_venv_python_is_ok(tmp_path):
    repo = _make_repo(tmp_path)
    assert doctor.check_hook_runtime(repo).severity == doctor.OK


# ── MCP 등록 (외부 CLI) ──────────────────────────────────────────────────────


def test_mcp_registration_without_claude_cli_is_unknown(monkeypatch):
    """fail-open — claude CLI가 없다고 '고장'으로 보고하지 않는다."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.check_mcp_registration().severity == doctor.UNKNOWN


def test_mcp_registration_found(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "devtrail-vault: devtrail mcp-serve\n"

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc())
    assert doctor.check_mcp_registration().severity == doctor.OK


def test_mcp_registration_missing_is_fail_with_add_command(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "figma: ...\ngmail: ...\n"

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc())
    result = doctor.check_mcp_registration()
    assert result.severity == doctor.FAIL
    assert result.hint == doctor.MCP_ADD_COMMAND


def test_mcp_registration_subprocess_error_is_unknown(monkeypatch):
    def _boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(doctor.subprocess, "run", _boom)
    assert doctor.check_mcp_registration().severity == doctor.UNKNOWN


# ── diagnose ────────────────────────────────────────────────────────────────


def test_diagnose_clean_machine_has_no_failures(tmp_path):
    repo = _make_repo(tmp_path, settings=True, vault_json={"project": "Devtrail"})
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)
    assert report.healthy, [(c.name, c.detail) for c in report.failures]


def test_diagnose_bare_clone_reports_the_silent_failure(tmp_path):
    """clone 직후 상태 — settings.json·vault.json 둘 다 없다. 이번 사고의 재현."""
    repo = _make_repo(tmp_path)
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    by_name = {c.name: c for c in report.checks}
    assert by_name["Claude Code 훅"].severity == doctor.WARN
    assert by_name["프로젝트 매핑"].severity == doctor.FAIL
    assert {c.name for c in report.fixable} == {"Claude Code 훅", "프로젝트 매핑"}


def test_diagnose_absorbs_check_exceptions(tmp_path, monkeypatch):
    """진단 도구가 진단 대상보다 잘 깨지면 안 된다."""
    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "check_hook_runtime", _boom)
    report = doctor.diagnose(_make_repo(tmp_path), str(_make_vault(tmp_path)), check_mcp=False)
    runtime = next(c for c in report.checks if c.name == "훅 실행 전제")
    assert runtime.severity == doctor.UNKNOWN
    assert "boom" in runtime.detail


def test_diagnose_skips_mcp_when_asked(tmp_path):
    report = doctor.diagnose(_make_repo(tmp_path), str(_make_vault(tmp_path)), check_mcp=False)
    assert "MCP 등록" not in {c.name for c in report.checks}


# ── repair ──────────────────────────────────────────────────────────────────


def test_repair_creates_settings_and_mapping(tmp_path):
    repo = _make_repo(tmp_path)
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    results = doctor.repair(report)

    assert (repo / ".claude" / "settings.json").exists()
    saved = json.loads((repo / ".claude" / "vault.json").read_text(encoding="utf-8"))
    assert saved["project"] == "Devtrail"
    assert all(r.changed for r in results if r.name in {"Claude Code 훅", "프로젝트 매핑"})


def test_repair_never_overwrites_existing_settings(tmp_path):
    repo = _make_repo(tmp_path, settings=True)
    (repo / ".claude" / "settings.json").write_text('{"mine": true}', encoding="utf-8")
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    doctor.repair(report)

    assert json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8")) == {"mine": True}


def test_repair_refuses_ambiguous_project(tmp_path):
    """후보가 여럿이면 자동 선택하지 않는다 — 잘못 매핑되면 남의 컨텍스트가 주입된다."""
    repo = _make_repo(tmp_path)
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    _make_vault(tmp_path, project="Orbit")
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    results = doctor.repair(report)

    mapping = next(r for r in results if r.name == "프로젝트 매핑")
    assert not mapping.changed
    assert "Devtrail" in mapping.detail and "Orbit" in mapping.detail
    assert not (repo / ".claude" / "vault.json").exists()


def test_repair_uses_explicit_project_when_ambiguous(tmp_path):
    repo = _make_repo(tmp_path)
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    _make_vault(tmp_path, project="Orbit")
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    doctor.repair(report, project="Orbit")

    saved = json.loads((repo / ".claude" / "vault.json").read_text(encoding="utf-8"))
    assert saved["project"] == "Orbit"


def test_repair_preserves_other_vault_json_keys(tmp_path):
    repo = _make_repo(tmp_path, vault_json={"project": "", "other": "keep"})
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    doctor.repair(report)

    saved = json.loads((repo / ".claude" / "vault.json").read_text(encoding="utf-8"))
    assert saved == {"project": "Devtrail", "other": "keep"}


def test_repair_creates_vault_structure(tmp_path):
    repo = _make_repo(tmp_path, settings=True, vault_json={"project": "Devtrail"})
    vault = _make_vault(tmp_path, project="Devtrail")
    report = doctor.diagnose(repo, str(vault), check_mcp=False)

    results = doctor.repair(report)

    structure = next(r for r in results if r.name == "vault 구조")
    assert structure.changed
    assert (vault / "60_Candidates" / "SessionHandoffs").is_dir()
    assert (vault / "40_AgentMemory" / "06_Lessons.md").exists()


def test_repair_on_healthy_machine_does_nothing(tmp_path):
    repo = _make_repo(tmp_path, settings=True, vault_json={"project": "Devtrail"})
    vault = _make_vault(tmp_path, project="Devtrail", full=True)
    report = doctor.diagnose(repo, str(vault), check_mcp=False)
    assert doctor.repair(report) == []


# ── candidate_projects ──────────────────────────────────────────────────────


def test_candidate_projects_requires_context_md(tmp_path):
    vault = _make_vault(tmp_path, project="Devtrail")
    (vault / "30_Projects" / "NoContext").mkdir(parents=True)
    assert doctor.candidate_projects(vault) == ["Devtrail"]


def test_candidate_projects_without_projects_dir(tmp_path):
    assert doctor.candidate_projects(tmp_path / "vault") == []
