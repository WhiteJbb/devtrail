"""의도 분류 결과 모델."""

from __future__ import annotations

from pydantic import BaseModel


class Intent(BaseModel):
    command: str
    arg: str = ""
    reason: str = ""
