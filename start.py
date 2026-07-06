"""devtrail 시작 점검 + 대시보드 실행.

실행: python start.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

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
    console = Console()
    def ok(msg):   console.print(f"  [green]✓[/green] {msg}")
    def warn(msg): console.print(f"  [yellow]![/yellow] {msg}")
    def info(msg): console.print(f"  [cyan]→[/cyan] {msg}")
    def fail(msg): console.print(f"  [red]✗[/red] {msg}"); sys.exit(1)
    def rule(msg): console.rule(f"[bold]{msg}[/bold]")
except ImportError:
    def ok(msg):   print(f"  [OK] {msg}")
    def warn(msg): print(f"  [!!] {msg}")
    def info(msg): print(f"  --> {msg}")
    def fail(msg): print(f"  [X] {msg}"); sys.exit(1)
    def rule(msg): print("=" * 50)


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


def ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/", timeout=2)
        return True
    except Exception:
        return False


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


def startup_checks(env: dict) -> Path | None:
    """환경 점검 후 vault Path 반환. 실패 시 None."""
    rule("devtrail  startup")

    ok(f"Python {sys.version.split()[0]}")

    if not ENV_FILE.exists():
        warn(".env 없음 — .env.example 복사 후 설정하세요")
    else:
        ok(".env 확인")

    try:
        for pkg in ("typer", "pydantic", "frontmatter", "httpx", "textual"):
            __import__(pkg)
        ok("패키지 정상")
    except ImportError as e:
        warn(f"패키지 누락: {e} — 설치 중...")
        subprocess.check_call([PYTHON, "-m", "pip", "install", "-e", str(PROJECT), "-q"])
        ok("패키지 설치 완료")

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
        warn(f"Ollama 없음 ({OLLAMA})")

    writer = env.get("WRITER_PROVIDER", "")
    if writer == "gemini" and env.get("GEMINI_API_KEY"):
        ok(f"Writer: Gemini ({env.get('GEMINI_FLASH_MODEL', 'gemini-2.5-flash')})")
    elif writer == "gemini":
        warn("GEMINI_API_KEY 미설정")
    else:
        info(f"Writer: {writer or '(미설정)'}")

    vault_path = env.get("OBSIDIAN_VAULT_PATH") or env.get("OBSIDIAN_VAULT_DIR", "")
    vault = Path(vault_path) if vault_path else None
    if vault and vault.exists():
        ok(f"Vault: {vault}")
    elif vault:
        warn(f"Vault 경로 없음: {vault}")
        vault = None
    else:
        warn("OBSIDIAN_VAULT_PATH 미설정")

    messenger = env.get("MESSENGER_PROVIDER", "")
    if messenger == "telegram":
        if _find_bot_pid():
            ok("Telegram 봇 실행 중")
        else:
            info("Telegram 봇 시작 중...")
            subprocess.Popen(
                [PYTHON, "-m", "app.cli", "serve-bot"],
                cwd=str(PROJECT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            time.sleep(2)
            ok("Telegram 봇 시작")

    return vault


def main() -> None:
    os.chdir(PROJECT)
    env = read_env()
    vault = startup_checks(env)

    if not vault:
        print()
        warn("Vault가 설정되지 않아 대시보드를 시작할 수 없습니다.")
        info("OBSIDIAN_VAULT_PATH를 .env에 설정 후 다시 실행하세요.")
        return

    print()
    try:
        input("  점검 완료. Enter로 대시보드 진입...")
    except (KeyboardInterrupt, EOFError):
        return

    from dashboard import run
    run(vault)


if __name__ == "__main__":
    main()
