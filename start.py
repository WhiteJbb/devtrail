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
PYTHON = sys.executable


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

def ok(msg):    print(f"  [OK] {msg}")
def warn(msg):  print(f"  [!!] {msg}")
def info(msg):  print(f"  --> {msg}")
def fail(msg):  print(f"  [X]  {msg}"); sys.exit(1)
def header(msg):
    print()
    print("=" * 58)
    print(f"  {msg}")
    print("=" * 58)
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


# ── Vault 상태 ────────────────────────────────────────────────────────────────

def vault_status(vault: Path) -> dict:
    """Vault의 현재 상태를 반환한다."""
    raw_count = sum(
        1 for p in vault.rglob("*.md")
        if any(str(p.relative_to(vault)).startswith(prefix)
               for prefix in ("00_Inbox", "10_Worklog"))
    )
    candidate_count = sum(
        1 for p in (vault / "60_Candidates").rglob("*.md")
        if (vault / "60_Candidates") in p.parents or p.parent == vault / "60_Candidates"
    ) if (vault / "60_Candidates").exists() else 0

    knowledge_count = sum(1 for _ in (vault / "20_Knowledge").rglob("*.md")) \
        if (vault / "20_Knowledge").exists() else 0

    return {
        "raw": raw_count,
        "candidates": candidate_count,
        "knowledge": knowledge_count,
    }


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    header("work-agent  |  Obsidian LLM Wiki Core")

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
    ollama_ok = False
    if ollama_running():
        ok("Ollama 실행 중 (localhost:11434)")
        ollama_ok = True
    elif OLLAMA.exists():
        info("Ollama 시작 중...")
        subprocess.Popen([str(OLLAMA)], creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(10):
            time.sleep(1)
            if ollama_running():
                ok("Ollama 시작 완료")
                ollama_ok = True
                break
        else:
            warn("Ollama 응답 없음 — 수동으로 확인하세요")
    else:
        warn(f"Ollama 없음: {OLLAMA}")

    # 6. 모델 확인
    if ollama_ok:
        model = env.get("OLLAMA_MODEL", "qwen3:8b")
        try:
            result = subprocess.run(
                [str(OLLAMA), "list"], capture_output=True, text=True, timeout=5,
            )
            base = model.split(":")[0]
            if base in result.stdout:
                ok(f"로컬 모델: {model}")
            else:
                warn(f"모델 '{model}' 없음 — 실행: ollama pull {model}")
        except Exception:
            warn("모델 목록 확인 실패")

    # 7. Gemini 설정 확인
    gemini_key = env.get("GEMINI_API_KEY", "")
    writer = env.get("WRITER_PROVIDER", "")
    if writer == "gemini" and gemini_key:
        ok(f"Writer: Gemini ({env.get('GEMINI_FLASH_MODEL', 'gemini-2.5-flash')})")
    elif writer == "gemini" and not gemini_key:
        warn("WRITER_PROVIDER=gemini 이지만 GEMINI_API_KEY 미설정 — 글쓰기 명령 동작 안 함")
    else:
        info(f"Writer: {writer or '(미설정)'}")

    # 8. Obsidian Vault 확인 및 상태
    vault_path = env.get("OBSIDIAN_VAULT_PATH") or env.get("OBSIDIAN_VAULT_DIR", "")
    vault = Path(vault_path) if vault_path else None

    if vault and vault.exists():
        status = vault_status(vault)
        ok(f"Vault: {vault}")
        print(f"       raw 기록: {status['raw']}개  |  후보 대기: {status['candidates']}개  |  지식: {status['knowledge']}개")

        # 다음 권장 액션 제안
        if status["raw"] > 0 and status["candidates"] == 0:
            info(f"raw 기록 {status['raw']}개 → distill-today 실행 권장")
        elif status["candidates"] > 0:
            info(f"후보 {status['candidates']}개 대기 중 → list-candidates 로 검토 권장")
    elif vault:
        warn(f"Vault 없음: {vault}  — init-vault 실행 권장")
    else:
        warn("OBSIDIAN_VAULT_PATH 미설정 — .env에서 경로를 지정하세요")

    # 9. Telegram 봇 시작
    messenger = env.get("MESSENGER_PROVIDER", "")
    if messenger == "telegram":
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
    else:
        info("Telegram 봇 비활성 (MESSENGER_PROVIDER 미설정)")

    # 10. 사용 안내
    py = f'"{PYTHON}"'
    header("실행 완료 — 사용 가능한 명령어")

    print("  [Vault 설정]")
    print(f"    {py} -m app.cli init-vault")
    print(f"    {py} -m app.cli install-hooks --repo <레포경로> --project <프로젝트명>")
    print()
    print("  [지식 순환 파이프라인]")
    print(f"    {py} -m app.cli capture '오늘 작업 내용' --project WorkAgent")
    print(f"    {py} -m app.cli capture-session --project WorkAgent --from-repo")
    print(f"    {py} -m app.cli distill-today")
    print(f"    {py} -m app.cli list-candidates")
    print(f"    {py} -m app.cli promote-candidate '60_Candidates/Knowledge/...'")
    print()
    print("  [검색 / Wiki]")
    print(f"    {py} -m app.cli search 'RAG 검색'")
    print(f"    {py} -m app.cli wiki-ingest")
    print(f"    {py} -m app.cli wiki-query 'vLLM 설정 방법'")
    print(f"    {py} -m app.cli build-context 'XCoreChat 개발환경 분리'")
    print()
    print("  [글쓰기]")
    print(f"    {py} -m app.cli write-blog 'XCoreChat RAG 전략'")
    print(f"    {py} -m app.cli summarize-project XCoreChat")
    print(f"    {py} -m app.cli interview-questions XCoreChat")
    print()
    print("  [자연어]")
    print(f"    {py} -m app.cli ask '오늘 작업 세션 정리해줘'")
    print()
    if messenger == "telegram":
        print("  [Telegram]")
        print("    /capture <메모>   /search <검색어>   /distill")
        print("    /context <주제>   /candidates        /draft <주제>")
        print("    /session <프로젝트>   /worklog   /todo")
        print()


def _find_bot_pid() -> int | None:
    """serve-bot 프로세스가 있으면 PID 반환."""
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


if __name__ == "__main__":
    main()
