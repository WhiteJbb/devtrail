"""work-agent CLI 진입점.

얇게 유지한다 — 인자 파싱과 출력만 담당하고, 실제 로직은 각 Agent에 위임한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

# Windows 콘솔/파이프 기본 인코딩이 cp949면 한글·em dash 출력 시 깨지므로 UTF-8로 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from app.agents import CareerBulletAgent, CaptureAgent, CuratorAgent, DistillAgent, NightlyDistillAgent, OpenLoopsAgent, PortfolioAgent, ProjectAgent, ResumeAgent, TodoAgent, WikiBlogAgent, WorklogAgent
from app.config import get_settings
from app.llm.base import LLMError, LLMNotConfiguredError
from app.memory import ContextPackBuilder
from app.services.wiki_service import WikiService

app = typer.Typer(
    add_completion=False,
    help="Work Agent — 작업 기록 기반 기술 블로그 초안 생성기",
    no_args_is_help=True,
)


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _handle_llm_errors(func):
    """LLM 미설정/호출 실패를 사용자 친화적 메시지로 변환."""
    try:
        return func()
    except LLMNotConfiguredError as e:
        _fail(
            f"LLM이 연결되어 있지 않습니다.\n  {e}\n"
            "  → .env에서 LLM_PROVIDER와 관련 설정을 채운 뒤 다시 시도하세요."
        )
    except LLMError as e:
        _fail(f"LLM 호출에 실패했습니다.\n  {e}")


def _wiki_service_from_settings() -> WikiService:
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env에서 Obsidian Vault 경로를 지정하세요.")
    return WikiService(Path(settings.obsidian_vault_root), wiki_folder=settings.wiki_folder)


def _capture_agent() -> CaptureAgent:
    try:
        return CaptureAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Capture를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")


def _distill_agent() -> DistillAgent:
    try:
        return DistillAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Distill을 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")


def _print_capture_result(label: str, result) -> None:
    verb = "생성" if result.created else "기존 파일 유지"
    typer.secho(f"\n{label} {verb} 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.echo(f"  vault path: {result.rel_path}")


def _print_distill_result(label: str, result) -> None:
    if not result.written:
        typer.echo(f"{label}: 생성된 후보가 없습니다.")
        return
    typer.secho(f"\n{label} 완료: 후보 {len(result.written)}개 생성", fg=typer.colors.GREEN, bold=True)
    for item in result.written:
        typer.echo(f"  - [{item.spec.kind}] {item.spec.title}")
        typer.echo(f"    {item.rel_path}")


@app.command("init-vault")
def init_vault() -> None:
    """Obsidian LLM Wiki Core 기본 폴더와 루트 파일을 만든다."""
    service = _wiki_service_from_settings()
    result = service.init_vault()

    typer.secho("\nVault 초기화 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  vault: {result.vault_dir}")
    typer.echo(f"  생성 폴더: {len(result.created_dirs)}개")
    typer.echo(f"  생성 파일: {len(result.created_files)}개")
    if result.existing_files:
        typer.echo(f"  기존 파일 유지: {len(result.existing_files)}개")


@app.command("install-hooks")
def install_hooks(
    repo: Path = typer.Argument(..., help="대상 git 레포지토리 경로"),
    project: str = typer.Option("", "--project", "-p", help="프로젝트 이름 (기본: 레포 폴더명)"),
    force: bool = typer.Option(False, "--force", "-f", help="기존 hook 덮어쓰기"),
) -> None:
    """대상 git 레포지토리에 work-agent post-commit hook을 설치한다.

    커밋할 때마다 자동으로 10_Worklog/GitSummaries/에 캡처된다.
    """
    import shutil
    import stat
    import subprocess
    import sys

    repo_path = repo.resolve()
    if not (repo_path / ".git").exists():
        _fail(f"{repo_path} 는 git 레포지토리가 아닙니다.")

    hooks_dir = repo_path / ".git" / "hooks"
    hook_dst = hooks_dir / "post-commit"

    if hook_dst.exists() and not force:
        typer.secho(f"이미 hook이 설치되어 있습니다: {hook_dst}", fg=typer.colors.YELLOW)
        typer.echo("덮어쓰려면 --force 옵션을 사용하세요.")
        raise typer.Exit(1)

    hook_src = Path(__file__).parent.parent / "scripts" / "hooks" / "post-commit"
    if not hook_src.exists():
        _fail(f"hook 스크립트를 찾을 수 없습니다: {hook_src}")

    # LF 줄 끝 강제 (Windows CRLF 환경에서도 Git Bash가 실행 가능하도록)
    content = hook_src.read_bytes().replace(b"\r\n", b"\n")
    hook_dst.write_bytes(content)
    current_mode = hook_dst.stat().st_mode
    hook_dst.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    work_agent_home = str(Path(__file__).parent.parent.resolve())
    python_exe = sys.executable
    project_name = project or repo_path.name

    for key, val in [
        ("work-agent.home", work_agent_home),
        ("work-agent.python", python_exe),
        ("work-agent.project", project_name),
    ]:
        subprocess.run(
            ["git", "config", "--local", key, val],
            cwd=str(repo_path),
            check=True,
            capture_output=True,
        )

    typer.secho("\npost-commit hook 설치 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  repo:    {repo_path}")
    typer.echo(f"  project: {project_name}")
    typer.echo(f"  python:  {python_exe}")
    typer.echo(f"  home:    {work_agent_home}")
    typer.echo("\n커밋할 때마다 자동으로 vault에 캡처됩니다.")


@app.command("index-vault")
def index_vault() -> None:
    """Obsidian Vault의 Markdown 노트를 읽고 root index.md를 갱신한다."""
    service = _wiki_service_from_settings()
    result = service.index_vault()

    typer.secho("\nVault index 갱신 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  notes: {len(result.notes)}")
    typer.echo(f"  index: {result.index_path}")


@app.command("related")
def related_notes(
    rel_path: str = typer.Argument(..., help="기준 노트 경로 (vault 기준 상대경로)"),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50),
) -> None:
    """주어진 노트와 관련된 노트를 태그·wikilink 기반으로 찾는다."""
    service = _wiki_service_from_settings()
    results = service.related_notes(rel_path, limit=limit)
    if not results:
        typer.echo("관련 노트를 찾지 못했습니다.")
        return
    for i, result in enumerate(results, 1):
        note = result.note
        typer.secho(f"\n[{i}] {note.title}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"  path: {note.path}")
        typer.echo(f"  score: {result.score}  matched: {', '.join(result.matched_terms)}")
        if note.summary:
            typer.echo(f"  {note.summary}")


@app.command("search")
def search_vault(
    query: str = typer.Argument(..., help="검색어"),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50, help="최대 결과 수"),
) -> None:
    """Obsidian Vault 노트를 간단한 keyword 검색으로 찾는다."""
    service = _wiki_service_from_settings()
    results = service.search(query, limit=limit)
    if not results:
        typer.echo("검색 결과가 없습니다.")
        return

    for i, result in enumerate(results, 1):
        note = result.note
        typer.secho(f"\n[{i}] {note.title}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"  path: {note.path}")
        typer.echo(f"  score: {result.score}  matched: {', '.join(result.matched_terms)}")
        if note.summary:
            typer.echo(f"  {note.summary}")


@app.command("capture")
def capture_note(
    text: str = typer.Argument(..., help="저장할 메모 내용"),
    project: str = typer.Option("", "--project", "-p", help="관련 프로젝트명"),
    source: str = typer.Option("manual", "--source", help="원본 출처"),
) -> None:
    """메모를 00_Inbox/Memos에 raw Markdown으로 저장한다."""
    try:
        result = _capture_agent().capture(text=text, project=project, source=source)
    except ValueError as e:
        _fail(str(e))
    _print_capture_result("capture", result)


@app.command("capture-commit")
def capture_commit(
    repo: Path = typer.Option(Path.cwd(), "--repo", "-r", help="커밋을 읽을 git 저장소"),
    project: str = typer.Option("", "--project", "-p", help="관련 프로젝트명"),
    ref: str = typer.Option("HEAD", "--ref", help="캡처할 commit/ref"),
    from_agent: bool = typer.Option(False, "--from-agent", help="LLM으로 커밋 의도·결정을 요약한다 (raw diff 대신)"),
) -> None:
    """git commit을 10_Worklog/GitSummaries에 Markdown으로 저장한다."""
    llm = None
    if from_agent:
        from app.llm.factory import get_task_llm_provider
        try:
            llm = get_task_llm_provider("light", get_settings())
        except Exception as e:
            _fail(f"LLM 초기화 실패: {e}")
    try:
        result = _capture_agent().capture_commit(
            repo_dir=repo, project=project, ref=ref, from_agent=from_agent, llm=llm
        )
    except ValueError as e:
        _fail(str(e))
    _print_capture_result("commit capture", result)


@app.command("daily-log")
def daily_log(
    project: str = typer.Option("", "--project", "-p", help="프로젝트별 daily log가 필요할 때 지정"),
    from_agent: bool = typer.Option(False, "--from-agent", help="LLM으로 오늘 컨텍스트를 읽어 내용을 미리 채운다"),
) -> None:
    """오늘 daily worklog 파일을 10_Worklog/Daily에 만든다 (세션 노트는 10_Worklog/Sessions)."""
    llm = None
    if from_agent:
        from app.llm.factory import get_task_llm_provider
        try:
            llm = get_task_llm_provider("light", get_settings())
        except Exception as e:
            _fail(f"LLM 초기화 실패: {e}")
    result = _capture_agent().daily_log(project=project, llm=llm)
    _print_capture_result("daily log", result)


@app.command("capture-session")
def capture_session(
    project: str = typer.Option("", "--project", "-p", help="프로젝트명"),
    repo: str = typer.Option(".", "--repo", "-r", help="Git repo 경로 (기본: 현재 디렉토리)"),
    from_repo: bool = typer.Option(False, "--from-repo", help="git diff, 변경 파일, 최근 커밋 수집"),
    from_agent: bool = typer.Option(False, "--from-agent", help="AI 세션 요약 포함 여부 (워크플로우 신호)"),
    summary_file: str = typer.Option("", "--summary-file", help="AI가 작성한 세션 요약 파일 경로"),
    source: str = typer.Option("agent_session", "--source", help="소스 식별자"),
    title: str = typer.Option("", "--title", help="세션 노트 제목 수동 지정"),
) -> None:
    """작업 세션을 구조화된 노트로 10_Worklog/Sessions에 저장한다.

    --from-agent 플래그는 Claude Code / Codex가 실행할 때 현재 세션을 요약해야 한다는
    워크플로우 신호다. --summary-file로 요약 파일을 전달하는 것을 권장한다.
    """
    try:
        result = _capture_agent().capture_session(
            project=project or None,
            repo=repo or None,
            from_repo=from_repo,
            from_agent=from_agent,
            summary_file=summary_file or None,
            source=source,
            title=title or None,
        )
    except (ValueError, RuntimeError) as e:
        _fail(str(e))

    verb = "생성" if result.created else "기존 파일 유지"
    typer.secho(f"\ncapture-session {verb} 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.echo(f"  vault path: {result.rel_path}")
    if from_agent:
        typer.secho(
            "\n  💡 --from-agent 플래그 감지됨.\n"
            "  AI는 현재 세션에서 수행한 작업을 요약해 이 노트를 채워야 합니다.\n"
            "  --summary-file <path>로 요약 파일을 전달하면 자동으로 포함됩니다.",
            fg=typer.colors.YELLOW,
        )


@app.command("distill-today")
def distill_today() -> None:
    """오늘 raw 기록을 읽어 Knowledge/Decision/Memory/Blog 후보를 만든다."""
    result = _handle_llm_errors(lambda: _distill_agent().distill_today())
    _print_distill_result("distill-today", result)


@app.command("suggest-knowledge")
def suggest_knowledge() -> None:
    """최근 raw 기록에서 Knowledge 후보를 60_Candidates/Knowledge에 만든다."""
    result = _handle_llm_errors(lambda: _distill_agent().suggest_knowledge())
    _print_distill_result("suggest-knowledge", result)


@app.command("suggest-blog-topics")
def suggest_blog_topics() -> None:
    """최근 raw 기록에서 BlogIdea 후보를 60_Candidates/BlogIdeas에 만든다."""
    result = _handle_llm_errors(lambda: _distill_agent().suggest_blog_topics())
    _print_distill_result("suggest-blog-topics", result)


@app.command("suggest-memory-patch")
def suggest_memory_patch() -> None:
    """최근 raw 기록에서 AgentMemory patch 후보를 60_Candidates/MemoryPatches에 만든다."""
    result = _handle_llm_errors(lambda: _distill_agent().suggest_memory_patch())
    _print_distill_result("suggest-memory-patch", result)


@app.command("build-context")
def build_context(
    topic: str = typer.Argument(..., help="문맥을 수집할 주제"),
    show_refs: bool = typer.Option(False, "--refs", "-r", help="source_refs 목록 출력"),
) -> None:
    """주제 관련 AgentMemory / Project Context / 관련 노트를 묶어 Context Pack을 만든다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    from pathlib import Path
    vault_dir = Path(settings.obsidian_vault_root)
    builder = ContextPackBuilder(vault_dir)
    pack = builder.build(topic)

    typer.secho(f"\nContext Pack: {topic}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  source_refs: {len(pack.source_refs)}개")
    typer.secho("\n--- Context Pack ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(pack.render())
    if show_refs:
        typer.secho("\n--- Source Refs ---", fg=typer.colors.BRIGHT_BLACK)
        for ref in pack.source_refs:
            typer.echo(f"  {ref}")


def _curator_agent() -> CuratorAgent:
    try:
        return CuratorAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Curator를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")


@app.command("list-candidates")
def list_candidates(
    include_handoffs: bool = typer.Option(
        False, "--include-handoffs", help="SessionHandoffs(Plan/Process) candidate도 함께 표시"
    ),
) -> None:
    """60_Candidates/ 하위 후보 노트 목록을 보여준다.

    session_handoff(Plan/Process)은 promote 대상이 아니라 다음 세션 briefing 전용
    운영 메모리이므로 기본 출력에서 제외한다. --include-handoffs로 함께 볼 수 있다.
    """
    items = _curator_agent().list_candidates(include_session_handoffs=include_handoffs)
    if not items:
        typer.echo("60_Candidates/ 에 후보가 없습니다.")
        return

    stale_count = sum(1 for i in items if i.is_stale)
    header = f"\n후보 {len(items)}개"
    if stale_count:
        header += f"  ({stale_count}개 stale)"
    typer.secho(header, fg=typer.colors.CYAN, bold=True)
    for item in items:
        stale_tag = "  ⚠ stale" if item.is_stale else ""
        typer.echo(
            f"  [{item.kind}] {item.title}"
            + (f"  ({item.project})" if item.project else "")
            + stale_tag
        )
        typer.echo(f"    {item.rel_path}")


@app.command("preview-candidate")
def preview_candidate(
    rel_path: str = typer.Argument(..., help="60_Candidates/ 기준 상대 경로"),
) -> None:
    """후보 노트의 내용을 미리 본다."""
    try:
        content = _curator_agent().preview_candidate(rel_path)
    except ValueError as e:
        _fail(str(e))
    typer.secho(f"\n--- {rel_path} ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(content)


@app.command("promote-candidate")
def promote_candidate(
    rel_path: str = typer.Argument(..., help="승격할 후보 노트 경로 (vault 기준)"),
) -> None:
    """후보 노트를 공식 Knowledge/Decision/Memory 영역으로 승격한다."""
    try:
        result = _curator_agent().promote_candidate(rel_path)
    except ValueError as e:
        _fail(str(e))

    typer.secho("\n승격 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  후보: {result.candidate_path}")
    typer.echo(f"  승격됨: {result.promoted_path}")
    typer.echo(f"  종류: {result.kind}")


@app.command("promote-all")
def promote_all_cmd(
    kind: str = typer.Option("", "--kind", "-k", help="종류 필터 (knowledge/decision/blog_idea). 생략 시 전체."),
) -> None:
    """60_Candidates 내 후보를 일괄 승격한다."""
    curator = _curator_agent()
    results = curator.promote_all(kind=kind or None)
    if not results:
        typer.echo("승격할 후보가 없습니다.")
        return
    typer.secho(f"\n{len(results)}개 승격 완료", fg=typer.colors.GREEN, bold=True)
    for r in results:
        typer.echo(f"  [{r.kind}] {r.promoted_path}")


@app.command("apply-memory-patch")
def apply_memory_patch(
    rel_path: str = typer.Argument(default="", help="적용할 MemoryPatch 후보 경로 (vault 기준). 생략 시 인터랙티브 선택."),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="목록에서 번호로 선택"),
) -> None:
    """MemoryPatch 후보를 40_AgentMemory/ 대상 파일에 반영(append)한다.

    경로를 생략하거나 -i 플래그를 쓰면 후보 목록에서 번호로 선택할 수 있다.
    """
    curator = _curator_agent()

    if not rel_path or interactive:
        patches = [c for c in curator.list_candidates() if c.kind == "memory_patch"]
        if not patches:
            typer.echo("적용할 MemoryPatch 후보가 없습니다.")
            raise typer.Exit()

        typer.secho("\nMemoryPatch 후보 목록", fg=typer.colors.CYAN, bold=True)
        for i, p in enumerate(patches, 1):
            typer.echo(f"  {i}. {p.title}")
            typer.echo(f"     {p.rel_path}")

        choice = typer.prompt("\n번호 선택 (취소: 0)", default="0")
        try:
            idx = int(choice)
        except ValueError:
            idx = 0
        if idx == 0 or idx > len(patches):
            typer.echo("취소했습니다.")
            raise typer.Exit()

        rel_path = patches[idx - 1].rel_path

    try:
        result = curator.apply_memory_patch(rel_path)
    except ValueError as e:
        _fail(str(e))

    typer.secho("\n메모리 패치 반영 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  후보: {result.candidate_path}")
    typer.echo(f"  반영됨: {result.promoted_path}")


@app.command("write-blog")
def write_blog(
    topic: str = typer.Argument(..., help="블로그 주제"),
    project: str = typer.Option("", "--project", "-p", help="관련 프로젝트명"),
) -> None:
    """Context Pack을 기반으로 블로그 초안을 생성해 50_Outputs/Blog/Drafts/에 저장한다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. write-draft로 기존 흐름을 사용하거나 .env에서 경로를 설정하세요.")
    try:
        agent = WikiBlogAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    draft = _handle_llm_errors(lambda: agent.write_blog(topic=topic, project=project))
    typer.secho(f"\n블로그 초안 생성 완료: {draft.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {draft.path}")
    typer.echo(f"  vault path: {draft.rel_path}")
    if draft.tags:
        typer.echo(f"  태그: {', '.join(draft.tags)}")
    if draft.source_refs:
        typer.echo(f"  source_refs: {len(draft.source_refs)}개")


@app.command("revise-blog")
def revise_blog(
    vault_path: str = typer.Argument(..., help="수정할 초안 경로 (vault 기준, 예: 50_Outputs/Blog/Drafts/abc.md)"),
) -> None:
    """Vault 블로그 초안을 읽어 문장·구조를 다듬고 status를 review로 변경한다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = WikiBlogAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))
    try:
        draft = _handle_llm_errors(lambda: agent.revise_blog(vault_path))
    except ValueError as e:
        _fail(str(e))

    typer.secho(f"\n초안 다듬기 완료: {draft.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {draft.path}")
    typer.echo(f"  status: review")


