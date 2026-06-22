"""work-agent CLI 진입점.

얇게 유지한다 — 인자 파싱과 출력만 담당하고, 실제 로직은 BlogAgent에 위임한다.
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

from app.agents import BlogAgent, PortfolioAgent, ResumeAgent, TodoAgent, WorklogAgent
from app.config import get_settings
from app.llm.base import LLMError, LLMNotConfiguredError
from app.models import DraftRequest
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


@app.command("index-vault")
def index_vault() -> None:
    """Obsidian Vault의 Markdown 노트를 읽고 root index.md를 갱신한다."""
    service = _wiki_service_from_settings()
    result = service.index_vault()

    typer.secho("\nVault index 갱신 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  notes: {len(result.notes)}")
    typer.echo(f"  index: {result.index_path}")


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


@app.command("suggest-topics")
def suggest_topics() -> None:
    """최근 작업 기록을 바탕으로 블로그 주제를 추천한다."""
    agent = BlogAgent()
    suggestions = _handle_llm_errors(agent.suggest_topics)

    if not suggestions:
        typer.echo("추천할 주제를 찾지 못했습니다. 작업 기록을 더 채운 뒤 다시 시도하세요.")
        return

    for i, s in enumerate(suggestions, 1):
        title = s.title_candidates[0] if s.title_candidates else "(제목 후보 없음)"
        typer.secho(f"\n[{i}] {title}", fg=typer.colors.CYAN, bold=True)
        for alt in s.title_candidates[1:]:
            typer.echo(f"    · {alt}")
        if s.reason:
            typer.echo(f"  이유: {s.reason}")
        if s.outline:
            typer.echo("  예상 목차:")
            for item in s.outline:
                typer.echo(f"    - {item}")
        if s.source_refs:
            typer.echo(f"  source: {', '.join(s.source_refs)}")


@app.command("write-draft")
def write_draft(
    topic: str = typer.Argument(..., help="블로그 주제"),
    source_project: str = typer.Option("", "--project", help="관련 프로젝트명"),
    no_notion: bool = typer.Option(False, "--no-notion", help="Notion 동기화 건너뛰기"),
) -> None:
    """특정 주제로 블로그 초안을 생성해 workspace/drafts/에 저장한다."""
    agent = BlogAgent()
    request = DraftRequest(topic=topic, source_project=source_project, sync_notion=not no_notion)
    post = _handle_llm_errors(lambda: agent.write_draft(request))

    typer.secho(f"\n초안 생성 완료: {post.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {post.local_path}")
    typer.echo(f"  slug: {post.slug}")
    if post.tags:
        typer.echo(f"  태그: {', '.join(post.tags)}")
    if post.source_refs:
        typer.echo(f"  source: {', '.join(post.source_refs)}")
    typer.echo("  (preview latest 로 확인할 수 있습니다)")


@app.command("revise")
def revise(target: str = typer.Argument("latest", help="latest 또는 slug")) -> None:
    """기존 초안을 source 범위 안에서 문장/구조만 다듬는다(새 사실 추가 없음)."""
    agent = BlogAgent()
    post = _handle_llm_errors(lambda: agent.revise(target))

    if post is None:
        if target == "latest":
            typer.echo("저장된 초안이 없습니다. write-draft 로 먼저 생성하세요.")
        else:
            typer.echo(f"'{target}' 초안을 찾지 못했습니다.")
        return

    typer.secho(f"\n초안 다듬기 완료: {post.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {post.local_path}")
    typer.echo("  (preview latest 로 확인할 수 있습니다)")


_STATUS_COLOR = {
    "idea": typer.colors.BRIGHT_BLACK,
    "draft": typer.colors.YELLOW,
    "review": typer.colors.CYAN,
    "published": typer.colors.GREEN,
}


@app.command("list")
def list_drafts() -> None:
    """저장된 초안을 상태/수정일과 함께 목록으로 보여준다."""
    agent = BlogAgent()
    posts = agent.list_drafts()
    if not posts:
        typer.echo("저장된 초안이 없습니다. write-draft 로 먼저 생성하세요.")
        return

    for post in posts:
        status = post.status.value
        color = _STATUS_COLOR.get(status, typer.colors.WHITE)
        date = post.updated_at.strftime("%Y-%m-%d")
        typer.echo(
            f"  {date}  "
            + typer.style(f"{status:<9}", fg=color)
            + f"{post.title}  "
            + typer.style(f"({post.slug})", fg=typer.colors.BRIGHT_BLACK)
        )
    typer.echo(f"\n  총 {len(posts)}건")


@app.command("preview")
def preview(target: str = typer.Argument("latest", help="latest 또는 slug")) -> None:
    """최신(또는 지정) 초안의 메타데이터와 본문 일부를 보여준다."""
    agent = BlogAgent()
    result = agent.preview(target)
    if result is None:
        if target == "latest":
            typer.echo("저장된 초안이 없습니다. write-draft 로 먼저 생성하세요.")
        else:
            typer.echo(f"'{target}' 초안을 찾지 못했습니다.")
        return

    post = result.post
    typer.secho(f"\n{post.title}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  status: {post.status.value}  |  slug: {post.slug}")
    if post.tags:
        typer.echo(f"  태그: {', '.join(post.tags)}")
    if post.source_project:
        typer.echo(f"  프로젝트: {post.source_project}")
    if post.source_refs:
        typer.echo(f"  source: {', '.join(post.source_refs)}")
    typer.echo(f"  파일: {post.local_path}")
    typer.secho("\n--- 본문 일부 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.excerpt)


@app.command("export-tistory")
def export_tistory(
    target: str = typer.Argument("latest", help="latest 또는 slug"),
    fmt: str = typer.Option("html", "--format", help="html 또는 md"),
) -> None:
    """초안을 티스토리에 붙여넣을 형식(HTML/MD)으로 변환해 workspace/blogs/에 저장한다."""
    agent = BlogAgent()
    try:
        result = agent.export_tistory(target, fmt)
    except ValueError as e:
        _fail(str(e))

    if result is None:
        if target == "latest":
            typer.echo("저장된 초안이 없습니다. write-draft 로 먼저 생성하세요.")
        else:
            typer.echo(f"'{target}' 초안을 찾지 못했습니다.")
        return

    post = result.post
    typer.secho(f"\n티스토리용 변환 완료 ({result.fmt})", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.echo("  → 이 파일 내용을 티스토리 글쓰기 화면에 붙여넣으세요"
               f" ({'HTML 모드' if result.fmt == 'html' else '마크다운 모드'}).")
    typer.secho("\n  아래는 티스토리 입력란에 따로 넣을 항목입니다:", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(f"    제목: {post.title}")
    if post.tags:
        typer.echo(f"    태그: {', '.join(post.tags)}")
    typer.echo("  (티스토리 공식 API는 2024년 종료되어 자동 게시는 지원하지 않습니다)")


@app.command("publish-done")
def publish_done(
    target: str = typer.Argument("latest", help="latest 또는 slug"),
    url: str = typer.Option("", "--url", help="게시된 티스토리 글 주소"),
) -> None:
    """티스토리 게시 완료를 기록한다(status=published + URL을 로컬·Notion에 반영)."""
    agent = BlogAgent()
    post = agent.publish_done(target, url)
    if post is None:
        if target == "latest":
            typer.echo("저장된 초안이 없습니다.")
        else:
            typer.echo(f"'{target}' 초안을 찾지 못했습니다.")
        return

    typer.secho(f"\n게시 완료 기록: {post.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  status: {post.status.value}")
    if post.published_url:
        typer.echo(f"  URL: {post.published_url}")
    typer.echo(f"  Notion 반영: {agent.notion_mode}")


@app.command("sync-notion")
def sync_notion(dry_run: bool = typer.Option(False, "--dry-run", help="실제 반영 없이 계획만 출력")) -> None:
    """로컬 draft 메타데이터를 Notion Blog DB와 동기화한다."""
    agent = BlogAgent()
    report = agent.sync_notion(dry_run=dry_run)

    mode_note = "mock(JSON 백엔드)" if report.mode == "mock" else "Notion API"
    if report.mode == "mock":
        typer.secho(
            "NOTION_API_KEY가 없어 mock 모드로 동작합니다(로컬 JSON에 기록).",
            fg=typer.colors.YELLOW,
        )
    header = "동기화 계획" if dry_run else "동기화 완료"
    typer.secho(f"\n{header} [{mode_note}]", fg=typer.colors.CYAN, bold=True)

    if not report.entries:
        typer.echo("  동기화할 로컬 초안이 없습니다.")
        return

    for e in report.entries:
        verb = "생성" if e.action == "create" else "갱신"
        mark = "(예정)" if dry_run else "완료"
        typer.echo(f"  - [{verb} {mark}] {e.title}  ({e.slug})")

    typer.echo(f"\n  생성 {len(report.created)}건 · 갱신 {len(report.updated)}건")


@app.command("worklog")
def worklog() -> None:
    """최근 작업(git/worklog/notion)을 자동 회고로 정리해 workspace/worklogs/에 저장한다."""
    agent = WorklogAgent()
    result = _handle_llm_errors(lambda: agent.generate())

    typer.secho("\n작업 회고 생성 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 회고 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("push-digest")
def push_digest(
    worklog: bool = typer.Option(False, "--worklog", help="작업 회고도 함께 보냄"),
) -> None:
    """주제 추천(+선택 작업 회고)을 메신저로 보낸다. 스케줄러로 정기 실행하면 알림처럼 동작."""
    from app.messaging import get_messenger_provider
    from app.messaging.base import MessengerNotConfiguredError
    from app.services import build_digest

    settings = get_settings()
    try:
        provider = get_messenger_provider(settings)
    except MessengerNotConfiguredError as e:
        _fail(
            f"메신저가 설정되지 않았습니다.\n  {e}\n"
            "  → .env에서 MESSENGER_PROVIDER, 토큰을 설정하세요."
        )
    if not settings.telegram_chat_id:
        _fail("보낼 대상이 없습니다. .env에서 TELEGRAM_CHAT_ID를 설정하세요.")

    suggestions = _handle_llm_errors(BlogAgent().suggest_topics)
    worklog_text = ""
    if worklog:
        worklog_text = _handle_llm_errors(lambda: WorklogAgent().generate(save=False).text)

    text = build_digest(suggestions, worklog_text)
    provider.send(settings.telegram_chat_id, text)
    typer.secho("푸시 전송 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  대상 chat: {settings.telegram_chat_id}  ·  주제 {len(suggestions)}건")


@app.command("todo")
def todo() -> None:
    """최근 작업(git/worklog/todo/notion)을 바탕으로 다음 할 일을 제안해 workspace/todos/에 저장한다."""
    agent = TodoAgent()
    result = _handle_llm_errors(lambda: agent.generate())

    typer.secho("\n다음 할 일 제안 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 할 일 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("portfolio")
def portfolio() -> None:
    """프로젝트 기록을 바탕으로 포트폴리오 설명 초안을 만들어 workspace/portfolio/에 저장한다."""
    result = _handle_llm_errors(lambda: PortfolioAgent().generate())
    typer.secho("\n포트폴리오 초안 생성 완료", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  파일: {result.path}")
    typer.secho("\n--- 초안 ---", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(result.text)


@app.command("resume")
def resume() -> None:
    """작업 기록을 바탕으로 이력서 bullet/자기소개서 초안을 만들어 workspace/resume/에 저장한다."""
    result = _handle_llm_errors(lambda: ResumeAgent().generate())
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


@app.command("wiki-ingest")
def wiki_ingest(
    folder: str = typer.Option("", "--folder", "-f", help="특정 폴더만 처리 (예: 50_Reference/AI)"),
) -> None:
    """Obsidian 볼트 소스 문서를 읽어 wiki 페이지를 생성·갱신한다."""
    from app.agents.wiki_agent import build_wiki_agent

    settings = get_settings()
    if not settings.wiki_enabled:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env를 확인하세요.")

    label = f"폴더: {folder}" if folder else f"전체 볼트: {settings.obsidian_vault_root}"
    typer.echo(f"wiki 생성 중... ({label})")
    agent = build_wiki_agent(char_budget=settings.context_char_budget)
    result = _handle_llm_errors(lambda: agent.ingest(folder_filter=folder))
    typer.secho(result, fg=typer.colors.GREEN)


@app.command("wiki-query")
def wiki_query(
    question: str = typer.Argument(..., help="위키에 물어볼 질문"),
    save: str = typer.Option("", "--save", "-s", help="답변을 wiki 페이지로 저장 (예: ai/rag-tips.md)"),
) -> None:
    """wiki를 탐색해 질문에 답한다. --save로 답변을 페이지로 저장할 수 있다."""
    from app.agents.wiki_agent import build_wiki_agent

    settings = get_settings()
    if not settings.wiki_enabled:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env를 확인하세요.")

    agent = build_wiki_agent(char_budget=settings.context_char_budget)
    answer = _handle_llm_errors(lambda: agent.query(question))
    typer.echo(answer)
    if save:
        msg = _handle_llm_errors(lambda: agent.file_answer(question, answer, save))
        typer.secho(f"\n{msg}", fg=typer.colors.GREEN)


@app.command("wiki-lint")
def wiki_lint() -> None:
    """wiki 건강 상태 점검: 고아 페이지, 누락 링크, 갱신 필요 항목 등."""
    from app.agents.wiki_agent import build_wiki_agent

    settings = get_settings()
    if not settings.wiki_enabled:
        _fail("OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env를 확인하세요.")

    typer.echo("wiki 점검 중...")
    agent = build_wiki_agent(char_budget=settings.context_char_budget)
    result = _handle_llm_errors(lambda: agent.lint())
    typer.echo(result)


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

    bot = MessengerBot(
        provider=provider,
        router=CommandRouter(),
        allowed_chat_ids=settings.allowed_chat_ids,
        default_chat_id=settings.telegram_chat_id,
        assistant=assistant,
    )
    typer.secho(f"봇 실행 중({provider.name}). Ctrl+C로 종료.", fg=typer.colors.GREEN)
    try:
        bot.run()
    except KeyboardInterrupt:
        typer.echo("\n봇을 종료합니다.")


if __name__ == "__main__":
    app()
