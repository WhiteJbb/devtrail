"""Capture Agent - raw work traces into the Obsidian vault."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter

from app.config import Settings, get_settings
from app.services.wiki_service import WikiService


@dataclass(frozen=True)
class CaptureResult:
    path: Path
    rel_path: str
    created: bool
    kind: str


class CaptureAgent:
    """Store memo, chat, commit, and daily-log captures in safe vault areas."""

    def __init__(self, settings: Settings | None = None, now: datetime | None = None) -> None:
        self.settings = settings or get_settings()
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)

    def capture(self, text: str, project: str = "", source: str = "manual") -> CaptureResult:
        if not text.strip():
            raise ValueError("capture text is empty.")

        stamp = self._timestamp()
        rel_path = f"00_Inbox/Captures/{stamp}-{self._slug(project or 'memo')}.md"
        title = f"Capture - {project}" if project else "Capture"
        metadata = {
            "type": "capture",
            "date": self._date(),
            "project": project,
            "source": source,
            "status": "raw",
            "tags": [],
        }
        body = f"# {title}\n\n{text.strip()}\n"
        result = self._write_note(rel_path, metadata, body, kind="capture")
        self._log("capture", project or "manual memo", result.rel_path)
        return result

    def capture_chat(self, file_path: Path, source: str, project: str = "") -> CaptureResult:
        if not source.strip():
            raise ValueError("chat source is empty.")
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))

        text = file_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise ValueError("chat file is empty.")

        stamp = self._timestamp()
        rel_path = f"00_Inbox/Chats/{stamp}-{self._slug(source)}-{self._slug(project or 'chat')}.md"
        title = f"Chat Capture - {source}"
        if project:
            title += f" / {project}"
        metadata = {
            "type": "chat_capture",
            "date": self._date(),
            "project": project,
            "source": source,
            "source_file": str(file_path),
            "status": "raw",
            "tags": [],
        }
        body = f"# {title}\n\n_source file: {file_path}_\n\n{text}\n"
        result = self._write_note(rel_path, metadata, body, kind="chat_capture")
        self._log("capture", f"{source} chat", result.rel_path)
        return result

    def capture_commit(self, repo_dir: Path, project: str = "", ref: str = "HEAD") -> CaptureResult:
        repo_dir = repo_dir.resolve()
        if self._git(repo_dir, ["rev-parse", "--is-inside-work-tree"]) is None:
            raise ValueError(f"not a git repository: {repo_dir}")

        meta_raw = self._git(repo_dir, ["show", ref, "-s", "--date=iso", "--format=%H%n%an%n%ad%n%s%n%b"])
        if not meta_raw:
            raise ValueError(f"git commit not found: {ref}")
        lines = meta_raw.splitlines()
        sha = lines[0].strip() if len(lines) > 0 else ""
        author = lines[1].strip() if len(lines) > 1 else ""
        date = lines[2].strip() if len(lines) > 2 else ""
        subject = lines[3].strip() if len(lines) > 3 else sha[:10]
        message_body = "\n".join(lines[4:]).strip()

        stat = (self._git(repo_dir, ["show", ref, "--stat", "--format="]) or "").strip()
        diff = (self._git(repo_dir, ["show", ref, "--format=", "--unified=2"]) or "").strip()
        if diff and len(diff) > self.settings.git_diff_max_chars:
            diff = diff[: self.settings.git_diff_max_chars].rstrip() + "\n...(diff 일부 생략)"

        stamp = self._timestamp()
        rel_path = f"10_Worklog/GitSummaries/{stamp}-{self._slug(project or repo_dir.name)}-{sha[:10]}.md"
        metadata = {
            "type": "git_summary",
            "date": self._date(),
            "project": project,
            "source": "git",
            "repo": str(repo_dir),
            "commit": sha,
            "status": "raw",
            "tags": [],
        }
        body = (
            f"# Git Summary - {subject}\n\n"
            f"- commit: `{sha}`\n"
            f"- author: {author}\n"
            f"- date: {date}\n"
            f"- project: {project or repo_dir.name}\n\n"
        )
        if message_body:
            body += f"## Message\n\n{message_body}\n\n"
        body += f"## Changed Files\n\n{stat or '(no stat)'}\n\n"
        if diff:
            body += f"## Diff\n\n```diff\n{diff}\n```\n"

        result = self._write_note(rel_path, metadata, body, kind="git_summary")
        self._log("capture", f"git {sha[:10]}", result.rel_path)
        return result

    def daily_log(self, project: str = "") -> CaptureResult:
        date = self._date()
        name = f"{date}-{self._slug(project)}.md" if project else f"{date}.md"
        rel_path = f"10_Worklog/Daily/{name}"
        path = self.vault_dir / rel_path
        if path.exists():
            self._log("daily-log", project or date, rel_path)
            return CaptureResult(path=path, rel_path=rel_path, created=False, kind="daily_log")

        metadata = {
            "type": "worklog",
            "date": date,
            "project": project,
            "tags": [],
            "source": "daily-log",
            "status": "raw",
        }
        body = (
            f"# Daily Log - {date}\n\n"
            "## Done\n\n"
            "- \n\n"
            "## Blockers\n\n"
            "- \n\n"
            "## Next\n\n"
            "- \n\n"
            "## Blog Seeds\n\n"
            "- \n"
        )
        result = self._write_note(rel_path, metadata, body, kind="daily_log")
        self._log("daily-log", project or date, result.rel_path)
        return result

    def _write_note(self, rel_path: str, metadata: dict[str, Any], body: str, kind: str) -> CaptureResult:
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(body.strip() + "\n", **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return CaptureResult(path=path, rel_path=rel_path, created=True, kind=kind)

    def _log(self, action: str, label: str, rel_path: str) -> None:
        self.wiki_service.append_vault_log(action, label, [rel_path])

    def _git(self, repo_dir: Path, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(repo_dir),
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

    def _now(self) -> datetime:
        return self.now or datetime.now()

    def _date(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    def _timestamp(self) -> str:
        return self._now().strftime("%Y%m%d-%H%M%S")

    def _slug(self, value: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^0-9a-z가-힣_-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-_")
        return text or "untitled"