@app.command("publish-ready")
def publish_ready(
    vault_path: str = typer.Argument(..., help="게시 준비 완료할 초안 경로 (vault 기준)"),
) -> None:
    """Vault 블로그 초안의 status를 review로 변경해 게시 준비 완료를 기록한다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = WikiBlogAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))
    try:
        draft = agent.publish_ready(vault_path)
    except ValueError as e:
        _fail(str(e))

    typer.secho(f"\n게시 준비 완료 기록: {draft.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {draft.path}")
    typer.echo(f"  status: review")


@app.command("suggest-topics")
def suggest_topics() -> None:
    """vault raw 기록에서 BlogIdea 후보를 만든다 (suggest-blog-topics와 동일)."""
    result = _handle_llm_errors(lambda: _distill_agent().suggest_blog_topics())
    _print_distill_result("suggest-topics", result)


@app.command("write-draft")
def write_draft(
    topic: str = typer.Argument(..., help="블로그 주제"),
    source_project: str = typer.Option("", "--project", help="관련 프로젝트명"),
) -> None:
    """블로그 초안을 50_Outputs/Blog/Drafts/에 저장한다 (write-blog와 동일)."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env에서 경로를 설정하세요.")
    try:
        agent = WikiBlogAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    draft = _handle_llm_errors(lambda: agent.write_blog(topic=topic, project=source_project))
    typer.secho(f"\n블로그 초안 생성 완료: {draft.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {draft.path}")
    typer.echo(f"  vault path: {draft.rel_path}")
    if draft.tags:
        typer.echo(f"  태그: {', '.join(draft.tags)}")
    if draft.source_refs:
        typer.echo(f"  source_refs: {len(draft.source_refs)}개")


