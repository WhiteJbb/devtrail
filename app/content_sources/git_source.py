"""Git 로그 소스 — 최근 커밋과 변경 파일을 읽는다."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import SourceChunk

# 커밋 구분자/필드 구분자로 충돌 가능성이 낮은 토큰을 사용.
_REC_SEP = "\x1e"
_FIELD_SEP = "\x1f"
_PRETTY = f"%H{_FIELD_SEP}%an{_FIELD_SEP}%ad{_FIELD_SEP}%s{_REC_SEP}"


class GitSource:
    """`git log`로 최근 N개 커밋(메시지 + 변경 파일)을 SourceChunk로 만든다.

    git 저장소가 아니거나 git이 없으면 빈 리스트를 반환한다(파이프라인 안전).
    """

    name = "git"

    def __init__(self, repo_dir: Path, limit: int = 20):
        self.repo_dir = repo_dir
        self.limit = limit

    def _run(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except (FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def fetch(self) -> list[SourceChunk]:
        if self._run(["rev-parse", "--is-inside-work-tree"]) is None:
            return []

        out = self._run(["log", f"-{self.limit}", f"--pretty=format:{_PRETTY}", "--date=short"])
        if not out:
            return []

        chunks: list[SourceChunk] = []
        for record in out.split(_REC_SEP):
            record = record.strip()
            if not record:
                continue
            parts = record.split(_FIELD_SEP)
            if len(parts) < 4:
                continue
            sha, author, date, subject = parts[0], parts[1], parts[2], parts[3]

            files = self._run(["show", "--name-only", "--pretty=format:", sha]) or ""
            file_list = [f for f in files.splitlines() if f.strip()]
            files_text = "\n".join(f"  - {f}" for f in file_list) if file_list else "  (변경 파일 없음)"

            text = f"[{date}] {subject} ({author})\n변경 파일:\n{files_text}"
            chunks.append(
                SourceChunk(
                    source_type="git",
                    ref=sha[:10],
                    title=subject,
                    text=text,
                )
            )
        return chunks
