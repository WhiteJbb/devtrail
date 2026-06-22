"""work-agent CLI 진입점.

이 파일은 얇게 유지한다 — 인자 파싱과 출력만 담당하고,
실제 로직은 services/agents 계층에 둔다. (스테이지 4에서 채운다)
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

app = typer.Typer(
    add_completion=False,
    help="Work Agent — 작업 기록 기반 기술 블로그 초안 생성기",
    no_args_is_help=True,
)

_PENDING = "이 명령은 다음 단계에서 구현됩니다."


@app.command("suggest-topics")
def suggest_topics() -> None:
    """최근 작업 기록을 바탕으로 블로그 주제를 추천한다."""
    typer.echo(_PENDING)


@app.command("write-draft")
def write_draft(topic: str = typer.Argument(..., help="블로그 주제")) -> None:
    """특정 주제로 블로그 초안을 생성한다."""
    typer.echo(_PENDING)


@app.command("preview")
def preview(target: str = typer.Argument("latest", help="latest 또는 slug")) -> None:
    """최신(또는 지정) 초안의 메타데이터와 본문 일부를 보여준다."""
    typer.echo(_PENDING)


@app.command("sync-notion")
def sync_notion(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """로컬 draft 메타데이터를 Notion Blog DB와 동기화한다."""
    typer.echo(_PENDING)


if __name__ == "__main__":
    app()
