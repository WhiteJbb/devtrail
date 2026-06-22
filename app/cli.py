"""work-agent CLI 진입점.

얇게 유지한다 — 인자 파싱과 출력만 담당하고, 실제 로직은 BlogAgent에 위임한다.
"""

from __future__ import annotations

import sys

import typer

# Windows 콘솔/파이프 기본 인코딩이 cp949면 한글·em dash 출력 시 깨지므로 UTF-8로 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from app.agents import BlogAgent
from app.config import get_settings
from app.llm.base import LLMError, LLMNotConfiguredError
from app.models import DraftRequest

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


@app.command("serve-bot")
def serve_bot() -> None:
    """메신저 봇(텔레그램)을 long-polling으로 실행한다. 명령+알림 양방향."""
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

    bot = MessengerBot(
        provider=provider,
        router=CommandRouter(),
        allowed_chat_ids=settings.allowed_chat_ids,
        default_chat_id=settings.telegram_chat_id,
    )
    typer.secho(f"봇 실행 중({provider.name}). Ctrl+C로 종료.", fg=typer.colors.GREEN)
    try:
        bot.run()
    except KeyboardInterrupt:
        typer.echo("\n봇을 종료합니다.")


if __name__ == "__main__":
    app()
