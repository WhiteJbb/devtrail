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
from app.llm.base import LLMProvider
from app.prompts import render_prompt
from app.services.repo_snapshot import RepoSnapshot, capture_repo_snapshot
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

    def capture_commit(
        self,
        repo_dir: Path,
        project: str = "",
        ref: str = "HEAD",
        from_agent: bool = False,
        llm: LLMProvider | None = None,
    ) -> CaptureResult:
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

        if from_agent:
            _llm = llm
            if _llm is None:
                from app.llm.factory import get_task_llm_provider
                _llm = get_task_llm_provider("light", self.settings)
            commit_context = f"메시지: {subject}\n\n변경 파일:\n{stat}\n\ndiff:\n{diff}"
            try:
                summary = _llm.complete(
                    render_prompt("commit_summary", COMMIT_CONTEXT=commit_context)
                )
                body += f"## AI 요약\n\n{summary}\n"
            except Exception:
                if diff:
                    body += f"## Diff\n\n```diff\n{diff}\n```\n"
        elif diff:
            body += f"## Diff\n\n```diff\n{diff}\n```\n"

        result = self._write_note(rel_path, metadata, body, kind="git_summary")
        self._log("capture", f"git {sha[:10]}", result.rel_path)
        return result

    def capture_session(
        self,
        project: str | None = None,
        repo: str | None = None,
        from_repo: bool = False,
        from_agent: bool = False,
        summary_file: str | None = None,
        source: str = "agent_session",
        title: str | None = None,
    ) -> CaptureResult:
        """작업 세션을 구조화된 Markdown 노트로 10_Worklog/Daily/에 저장한다."""
        date = self._date()
        project = (project or "").strip()
        slug_parts = [date, self._slug(project) if project else None, "session"]
        base_name = "-".join(p for p in slug_parts if p)

        # 파일명 충돌 해소
        rel_path = self._unique_rel_path(f"10_Worklog/Daily/{base_name}.md")

        # Git snapshot
        snap: RepoSnapshot | None = None
        if from_repo:
            repo_path = repo or "."
            snap = capture_repo_snapshot(repo_path)

        # summary-file 읽기
        summary_text = ""
        if summary_file:
            try:
                summary_text = Path(summary_file).read_text(encoding="utf-8").strip()
            except OSError:
                summary_text = ""

        # ISO 타임스탬프
        now = self._now()
        iso_now = now.strftime("%Y-%m-%dT%H:%M:%S+09:00")

        # frontmatter
        changed_files: list[str] = snap.changed_files if snap else []
        branch = snap.branch if snap else None
        commit = snap.commit if snap else None
        metadata: dict[str, Any] = {
            "type": "session",
            "project": project,
            "source": source,
            "status": "raw",
            "needs_distill": True,
            "created_at": iso_now,
            "updated_at": iso_now,
            "from_repo": from_repo,
            "from_agent": from_agent,
            "agent_summary_missing": from_agent and not summary_text,
            "repo_path": repo or ("." if from_repo else ""),
            "branch": branch or "",
            "commit": commit or "",
            "changed_files": changed_files,
            "source_refs": [f"git:{commit[:10]}" for commit in ([commit] if commit else [])],
            "tags": ["session", "worklog"],
        }

        body = self._build_session_body(
            title=title or (f"{project} 작업 세션" if project else "작업 세션"),
            summary_text=summary_text,
            snap=snap,
        )

        result = self._write_note(rel_path, metadata, body, kind="session")
        self._log_session(
            project=project or "session",
            rel_path=result.rel_path,
            from_repo=from_repo,
            from_agent=from_agent,
        )
        return result

    def _log_session(self, project: str, rel_path: str, from_repo: bool, from_agent: bool) -> None:
        """capture-session 전용 log.md 기록 (from_repo / from_agent 포함)."""
        log_path = self.vault_dir / "log.md"
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        today = self._date()
        lines = [
            f"## [{today}] capture-session | {project}",
            "",
            f"- project: {project}",
            f"- output: {rel_path}",
            f"- from_repo: {str(from_repo).lower()}",
            f"- from_agent: {str(from_agent).lower()}",
            "",
        ]
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _unique_rel_path(self, rel_path: str) -> str:
        """이미 파일이 있으면 -2, -3, ... suffix를 붙여 고유 경로를 반환한다."""
        path = self.vault_dir / rel_path
        if not path.exists():
            return rel_path
        stem = Path(rel_path).stem
        suffix = Path(rel_path).suffix
        parent = str(Path(rel_path).parent)
        counter = 2
        while True:
            candidate = f"{parent}/{stem}-{counter}{suffix}"
            if not (self.vault_dir / candidate).exists():
                return candidate
            counter += 1

    def _build_session_body(
        self,
        title: str,
        summary_text: str,
        snap: RepoSnapshot | None,
    ) -> str:
        lines = [f"# {title}", ""]

        if summary_text:
            # summary-file 제공 시 템플릿 섹션 없이 내용을 그대로 사용
            lines += [summary_text, ""]
        else:
            lines += [
                "## 1. 오늘 작업", "- ", "",
                "## 2. 변경한 파일 / 모듈", "- ", "",
                "## 3. 해결한 문제", "- ", "",
                "## 4. 설계 결정 / 이유", "- ", "",
                "## 5. 남은 문제", "- ", "",
                "## 6. 다음 할 일", "- ", "",
                "## 7. 블로그 / 포트폴리오 소재", "- ", "",
                "## 8. Git / Source Refs", "- ", "",
            ]

        # Repo Snapshot 섹션
        lines += ["## 9. Repo Snapshot", ""]
        if snap is None:
            lines += ["_repo 정보 없음 (--from-repo 없이 실행됨)_", ""]
        elif snap.error:
            lines += [f"_Git 정보 수집 실패: {snap.error}_", ""]
        else:
            lines += [
                "### Branch",
                f"`{snap.branch or '(unknown)'}`",
                "",
                "### Recent Commits",
            ]
            if snap.recent_commits:
                for c in snap.recent_commits:
                    lines.append(f"- {c}")
            else:
                lines.append("- (없음)")
            lines += [
                "",
                "### Changed Files",
            ]
            if snap.changed_files:
                for f in snap.changed_files:
                    lines.append(f"- {f}")
            else:
                lines.append("- (없음)")
            lines += [
                "",
                "### Diff Stat",
                f"```\n{snap.diff_stat or '(없음)'}\n```",
                "",
            ]

        lines += [
            "## 10. Notes",
            "- 실제로 하지 않은 일은 적지 말 것.",
            "- 불확실한 내용은 `확실하지 않음`으로 표시할 것.",
        ]

        return "\n".join(lines) + "\n"

    def capture_attachment(
        self,
        file_path: Path,
        source: str = "telegram",
        caption: str = "",
    ) -> CaptureResult:
        """voice/image attachment를 00_Inbox/Captures/에 노트로 저장한다.

        파일 자체는 이미 00_Inbox/Raw/Attachments/에 저장돼 있어야 한다.
        """
        stamp = self._timestamp()
        try:
            rel_attachment = str(file_path.relative_to(self.vault_dir)).replace("\\", "/")
        except ValueError:
            rel_attachment = file_path.name
        is_voice = "voice" in source.lower()
        kind_str = "voice" if is_voice else "image"
        note_slug = self._slug(f"{kind_str}-{file_path.stem[:30]}")
        rel_path = f"00_Inbox/Captures/{stamp}-{note_slug}.md"
        title = "음성 Capture" if is_voice else "이미지 Capture"

        metadata: dict[str, Any] = {
            "type": "capture",
            "date": self._date(),
            "source": source,
            "status": "raw",
            "needs_distill": True,
            "attachments": [rel_attachment],
            "tags": ["capture", kind_str],
        }

        if is_voice:
            body = (
                f"# {title}\n\n"
                "## Attachment\n\n"
                f"- `{rel_attachment}`\n\n"
                "## Notes\n\n"
                "- STT/caption provider is not configured.\n"
            )
        else:
            body = (
                f"# {title}\n\n"
                "## Attachment\n\n"
                f"![[{rel_attachment}]]\n\n"
                "## Notes\n\n"
            )
            if caption:
                body += f"{caption}\n"
            else:
                body += "- OCR/caption provider is not configured.\n"

        result = self._write_note(rel_path, metadata, body, kind="attachment_capture")
        self._log(f"capture-{kind_str}", source, result.rel_path)
        return result

    def capture_url(
        self,
        url: str,
        title: str = "",
        source: str = "telegram_url",
        llm: LLMProvider | None = None,
    ) -> CaptureResult:
        """URL을 00_Inbox/Captures/에 노트로 저장한다."""
        import json
        import urllib.parse

        stamp = self._timestamp()
        domain = urllib.parse.urlparse(url).netloc or "url"
        rel_path = f"00_Inbox/Captures/{stamp}-{self._slug(domain)}.md"

        fetched_title, page_text = self._fetch_url_content(url)
        if title:
            fetched_title = title

        summary = ""
        tags: list[str] = ["capture", "url"]

        if llm and page_text:
            try:
                raw = llm.complete(
                    render_prompt(
                        "url_summary",
                        URL=url,
                        TITLE=fetched_title or "(없음)",
                        CONTENT=page_text,
                    )
                ).strip()
                parsed = json.loads(raw)
                summary = parsed.get("summary", "")
                extra = parsed.get("tags", [])
                if extra:
                    tags = list(dict.fromkeys(tags + [str(t) for t in extra]))
            except Exception:
                pass

        metadata: dict[str, Any] = {
            "type": "capture",
            "date": self._date(),
            "source": source,
            "url": url,
            "title": fetched_title,
            "status": "raw",
            "needs_distill": True,
            "tags": tags,
        }
        body = (
            "# URL Capture\n\n"
            f"- url: {url}\n"
            f"- title: {fetched_title or '(없음)'}\n"
            f"- captured_from: {source.replace('_', ' ')}\n"
        )
        if summary:
            body += f"\n## Summary\n\n{summary}\n"

        result = self._write_note(rel_path, metadata, body, kind="url_capture")
        self._log("capture-url", url[:60], result.rel_path)
        return result

    @staticmethod
    def _fetch_url_content(url: str) -> tuple[str, str]:
        """URL에서 title과 본문 텍스트를 추출한다. (title, text) 반환. 실패하면 ('', '')."""
        import re as _re
        try:
            import httpx
            resp = httpx.get(url, timeout=15.0, follow_redirects=True)
            html = resp.text
            m = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
            fetched_title = m.group(1).strip() if m else ""
            # script/style 제거 후 태그 strip
            text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=_re.IGNORECASE | _re.DOTALL)
            text = _re.sub(r"<[^>]+>", " ", text)
            text = _re.sub(r"\s+", " ", text).strip()
            return fetched_title, text[:4000]
        except Exception:
            return "", ""

    def daily_log(self, project: str = "", llm: LLMProvider | None = None) -> CaptureResult:
        date = self._date()
        name = f"{date}-{self._slug(project)}.md" if project else f"{date}.md"
        rel_path = f"10_Worklog/Daily/{name}"
        path = self.vault_dir / rel_path
        if path.exists():
            self._log("daily-log", project or date, rel_path)
            return CaptureResult(path=path, rel_path=rel_path, created=False, kind="daily_log")

        sections = ""
        if llm:
            context = self._gather_daily_context(date, project)
            if context:
                try:
                    sections = llm.complete(
                        render_prompt("daily_log_suggest", CONTEXT=context)
                    ).strip()
                except Exception:
                    sections = ""

        if not sections:
            sections = (
                "## Done\n\n- \n\n"
                "## Blockers\n\n- \n\n"
                "## Next\n\n- \n\n"
                "## Blog Seeds\n\n- \n"
            )

        metadata = {
            "type": "worklog",
            "date": date,
            "project": project,
            "tags": [],
            "source": "daily-log",
            "status": "raw",
        }
        body = f"# Daily Log - {date}\n\n{sections}\n"
        result = self._write_note(rel_path, metadata, body, kind="daily_log")
        self._log("daily-log", project or date, result.rel_path)
        return result

    def _gather_daily_context(self, date: str, project: str = "") -> str:
        """오늘의 작업 컨텍스트를 수집한다: 캡처, git 요약, open loops."""
        parts: list[str] = []

        captures_dir = self.vault_dir / "00_Inbox" / "Captures"
        if captures_dir.exists():
            for f in sorted(captures_dir.glob(f"{date}*.md"))[:10]:
                try:
                    parts.append(f"[캡처] {f.stem}\n{f.read_text(encoding='utf-8')[:300]}")
                except Exception:
                    pass

        git_dir = self.vault_dir / "10_Worklog" / "GitSummaries"
        if git_dir.exists():
            for f in sorted(git_dir.glob(f"{date}*.md"))[:5]:
                try:
                    parts.append(f"[Git] {f.stem}\n{f.read_text(encoding='utf-8')[:600]}")
                except Exception:
                    pass

        open_loops = self.vault_dir / "40_AgentMemory" / "05_OpenLoops.md"
        if open_loops.exists():
            try:
                parts.append(f"[OpenLoops]\n{open_loops.read_text(encoding='utf-8')[:600]}")
            except Exception:
                pass

        return "\n\n---\n\n".join(parts)

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
