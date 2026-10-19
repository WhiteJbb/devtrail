"""Nightly Distill Agent — 하루 작업을 종합 정제하고 요약을 전송한다.

distill-today + suggest-career-bullets + daily digest 생성 + Telegram 전송을 묶는다.
"""

from __future__ import annotations

import re
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
# 후보가 이 일수만큼 조용하면(마지막 갱신 기준) nightly가 공식 영역으로 승격한다.
# ponytail: 20_Knowledge에 같은 주제가 날짜만 다르게 쌓이면 이 값을 늘린다.
_PROMOTE_AFTER_DAYS = 2
_AUTO_PROMOTE_KINDS = ("knowledge", "decision", "problem")
# 번호 목록(1. / 1))과 불릿(-) 항목 — 내용이 있는 것만
_LIST_ITEM_RE = re.compile(r"^(?:\d+[.)]|-)\s+(.*\S)")


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
    auto_applied_patches: list[str] = field(default_factory=list)  # 자동 반영(교훈 패치) + 자동 승격


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

        # 이력서 소재는 매일 뽑을 만큼 쌓이지 않는다(후보 21건/소비 0, 2026-10-19). 일요일에만 한 주치를 본다.
        if (self.now or datetime.now()).weekday() == 6:
            career_agent = CareerBulletAgent(settings=self.settings, llm=self.llm, now=self.now)
            career_result = career_agent.suggest()
        else:
            career_result = CareerBulletResult(written=[], source_refs=[])

        # TTL 지난 후보 정리 — 재생성 가능 kind는 삭제, decision/memory_patch는 _Archive/.
        # 검토 안 된 후보가 무한 누적되는 것을 막는다 (2026-07 대청소 44개의 재발 방지).
        from app.services.retention import cleanup_candidates

        expired, archived = cleanup_candidates(self.vault_dir, now=self.now)

        # 사람 검토 게이트는 없다(2026-10-18 결정: 사람은 보기만 한다). 교훈 패치는 바로
        # 반영하고, 지식·결정·문제 후보는 며칠 조용하면 공식 영역으로 올린다.
        auto_applied = self._auto_apply_patches() + self._auto_promote()

        digest_text = self._build_digest(
            distill_result,
            career_result,
            weekly=weekly,
            expired=expired,
            archived=archived,
            auto_applied=auto_applied,
        )

        # 실질 내용이 0인 날은 vault에 남기지 않는다. 기록이 없는 날에도 파일이
        # 쌓이면 나중에 "그날 무엇을 했나"를 되묻는 사람이 빈 문서만 보게 되고,
        # WeeklyReview가 빈 digest를 입력으로 받아 없던 활동을 서술한다.
        # Telegram은 그대로 보낸다 — "오늘 기록 없음"은 사람이 알아야 한다.
        has_content = self._has_content(
            distill_result, career_result, weekly=weekly,
            expired=expired, archived=archived, auto_applied=auto_applied,
        )
        if has_content:
            digest_path, digest_rel = self._save_digest(digest_text, weekly=weekly)
        else:
            digest_path, digest_rel = None, ""
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

    def _auto_apply_patches(self) -> list[str]:
        """status=candidate인 MemoryPatch 후보를 전부 대상 파일에 자동 반영한다.

        requires_user_review는 기록으로만 남는다 — 검토할 사람이 없는 게이트는 적체만 만들었다.
        """
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
            rel = str(md_path.relative_to(self.vault_dir)).replace("\\", "/")
            try:
                result = curator.apply_memory_patch(rel)
                applied.append(f"{rel} → {result.promoted_path}")
            except Exception:
                continue  # 개별 패치 실패가 nightly 전체를 막지 않는다
        return applied

    def _auto_promote(self) -> list[str]:
        """지식·결정·문제 후보를 공식 영역(20_Knowledge/, 30_Projects/<P>/)으로 승격한다.

        마지막 갱신 뒤 _PROMOTE_AFTER_DAYS가 지난 후보만 — 그 안에는 distill dedup이 같은 주제를
        기존 후보에 합치므로, 바로 올리면 같은 지식이 날짜만 다르게 두 번 승격된다.
        """
        from datetime import timedelta
        from app.agents.curator_agent import CuratorAgent

        curator = CuratorAgent(settings=self.settings, now=self.now)
        cutoff = ((self.now or datetime.now()) - timedelta(days=_PROMOTE_AFTER_DAYS)).strftime("%Y-%m-%d")
        promoted: list[str] = []
        for item in curator.list_candidates():
            if item.kind not in _AUTO_PROMOTE_KINDS:
                continue
            try:
                meta = frontmatter.loads((self.vault_dir / item.rel_path).read_text(encoding="utf-8")).metadata
            except Exception:
                continue
            last = str(meta.get("updated_at") or item.created_at or "")[:10]
            if not last or last > cutoff:
                continue
            try:
                result = curator.promote_candidate(item.rel_path)
                promoted.append(f"{item.rel_path} → {result.promoted_path}")
            except Exception:
                continue  # 개별 승격 실패가 nightly 전체를 막지 않는다
        return promoted

    # ── Digest 빌더 ──────────────────────────────────────────────────────────

    def _has_content(
        self,
        distill: DistillResult,
        career: CareerBulletResult,
        weekly: bool = False,
        expired: list[str] | None = None,
        archived: list[str] | None = None,
        auto_applied: list[str] | None = None,
    ) -> bool:
        """이 digest에 그날 새로 생긴 사실이 하나라도 있는가.

        기한 초과 태스크는 판정에서 뺀다 — 매일 같은 값이라 "오늘 있었던 일"이
        아니고, 넣으면 초과 태스크 하나 때문에 빈 digest가 영구히 쌓인다.

        판정은 AND(전부 0일 때만 비었다고 본다)로 좁게 잡는다. 하나라도 있으면
        저장한다 — 실제 기록을 잃는 쪽이 빈 파일이 남는 쪽보다 나쁘다.
        """
        sessions = self._week_sessions() if weekly else self._today_sessions()
        return bool(
            sessions
            or distill.written
            or career.written
            or self._done_tasks(weekly=weekly)
            or expired
            or archived
            or auto_applied
        )

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
                lines.append(f"- {self._session_headline(s)}")
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
            lines += ["## 자동 반영 (교훈 패치 · 후보 승격)", ""]
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
            from app.services.blog_thread import format_thread_block

            thread_block = format_thread_block(self.vault_dir, date)
            if thread_block:
                lines += ["", thread_block]

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

    def _session_headline(self, note: WikiNote) -> str:
        """digest '오늘 한 일'용 한 줄 요약 — 세션 노트 제목은 대부분
        '<프로젝트> 작업 세션'으로 동일해 제목만 나열하면 하루 목록이 구분되지 않는다.
        본문 첫 불릿(What Changed 첫 항목)을 붙여 각 세션이 무엇이었는지 드러낸다."""
        for line in note.body.splitlines():
            # Process 노트의 What Changed는 번호 목록이다 — "- "만 보면 그 뒤 Project Decisions의
            # "- 결정:" 라벨을 집어 빈 headline이 된다(2026-10-16 digest 실측).
            match = _LIST_ITEM_RE.match(line.strip())
            if not match:
                continue
            headline = match.group(1).replace("**", "").strip()
            if not headline or headline.endswith(":"):
                continue
            if len(headline) > 90:
                headline = headline[:90].rstrip() + "…"
            return f"{note.title} — {headline}"
        return note.title

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
            # 저장된 digest는 실질 내용이 있다는 뜻이다(빈 날은 저장 자체를 건너뛴다).
            # WeeklyReview가 입력을 고를 때 본문을 파싱하지 않고 이 키로 판단한다.
            "has_content": True,
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
