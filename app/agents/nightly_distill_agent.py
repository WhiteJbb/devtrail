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
from app.services.wiki_service import WikiNote, WikiService


@dataclass(frozen=True)
class NightlyDistillResult:
    distill: DistillResult
    career: CareerBulletResult
    digest_text: str
    digest_path: Path | None
    digest_rel_path: str
    sent_telegram: bool


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
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)

    def run(self) -> NightlyDistillResult:
        # 1. distill-today (knowledge / decisions / mempatches / blogideas)
        distill_agent = DistillAgent(settings=self.settings, llm=self.llm, now=self.now)
        distill_result = distill_agent.distill_today()

        # 2. career bullets
        career_agent = CareerBulletAgent(settings=self.settings, llm=self.llm, now=self.now)
        career_result = career_agent.suggest()

        # 3. digest 생성 (LLM 추가 호출 없이 결과 정리)
        digest_text = self._build_digest(distill_result, career_result)

        # 4. digest 저장
        digest_path, digest_rel = self._save_digest(digest_text)

        # 5. Telegram 전송 시도
        sent = self._try_send_telegram(digest_text)

        return NightlyDistillResult(
            distill=distill_result,
            career=career_result,
            digest_text=digest_text,
            digest_path=digest_path,
            digest_rel_path=digest_rel,
            sent_telegram=sent,
        )

    # ── Digest 빌더 ──────────────────────────────────────────────────────────

    def _build_digest(
        self,
        distill: DistillResult,
        career: CareerBulletResult,
    ) -> str:
        date = self._date()
        lines = [f"# Daily Digest — {date}", ""]

        # 오늘 한 일: session 노트 제목 수집
        sessions = self._today_sessions()
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

        total = len(distill.written) + len(career.written)
        lines.append(f"_총 후보 {total}개 생성 | distill {len(distill.written)} / career {len(career.written)}_")

        return "\n".join(lines)

    def _today_sessions(self) -> list[WikiNote]:
        today = self._date()
        notes = self.wiki_service.scan_notes()
        return [
            n for n in notes
            if n.path.startswith("10_Worklog/Daily/")
            and "session" in Path(n.path).name.lower()
            and str(n.metadata.get("created_at") or n.metadata.get("date") or "")[:10] == today
        ]

    def _save_digest(self, digest_text: str) -> tuple[Path | None, str]:
        date = self._date()
        rel_path = f"50_Outputs/Digest/{date}-daily-digest.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "type": "digest",
            "date": date,
            "status": "generated",
            "tags": ["digest", "daily"],
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
