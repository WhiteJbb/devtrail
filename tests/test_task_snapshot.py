"""태스크 번호 스냅샷 · 버튼 폴백 로깅 · 429 백오프 테스트."""

from types import SimpleNamespace

from app.messaging.base import IncomingMessage
from app.messaging.bot import MessengerBot
from app.messaging.router import CommandRouter

ACTIVE = """# Active Tasks

## 오늘
- [ ] 첫번째 할일 ^aaa111
- [ ] 두번째 할일 ^bbb222
- [ ] 세번째 할일 ^ccc333

## 이번 주

## 언제든지
"""


def _patch_vault(tmp_path, monkeypatch):
    (tmp_path / "70_Tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "70_Tasks" / "Active.md").write_text(ACTIVE, encoding="utf-8")
    monkeypatch.setattr(
        "app.agents.task_agent.get_settings",
        lambda: SimpleNamespace(obsidian_vault_root=str(tmp_path)),
    )


def _read_active(tmp_path) -> str:
    return (tmp_path / "70_Tasks" / "Active.md").read_text(encoding="utf-8")


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


def _msg(text, update_id):
    return [IncomingMessage(chat_id="1", text=text, update_id=update_id)]


def test_snapshot_keeps_numbers_after_done(tmp_path, monkeypatch):
    """목록을 본 뒤 1번을 완료해 번호가 밀려도, '3번'은 봤던 세번째 항목을 가리킨다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = FakeProvider([
        (_msg("/tasks", 1), 2),
        (_msg("/done 1", 2), 3),
        (_msg("/done 3", 3), 4),
    ])
    bot = MessengerBot(provider, CommandRouter())
    bot.process_once()
    bot.process_once()
    bot.process_once()

    assert "세번째 할일" in provider.sent[-1][1]
    active = _read_active(tmp_path)
    assert "세번째 할일" not in active
    assert "두번째 할일" in active  # 밀린 현재 번호가 아니라 스냅샷 번호로 처리됨


def test_snapshot_stale_number_fails_gracefully(tmp_path, monkeypatch):
    """이미 처리한 번호를 다시 지정하면 다른 항목을 건드리지 않고 안내한다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = FakeProvider([
        (_msg("/tasks", 1), 2),
        (_msg("/done 3", 2), 3),
        (_msg("/done 3", 3), 4),
    ])
    bot = MessengerBot(provider, CommandRouter())
    bot.process_once()
    bot.process_once()
    bot.process_once()

    assert "못 찾았어요" in provider.sent[-1][1]
    active = _read_active(tmp_path)
    assert "첫번째 할일" in active
    assert "두번째 할일" in active


def test_done_without_snapshot_uses_position(tmp_path, monkeypatch):
    """목록을 본 적 없으면(스냅샷 없음) 기존처럼 현재 번호로 처리한다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = FakeProvider([(_msg("/done 2", 1), 2)])
    bot = MessengerBot(provider, CommandRouter())
    bot.process_once()

    assert "두번째 할일" in provider.sent[-1][1]


def test_tasks_refreshes_snapshot(tmp_path, monkeypatch):
    """/tasks 를 다시 보면 스냅샷이 현재 번호로 갱신된다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = FakeProvider([
        (_msg("/tasks", 1), 2),
        (_msg("/done 1", 2), 3),
        (_msg("/tasks", 3), 4),
        (_msg("/done 1", 4), 5),  # 갱신된 목록의 1번 = 두번째 할일
    ])
    bot = MessengerBot(provider, CommandRouter())
    for _ in range(4):
        bot.process_once()

    assert "두번째 할일" in provider.sent[-1][1]


class FakeAssistant:
    """LLM 없이 task-done intent만 흉내내는 대역."""

    def interpret(self, text):
        from app.assistant.intent import Intent
        return Intent(command="task-done", arg="3", reason="test")

    def describe(self, intent):
        return f'할 일 완료 처리 ("{intent.arg}")'

    def execute(self, intent):
        from app.agents.task_agent import TaskAgent
        return TaskAgent().done(intent.arg).message

    def help_text(self):
        return "help"


def test_natural_language_done_uses_snapshot(tmp_path, monkeypatch):
    """자연어 '3번 완료' 확인 흐름에서도 스냅샷 번호가 유지된다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = FakeProvider([
        (_msg("/tasks", 1), 2),
        (_msg("/done 1", 2), 3),
        (_msg("3번 완료해줘", 3), 4),
        (_msg("예", 4), 5),
    ])
    bot = MessengerBot(provider, CommandRouter(), assistant=FakeAssistant())
    for _ in range(4):
        bot.process_once()

    assert "세번째 할일" in provider.sent[-1][1]
    assert "세번째 할일" not in _read_active(tmp_path)


def test_edit_accepts_stable_id(tmp_path, monkeypatch):
    """TaskAgent.edit이 ^id 인자를 현재 번호로 해석한다."""
    _patch_vault(tmp_path, monkeypatch)
    from app.agents.task_agent import TaskAgent

    result = TaskAgent().edit("^bbb222 새로운 내용")

    assert result.ok
    active = _read_active(tmp_path)
    assert "새로운 내용" in active
    assert "두번째 할일" not in active


class ButtonFailProvider(FakeProvider):
    def send_with_buttons(self, chat_id, text, buttons):
        raise RuntimeError("Bad Request: can't parse entities")


def test_button_failure_logged_and_falls_back(tmp_path, monkeypatch, capsys):
    """버튼 전송 실패 시 일반 메시지로 폴백하고 원인을 로그에 남긴다."""
    _patch_vault(tmp_path, monkeypatch)
    provider = ButtonFailProvider([(_msg("/tasks", 1), 2)])
    bot = MessengerBot(provider, CommandRouter())
    bot.process_once()

    assert provider.sent  # 폴백 전송됨
    assert "버튼 전송 실패" in capsys.readouterr().out


def test_get_updates_429_backoff(monkeypatch):
    """429 응답이면 retry_after만큼 대기 후 빈 결과를 반환한다."""
    import time as _time

    from app.messaging import telegram_provider as tp

    class FakeResp:
        status_code = 429

        def json(self):
            return {"ok": False, "parameters": {"retry_after": 7}}

        def raise_for_status(self):
            raise AssertionError("429는 raise_for_status 전에 처리돼야 한다")

    sleeps: list[float] = []
    monkeypatch.setattr(tp.httpx, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))

    msgs, offset = tp.TelegramProvider("tok").get_updates(5)

    assert msgs == []
    assert offset == 5
    assert sleeps == [7]
