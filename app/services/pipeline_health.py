"""파이프라인 헬스체크 — nightly-distill이 조용히 멈춘 것을 감지한다.

nightly-distill은 60_Candidates/ 후보를 만드는 시스템의 심장인데, 스케줄러가
멈춰도(서버 절전, 태스크 미등록 등) 아무 신호가 없다. 마지막 daily digest
날짜를 기준으로 정지 여부를 판정해 notify morning / list-candidates에 노출한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DIGEST_DIR = "50_Outputs/Digest"
_DIGEST_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-daily-digest\.md$")
_STALE_AFTER_DAYS = 2  # 매일 도는 nightly가 이틀 넘게 밀리면 정지로 본다


@dataclass(frozen=True)
class PipelineHealth:
    last_digest_date: str  # YYYY-MM-DD, 한 번도 안 돌았으면 ""
    age_days: int | None  # 마지막 실행 이후 경과일, 기록 없으면 None

    @property
    def is_stale(self) -> bool:
        return self.age_days is not None and self.age_days > _STALE_AFTER_DAYS


def check_pipeline_health(vault_dir: Path, now: datetime | None = None) -> PipelineHealth:
    """50_Outputs/Digest/의 최신 digest 날짜로 nightly-distill 정지 여부를 판정한다.

    파일명(YYYY-MM-DD-daily-digest.md)의 날짜를 신뢰한다 — mtime은 vault git 동기화
    등으로 실제 생성 시점과 어긋날 수 있다.
    """
    now = now or datetime.now()
    digest_dir = vault_dir / _DIGEST_DIR
    if not digest_dir.exists():
        return PipelineHealth(last_digest_date="", age_days=None)

    dates: list[str] = []
    for path in digest_dir.glob("*.md"):
        match = _DIGEST_RE.match(path.name)
        if match:
            dates.append(match.group(1))
    if not dates:
        return PipelineHealth(last_digest_date="", age_days=None)

    latest = max(dates)
    try:
        latest_dt = datetime.strptime(latest, "%Y-%m-%d")
    except ValueError:
        return PipelineHealth(last_digest_date="", age_days=None)
    return PipelineHealth(last_digest_date=latest, age_days=(now - latest_dt).days)


def stale_warning(health: PipelineHealth) -> str:
    """정지 상태일 때만 사람이 읽을 경고 한 줄을 반환한다."""
    if not health.is_stale:
        return ""
    return (
        f"⚠ nightly-distill이 {health.age_days}일째 실행되지 않았어요 "
        f"(마지막: {health.last_digest_date}). 스케줄러가 살아 있는지 확인하세요."
    )
