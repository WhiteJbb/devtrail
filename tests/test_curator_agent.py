"""Phase 9: CuratorAgent 테스트 — list/preview/promote/apply-memory-patch."""

from pathlib import Path
from types import SimpleNamespace

import frontmatter
import pytest
from typer.testing import CliRunner

from app import cli
from app.agents.curator_agent import CandidateItem, CuratorAgent, PromoteResult
from app.config import Settings


runner = CliRunner()


def _settings(vault: Path) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="", MESSENGER_PROVIDER="")


def _write_candidate(
    vault: Path,
    kind: str,
    title: str,
    body: str = "후보 본문",
    project: str = "",
    target_file: str = "",
) -> str:
    subdir = {
        "knowledge": "60_Candidates/Knowledge",
        "decision": "60_Candidates/Decisions",
        "memory_patch": "60_Candidates/MemoryPatches",
        "blog_idea": "60_Candidates/BlogIdeas",
    }[kind]
    path = vault / subdir / f"{title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "type": "candidate",
        "candidate_type": kind,
        "status": "candidate",
        "created_at": "2026-06-23",
        "project": project,
        "tags": [kind],
        "source_refs": ["00_Inbox/Captures/test.md"],
    }
    if target_file:
        metadata["target_file"] = target_file
    post = frontmatter.Post(f"# {title}\n\n{body}", **metadata)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    rel = str(path.relative_to(vault)).replace("\\", "/")
    return rel


# ── list_candidates ──────────────────────────────────────────────────


def test_list_candidates_returns_all_kinds(tmp_path):
    _write_candidate(tmp_path, "knowledge", "RAG 지식")
    _write_candidate(tmp_path, "decision", "설계 결정")
    _write_candidate(tmp_path, "blog_idea", "블로그 아이디어")

    agent = CuratorAgent(settings=_settings(tmp_path))
    items = agent.list_candidates()

    assert len(items) == 3
    kinds = {item.kind for item in items}
    assert "knowledge" in kinds
    assert "decision" in kinds
    assert "blog_idea" in kinds


def test_list_candidates_empty_vault(tmp_path):
    agent = CuratorAgent(settings=_settings(tmp_path))
    assert agent.list_candidates() == []


def test_list_candidates_has_correct_title(tmp_path):
    _write_candidate(tmp_path, "knowledge", "RAG 파이프라인 설계")

    agent = CuratorAgent(settings=_settings(tmp_path))
    items = agent.list_candidates()

    assert items[0].title == "RAG 파이프라인 설계"


# ── preview_candidate ────────────────────────────────────────────────


def test_preview_candidate_returns_content(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "RAG 지식", body="BM25와 벡터 검색")

    agent = CuratorAgent(settings=_settings(tmp_path))
    content = agent.preview_candidate(rel)

    assert "BM25와 벡터 검색" in content


def test_preview_candidate_raises_on_missing(tmp_path):
    agent = CuratorAgent(settings=_settings(tmp_path))
    with pytest.raises(ValueError, match="후보를 찾지 못했습니다"):
        agent.preview_candidate("60_Candidates/Knowledge/없는파일.md")


# ── promote_candidate ────────────────────────────────────────────────


def test_promote_candidate_creates_file_in_knowledge(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "RAG 지식")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.promote_candidate(rel)

    assert result.kind == "knowledge"
    promoted = tmp_path / result.promoted_path
    assert promoted.exists()
    assert result.promoted_path.startswith("20_Knowledge/")


def test_promote_candidate_with_project_uses_project_subdir(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "XCoreChat 구조", project="XCoreChat")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.promote_candidate(rel)

    assert "XCoreChat" in result.promoted_path


def test_promote_candidate_decision_goes_to_projects_decisions(tmp_path):
    rel = _write_candidate(tmp_path, "decision", "아키텍처 결정", project="WorkAgent")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.promote_candidate(rel)

    assert result.promoted_path.startswith("30_Projects/WorkAgent/Decisions/")


