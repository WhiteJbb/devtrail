"""Weekly Review Agent — 한 주의 daily digest를 종합해 주간 회고를 생성한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import frontmatter

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.prompts import render_prompt


@dataclass(frozen=True)
class WeeklyReviewResult:
    review_text: str
    review_path: Path | None
    review_rel_path: str
    sent_telegram: bool
    digest_count: int


class WeeklyReviewAgent:
    """이번 주 daily digest들을 읽어 주간 회고 노트를 생성한다."""

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

    def run(self) -> WeeklyReviewResult:
        digests = self._load_weekly_digests()
        if not digests:
            return WeeklyReviewResult(
                review_text="",
                review_path=None,
                review_rel_path="",
                sent_telegram=False,
                digest_count=0,
            )

        context = "\n\n---\n\n".join(digests)
        prompt = render_prompt("weekly_review", DATE=self._date(), CONTEXT=context)
        review_text = self._llm().complete(prompt).strip()

        path, rel = self._save_review(review_text)
        sent = self._try_send_telegram(review_text)

        return WeeklyReviewResult(
            review_text=review_text,
            review_path=path,
            review_rel_path=rel,
            sent_telegram=sent,
            digest_count=len(digests),
        )

    def _load_weekly_digests(self) -> list[str]:
        """최근 7일치 daily-digest 파일을 날짜 오름차순으로 반환한다."""
        digest_dir = self.vault_dir / "50_Outputs" / "Digest"
        if not digest_dir.exists():
            return []

        today = (self.now or datetime.now()).date()
        cutoff = today - timedelta(days=7)

        digests: list[tuple[str, str]] = []  # (date_str, content)
        for f in digest_dir.glob("*-daily-digest.md"):
            date_str = f.name[:10]
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if cutoff <= file_date <= today:
                try:
                    digests.append((date_str, f.read_text(encoding="utf-8")))
                except OSError:
                    continue

        digests.sort(key=lambda x: x[0])
        return [content for _, content in digests]

    def _save_review(self, text: str) -> tuple[Path | None, str]:
        date = self._date()
        rel_path = f"50_Outputs/WeeklyReview/{date}-weekly-review.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "type": "weekly_review",
            "date": date,
            "status": "generated",
            "tags": ["weekly-review", "digest"],
        }
        post = frontmatter.Post(f"# 주간 회고 — {date}\n\n{text}\n", **metadata)
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
            header = f"📅 **주간 회고 — {self._date()}**\n\n"
            provider.send(settings.telegram_chat_id, header + text)
            return True
        except Exception:
            return False

    def _llm(self) -> LLMProvider:
        from app.llm.factory import get_task_llm_provider
        return self.llm or get_task_llm_provider("writer", self.settings)

    def _date(self) -> str:
        return (self.now or datetime.now()).strftime("%Y-%m-%d")
