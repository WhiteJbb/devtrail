"""Phase 6: ContextPackBuilder / AgentMemoryLoader / ProjectMemoryLoader 테스트."""

from pathlib import Path
from types import SimpleNamespace

import frontmatter
import pytest

from app import cli
from app.memory.agent_memory_loader import AgentMemoryLoader
from app.memory.context_pack_builder import ContextPackBuilder
from app.memory.project_memory_loader import ProjectMemoryLoader
from app.models.context_pack import ContextPack
from typer.testing import CliRunner


runner = CliRunner()


# ── 헬퍼 ────────────────────────────────────────────────────────────


def _write_agent_memory(vault: Path, filename: str, title: str, body: str) -> None:
    path = vault / "40_AgentMemory" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    full_body = f"# {title}\n\n{body}"
    post = frontmatter.Post(full_body, **{"type": "agent_memory", "scope": "global", "status": "active"})
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _write_project_context(vault: Path, project: str, body: str) -> None:
    path = vault / "30_Projects" / project / "Context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **{"type": "project", "project": project, "status": "active"})
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _write_knowledge(vault: Path, rel: str, body: str) -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **{"type": "knowledge", "tags": ["rag"]})
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


# ── AgentMemoryLoader ────────────────────────────────────────────────


def test_agent_memory_loader_reads_existing_files(tmp_path):
    _write_agent_memory(tmp_path, "00_Profile.md", "Profile", "개발자 프로필\n코드를 좋아한다.")
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "Current Focus", "RAG 시스템 개발 중.")

    loader = AgentMemoryLoader(tmp_path)
    memory = loader.load()

    assert len(memory.blocks) == 2
    assert memory.blocks[0].title == "Profile"
    assert "코드를 좋아한다" in memory.blocks[0].body
    assert "40_AgentMemory/00_Profile.md" in memory.source_refs


def test_agent_memory_loader_skips_missing_files(tmp_path):
    loader = AgentMemoryLoader(tmp_path)
    memory = loader.load()
    assert memory.blocks == []
    assert memory.render() == ""


def test_agent_memory_render_contains_all_titles(tmp_path):
    _write_agent_memory(tmp_path, "00_Profile.md", "Profile", "프로필 내용")
    _write_agent_memory(tmp_path, "02_ProjectMap.md", "Project Map", "프로젝트 목록")

    memory = AgentMemoryLoader(tmp_path).load()
    rendered = memory.render()

    assert "### Profile" in rendered
    assert "### Project Map" in rendered


# ── ProjectMemoryLoader ──────────────────────────────────────────────


def test_project_memory_loader_reads_context(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "XCoreChat RAG 프로젝트 설명")

    loader = ProjectMemoryLoader(tmp_path)
    memory = loader.load()

    assert len(memory.contexts) == 1
    ctx = memory.contexts[0]
    assert ctx.project == "XCoreChat"
    assert "XCoreChat RAG" in ctx.body
    assert ctx.rel_path == "30_Projects/XCoreChat/Context.md"


def test_project_memory_match_topic_finds_by_name(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "RAG 아키텍처")
    _write_project_context(tmp_path, "Orbit", "브라우저 에이전트")

    memory = ProjectMemoryLoader(tmp_path).load()

    matched = memory.match_topic("XCoreChat 개발환경 분리 작업")
    assert len(matched) == 1
    assert matched[0].project == "XCoreChat"


def test_project_memory_no_match_returns_empty(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "RAG")

    memory = ProjectMemoryLoader(tmp_path).load()
    matched = memory.match_topic("Django 튜토리얼")

    assert matched == []


# ── ContextPackBuilder ───────────────────────────────────────────────


def test_context_pack_builder_assembles_pack(tmp_path):
    _write_agent_memory(tmp_path, "00_Profile.md", "Profile", "개발자 프로필")
    _write_project_context(tmp_path, "XCoreChat", "XCoreChat 개요")
    _write_knowledge(tmp_path, "20_Knowledge/AI/rag-basics.md", "# RAG\n\nRAG 기초 설명")

    builder = ContextPackBuilder(tmp_path)
    pack = builder.build("XCoreChat RAG 검색")

    assert isinstance(pack, ContextPack)
    assert pack.topic == "XCoreChat RAG 검색"
    assert "개발자 프로필" in pack.agent_memory_section
    assert "XCoreChat 개요" in pack.project_section
    assert len(pack.source_refs) > 0


def test_context_pack_render_has_all_sections(tmp_path):
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "Current Focus", "이번 주 목표: RAG 완성")
    _write_project_context(tmp_path, "Devtrail", "Devtrail 개요")

    builder = ContextPackBuilder(tmp_path)
    pack = builder.build("Devtrail 아키텍처")
    rendered = pack.render()

    assert "# Context Pack" in rendered
    assert "## Agent Memory" in rendered
    assert "## Project Context" in rendered
    assert "## Source Refs" in rendered
    assert "## Task" in rendered
    assert "Devtrail 아키텍처" in rendered


