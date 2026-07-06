"""SessionStart 훅이 호출하는 독립 스크립트 — get_project_briefing 결과를 stdout에 출력한다.

work-agent가 설치된 환경(`pip install -e .` 또는 배포 패키지)에서 실행해야 한다.
Vault 미설정, 매칭 실패 등 어떤 예외 상황에서도 훅 전체를 실패시키지 않도록
항상 exit code 0으로 종료하고, 문제가 있으면 안내 문구만 출력한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows 콘솔 기본 인코딩이 cp949면 한글 출력 시 깨지므로 UTF-8로 강제(app/cli.py와 동일 처리).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from app import vault_tools
from app.config import get_settings


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else str(Path.cwd())
    settings = get_settings()
    if not settings.obsidian_vault_root:
        print("(work-agent Vault가 설정되지 않아 briefing을 건너뜁니다. .env의 OBSIDIAN_VAULT_PATH를 확인하세요.)")
        return 0
    try:
        briefing = vault_tools.get_project_briefing(repo, settings=settings)
    except Exception as e:  # 훅은 항상 통과시켜야 하므로 예외를 삼킨다
        print(f"(briefing 조회 실패: {e})")
        return 0
    print(briefing.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
