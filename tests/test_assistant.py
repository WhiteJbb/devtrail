import json
from pathlib import Path
from types import SimpleNamespace

from app.assistant.assistant import Assistant
from app.messaging.router import CommandRouter
from app.models import BlogPost
from tests.conftest import FakeLLM


class StubBlogAgent:
    def __init__(self):
        self.drafted = None

    def list_drafts(self):
        return [BlogPost(title="글A", slug="s1")]

    def write_draft(self, request):
        self.drafted = request.topic
        return BlogPost(title=request.topic, slug="new")


class FakeDocAgent:
    def generate(self):
        return SimpleNamespace(path=Path("ws/20260101.md"), text="회고 내용입니다")


def _assistant(llm):
    blog = StubBlogAgent()
    return Assistant(
        llm=llm,
        command_router=CommandRouter(make_agent=lambda: blog),
        doc_agents={"worklog": lambda: FakeDocAgent()},
    ), blog


def test_interpret_parses_intent():
    llm = FakeLLM(json.dumps({"command": "write-draft", "arg": "RAG 분리", "reason": "x"}))
    assistant, _ = _assistant(llm)
    intent = assistant.interpret("RAG 분리로 글 써줘")
    assert intent.command == "write-draft"
    assert intent.arg == "RAG 분리"
    # 컨텍스트(요청문)가 프롬프트에 들어갔는지
    assert "RAG 분리로 글 써줘" in llm.last_prompt


def test_describe():
    assistant, _ = _assistant(FakeLLM("{}"))
    from app.assistant.intent import Intent

    assert assistant.describe(Intent(command="worklog")) == "작업 회고 생성"
    assert "RAG" in assistant.describe(Intent(command="write-draft", arg="RAG"))


def test_execute_blog_command_delegates_to_router():
    assistant, blog = _assistant(FakeLLM("{}"))
    from app.assistant.intent import Intent

    out = assistant.execute(Intent(command="write-draft", arg="환경 분리"))
    assert "초안 생성 완료" in out
    assert blog.drafted == "환경 분리"


def test_execute_doc_agent():
    assistant, _ = _assistant(FakeLLM("{}"))
    from app.assistant.intent import Intent

    out = assistant.execute(Intent(command="worklog"))
    assert "작업 회고 생성 완료" in out
    assert "회고 내용입니다" in out


def test_execute_unknown_returns_help():
    assistant, _ = _assistant(FakeLLM("{}"))
    from app.assistant.intent import Intent

    assert "자유롭게 말해보세요" in assistant.execute(Intent(command="unknown"))
