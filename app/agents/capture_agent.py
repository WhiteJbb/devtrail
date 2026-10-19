"""Capture Agent - raw work traces into the Obsidian vault."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter

from app.config import Settings, get_settings
from app.services.candidate_writer import atomic_write_text
from app.services.identity import resolve_agent, resolve_host
from app.services.repo_snapshot import RepoSnapshot, capture_repo_snapshot
from app.services.review_question import HEADING_AI_LED, HEADING_QUESTIONS, HEADING_RELATED, HEADING_UNCLEAR
from app.services.wiki_service import WikiService


@dataclass(frozen=True)
class CaptureResult:
    path: Path
    rel_path: str
    created: bool
    kind: str


class CaptureAgent:
    """세션 노트(10_Worklog/Sessions)를 쓴다 — MCP 미연결 시 capture-session fallback."""

    def __init__(self, settings: Settings | None = None, now: datetime | None = None) -> None:
        self.settings = settings or get_settings()
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir)

    def capture_session(
        self,
        project: str | None = None,
        repo: str | None = None,
        from_repo: bool = False,
        from_agent: bool = False,
        summary_file: str | None = None,
        summary_text: str | None = None,
        session_id: str | None = None,
        source: str = "agent_session",
        title: str | None = None,
        needs_distill: bool = True,
        distill_kinds: list[str] | None = None,
        agent: str = "",
    ) -> CaptureResult:
        """작업 세션을 구조화된 Markdown 노트로 10_Worklog/Sessions/에 저장한다.

        summary_text가 주어지면 summary_file보다 우선한다(MCP처럼 요약 텍스트를 직접
        전달하는 호출 경로에서 임시 파일을 만들 필요가 없게 한다).

        needs_distill=False는 nightly distill의 재추출·중복 생성을 막기 위해 쓴다.
        distill_kinds는 부분 제외용이다 — write_session_process처럼 Decision/MemoryPatch
        분리는 끝냈지만 knowledge/blog_idea 추출은 distill에 맡겨야 하는 경로가
        ["knowledge", "blog_idea"]를 넘기면, DistillAgent가 이 노트에서는 해당 종류만
        후보로 만든다.
        """
        date = self._date()
        project = (project or "").strip()
        slug_parts = [date, self._slug(project) if project else None, "session"]
        base_name = "-".join(p for p in slug_parts if p)

        # 파일명 충돌 해소
        rel_path = self._unique_rel_path(f"10_Worklog/Sessions/{base_name}.md")

        # Git snapshot
        snap: RepoSnapshot | None = None
        if from_repo:
            repo_path = repo or "."
            snap = capture_repo_snapshot(repo_path)

        # summary_text > summary_file 순으로 요약을 확보한다
        resolved_summary = (summary_text or "").strip()
        if not resolved_summary and summary_file:
            try:
                resolved_summary = Path(summary_file).read_text(encoding="utf-8").strip()
            except OSError:
                resolved_summary = ""
        summary_text = resolved_summary

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
            "needs_distill": needs_distill,
            "created_at": iso_now,
            "updated_at": iso_now,
            "session_id": session_id or "",
            # 어느 노드에서 어느 에이전트가 남긴 기록인가. 기록 시점에만 알 수
            # 있어 나중에 채울 수 없다 — 값이 없으면 빈 문자열로 남는다.
            "host": resolve_host(),
            "agent": resolve_agent(agent),
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
        if distill_kinds:
            metadata["distill_kinds"] = list(distill_kinds)

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
                "## 9. Learning Recovery", "",
                f"### {HEADING_AI_LED}", "- ", "",
                f"### {HEADING_UNCLEAR}", "- ", "",
                f"### {HEADING_QUESTIONS}", "1. ", "",
                f"### {HEADING_RELATED}", "- ", "",
            ]

        # Repo Snapshot 섹션
        lines += ["## 10. Repo Snapshot", ""]
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
            "## 11. Notes",
            "- 실제로 하지 않은 일은 적지 말 것.",
            "- 불확실한 내용은 `확실하지 않음`으로 표시할 것.",
        ]

        return "\n".join(lines) + "\n"

    def _write_note(self, rel_path: str, metadata: dict[str, Any], body: str, kind: str) -> CaptureResult:
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(body.strip() + "\n", **metadata)
        atomic_write_text(path, frontmatter.dumps(post))
        return CaptureResult(path=path, rel_path=rel_path, created=True, kind=kind)

    def _log(self, action: str, label: str, rel_path: str) -> None:
        self.wiki_service.append_vault_log(action, label, [rel_path])

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
