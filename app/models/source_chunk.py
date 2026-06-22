"""content source가 반환하는 공통 단위."""

from __future__ import annotations

from pydantic import BaseModel


class SourceChunk(BaseModel):
    """수집된 한 조각의 컨텍스트.

    모든 content source(local docs, git, notion)는 이 타입의 리스트를 반환한다.
    LLM 프롬프트에 들어가는 컨텍스트의 기본 단위이자, 결과의 source_refs 근거가 된다.
    """

    source_type: str  # 예: "worklog", "project-context", "git", "notion-idea"
    ref: str          # 출처 식별자. 예: 파일 경로, 커밋 해시, notion page id
    text: str         # 실제 내용
    title: str = ""   # 사람이 읽을 짧은 제목(선택)

    def as_ref(self) -> str:
        """source_refs 표기에 쓸 짧은 참조 문자열."""
        label = self.title or self.ref
        return f"{self.source_type}:{label}"
