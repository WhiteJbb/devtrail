"""초안 생성 요청 모델."""

from __future__ import annotations

from pydantic import BaseModel


class DraftRequest(BaseModel):
    """`write-draft "주제"`로 들어오는 요청.

    topic은 필수. 나머지는 수집 단계에서 채워지거나 사용자가 옵션으로 지정한다.
    """

    topic: str
    source_project: str = ""
    tags: list[str] = []
    sync_notion: bool = True
