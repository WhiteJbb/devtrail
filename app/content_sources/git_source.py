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

    def __init__(
        self,
        repo_dir: Path,
        limit: int = 20,
        include_diff: bool = True,
        diff_max_chars: int = 800,
    ):
        self.repo_dir = repo_dir
        self.limit = limit
        self.include_diff = include_diff
        self.diff_max_chars = diff_max_chars

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

            # 변경 파일 + 통계(추가/삭제 라인 수)
            stat = self._run(["show", sha, "--stat", "--format="]) or ""
            stat_lines = [s for s in stat.splitlines() if s.strip()]
            stat_text = "\n".join(stat_lines) if stat_lines else "(변경 파일 없음)"

            text = f"[{date}] {subject} ({author})\n변경 요약:\n{stat_text}"

            # 실제 변경 일부(diff)를 근거로 포함. 토큰 예산을 위해 잘라 넣는다.
            if self.include_diff and self.diff_max_chars > 0:
                diff = self._run(["show", sha, "--format=", "--unified=1"]) or ""
                diff = diff.strip()
                if diff:
                    if len(diff) > self.diff_max_chars:
                        diff = diff[: self.diff_max_chars].rstrip() + "\n…(diff 일부 생략)"
                    text += f"\n변경 내용(일부):\n{diff}"

            chunks.append(
                SourceChunk(
                    source_type="git",
                    ref=sha[:10],
                    title=subject,
                    text=text,
                )
            )
        return chunks
