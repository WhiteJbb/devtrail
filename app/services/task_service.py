"""태스크 서비스 — 70_Tasks/Active.md CRUD."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

ACTIVE_FILE = "70_Tasks/Active.md"
DONE_DIR = "70_Tasks/Done"

SECTIONS = ["오늘", "이번 주", "언제든지"]

_TEMPLATE = "# Active Tasks\n\n## 오늘\n\n## 이번 주\n\n## 언제든지\n"

# 줄 끝 ^xxxxxx (6자리 hex) — Obsidian 블록 레퍼런스 형식
_ID_RE = re.compile(r"\s*\^([a-f0-9]{6})\s*$")


def _new_id() -> str:
    return secrets.token_hex(3)  # 예: "a3f2b1"


@dataclass
class Task:
    number: int
    text: str
    due: str | None
    section: str
    id: str = ""  # 6자리 hex 안정 ID; 구형 태스크는 빈 문자열


class TaskService:
    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir
        self.active_path = vault_dir / ACTIVE_FILE

    def _ensure_file(self) -> None:
        if not self.active_path.exists():
            self.active_path.parent.mkdir(parents=True, exist_ok=True)
            self.active_path.write_text(_TEMPLATE, encoding="utf-8")

    def _read_lines(self) -> list[str]:
        self._ensure_file()
        return self.active_path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines: list[str]) -> None:
        content = "\n".join(lines)
        if not content.endswith("\n"):
            content += "\n"
        self.active_path.write_text(content, encoding="utf-8")

    def list_tasks(self) -> list[Task]:
        lines = self._read_lines()
        tasks: list[Task] = []
        n = 1
        current_section = "언제든지"
        for line in lines:
            s = line.strip()
            m = re.match(r"^## (.+)$", s)
            if m:
                current_section = m.group(1).strip()
                continue
            m = re.match(r"^- \[ \] (.+)$", s)
            if m:
                raw = m.group(1).strip()
                # 안정 ID 파싱 후 제거
                id_m = _ID_RE.search(raw)
                task_id = id_m.group(1) if id_m else ""
                raw = _ID_RE.sub("", raw).strip()
                # due 파싱
                due_m = re.search(r"📅\s*(\S+)", raw)
                due = due_m.group(1) if due_m else None
                text = re.sub(r"\s*📅\s*\S+", "", raw).strip()
                tasks.append(Task(number=n, text=text, due=due, section=current_section, id=task_id))
                n += 1
        return tasks

    def add_task(self, text: str, due: str | None, section: str, _reuse_id: str = "") -> Task:
        if section not in SECTIONS:
            section = "언제든지"

        task_id = _reuse_id or _new_id()
        lines = self._read_lines()
        entry = f"- [ ] {text}"
        if due:
            entry += f" 📅 {due}"
        entry += f" ^{task_id}"

        target_header = f"## {section}"
        insert_idx: int | None = None
        for i, line in enumerate(lines):
            if line.strip() == target_header:
                j = i + 1
                while j < len(lines) and not lines[j].startswith("## "):
                    j += 1
                insert_idx = j
                while insert_idx > i + 1 and lines[insert_idx - 1].strip() == "":
                    insert_idx -= 1
                break

        if insert_idx is None:
            lines.append(f"## {section}")
            lines.append(entry)
            lines.append("")
        else:
            lines.insert(insert_idx, entry)

        self._write_lines(lines)

        # ID로 정확히 매칭 — 텍스트 중복이어도 안전
        tasks = self.list_tasks()
        for t in reversed(tasks):
            if t.id == task_id:
                return t
        return Task(number=len(tasks), text=text, due=due, section=section, id=task_id)

    # ── 공통 제거 로직 ──────────────────────────────────────────────────────

    def _remove_task_line(self, target: Task, write_done: bool) -> Task | None:
        """Active.md에서 target 줄을 제거하고, write_done이면 Done 파일에 기록한다."""
        lines = self._read_lines()
        new_lines: list[str] = []
        removed = False
        for line in lines:
            if not removed:
                s = line.strip()
                if target.id and s.startswith("- [ ] ") and s.endswith(f" ^{target.id}"):
                    removed = True
                    continue
                elif not target.id:
                    # ID 없는 구형 태스크: 텍스트 재조합으로 폴백
                    expected = f"- [ ] {target.text}"
                    if target.due:
                        expected += f" 📅 {target.due}"
                    if s == expected:
                        removed = True
                        continue
            new_lines.append(line)

        if not removed:
            return None

        self._write_lines(new_lines)
        if write_done:
            self._append_done_entry(target)
        return target

    def _append_done_entry(self, target: Task) -> None:
        today_str = date.today().isoformat()
        done_dir = self.vault_dir / DONE_DIR
        done_dir.mkdir(parents=True, exist_ok=True)
        done_file = done_dir / f"{today_str}.md"

        now_str = datetime.now().strftime("%H:%M")
        due_part = f" (기한: {target.due})" if target.due else ""
        entry = f"- [x] {target.text}{due_part} ✅ {now_str}\n"

        if done_file.exists() and done_file.stat().st_size > 0:
            with open(done_file, "a", encoding="utf-8") as f:
                f.write(entry)
        else:
            done_file.write_text(f"# {today_str} 완료\n\n{entry}", encoding="utf-8")

    # ── 번호 기반 (타이핑 명령) ──────────────────────────────────────────────

    def complete_task(self, number: int) -> Task | None:
        target = next((t for t in self.list_tasks() if t.number == number), None)
        if target is None:
            return None
        return self._remove_task_line(target, write_done=True)

    def delete_task(self, number: int) -> Task | None:
        target = next((t for t in self.list_tasks() if t.number == number), None)
        if target is None:
            return None
        return self._remove_task_line(target, write_done=False)

    # ── ID 기반 (인라인 버튼) ────────────────────────────────────────────────

    def complete_task_by_id(self, task_id: str) -> Task | None:
        target = next((t for t in self.list_tasks() if t.id == task_id), None)
        if target is None:
            return None
        return self._remove_task_line(target, write_done=True)

    def delete_task_by_id(self, task_id: str) -> Task | None:
        target = next((t for t in self.list_tasks() if t.id == task_id), None)
        if target is None:
            return None
        return self._remove_task_line(target, write_done=False)

    # ── 수정 ────────────────────────────────────────────────────────────────

    def edit_task(self, number: int, new_text: str, new_due: str | None, new_section: str) -> Task | None:
        deleted = self.delete_task(number)
        if deleted is None:
            return None
        return self.add_task(new_text, new_due, new_section, _reuse_id=deleted.id)

    # ── 출력 ────────────────────────────────────────────────────────────────

    def format_list(self, tasks: list[Task]) -> str:
        if not tasks:
            return "등록된 태스크가 없습니다.\n\n/task <내용> 으로 추가하세요."

        today = date.today().isoformat()
        by_section: dict[str, list[Task]] = {}
        for t in tasks:
            by_section.setdefault(t.section, []).append(t)

        overdue_count = 0
        lines = ["**할 일 목록**"]
        for section in SECTIONS:
            section_tasks = by_section.get(section, [])
            if not section_tasks:
                continue
            lines.append(f"\n**{section}**")
            for t in section_tasks:
                if t.due and t.due.split("T")[0] < today:
                    due_str = f" ⚠️ `{t.due}`"
                    overdue_count += 1
                elif t.due:
                    due_str = f" `{t.due}`"
                else:
                    due_str = ""
                # text에는 이미 ^id가 제거된 상태 (list_tasks에서 파싱 시 제거됨)
                lines.append(f"{t.number}. {t.text}{due_str}")

        if overdue_count:
            lines.append(f"\n⚠️ 기한 초과 {overdue_count}개")
        lines.append("\n`/done <번호>` · `/del <번호>` · `/edit <번호> <새내용>`")
        return "\n".join(lines)
