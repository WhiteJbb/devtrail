"""work-agent 대화형 대시보드.

실행: python start.py
"""

import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Windows cp949 콘솔 한글 깨짐 방지
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT = Path(__file__).parent.resolve()
OLLAMA = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
ENV_FILE = PROJECT / ".env"
PYTHON = sys.executable

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    _RICH = True
except ImportError:
    _RICH = False

console = Console() if _RICH else None


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

def ok(msg):
    if _RICH:
        console.print(f"  [green]✓[/green] {msg}")
    else:
        print(f"  [OK] {msg}")

def warn(msg):
    if _RICH:
        console.print(f"  [yellow]![/yellow] {msg}")
    else:
        print(f"  [!!] {msg}")

def info(msg):
    if _RICH:
        console.print(f"  [cyan]→[/cyan] {msg}")
    else:
        print(f"  --> {msg}")

def fail(msg):
    if _RICH:
        console.print(f"  [red]✗[/red] {msg}")
    else:
        print(f"  [X] {msg}")
    sys.exit(1)


# ── .env 파싱 ─────────────────────────────────────────────────────────────────

def read_env() -> dict:
    env = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/", timeout=2)
        return True
    except Exception:
        return False


# ── Vault 상태 ────────────────────────────────────────────────────────────────

def vault_status(vault: Path) -> dict:
    today = time.strftime("%Y-%m-%d")

    raw_count = sum(
        1 for p in vault.rglob("*.md")
        if any(str(p.relative_to(vault)).startswith(prefix)
               for prefix in ("00_Inbox", "10_Worklog"))
    )

    candidate_by_kind: dict[str, int] = {}
    candidate_today = 0
    cand_dir = vault / "60_Candidates"
    if cand_dir.exists():
        for p in cand_dir.rglob("*.md"):
            stem = p.stem
            if stem[:8].replace("-", "") == today.replace("-", ""):
                candidate_today += 1
            kind_folder = p.parent.name
            candidate_by_kind[kind_folder] = candidate_by_kind.get(kind_folder, 0) + 1
    candidate_count = sum(candidate_by_kind.values())

    knowledge_count = sum(1 for _ in (vault / "20_Knowledge").rglob("*.md")) \
        if (vault / "20_Knowledge").exists() else 0

    last_distill = ""
    digest_dir = vault / "50_Outputs" / "Digest"
    if digest_dir.exists():
        digests = sorted(digest_dir.glob("*.md"), reverse=True)
        if digests:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", digests[0].stem)
            last_distill = m.group(1) if m else ""

    return {
        "raw": raw_count,
        "candidates": candidate_count,
        "candidate_today": candidate_today,
        "candidate_by_kind": candidate_by_kind,
        "knowledge": knowledge_count,
        "last_distill": last_distill,
        "recent_knowledge": _recent_knowledge(vault),
        "open_loops": _open_loops(vault),
    }


