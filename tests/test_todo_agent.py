from app.agents.todo_agent import TodoAgent
from app.config import Settings
from app.content_sources.collector import SourceCollector
from app.services.doc_summary_service import DocSummaryService
from tests.conftest import FakeLLM, FakeSource, sample_chunks


def test_todo_suggest_via_doc_service():
    collector = SourceCollector([FakeSource(sample_chunks())])
    llm = FakeLLM("## 다음 할 일 (우선순위 순)\n- [ ] 헬스체크 추가 — worklog 근거")
    out = DocSummaryService(collector, llm, "todo_suggest").summarize()
    assert "다음 할 일" in out
    assert "환경 분리 작업" in llm.last_prompt  # 컨텍스트 반영


def test_todo_agent_saves_file(tmp_path, monkeypatch):
    settings = Settings(WORKSPACE_DIR=str(tmp_path / "ws"), LLM_PROVIDER="ollama")
    agent = TodoAgent(settings=settings, repo_dir=tmp_path)

    monkeypatch.setattr(agent, "_llm", lambda: FakeLLM("## 다음 할 일 (우선순위 순)\n- [ ] 작업"))
    monkeypatch.setattr(
        "app.agents.doc_agent.build_source_collector",
        lambda s, r: SourceCollector([FakeSource(sample_chunks())]),
    )

    result = agent.generate()
    assert result.path.exists()
    assert "다음 할 일" in result.path.read_text(encoding="utf-8")
    assert result.path.parent == settings.todos_path
    assert agent.prompt_name == "todo_suggest"
