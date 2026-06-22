"""로컬 문서 소스 — workspace/docs/*.md 를 읽는다."""

from __future__ import annotations

from pathlib import Path

from app.models import SourceChunk

# 파일명(확장자 제외) → source_type 매핑. 이 목록에 있는 문서만 읽는다.
_DOC_TYPES = {
    "worklog": "worklog",
    "project-context": "project-context",
    "blog-ideas": "blog-ideas",
    "todo": "todo",
}


class LocalDocSource:
    """workspace/docs 아래 알려진 마크다운 문서를 SourceChunk로 읽는다."""

    name = "local-docs"

    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir

    def fetch(self) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        if not self.docs_dir.exists():
            return chunks

        for stem, source_type in _DOC_TYPES.items():
            path = self.docs_dir / f"{stem}.md"
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            chunks.append(
                SourceChunk(
                    source_type=source_type,
                    ref=str(path),
                    title=stem,
                    text=text,
                )
            )
        return chunks