def _recent_knowledge(vault: Path, limit: int = 5) -> list[str]:
    kdir = vault / "20_Knowledge"
    if not kdir.exists():
        return []
    files = sorted(kdir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    titles = []
    for f in files[:limit]:
        try:
            import frontmatter
            post = frontmatter.loads(f.read_text(encoding="utf-8"))
            title = str(post.metadata.get("title") or "").strip() or f.stem
        except Exception:
            title = f.stem
        titles.append(title)
    return titles


def _open_loops(vault: Path, limit: int = 4) -> list[str]:
    loops_file = vault / "40_AgentMemory" / "05_OpenLoops.md"
    if not loops_file.exists():
        return []
    content = loops_file.read_text(encoding="utf-8")
    items = re.findall(r"^[-*]\s+(?:\[[ x]\]\s+)?(.+)$", content, re.MULTILINE)
    return [i.strip() for i in items if i.strip()][:limit]


# ── 대시보드 출력 ──────────────────────────────────────────────────────────────

def _render_dashboard(status: dict, env: dict) -> None:
    today = time.strftime("%Y-%m-%d")

    if not _RICH:
        print(f"\n  raw:{status['raw']}  후보:{status['candidates']}  지식:{status['knowledge']}")
        return

    # 상단 수치 행
    counts = Table.grid(padding=(0, 2))
    counts.add_column(style="bold")
    counts.add_column()
    counts.add_row(
        f"[dim]raw[/dim]  [bold white]{status['raw']}[/bold white]",
        f"[dim]후보[/dim]  [bold yellow]{status['candidates']}[/bold yellow]",
    )
    counts.add_row(
        f"[dim]지식[/dim]  [bold green]{status['knowledge']}[/bold green]",
        f"[dim]distill[/dim]  " + (
            "[bold green]오늘[/bold green]" if status["last_distill"] == today
            else f"[dim]{status['last_distill'] or '없음'}[/dim]"
        ),
    )

    # 최근 지식
    if status["recent_knowledge"]:
        knowledge_lines = "\n".join(
            f"  [cyan]·[/cyan] {t}" for t in status["recent_knowledge"]
        )
    else:
        knowledge_lines = "  [dim](아직 없음 — promote-candidate로 추가)[/dim]"

    # 오픈 루프
    if status["open_loops"]:
        loop_lines = "\n".join(
            f"  [yellow]·[/yellow] {item}" for item in status["open_loops"]
        )
    else:
        loop_lines = "  [dim](없음)[/dim]"

    # kind breakdown
    if status["candidate_by_kind"]:
        kind_str = "  " + "  ".join(
            f"[dim]{k}[/dim]:[bold]{v}[/bold]"
            for k, v in sorted(status["candidate_by_kind"].items())
        )
    else:
        kind_str = ""

    body = (
        f"{counts}\n\n"
        f"[bold]최근 지식[/bold]\n{knowledge_lines}\n\n"
        f"[bold]오픈 루프[/bold]\n{loop_lines}"
    )
    if kind_str:
        body += f"\n\n[bold]후보 종류별[/bold]\n{kind_str}"

    writer = env.get("WRITER_PROVIDER", "")
    model_info = env.get("GEMINI_FLASH_MODEL", "gemini-2.5-flash") if writer == "gemini" else (writer or "미설정")
    footer = f"[dim]{today}  |  LLM: {model_info}[/dim]"

    console.print()
    console.print(Panel(
        body,
        title="[bold]work-agent[/bold]",
        subtitle=footer,
        border_style="bright_blue",
        padding=(1, 2),
    ))


def _render_menu() -> None:
    if _RICH:
        console.print(
            "  [bold cyan][1][/bold cyan] distill-today      "
            "[bold cyan][2][/bold cyan] nightly-distill\n"
            "  [bold cyan][3][/bold cyan] list-candidates    "
            "[bold cyan][4][/bold cyan] apply-memory-patch\n"
            "  [bold cyan][5][/bold cyan] push-digest        "
            "[bold cyan][6][/bold cyan] weekly-distill\n"
            "  [bold cyan][c][/bold cyan] capture 메모       "
            "[bold cyan][s][/bold cyan] search 키워드\n"
            "  [bold cyan][q][/bold cyan] 종료\n"
        )
    else:
        print("  [1] distill-today   [2] nightly-distill")
        print("  [3] list-candidates [4] apply-memory-patch")
        print("  [5] push-digest     [6] weekly-distill")
        print("  [c] capture 메모    [s] search 키워드")
        print("  [q] 종료\n")


def _run_cli(*args: str) -> None:
    print()
    subprocess.run([PYTHON, "-m", "app.cli", *args], cwd=str(PROJECT))
    print()
    input("  계속하려면 Enter...")


# ── 인터랙티브 루프 ────────────────────────────────────────────────────────────

def run_dashboard(vault: Path, env: dict) -> None:
    while True:
        if _RICH:
            console.clear()
        status = vault_status(vault)
        _render_dashboard(status, env)
        _render_menu()

        try:
            choice = input("  > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "q":
            break
        elif choice == "1":
            _run_cli("distill-today")
        elif choice == "2":
            _run_cli("nightly-distill")
        elif choice == "3":
            _run_cli("list-candidates")
        elif choice == "4":
            _run_cli("apply-memory-patch", "--interactive")
        elif choice == "5":
            _run_cli("push-digest", "--daily")
        elif choice == "6":
            _run_cli("weekly-distill")
        elif choice == "c":
            try:
                text = input("  메모: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue
            if text:
                _run_cli("capture", text)
        elif choice == "s":
            try:
                query = input("  검색어: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue
            if query:
                _run_cli("search", query)
        else:
            if _RICH:
                console.print("  [dim]알 수 없는 선택입니다.[/dim]")
            else:
                print("  알 수 없는 선택입니다.")
            time.sleep(0.8)


# ── 시작 점검 ─────────────────────────────────────────────────────────────────

def startup_checks(env: dict) -> tuple[bool, Path | None]:
    """환경 점검 후 (vault_ok, vault_path) 반환."""
    if _RICH:
        console.rule("[bold]work-agent  startup[/bold]")
    else:
        print("=" * 50)

    ok(f"Python {sys.version.split()[0]}")

    if not ENV_FILE.exists():
        warn(".env 없음 — .env.example 복사 후 설정하세요")
    else:
        ok(".env 확인")

    try:
        for _pkg in ("typer", "pydantic", "frontmatter", "httpx"):
            __import__(_pkg)
        ok("패키지 정상")
    except ImportError as e:
        warn(f"패키지 누락: {e} — 설치 중...")
        subprocess.check_call([PYTHON, "-m", "pip", "install", "-e", str(PROJECT), "-q"])
        ok("패키지 설치 완료")

    # Ollama
    if ollama_running():
        ok("Ollama 실행 중")
    elif OLLAMA.exists():
        info("Ollama 시작 중...")
        subprocess.Popen([str(OLLAMA)], creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(10):
            time.sleep(1)
            if ollama_running():
                ok("Ollama 시작 완료")
                break
        else:
            warn("Ollama 응답 없음")
    else:
        warn(f"Ollama 없음: {OLLAMA}")

    # Writer
    writer = env.get("WRITER_PROVIDER", "")
    gemini_key = env.get("GEMINI_API_KEY", "")
    if writer == "gemini" and gemini_key:
        ok(f"Writer: Gemini ({env.get('GEMINI_FLASH_MODEL', 'gemini-2.5-flash')})")
    elif writer == "gemini":
        warn("GEMINI_API_KEY 미설정")
    else:
        info(f"Writer: {writer or '(미설정)'}")

    # Vault
    vault_path = env.get("OBSIDIAN_VAULT_PATH") or env.get("OBSIDIAN_VAULT_DIR", "")
    vault = Path(vault_path) if vault_path else None
    if vault and vault.exists():
        ok(f"Vault: {vault}")
    elif vault:
        warn(f"Vault 없음: {vault}")
        vault = None
    else:
        warn("OBSIDIAN_VAULT_PATH 미설정")

    # Telegram bot
    messenger = env.get("MESSENGER_PROVIDER", "")
    if messenger == "telegram":
        bot_pid = _find_bot_pid()
        if bot_pid:
            ok(f"Telegram 봇 실행 중 (PID: {bot_pid})")
        else:
            info("Telegram 봇 시작 중...")
            subprocess.Popen(
                [PYTHON, "-m", "app.cli", "serve-bot"],
                cwd=str(PROJECT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            time.sleep(2)
            ok("Telegram 봇 시작")

    return vault is not None, vault


def _find_bot_pid() -> int | None:
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "serve-bot" in line:
                parts = line.strip().split(",")
                if parts:
                    try:
                        return int(parts[-1])
                    except ValueError:
                        return -1
    except Exception:
        pass
    return None


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    os.chdir(PROJECT)
    env = read_env()
    vault_ok, vault = startup_checks(env)

    if vault_ok:
        print()
        input("  점검 완료. Enter로 대시보드 진입...")
        run_dashboard(vault, env)
    else:
        print()
        warn("Vault가 설정되지 않아 대화형 모드를 시작할 수 없습니다.")
        info("OBSIDIAN_VAULT_PATH를 .env에 설정 후 다시 실행하세요.")


if __name__ == "__main__":
    main()
