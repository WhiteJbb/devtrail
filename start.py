"""work-agent 실행환경 시작 스크립트.

실행: python start.py
"""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Windows cp949 콘솔에서 한글/특수문자 출력 깨짐 방지
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT = Path(__file__).parent.resolve()
OLLAMA = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
ENV_FILE = PROJECT / ".env"

# py 런처로 Python 3.14 경로를 확인, 없으면 현재 인터프리터 사용
def _find_python() -> str:
    try:
        result = subprocess.run(
            ["py", "-3.14", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return sys.executable

PYTHON = _find_python()


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

def ok(msg):   print(f"  [OK] {msg}")
def warn(msg): print(f"  [!!] {msg}")
def info(msg): print(f"  --> {msg}")
def fail(msg): print(f"  [X] {msg}"); sys.exit(1)
def header(msg):
    print()
    print("=" * 53)
    print(f"  {msg}")
    print("=" * 53)
    print()


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


# ── Ollama 헬퍼 ───────────────────────────────────────────────────────────────

def ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/", timeout=2)
        return True
    except Exception:
        return False


def ollama_model(env: dict) -> str:
    return env.get("OLLAMA_MODEL", "qwen2.5:14b-instruct-q4_K_M")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    header("work-agent  |  Second Brain Launcher")

    # 1. 프로젝트 디렉토리
    os.chdir(PROJECT)
    ok(f"Project: {PROJECT}")

    # 2. .env 확인
    env = read_env()
    if not ENV_FILE.exists():
        warn(".env 없음 — .env.example 복사 후 설정하세요")
    else:
        ok(".env 확인")

    # 3. Python 버전
    ok(f"Python: {sys.version.split()[0]}  ({PYTHON})")

    # 4. 패키지 확인
    try:
        import typer, pydantic, frontmatter, httpx  # noqa: F401
        ok("패키지 정상")
    except ImportError as e:
        warn(f"패키지 누락: {e} — pip install 실행 중...")
        subprocess.check_call([PYTHON, "-m", "pip", "install", "-e", str(PROJECT), "-q"])
        ok("패키지 설치 완료")

    # 5. Ollama 상태 확인
    if ollama_running():
        ok("Ollama 실행 중 (localhost:11434)")
    elif OLLAMA.exists():
        info("Ollama 시작 중...")
        subprocess.Popen([str(OLLAMA)], creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(10):
            time.sleep(1)
            if ollama_running():
                ok("Ollama 시작 완료")
                break
        else:
            warn("Ollama 응답 없음 — 수동으로 확인하세요")
    else:
        warn(f"Ollama 없음: {OLLAMA}")

    # 6. 모델 확인
    if ollama_running():
        model = ollama_model(env)
        try:
            result = subprocess.run([str(OLLAMA), "list"], capture_output=True, text=True, timeout=5)
            base = model.split(":")[0]
            if base in result.stdout:
                ok(f"모델: {model}")
            else:
                warn(f"모델 '{model}' 없음 — 실행: ollama pull {model}")
        except Exception:
            warn("모델 목록 확인 실패")

    # 7. Obsidian Vault
    vault = Path(env.get("OBSIDIAN_VAULT_DIR", r"D:\personal-vault"))
    if vault.exists():
        wiki = vault / env.get("WIKI_FOLDER", "60_Wiki")
        wiki_count = len(list(wiki.rglob("*.md"))) if wiki.exists() else 0
        ok(f"Vault: {vault}  |  Wiki 페이지: {wiki_count}개")
    else:
        warn(f"Vault 없음: {vault}")

    # 8. Telegram 봇 시작
    bot_pid = _find_bot_pid()
    if bot_pid:
        ok(f"Telegram 봇 이미 실행 중 (PID: {bot_pid})")
    else:
        info("Telegram 봇 시작 중 (별도 창)...")
        subprocess.Popen(
            [PYTHON, "-m", "app.cli", "serve-bot"],
            cwd=str(PROJECT),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        time.sleep(2)
        ok("Telegram 봇 시작")

    # 9. 사용 안내
    py = f'"{PYTHON}"'
    header("실행 완료 - 사용 가능한 명령어")
    print("  [CLI] 이 창 또는 터미널에서:")
    print(f"    {py} -m app.cli suggest-topics")
    print(f"    {py} -m app.cli write-draft 'RAG 파이프라인'")
    print(f"    {py} -m app.cli wiki-query 'vLLM 설정 방법'")
    print(f"    {py} -m app.cli wiki-ingest --folder 50_Reference/AI")
    print(f"    {py} -m app.cli ask '오늘 작업 회고 정리해줘'")
    print()
    print("  [Telegram] /suggest  /worklog  /todo  /portfolio  /resume")
    print("             자연어 질문도 가능")
    print()
    wiki_folder = env.get("WIKI_FOLDER", "60_Wiki")
    print(f"  [Wiki] {vault / wiki_folder}")
    print()


def _find_bot_pid() -> int | None:
    """serve-bot 프로세스가 있으면 PID 반환."""
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
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


if __name__ == "__main__":
    main()
