"""WeeklyReviewAgent 단위 테스트 — 특히 빈 digest 입력 차단."""

from datetime import datetime

from app.agents.weekly_review_agent import WeeklyReviewAgent
from app.config import Settings
from tests.conftest import FakeLLM


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _write_digest(vault, date: str, *, has_content: bool | None, body: str = "") -> None:
    d = vault / "50_Outputs" / "Digest"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: digest", f"date: '{date}'", "status: generated"]
    if has_content is not None:
        lines.append(f"has_content: {str(has_content).lower()}")
    lines += ["---", "", body or f"# Daily Digest — {date}", ""]
    (d / f"{date}-daily-digest.md").write_text("\n".join(lines), encoding="utf-8")


_EMPTY_BODY = """# Daily Digest — 2026-06-20

## 오늘 한 일

- (session 노트 없음)

_총 후보 0개 생성 | distill 0 / career 0_
"""


def test_empty_digests_produce_no_review(tmp_path):
    """빈 digest만 있는 주는 회고를 만들지 않는다.

    회귀 방지: 2026-09-20 회고가 세션 기록 0건인 주를 "집중했다 / 매일
    반복되었다"로 서술했다 — source에 없는 사실 생성 금지 불변식 위반.
    """
    for day in ("2026-06-18", "2026-06-19", "2026-06-20"):
        _write_digest(tmp_path, day, has_content=False)

    llm = FakeLLM("주간 회고 본문")
    agent = WeeklyReviewAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 21))

    result = agent.run()

    assert result.digest_count == 0
    assert result.review_path is None
    assert result.review_text == ""
    # LLM을 아예 부르지 않는다
    assert llm.last_prompt == ""


def test_review_uses_only_digests_with_content(tmp_path):
    _write_digest(tmp_path, "2026-06-18", has_content=False)
    _write_digest(tmp_path, "2026-06-19", has_content=True, body="# Daily Digest\n\n## 오늘 한 일\n\n- 실제 작업\n")

    llm = FakeLLM("주간 회고 본문")
    agent = WeeklyReviewAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 21))

    result = agent.run()

    assert result.digest_count == 1
    assert result.review_path is not None
    assert "실제 작업" in llm.last_prompt


def test_legacy_digest_without_flag_falls_back_to_body(tmp_path):
    """has_content 키가 없는 기존 파일은 본문 문자열로 판정한다."""
    _write_digest(tmp_path, "2026-06-20", has_content=None, body=_EMPTY_BODY)

    llm = FakeLLM("주간 회고 본문")
    agent = WeeklyReviewAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 21))

    result = agent.run()

    assert result.digest_count == 0
    assert result.review_path is None


def test_legacy_digest_with_real_content_is_kept(tmp_path):
    _write_digest(
        tmp_path,
        "2026-06-20",
        has_content=None,
        body="# Daily Digest\n\n## 오늘 한 일\n\n- [[세션 노트]]\n\n_총 후보 2개 생성 | distill 2 / career 0_\n",
    )

    llm = FakeLLM("주간 회고 본문")
    agent = WeeklyReviewAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 21))

    result = agent.run()

    assert result.digest_count == 1
    assert result.review_path is not None
