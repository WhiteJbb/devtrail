"""태스크 에이전트 — /task, /tasks, /done 처리."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from app.config import Settings, get_settings
from app.services.task_service import Task, TaskService


@dataclass
class TaskResult:
    ok: bool
    message: str
    task: Task | None = None


class TaskAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.service = TaskService(Path(self.settings.obsidian_vault_root))

    def add(self, text: str) -> TaskResult:
        task_text, due, section = _parse_task(text)
        task = self.service.add_task(task_text, due, section)
        due_str = f"\n기한: `{due}`" if due else ""
        return TaskResult(
            ok=True,
            message=f"태스크 추가 ✅\n**[{section}]** {task_text}{due_str}",
            task=task,
        )

    def list_tasks(self) -> TaskResult:
        tasks = self.service.list_tasks()
        return TaskResult(ok=True, message=self.service.format_list(tasks))

    def done(self, number_str: str) -> TaskResult:
        try:
            n = int(number_str.strip())
        except ValueError:
            return TaskResult(ok=False, message="번호를 입력해주세요. 예: /done 2")

        task = self.service.complete_task(n)
        if task is None:
            total = len(self.service.list_tasks())
            return TaskResult(
                ok=False,
                message=f"{n}번 태스크를 찾지 못했습니다. (현재 {total}개)\n/tasks 로 목록 확인",
            )
        return TaskResult(
            ok=True,
            message=f"완료 ✅\n~~{task.text}~~",
            task=task,
        )


# ── 날짜/섹션 파싱 ─────────────────────────────────────────────────────────


_WEEKDAY_MAP: dict[str, int] = {
    "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_STRIP_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
    r"\d{4}-\d{2}-\d{2}",
    r"(오전|오후)\s*\d{1,2}시",
    r"(오늘|내일)",
    r"이번\s*주",
    r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일)",
    r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"(까지|안에)",
    r"\b(by|on)\b",
]


def _parse_task(text: str) -> tuple[str, str | None, str]:
    """자연어 텍스트에서 (task_text, due_iso, section)을 추출한다."""
    today = date.today()
    due: str | None = None
    section = "언제든지"
    target_date: date | None = None

    # ISO datetime
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\b", text)
    if m:
        due = m.group(1)
        target_date = date.fromisoformat(m.group(1).split("T")[0])
    else:
        # ISO date
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if m:
            due = m.group(1)
            target_date = date.fromisoformat(m.group(1))

    if target_date is None:
        if re.search(r"오늘|today", text, re.IGNORECASE):
            target_date = today
        elif re.search(r"내일|tomorrow", text, re.IGNORECASE):
            target_date = today + timedelta(days=1)
        else:
            m = re.search(
                r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일"
                r"|\bmonday|tuesday|wednesday|thursday|friday|saturday|sunday\b)",
                text, re.IGNORECASE,
            )
            if m:
                wd_raw = m.group(1).lower()
                wd_key = wd_raw[:1] if wd_raw.endswith("요일") else wd_raw
                target_wd = _WEEKDAY_MAP.get(wd_key) if len(wd_key) == 1 else _WEEKDAY_MAP.get(wd_raw)
                if target_wd is not None:
                    days_ahead = (target_wd - today.weekday()) % 7 or 7
                    target_date = today + timedelta(days=days_ahead)

    # 시간 추가
    if target_date is not None and due is None:
        due = target_date.isoformat()
    if target_date is not None and due and "T" not in due:
        time_m = re.search(r"(오전|오후)\s*(\d{1,2})시", text)
        if time_m:
            hour = int(time_m.group(2))
            if time_m.group(1) == "오후" and hour < 12:
                hour += 12
            due = f"{due}T{hour:02d}:00"

    # 이번 주 (날짜 없이)
    if target_date is None and re.search(r"이번\s*주", text):
        section = "이번 주"

    # 섹션 결정
    if target_date is not None:
        if target_date <= today:
            section = "오늘"
        elif target_date <= today + timedelta(days=6):
            section = "이번 주"
        else:
            section = "언제든지"

    # 태스크 텍스트 정제
    task_text = text
    for pattern in _STRIP_PATTERNS:
        task_text = re.sub(pattern, "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"\s{2,}", " ", task_text).strip().strip(",").strip()

    if not task_text:
        task_text = text.strip()

    return task_text, due, section
