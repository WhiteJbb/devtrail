import json
from pathlib import Path
from types import SimpleNamespace

from app.assistant.assistant import Assistant
from app.messaging.base import IncomingMessage
from app.messaging.bot import MessengerBot
from app.messaging.router import CommandRouter
from tests.conftest import FakeLLM


class FakeProvider:
    name = "fake"

    def __init__(self, batches):
        self._batches = list(batches)
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    def get_updates(self, offset=None):
        if self._batches:
            return self._batches.pop(0)
        return [], offset or 0


class FakeDocAgent:
    def generate(self):
        return SimpleNamespace(path=Path("ws/20260101.md"), text="회고 내용")


def _assistant(command="worklog"):
    llm = FakeLLM(json.dumps({"command": command, "arg": "", "reason": "x"}))
    return Assistant(llm=llm, doc_agents={"worklog": lambda: FakeDocAgent()})


def _msg(text, uid):
    return IncomingMessage(chat_id="100", text=text, update_id=uid)


def test_nl_asks_confirmation_then_executes():
    provider = FakeProvider(
        [([_msg("오늘 회고 정리해줘", 1)], 2), ([_msg("예", 2)], 3)]
    )
    bot = MessengerBot(
        provider, CommandRouter(), allowed_chat_ids=["100"], assistant=_assistant()
    )

    bot.process_once()  # 첫 메시지 → 확인 요청
    assert "실행할까요?" in provider.sent[-1][1]
    assert "작업 회고 생성" in provider.sent[-1][1]

    bot.process_once()  # "예" → 실행
    assert "작업 회고 생성 완료" in provider.sent[-1][1]


def test_nl_cancel():
    provider = FakeProvider(
        [([_msg("회고 정리", 1)], 2), ([_msg("아니", 2)], 3)]
    )
    bot = MessengerBot(
        provider, CommandRouter(), allowed_chat_ids=["100"], assistant=_assistant()
    )
    bot.process_once()
    bot.process_once()
    assert provider.sent[-1][1] == "취소했습니다."


def test_unknown_intent_shows_help():
    provider = FakeProvider([([_msg("아무말", 1)], 2)])
    bot = MessengerBot(
        provider, CommandRouter(), allowed_chat_ids=["100"], assistant=_assistant("unknown")
    )
    bot.process_once()
    assert "자유롭게 말해보세요" in provider.sent[-1][1]


def test_slash_still_works_with_assistant():
    provider = FakeProvider([([_msg("/help", 1)], 2)])
    bot = MessengerBot(
        provider, CommandRouter(), allowed_chat_ids=["100"], assistant=_assistant()
    )
    bot.process_once()
    assert "사용 가능한 명령" in provider.sent[-1][1]