def test_promote_candidate_updates_status_in_promoted_file(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "RAG 지식")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.promote_candidate(rel)

    promoted_content = (tmp_path / result.promoted_path).read_text(encoding="utf-8")
    post = frontmatter.loads(promoted_content)
    assert post.metadata.get("status") == "stable"
    assert post.metadata.get("promoted_at") is not None


def test_promote_candidate_marks_original_as_promoted(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "RAG 지식")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.promote_candidate(rel)

    original_content = (tmp_path / rel).read_text(encoding="utf-8")
    post = frontmatter.loads(original_content)
    assert post.metadata.get("status") == "promoted"
    assert post.metadata.get("promoted_to") == result.promoted_path


def test_promote_candidate_appends_vault_log(tmp_path):
    rel = _write_candidate(tmp_path, "knowledge", "RAG 지식")

    agent = CuratorAgent(settings=_settings(tmp_path))
    agent.promote_candidate(rel)

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "promote" in log


# ── apply_memory_patch ───────────────────────────────────────────────


def test_apply_memory_patch_appends_to_target(tmp_path):
    target = "40_AgentMemory/05_OpenLoops.md"
    (tmp_path / "40_AgentMemory").mkdir(parents=True, exist_ok=True)
    (tmp_path / target).write_text("# Open Loops\n\n기존 내용\n", encoding="utf-8")

    rel = _write_candidate(tmp_path, "memory_patch", "규칙 추가", body="패치 내용", target_file=target)

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.apply_memory_patch(rel)

    content = (tmp_path / target).read_text(encoding="utf-8")
    assert "패치 내용" in content
    assert "기존 내용" in content  # 기존 내용 보존
    assert result.promoted_path == target


def test_apply_memory_patch_defaults_to_open_loops(tmp_path):
    rel = _write_candidate(tmp_path, "memory_patch", "규칙 추가", body="패치 내용")

    agent = CuratorAgent(settings=_settings(tmp_path))
    result = agent.apply_memory_patch(rel)

    assert result.promoted_path == "40_AgentMemory/05_OpenLoops.md"


def test_apply_memory_patch_marks_original_applied(tmp_path):
    rel = _write_candidate(tmp_path, "memory_patch", "규칙 추가", body="패치 내용")

    agent = CuratorAgent(settings=_settings(tmp_path))
    agent.apply_memory_patch(rel)

    post = frontmatter.loads((tmp_path / rel).read_text(encoding="utf-8"))
    assert post.metadata.get("status") == "applied"


# ── CLI 테스트 ───────────────────────────────────────────────────────


def test_cli_list_candidates_shows_items(monkeypatch, tmp_path):
    items = [
        CandidateItem(kind="knowledge", title="RAG 지식", rel_path="60_Candidates/Knowledge/abc.md",
                      created_at="2026-06-23", project="WorkAgent"),
    ]

    class _FakeCurator:
        def list_candidates(self):
            return items

    monkeypatch.setattr(cli, "_curator_agent", lambda: _FakeCurator())

    out = runner.invoke(cli.app, ["list-candidates"])

    assert out.exit_code == 0
    assert "후보 1개" in out.output
    assert "RAG 지식" in out.output


def test_cli_promote_candidate_shows_result(monkeypatch, tmp_path):
    result = PromoteResult(
        candidate_path="60_Candidates/Knowledge/abc.md",
        promoted_path="20_Knowledge/abc.md",
        kind="knowledge",
    )

    class _FakeCurator:
        def promote_candidate(self, rel_path):
            return result

    monkeypatch.setattr(cli, "_curator_agent", lambda: _FakeCurator())

    out = runner.invoke(cli.app, ["promote-candidate", "60_Candidates/Knowledge/abc.md"])

    assert out.exit_code == 0
    assert "승격 완료" in out.output
    assert "20_Knowledge/abc.md" in out.output