def test_context_pack_without_vault_returns_empty_pack(tmp_path):
    builder = ContextPackBuilder(tmp_path)
    pack = builder.build("존재하지 않는 주제")

    assert pack.topic == "존재하지 않는 주제"
    assert pack.agent_memory_section == ""
    assert pack.project_section == ""
    assert pack.source_refs == []


# ── CLI build-context ────────────────────────────────────────────────


def test_cli_build_context_renders_pack(monkeypatch, tmp_path):
    _write_agent_memory(tmp_path, "00_Profile.md", "Profile", "개발자 프로필")
    fake_pack = ContextPack(
        topic="테스트 주제",
        agent_memory_section="에이전트 메모리",
        project_section="",
        relevant_notes_section="",
        source_refs=["40_AgentMemory/00_Profile.md"],
    )

    class _FakeBuilder:
        def build(self, topic):
            return fake_pack

    monkeypatch.setattr("app.cli.ContextPackBuilder", lambda *a, **kw: _FakeBuilder())
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(obsidian_vault_root=str(tmp_path)),
    )

    out = runner.invoke(cli.app, ["build-context", "테스트 주제"])

    assert out.exit_code == 0, out.output
    assert "Context Pack" in out.output
    assert "source_refs: 1개" in out.output


def test_agent_memory_loader_includes_lessons(tmp_path):
    """06_Lessons.md가 briefing에 포함되도록 로더가 읽어야 한다."""
    lessons = tmp_path / "40_AgentMemory" / "06_Lessons.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text("# Lessons\n\n- 테스트는 .venv로 실행한다", encoding="utf-8")

    memory = AgentMemoryLoader(tmp_path).load()

    assert "40_AgentMemory/06_Lessons.md" in memory.source_refs
    assert "테스트는 .venv로 실행한다" in memory.render()


def test_agent_memory_loader_keeps_latest_tail_when_file_is_long(tmp_path):
    _write_agent_memory(tmp_path, "06_Lessons.md", "Lessons", "- 오래된 교훈\n" * 600 + "- LATEST_LESSON_3200_MARKER")

    memory = AgentMemoryLoader(tmp_path).load()

    assert "LATEST_LESSON_3200_MARKER" in memory.render()
    assert len(memory.blocks[0].body) <= 2020


def test_agent_memory_loader_keeps_current_focus_head_when_file_is_long(tmp_path):
    _write_agent_memory(
        tmp_path,
        "01_CurrentFocus.md",
        "Current Focus",
        "IMPORTANT_CURRENT_FOCUS\n" + "x" * 3200,
    )

    memory = AgentMemoryLoader(tmp_path).load()

    focus = next(block for block in memory.blocks if block.rel_path.endswith("01_CurrentFocus.md"))
    assert "IMPORTANT_CURRENT_FOCUS" in focus.body
    assert len(focus.body) <= 2020


def test_project_scoped_memory_patch_only_loads_for_matching_project(tmp_path):
    lessons = (
        '<!-- devtrail-memory-patch: {"scope":"project","project":"Alpha"} -->\nalpha-only\n\n'
        '<!-- devtrail-memory-patch: {"scope":"project","project":"Beta"} -->\nbeta-only\n\n'
        '<!-- devtrail-memory-patch: {"scope":"global","project":""} -->\nglobal-lesson\n'
    )
    _write_agent_memory(tmp_path, "06_Lessons.md", "Lessons", lessons)

    alpha = AgentMemoryLoader(tmp_path).load(project="Alpha").render()
    beta = AgentMemoryLoader(tmp_path).load(project="Beta").render()
    global_memory = AgentMemoryLoader(tmp_path).load().render()

    assert "alpha-only" in alpha and "beta-only" not in alpha
    assert "beta-only" in beta and "alpha-only" not in beta
    assert "global-lesson" in alpha and "global-lesson" in beta
    assert "alpha-only" not in global_memory and "beta-only" not in global_memory


@pytest.mark.parametrize("scope_json", ["[]", "null"])
def test_project_memory_loader_tolerates_non_object_scope_marker(tmp_path, scope_json):
    _write_agent_memory(
        tmp_path,
        "06_Lessons.md",
        "Lessons",
        f"<!-- devtrail-memory-patch: {scope_json} -->\nlegacy-patch",
    )

    memory = AgentMemoryLoader(tmp_path).load().render()

    assert "legacy-patch" in memory


def test_context_pack_excludes_scoped_agent_memory_from_related_notes(tmp_path):
    _write_project_context(tmp_path, "Beta", "Beta context")
    _write_agent_memory(
        tmp_path,
        "06_Lessons.md",
        "Lessons",
        '<!-- devtrail-memory-patch: {"scope":"project","project":"Alpha"} -->\n'
        "SECRET_A_PROJECT_FACT",
    )

    pack = ContextPackBuilder(tmp_path).build("Beta SECRET_A_PROJECT_FACT")

    assert "SECRET_A_PROJECT_FACT" not in pack.agent_memory_section
    assert "SECRET_A_PROJECT_FACT" not in pack.relevant_notes_section
