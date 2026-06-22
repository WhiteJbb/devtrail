from app.agents.worklog_agent import WorklogAgent
from app.config import Settings
from app.content_sources.collector import SourceCollector
from app.services.worklog_summarizer import WorklogSummarizer
from tests.conftest import FakeLLM, FakeSource, sample_chunks


def test_summarizer_uses_context_and_returns_markdown():
    collector = SourceCollector([FakeSource(sample_chunks())])
    llm = FakeLLM("## 한 일\n- 환경 분리")
    out = WorklogSummarizer(collector, llm).summarize()
    assert "## 한 일" in out
    # 컨텍스트가 프롬프트에 들어갔는지(수집 텍스트 반영)
    assert "환경 분리 작업" in llm.last_prompt


def test_worklog_agent_saves_file(tmp_path, monkeypatch):
    settings = Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER="ollama")
    agent = WorklogAgent(settings=settings, repo_dir=tmp_path)

    # LLM과 collector를 가짜로 주입
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 한 일\n- 작업"))
    monkeypatch.setattr(
        "app.agents.worklog_agent.build_source_collector",
        lambda s, r: SourceCollector([FakeSource(sample_chunks())]),
    )

    result = agent.generate()
    assert result.path.exists()
    assert "## 한 일" in result.path.read_text(encoding="utf-8")
    assert result.path.parent == settings.worklogs_path
