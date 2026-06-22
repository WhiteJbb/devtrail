from app.agents.portfolio_agent import PortfolioAgent
from app.agents.resume_agent import ResumeAgent
from app.config import Settings
from app.content_sources.collector import SourceCollector
from app.services.doc_summary_service import DocSummaryService
from tests.conftest import FakeLLM, FakeSource, sample_chunks


def test_doc_summary_service_renders_named_prompt():
    collector = SourceCollector([FakeSource(sample_chunks())])
    llm = FakeLLM("## 이력서 bullet\n- 한 일")
    out = DocSummaryService(collector, llm, "resume").summarize()
    assert "이력서 bullet" in out
    assert "환경 분리 작업" in llm.last_prompt  # 컨텍스트 반영


def test_portfolio_agent_saves(tmp_path, monkeypatch):
    settings = Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER="ollama")
    agent = PortfolioAgent(settings=settings, repo_dir=tmp_path)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## XCoreChat\n- 한 줄 소개: RAG"))
    monkeypatch.setattr(
        "app.agents.doc_agent.build_source_collector",
        lambda s, r: SourceCollector([FakeSource(sample_chunks())]),
    )
    result = agent.generate()
    assert result.path.exists()
    assert result.path.parent == settings.portfolio_path
    assert "XCoreChat" in result.path.read_text(encoding="utf-8")


def test_resume_agent_uses_resume_dir(tmp_path, monkeypatch):
    settings = Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER="ollama")
    agent = ResumeAgent(settings=settings, repo_dir=tmp_path)
    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 이력서 bullet\n- x"))
    monkeypatch.setattr(
        "app.agents.doc_agent.build_source_collector",
        lambda s, r: SourceCollector([FakeSource(sample_chunks())]),
    )
    result = agent.generate()
    assert result.path.parent == settings.resume_path
    assert agent.prompt_name == "resume"