_STATUS_COLOR = {
    "idea": typer.colors.BRIGHT_BLACK,
    "draft": typer.colors.YELLOW,
    "review": typer.colors.CYAN,
    "published": typer.colors.GREEN,
}


@app.command("list")
def list_drafts() -> None:
    """Vault 블로그 초안 목록을 상태/날짜와 함께 보여준다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    agent = WikiBlogAgent(settings=settings)
    drafts = agent.list_drafts()
    if not drafts:
        typer.echo("저장된 초안이 없습니다. write-blog 로 먼저 생성하세요.")
        return

    for draft in drafts:
        color = _STATUS_COLOR.get(draft.status, typer.colors.WHITE)
        typer.echo(
            f"  {draft.created_at or '----'  }  "
            + typer.style(f"{draft.status:<9}", fg=color)
            + f"{draft.title}  "
            + typer.style(f"({draft.rel_path})", fg=typer.colors.BRIGHT_BLACK)
        )
    typer.echo(f"\n  총 {len(drafts)}건")


@app.command("preview")
def preview(target: str = typer.Argument("latest", help="latest 또는 vault rel_path")) -> None:
    """최신(또는 지정) Vault 초안의 메타데이터와 본문 일부를 보여준다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    agent = WikiBlogAgent(settings=settings)
    result = agent.preview_draft(target)
    if result is None:
        typer.echo("초안을 찾지 못했습니다." if target != "latest" else "저장된 초안이 없습니다. write-blog 로 먼저 생성하세요.")
        return

    draft, excerpt = result
    typer.secho(f"\n{draft.title}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  status: {draft.status}  |  created: {draft.created_at}")
    if draft.tags:
        typer.echo(f"  태그: {', '.join(draft.tags)}")
    if draft.source_refs:
        typer.echo(f"  source_refs: {len(draft.source_refs)}개")
    typer.echo(f"  파일: {draft.rel_path}")
    typer.secho("\n--- 본문 일부 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(excerpt)


@app.command("export-tistory")
def export_tistory(
    target: str = typer.Argument("latest", help="latest 또는 vault rel_path"),
    fmt: str = typer.Option("html", "--format", help="html 또는 md"),
) -> None:
    """Vault 초안을 티스토리에 붙여넣을 형식(HTML/MD)으로 변환해 50_Outputs/Blog/Export/에 저장한다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    agent = WikiBlogAgent(settings=settings)
    try:
        result = agent.export_tistory(target, fmt)
    except ValueError as e:
        _fail(str(e))

    if result is None:
        typer.echo("초안을 찾지 못했습니다." if target != "latest" else "저장된 초안이 없습니다. write-blog 로 먼저 생성하세요.")
        return

    typer.secho(f"\n티스토리용 변환 완료 ({result.fmt})", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.echo(f"  → 이 파일 내용을 티스토리 글쓰기 화면에 붙여넣으세요 ({'HTML 모드' if result.fmt == 'html' else '마크다운 모드'}).")
    typer.secho("\n  아래는 티스토리 입력란에 따로 넣을 항목입니다:", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(f"    제목: {result.draft.title}")
    if result.draft.tags:
        typer.echo(f"    태그: {', '.join(result.draft.tags)}")
    typer.echo("  (티스토리 공식 API는 2024년 종료되어 자동 게시는 지원하지 않습니다)")


@app.command("publish-done")
def publish_done(
    target: str = typer.Argument("latest", help="latest 또는 vault rel_path"),
    url: str = typer.Option("", "--url", help="게시된 티스토리 글 주소"),
) -> None:
    """Vault 초안에 게시 완료를 기록한다 (status=published + URL 저장)."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    agent = WikiBlogAgent(settings=settings)
    draft = agent.publish_done(target, url)
    if draft is None:
        typer.echo("초안을 찾지 못했습니다." if target != "latest" else "저장된 초안이 없습니다.")
        return

    typer.secho(f"\n게시 완료 기록: {draft.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  status: {draft.status}")
    if draft.published_url:
        typer.echo(f"  URL: {draft.published_url}")


@app.command("worklog")
def worklog() -> None:
    """최근 raw 기록(00_Inbox, 10_Worklog)을 읽어 작업 회고를 10_Worklog/Summaries/에 저장한다."""
    try:
        agent = WorklogAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Worklog를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")
    result = _handle_llm_errors(lambda: agent.generate())

    typer.secho("\n작업 회고 생성 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 회고 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("nightly-distill")
def nightly_distill() -> None:
    """하루 raw 기록을 종합 정제하고 daily digest를 생성한다.

    distill-today + suggest-career-bullets를 순서대로 실행하고
    60_Candidates/ 전 카테고리에 후보를 쌓는다.
    MESSENGER_PROVIDER=telegram이면 digest를 자동 전송한다.
    """
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = NightlyDistillAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    result = _handle_llm_errors(lambda: agent.run())

    total = len(result.distill.written) + len(result.career.written)
    typer.secho(f"\nnightly-distill 완료: 후보 {total}개 생성", fg=typer.colors.GREEN, bold=True)
    for w in result.distill.written:
        typer.echo(f"  [{w.spec.kind}] {w.spec.title}")
    for w in result.career.written:
        typer.echo(f"  [career_bullet] {w.spec.title}")
    typer.echo(f"\n  digest: {result.digest_rel_path}")
    if result.sent_telegram:
        typer.secho("  → Telegram 전송 완료", fg=typer.colors.CYAN)


@app.command("weekly-distill")
def weekly_distill() -> None:
    """이번 주 daily digest를 종합해 주간 회고를 생성한다.

    금요일 마감 시 한 주를 정리하는 용도로 사용한다.
    MESSENGER_PROVIDER=telegram이면 회고를 자동 전송한다.
    """
    from app.agents.weekly_review_agent import WeeklyReviewAgent

    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = WeeklyReviewAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    result = _handle_llm_errors(lambda: agent.run())

    if not result.review_text:
        typer.secho("이번 주 daily digest가 없습니다. nightly-distill이 먼저 실행됐는지 확인하세요.", fg=typer.colors.YELLOW)
        return

    typer.secho(f"\nweekly-distill 완료: digest {result.digest_count}개 → 주간 회고 생성", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  review: {result.review_rel_path}")
    if result.sent_telegram:
        typer.secho("  → Telegram 전송 완료", fg=typer.colors.CYAN)


@app.command("suggest-career-bullets")
def suggest_career_bullets(
    project: str = typer.Option("", "--project", "-p", help="특정 프로젝트 필터 (기본: 전체)"),
) -> None:
    """작업 기록에서 이력서/포트폴리오 bullet 후보를 60_Candidates/CareerBullets/에 저장한다."""
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = CareerBulletAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    result = _handle_llm_errors(lambda: agent.suggest(project=project))

    if not result.written:
        typer.echo("이력서/포폴 후보가 생성되지 않았습니다.")
        return
    typer.secho(f"\ncareer bullet 후보 {len(result.written)}개 생성", fg=typer.colors.GREEN, bold=True)
    for w in result.written:
        typer.echo(f"  {w.spec.title}" + (f"  ({w.spec.project})" if w.spec.project else ""))
        typer.echo(f"    {w.rel_path}")


@app.command("update-open-loops")
def update_open_loops() -> None:
    """미해결 이슈·다음 할 일을 분석해 Open Loops MemoryPatch 후보를 만든다.

    40_AgentMemory/05_OpenLoops.md를 직접 수정하지 않고
    60_Candidates/MemoryPatches/에 후보를 생성한다.
    반영은 apply-memory-patch 명령으로 한다.
    """
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")
    try:
        agent = OpenLoopsAgent(settings=settings)
    except RuntimeError as e:
        _fail(str(e))

    result = _handle_llm_errors(lambda: agent.suggest())

    if not result.written:
        typer.echo("Open Loops 패치 후보가 생성되지 않았습니다.")
        return
    typer.secho("\nOpen Loops 패치 후보 생성 완료", fg=typer.colors.GREEN, bold=True)
    for w in result.written:
        typer.echo(f"  {w.rel_path}")
    typer.secho(
        "\n  → apply-memory-patch <path>로 40_AgentMemory/05_OpenLoops.md에 반영하세요.",
        fg=typer.colors.YELLOW,
    )


@app.command("print-schedule")
def print_schedule(
    windows: bool = typer.Option(False, "--windows", help="Windows schtasks 형식 출력"),
    cron: bool = typer.Option(False, "--cron", help="Linux/Mac cron 형식 출력"),
) -> None:
    """OS 스케줄러에 nightly-distill / push-digest를 등록하는 명령을 출력한다."""
    import sys

    exe = sys.executable

    if not windows and not cron:
        typer.echo("--windows 또는 --cron 옵션을 지정하세요.")
        raise typer.Exit(1)

    if windows:
        agent_exe = str(Path(exe).parent / "work-agent.exe")
        typer.secho("# Windows Task Scheduler (PowerShell에서 실행)", fg=typer.colors.CYAN, bold=True)
        typer.echo(
            f'schtasks /create /tn "work-agent-nightly" '
            f'/tr "{agent_exe} nightly-distill" '
            f"/sc daily /st 23:30 /f"
        )
        typer.echo(
            f'schtasks /create /tn "work-agent-digest" '
            f'/tr "{agent_exe} push-digest --daily" '
            f"/sc daily /st 08:30 /f"
        )

    if cron:
        venv_bin = str(Path(exe).parent / "work-agent")
        typer.secho("# crontab -e 에 추가", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"30 23 * * * {venv_bin} nightly-distill")
        typer.echo(f"30 8  * * * {venv_bin} push-digest --daily")


@app.command("push-digest")
def push_digest(
    include_worklog: bool = typer.Option(False, "--worklog", help="작업 회고도 함께 보냄"),
    daily: bool = typer.Option(False, "--daily", help="오늘 생성된 모든 후보 카테고리를 digest 형식으로 보냄"),
    weekly: bool = typer.Option(False, "--weekly", help="최근 7일 후보를 주간 요약으로 보냄"),
) -> None:
    """vault 후보 요약을 메신저로 보낸다.

    기본: BlogIdea 후보 목록
    --daily: 오늘 전 카테고리 요약 (daily digest 형식)
    --weekly: 최근 7일 전 카테고리 요약
    """
    from datetime import datetime, timedelta

    from app.messaging import get_messenger_provider
    from app.messaging.base import MessengerNotConfiguredError

    settings = get_settings()
    try:
        provider = get_messenger_provider(settings)
    except MessengerNotConfiguredError as e:
        typer.secho(
            f"메신저가 설정되지 않았습니다.\n  {e}\n"
            "  → .env에서 MESSENGER_PROVIDER, 토큰을 설정하세요.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0)
    if not settings.telegram_chat_id:
        typer.secho(
            "보낼 대상이 없습니다. .env에서 TELEGRAM_CHAT_ID를 설정하세요.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0)

    try:
        all_candidates = _curator_agent().list_candidates()
    except Exception:
        all_candidates = []

    if daily or weekly:
        cutoff = (datetime.now() - timedelta(days=7 if weekly else 0)).strftime("%Y-%m-%d")
        if daily:
            today = datetime.now().strftime("%Y-%m-%d")
            filtered = [c for c in all_candidates if (c.created_at or "")[:10] == today]
            header = f"**Daily Digest — {today}**"
        else:
            filtered = [c for c in all_candidates if (c.created_at or "")[:10] >= cutoff]
            header = f"**Weekly Summary (최근 7일)**"

        by_kind: dict[str, list] = {}
        for c in filtered:
            by_kind.setdefault(c.kind, []).append(c)

        lines = [header, ""]
        for kind, items in by_kind.items():
            kind_label = {
                "knowledge": "정리된 지식",
                "decision": "결정 사항",
                "blog_idea": "블로그 후보",
                "memory_patch": "메모리 패치",
                "career_bullet": "이력서/포폴 소재",
            }.get(kind, kind)
            lines.append(f"**{kind_label}** ({len(items)}개)")
            for item in items[:3]:
                lines.append(f"  · {item.title}" + (f" ({item.project})" if item.project else ""))
            if len(items) > 3:
                lines.append(f"  · ... +{len(items) - 3}개")
            lines.append("")

        if daily:
            from app.services.review_question import format_review_block

            review_block = format_review_block(Path(settings.obsidian_vault_root))
            if review_block:
                lines.append(review_block)
                lines.append("")
    else:
        # 기본 동작: BlogIdea 목록
        blog_ideas = [c for c in all_candidates if c.kind == "blog_idea"]
        lines = ["**블로그 주제 후보**"]
        if blog_ideas:
            for i, c in enumerate(blog_ideas[:5], 1):
                lines.append(f"{i}. {c.title}" + (f"  ({c.project})" if c.project else ""))
        else:
            lines.append("후보 없음 — `distill-today` 실행 권장")

    text = "\n".join(lines)

    if include_worklog:
        try:
            worklog_agent = WorklogAgent(settings=settings)
            wlog = worklog_agent.generate(save=False)
            if wlog:
                text += f"\n\n**작업 회고**\n{wlog.text[:1500]}"
        except Exception:
            pass

    provider.send(settings.telegram_chat_id, text)
    typer.secho("푸시 전송 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  대상 chat: {settings.telegram_chat_id}  ·  후보 {len(all_candidates)}건")


@app.command("todo")
def todo() -> None:
    """최근 raw 기록을 읽어 다음 할 일을 제안해 50_Outputs/Todo/에 저장한다."""
    try:
        agent = TodoAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Todo를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")
    result = _handle_llm_errors(lambda: agent.generate())

    typer.secho("\n다음 할 일 제안 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 할 일 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("portfolio")
def portfolio() -> None:
    """전체 프로젝트 기록을 바탕으로 포트폴리오 초안을 50_Outputs/Portfolio/에 저장한다."""
    try:
        agent = PortfolioAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Portfolio를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")
    result = _handle_llm_errors(lambda: agent.generate())
    typer.secho("\n포트폴리오 초안 생성 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 초안 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


def _project_agent() -> ProjectAgent:
    try:
        return ProjectAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"ProjectAgent를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")


@app.command("summarize-project")
def summarize_project(
    project: str = typer.Argument(..., help="프로젝트명 (예: XCoreChat)"),
) -> None:
    """프로젝트 Context Pack을 읽어 800자 이내 요약을 50_Outputs/Portfolio/에 저장한다."""
    result = _handle_llm_errors(lambda: _project_agent().summarize_project(project))
    typer.secho(f"\n프로젝트 요약 완료: {project}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 요약 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("portfolio-draft")
def portfolio_draft(
    project: str = typer.Argument(..., help="프로젝트명 (예: XCoreChat)"),
) -> None:
    """프로젝트별 포트폴리오 설명 초안을 50_Outputs/Portfolio/에 저장한다."""
    result = _handle_llm_errors(lambda: _project_agent().portfolio_draft(project))
    typer.secho(f"\n포트폴리오 초안 완료: {project}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 초안 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("interview-questions")
def interview_questions(
    project: str = typer.Argument(..., help="프로젝트명 (예: XCoreChat)"),
) -> None:
    """프로젝트별 면접 예상 질문·답변 초안을 50_Outputs/Interview/에 저장한다."""
    result = _handle_llm_errors(lambda: _project_agent().interview_questions(project))
    typer.secho(f"\n면접 질문 초안 완료: {project}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 면접 질문 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("resume")
def resume() -> None:
    """CareerContext + 전체 프로젝트를 읽어 이력서/자기소개서 초안을 50_Outputs/Resume/에 저장한다."""
    try:
        agent = ResumeAgent(settings=get_settings())
    except RuntimeError as e:
        _fail(f"Resume를 사용할 수 없습니다.\n  {e}\n  → .env에서 OBSIDIAN_VAULT_PATH를 설정하세요.")
    result = _handle_llm_errors(lambda: agent.generate())
    typer.secho("\n이력서/자기소개서 초안 생성 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 초안 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("ask")
def ask(
    text: str = typer.Argument(..., help="자연어 지시. 예: \"오늘 작업 회고 정리해줘\""),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 없이 바로 실행"),
) -> None:
    """자연어 문장을 해석해 알맞은 명령을 실행한다(실행 전 확인)."""
    from app.assistant import Assistant
    from app.llm.factory import get_llm_provider

    settings = get_settings()
    try:
        llm = get_llm_provider(settings)
    except LLMNotConfiguredError as e:
        _fail(
            f"LLM이 연결되어 있지 않습니다.\n  {e}\n"
            "  → 자연어 해석에는 LLM이 필요합니다. .env의 LLM_PROVIDER를 설정하세요."
        )

    assistant = Assistant(llm=llm)
    intent = _handle_llm_errors(lambda: assistant.interpret(text))

    if intent.command in ("unknown", "help", ""):
        typer.echo(assistant.help_text())
        return

    typer.secho(f"해석: {assistant.describe(intent)}", fg=typer.colors.CYAN)
    if not yes and not typer.confirm("실행할까요?"):
        typer.echo("취소했습니다.")
        return

    reply = _handle_llm_errors(lambda: assistant.execute(intent))
    typer.echo(reply)


@app.command("notify")
def notify(
    kind: str = typer.Argument(..., help="morning | evening"),
) -> None:
    """Telegram으로 아침/저녁 알림을 전송한다. Task Scheduler에서 호출하도록 설계됨."""
    from app.messaging.telegram_provider import TelegramProvider

    settings = get_settings()
    if not settings.telegram_bot_token:
        _fail("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
    if not settings.telegram_chat_id:
        _fail("TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    provider = TelegramProvider(settings.telegram_bot_token)

    # 활성 태스크 목록 수집
    task_lines: list[str] = []
    try:
        from app.agents.task_agent import TaskAgent
        tasks = TaskAgent().service.list_tasks()
        active = [t for t in tasks if getattr(t, "status", "todo") != "done"]
        task_lines = [f"· #{t.number} {t.text}" for t in active[:5]]
        if len(active) > 5:
            task_lines.append(f"  ... +{len(active) - 5}건")
    except Exception:
        pass

    # 후보 개수
    candidate_count = 0
    try:
        from app.agents.curator_agent import CuratorAgent
        candidate_count = len(CuratorAgent().list_candidates())
    except Exception:
        pass

    candidate_hint = f"\n\n후보 {candidate_count}개 쌓여있어요 → /review" if candidate_count else ""

    if kind == "morning":
        task_block = ("\n" + "\n".join(task_lines)) if task_lines else "\n할 일이 없습니다."
        text = f"🌅 **오늘 할 일**{task_block}{candidate_hint}"
    elif kind == "evening":
        text = (
            "🌙 **오늘 마무리 체크**\n\n"
            "오늘 기록할 것 있으면 남겨두세요.\n"
            "/capture <내용>  또는  /session"
            f"{candidate_hint}"
        )
    else:
        _fail(f"알 수 없는 알림 종류: {kind}  (morning | evening 중 선택)")

    provider.send(settings.telegram_chat_id, text)
    typer.secho(f"알림 전송 완료 ({kind})", fg=typer.colors.GREEN)


@app.command("serve-bot")
def serve_bot() -> None:
    """메신저 봇(텔레그램)을 long-polling으로 실행한다. 자연어/명령 + 알림 양방향."""
    from app.assistant import Assistant
    from app.llm.base import LLMNotConfiguredError as _LLMNC
    from app.llm.factory import get_llm_provider
    from app.messaging import CommandRouter, MessengerBot, get_messenger_provider
    from app.messaging.base import MessengerNotConfiguredError

    settings = get_settings()
    try:
        provider = get_messenger_provider(settings)
    except MessengerNotConfiguredError as e:
        _fail(
            f"메신저가 설정되지 않았습니다.\n  {e}\n"
            "  → .env에서 MESSENGER_PROVIDER=telegram, TELEGRAM_BOT_TOKEN을 설정하세요."
        )

    if not settings.allowed_chat_ids:
        typer.secho(
            "경고: TELEGRAM_ALLOWED_CHAT_IDS가 비어 있어 누구나 봇에 명령할 수 있습니다. "
            "본인 chat id로 제한하세요.",
            fg=typer.colors.YELLOW,
        )

    # LLM이 설정돼 있으면 자연어 의도 라우팅 활성화. 아니면 슬래시 명령만.
    assistant = None
    try:
        assistant = Assistant(llm=get_llm_provider(settings))
    except _LLMNC:
        typer.secho(
            "참고: LLM 미설정이라 자연어 명령은 비활성입니다(슬래시 명령만 동작).",
            fg=typer.colors.YELLOW,
        )

    # Vault가 설정돼 있으면 미디어(voice/image/URL) 처리 활성화
    media_handler = None
    if settings.obsidian_vault_root:
        from app.llm.stt import get_stt_provider
        from app.messaging.media_handler import TelegramMediaHandler
        from pathlib import Path as _Path
        try:
            _capture = CaptureAgent(settings=settings)
            media_handler = TelegramMediaHandler(
                provider=provider,
                capture_agent=_capture,
                vault_dir=_Path(settings.obsidian_vault_root),
                stt=get_stt_provider(),
            )
            typer.secho("미디어 처리 활성 (voice/image/URL capture).", fg=typer.colors.CYAN)
        except Exception:
            pass

    bot = MessengerBot(
        provider=provider,
        router=CommandRouter(),
        allowed_chat_ids=settings.allowed_chat_ids,
        default_chat_id=settings.telegram_chat_id,
        assistant=assistant,
        media_handler=media_handler,
    )
    typer.secho(f"봇 실행 중({provider.name}). Ctrl+C로 종료.", fg=typer.colors.GREEN)
    try:
        bot.run()
    except KeyboardInterrupt:
        typer.echo("\n봇을 종료합니다.")


@app.command("vault-cleanup")
def vault_cleanup(
    dry_run: bool = typer.Option(False, "--dry-run", help="삭제하지 않고 대상만 표시"),
    keep: int = typer.Option(3, "--keep", help="프로젝트당 보존할 최신 세션(Plan+Process 짝) 수"),
    worklog_days: int = typer.Option(30, "--worklog-days", help="distill된 worklog 세션 보존 기간(일)"),
    handoff_days: int = typer.Option(30, "--handoff-days", help="최신 N개를 넘는 SessionHandoffs 보존 기간(일)"),
) -> None:
    """오래된 10_Worklog/Sessions/와 60_Candidates/SessionHandoffs/를 정리한다.

    사람이 직접 실행하는 destructive 명령이며 MCP에는 노출하지 않는다.
    """
    from app.services.retention import cleanup_vault

    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다.")

    result = cleanup_vault(
        Path(settings.obsidian_vault_root),
        keep_per_project=keep,
        worklog_retention_days=worklog_days,
        handoff_retention_days=handoff_days,
        dry_run=dry_run,
    )

    total = len(result.deleted_worklog) + len(result.deleted_handoffs)
    if total == 0:
        typer.echo("정리할 대상이 없습니다.")
        return

    verb = "삭제 예정 (--dry-run)" if dry_run else "삭제 완료"
    typer.secho(
        f"\n{verb}: worklog {len(result.deleted_worklog)}개, handoff {len(result.deleted_handoffs)}개",
        fg=typer.colors.GREEN,
        bold=True,
    )
    for rel in result.deleted_worklog:
        typer.echo(f"  [worklog] {rel}")
    for rel in result.deleted_handoffs:
        typer.echo(f"  [handoff] {rel}")


@app.command("mcp-serve")
def mcp_serve() -> None:
    """Vault tool 레이어를 MCP(stdio)로 노출한다 — Claude Code/Desktop에서 등록해 사용.

    등록 예:
      claude mcp add work-agent-vault -- work-agent mcp-serve
    """
    settings = get_settings()
    if not settings.obsidian_vault_root:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env에서 Obsidian Vault 경로를 지정하세요.")
    from app.mcp_server import main as run_mcp_server

    run_mcp_server()


@app.command("project-briefing")
def project_briefing(
    repo: str = typer.Argument(".", help="프로젝트 판별에 쓸 repo 경로 (기본: 현재 디렉터리)"),
) -> None:
    """get_project_briefing() 결과를 stdout에 출력한다.

    Tier 1 SessionStart 훅(scripts/hooks/session-start-briefing.ps1)이 호출하는
    용도다. Vault 미설정, 매칭 실패 등 어떤 예외 상황에서도 훅 전체를 실패시키지
    않도록 항상 exit code 0으로 종료하고, 문제가 있으면 안내 문구만 출력한다.
    """
    settings = get_settings()
    if not settings.obsidian_vault_root:
        typer.echo("(work-agent Vault가 설정되지 않아 briefing을 건너뜁니다. .env의 OBSIDIAN_VAULT_PATH를 확인하세요.)")
        return
    try:
        from app import vault_tools

        briefing = vault_tools.get_project_briefing(repo, settings=settings)
    except Exception as e:
        typer.echo(f"(briefing 조회 실패: {e})")
        return
    typer.echo(briefing.text)


if __name__ == "__main__":
    app()
