from app.messaging.base import IncomingMessage
from app.messaging.bot import MessengerBot
from app.messaging.router import CommandRouter


class FakeProvider:
    name = "fake"

    def __init__(self, batches):
        # batches: 폴링마다 반환할 (messages, next_offset) 목록
        self._batches = list(batches)
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    def get_updates(self, offset=None):
        if self._batches:
            return self._batches.pop(0)
        return [], offset or 0


def _router_echo():
    # 라우터는 고정 응답만 내도록 stub agent 사용
    class _Agent:
        def list_drafts(self):
            return []

    return CommandRouter(make_agent=lambda: _Agent())


def test_replies_to_allowed_chat():
    msgs = [IncomingMessage(chat_id="100", text="/list", update_id=1)]
    provider = FakeProvider([(msgs, 2)])
    bot = MessengerBot(provider, _router_echo(), allowed_chat_ids=["100"])

    handled = bot.process_once()
    assert handled == 1
    assert len(provider.sent) == 1
    assert provider.sent[0][0] == "100"


def test_ignores_disallowed_chat():
    msgs = [IncomingMessage(chat_id="999", text="/list", update_id=1)]
    provider = FakeProvider([(msgs, 2)])
    bot = MessengerBot(provider, _router_echo(), allowed_chat_ids=["100"])

    handled = bot.process_once()
    assert handled == 0
    assert provider.sent == []


def test_offset_advances():
    msgs = [IncomingMessage(chat_id="100", text="/list", update_id=5)]
    provider = FakeProvider([(msgs, 6)])
    bot = MessengerBot(provider, _router_echo(), allowed_chat_ids=["100"])
    bot.process_once()
    assert bot._offset == 6


def test_notify_uses_default_chat():
    provider = FakeProvider([])
    bot = MessengerBot(provider, _router_echo(), default_chat_id="42")
    bot.notify("알림")
    assert provider.sent == [("42", "알림")]


def test_notify_without_target_raises():
    import pytest

    provider = FakeProvider([])
    bot = MessengerBot(provider, _router_echo())
    with pytest.raises(ValueError):
        bot.notify("x")
