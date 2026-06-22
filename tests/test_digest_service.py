from typer.testing import CliRunner

from app import cli
from app.models import TopicSuggestion
from app.services.digest_service import build_digest

runner = CliRunner()


def test_digest_with_suggestions():
    suggestions = [
        TopicSuggestion(title_candidates=["RAG 분리"], reason="worklog 근거"),
        TopicSuggestion(title_candidates=["vLLM 연결"], reason="커밋 근거"),
    ]
    out = build_digest(suggestions)
    assert "블로그 주제 추천" in out
    assert "1. RAG 분리" in out
    assert "worklog 근거" in out
    assert "작업 회고" not in out


def test_digest_with_worklog():
    out = build_digest([], worklog_text="## 한 일\n- 분리")
    assert "추천할 주제를 찾지 못했습니다" in out
    assert "[작업 회고]" in out
    assert "## 한 일" in out


def test_push_digest_messenger_not_configured(monkeypatch):
    # MESSENGER_PROVIDER가 비어 있으면 친화적 안내 후 exit 1
    from app.config import Settings
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(MESSENGER_PROVIDER=""))
    result = runner.invoke(cli.app, ["push-digest"])
    assert result.exit_code == 1
    assert "메신저가 설정되지 않았습니다" in result.output
