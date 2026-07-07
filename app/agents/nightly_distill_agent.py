"""Nightly Distill Agent — 하루 작업을 종합 정제하고 요약을 전송한다.

distill-today + suggest-career-bullets + daily digest 생성 + Telegram 전송을 묶는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import frontmatter

from app.agents.career_bullet_agent import CareerBulletAgent, CareerBulletResult
from app.agents.distill_agent import DistillAgent, DistillResult
from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.services.task_service import DONE_DIR
from app.services.wiki_service import WikiNote, WikiService

_WEEKLY_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class NightlyDistillResult:
    distill: DistillResult
    career: CareerBulletResult
    digest_text: str
    digest_path: Path | None
    digest_rel_path: str
    sent_telegram: bool
    expired_candidates: list[str] = field(default_factory=list)  # TTL 삭제
    archived_candidates: list[str] = field(default_factory=list)  # TTL 아카이브
    auto_applied_patches: list[str] = field(default_factory=list)  # 저위험 패치 자동 반영


class NightlyDistillAgent:
    """하루 마감 시 raw 기록을 종합 정제하고 daily digest를 생성한다."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir)

    def run(self, weekly: bool = False) -> NightlyDistillResult:
        """daily(기본) 또는 weekly 모드로 정제 + digest를 생성한다."""
        distill_agent = DistillAgent(settings=self.settings, llm=self.llm, now=self.now)

        if weekly:
            distill_result = distill_agent.distill_range(days=_WEEKLY_LOOKBACK_DAYS)
        else:
            distill_result = distill_agent.distill_today()

        career_agent = CareerBulletAgent(settings=self.settings, llm=self.llm, now=self.now)
        career_result = career_agent.suggest()

        # TTL 지난 후보 정리 — 재생성 가능 kind는 삭제, decision/memory_patch는 _Archive/.
        # 검토 안 된 후보가 무한 누적되는 것을 막는다 (2026-07 대청소 44개의 재발 방지).
        from app.services.retention import cleanup_candidates

        expired, archived = cleanup_candidates(self.vault_dir, now=self.now)

        # 저위험 패치 자동 반영 — requires_user_review=False로 명시된 것만.
        # Lessons/OpenLoops는 append 전용이라 오염 반경이 작아 검토 게이트를 생략한다.
        auto_applied = self._auto_apply_low_risk_patches()

        digest_text = self._build_digest(
            distill_result,
            career_result,
            weekly=weekly,
            expired=expired,
            archived=archived,
            auto_applied=auto_applied,
        )
        digest_path, digest_rel = self._save_digest(digest_text, weekly=weekly)
        sent = self._try_send_telegram(digest_text)

        return NightlyDistillResult(
            distill=distill_result,
            career=career_result,
            digest_text=digest_text,
            digest_path=digest_path,
            digest_rel_path=digest_rel,
            sent_telegram=sent,
            expired_candidates=expired,
            archived_candidates=archived,
            auto_applied_patches=auto_applied,
        )

    def _auto_apply_low_risk_patches(self) -> list[str]:
        """requires_user_review=False인 MemoryPatch 후보를 대상 파일에 자동 반영한다."""
        patches_dir = self.vault_dir / "60_Candidates" / "MemoryPatches"
        if not patches_dir.exists():
            return []

        from app.agents.curator_agent import CuratorAgent

        curator = CuratorAgent(settings=self.settings, now=self.now)
        applied: list[str] = []
        for md_path in sorted(patches_dir.glob("*.md")):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            meta = post.metadata
            if str(meta.get("status", "") or "").strip().lower() != "candidate":
                continue
            if meta.get("requires_user_review", True):
                continue
            rel = str(md_path.relative_to(self.vault_dir)).replace("\\", "/")
            try:
                result = curator.apply_memory_patch(rel)
                applied.append(f"{rel} → {result.promoted_path}")
            except Exception:
                continue  # 개별 패치 실패가 nightly 전체를 막지 않는다
        return applied

    # ── Digest 빌더 ──────────────────────────────────────────────────────────

    def _build_digest(
        self,
        distill: DistillResult,
        career: CareerBulletResult,
        weekly: bool = False,
        expired: list[str] | None = None,
        archived: list[str] | None = None,
        auto_applied: list[str] | None = None,
    ) -> str:
        date = self._date()
        label = "Weekly Digest" if weekly else "Daily Digest"
        lines = [f"# {label} — {date}", ""]

        # 기한 초과 태스크 (가장 먼저 표시 — 주의 필요)
        overdue = self._overdue_tasks()
        if overdue:
            lines += ["## ⚠️ 기한 초과 태스크", ""]
            for text, due, days in overdue:
                lines.append(f"- {text}  (기한: `{due}`, {days}일 초과)")
            lines.append("")

        # 완료한 태스크
        done_tasks = self._done_tasks(weekly=weekly)
        if done_tasks:
            lines += ["## 완료한 태스크", ""]
            for entry in done_tasks:
                lines.append(f"- {entry}")
            lines.append("")

        # 이번 기간 session 노트 수집 (weekly면 7일치, daily면 오늘만)
        sessions = self._week_sessions() if weekly else self._today_sessions()
        lines += ["## 오늘 한 일", ""]
        if sessions:
            for s in sessions:
                lines.append(f"- {s.title}")
        else:
            lines.append("- (session 노트 없음)")
        lines.append("")

        # 정리된 지식 후보
        knowledge = [w for w in distill.written if w.spec.kind == "knowledge"]
        lines += ["## 정리된 지식 후보", ""]
        if knowledge:
            for w in knowledge:
                lines.append(f"- {w.spec.title}" + (f"  ({w.spec.project})" if w.spec.project else ""))
        else:
            lines.append("- (없음)")
        lines.append("")

        # 블로그 후보
        blog = [w for w in distill.written if w.spec.kind == "blog_idea"]
        lines += ["## 블로그 후보", ""]
        if blog:
            for w in blog:
                lines.append(f"- {w.spec.title}")
        else:
            lines.append("- (없음)")
        lines.append("")

        # 이력서/포폴 소재
        lines += ["## 이력서/포폴 소재", ""]
        if career.written:
            for w in career.written:
                lines.append(f"- {w.spec.title}" + (f"  ({w.spec.project})" if w.spec.project else ""))
        else:
            lines.append("- (없음)")
        lines.append("")

        # 다음 할 일: memory_patch / decisions에서 수집
        mem = [w for w in distill.written if w.spec.kind == "memory_patch"]
        lines += ["## 다음 할 일", ""]
        if mem:
            for w in mem:
                lines.append(f"- {w.spec.title}")
        else:
            lines.append("- (없음 — todo 명령으로 생성 가능)")
        lines.append("")

        # 미해결 이슈: decision 후보에서 수집
        decisions = [w for w in distill.written if w.spec.kind == "decision"]
        lines += ["## 미해결 이슈", ""]
        if decisions:
            for w in decisions:
                lines.append(f"- {w.spec.title}")
        else:
            lines.append("- (없음)")
        lines.append("")

        # critic 게이트 탈락 — 오탐이면 사람이 여기서 발견해 수동 복구할 수 있다
        if distill.dropped:
            lines += ["## critic 게이트 탈락 후보", ""]
            for entry in distill.dropped:
                lines.append(f"- {entry}")
            lines.append("")

        if auto_applied:
            lines += ["## 자동 반영된 교훈 (검토 불필요 패치)", ""]
            for entry in auto_applied:
                lines.append(f"- {entry}")
            lines.append("")

        # TTL 정리 결과 — 조용히 지우면 "정리된 줄 모르는" 상태가 되므로 digest에 남긴다
        if expired or archived:
            lines += ["## 후보 정리 (TTL 초과)", ""]
            for rel in expired or []:
                lines.append(f"- 삭제: {rel}")
            for rel in archived or []:
                lines.append(f"- 보관(_Archive): {rel}")
            lines.append("")

        total = len(distill.written) + len(career.written)
        lines.append(f"_총 후보 {total}개 생성 | distill {len(distill.written)} / career {len(career.written)}_")

        if not weekly:
            from app.services.review_question import format_review_block

            review_block = format_review_block(self.vault_dir)
            if review_block:
                lines += ["", review_block]

        return "\n".join(lines)

    def _overdue_tasks(self) -> list[tuple[str, str, int]]:
        """Active.md에서 기한 초과 태스크를 찾는다. (text, due, days_overdue) 반환."""
        from datetime import date as date_cls
        from app.services.task_service import TaskService
        try:
            svc = TaskService(self.vault_dir)
            today_str = self._date()
            today = date_cls.fromisoformat(today_str)
            result = []
            for t in svc.list_tasks():
                if not t.due:
                    continue
                due_str = t.due.split("T")[0]
                if due_str < today_str:
                    days = (today - date_cls.fromisoformat(due_str)).days
                    result.append((t.text, t.due, days))
            return result
        except Exception:
            return []

    def _done_tasks(self, weekly: bool = False) -> list[str]:
        """70_Tasks/Done/ 에서 완료 태스크 항목을 읽어 반환한다."""
        import re
        done_dir = self.vault_dir / DONE_DIR
        if not done_dir.exists():
            return []

        if weekly:
            from datetime import timedelta
            cutoff = ((self.now or datetime.now()) - timedelta(days=_WEEKLY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
            files = sorted(f for f in done_dir.glob("*.md") if f.stem >= cutoff)
        else:
            today = self._date()
            done_file = done_dir / f"{today}.md"
            files = [done_file] if done_file.exists() else []

        entries: list[str] = []
        for f in files:
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    # "(기한: ...) ✅ HH:MM" 서픽스를 제거해 태스크 텍스트만 추출
                    m = re.match(
                        r"^- \[x\] (.+?)(?:\s+\(기한:[^)]*\))?\s+✅\s+\d{2}:\d{2}\s*$",
                        line.strip(),
                    )
                    if not m:
                        # 타임스탬프 없는 구형 형식 호환
                        m = re.match(r"^- \[x\] (.+)$", line.strip())
                    if m:
                        entries.append(m.group(1).strip())
            except OSError:
                continue
        return entries

    def _today_sessions(self) -> list[WikiNote]:
        today = self._date()
        notes = self.wiki_service.scan_notes()
        return [
            n for n in notes
            if n.path.startswith("10_Worklog/Sessions/")
            and "session" in Path(n.path).name.lower()
            and str(n.metadata.get("created_at") or n.metadata.get("date") or "")[:10] == today
        ]

    def _week_sessions(self) -> list[WikiNote]:
        from datetime import timedelta
        cutoff = ((self.now or datetime.now()) - timedelta(days=_WEEKLY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        notes = self.wiki_service.scan_notes()
        return [
            n for n in notes
            if n.path.startswith("10_Worklog/Sessions/")
            and "session" in Path(n.path).name.lower()
            and str(n.metadata.get("created_at") or n.metadata.get("date") or "")[:10] >= cutoff
        ]

    def _save_digest(self, digest_text: str, weekly: bool = False) -> tuple[Path | None, str]:
        date = self._date()
        kind = "weekly" if weekly else "daily"
        rel_path = f"50_Outputs/Digest/{date}-{kind}-digest.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "type": "digest",
            "date": date,
            "status": "generated",
            "tags": ["digest", kind],
        }
        post = frontmatter.Post(digest_text.strip() + "\n", **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return path, rel_path

    def _try_send_telegram(self, text: str) -> bool:
        settings = self.settings
        if settings.messenger_provider.lower() != "telegram":
            return False
        if not settings.telegram_chat_id:
            return False
        try:
            from app.messaging import get_messenger_provider
            provider = get_messenger_provider(settings)
            provider.send(settings.telegram_chat_id, text)
            return True
        except Exception:
            return False

    def _date(self) -> str:
        return (self.now or datetime.now()).strftime("%Y-%m-%d")
