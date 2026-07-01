"""메신저 봇 루프 — provider/라우터/비서를 잇는다.

허용된 chat에서 온 메시지만 처리한다.
- "/명령" → CommandRouter(슬래시 명령)
- 그 외 자유 문장 → Assistant로 의도 분류 후 "실행할까요?" 확인을 받고 실행(항상 확인)
assistant가 없으면(LLM 미설정) 자유 문장은 도움말로 안내한다.
process_once는 네트워크 한 번 폴링 단위라 테스트하기 쉽다.
"""

from __future__ import annotations

from pathlib import Path

from app.messaging.base import MessengerProvider
from app.messaging.media_handler import TelegramMediaHandler, is_url
from app.messaging.router import CommandRouter

_OFFSET_FILE = Path.home() / ".work-agent" / "bot_offset"


def _load_offset() -> int | None:
    try:
        val = _OFFSET_FILE.read_text().strip()
        return int(val) if val else None
    except Exception:
        return None


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_FILE.write_text(str(offset))
    except Exception as exc:
        print(f"[bot] offset 저장 실패: {exc}", flush=True)

_YES = {"예", "네", "ㅇ", "응", "ok", "오케이", "yes", "y"}
_NO = {"아니", "아니오", "ㄴ", "취소", "cancel", "no", "n"}
_TASKS_CMDS = {"tasks", "할일", "할_일"}  # /tasks 명령 별칭 집합
_REVIEW_CMDS = {"/review", "/review_promote", "/review_skip", "/review_delete", "/review_stop"}

_KIND_EMOJI = {
    "knowledge": "📚",
    "decision": "⚖️",
    "memory_patch": "🧠",
    "blog_idea": "✍️",
}


def _is_tasks_cmd(text: str) -> bool:
    t = text.strip()
    if not t.startswith("/"):
        return False
    cmd = t.lstrip("/").split()[0].lower()
    return cmd in _TASKS_CMDS


def _is_review_cmd(text: str) -> bool:
    return text.strip().lower() in _REVIEW_CMDS


_CARD_BODY_MAX = 1800  # 카드에 본문을 직접 담을 수 있는 최대 길이

def _extract_body(raw: str) -> str:
    """frontmatter와 첫 H1을 제거한 전체 본문을 반환한다."""
    text = raw
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3:].lstrip("\n")
    lines = [l for l in text.splitlines() if not l.startswith("# ")]
    return "\n".join(lines).strip()


class MessengerBot:
    def __init__(
        self,
        provider: MessengerProvider,
        router: CommandRouter,
        allowed_chat_ids: list[str] | None = None,
        default_chat_id: str = "",
        assistant=None,
        media_handler: TelegramMediaHandler | None = None,
    ):
        self.provider = provider
        self.router = router
        self.assistant = assistant
        self.media_handler = media_handler
        self.allowed_chat_ids = set(allowed_chat_ids or [])
        self.default_chat_id = default_chat_id
        self._offset: int | None = _load_offset()
        self._pending: dict[str, object] = {}  # chat_id → 확인 대기 중인 Intent
        self._review_queue: dict[str, list] = {}  # chat_id → CandidateItem 목록

    def _is_allowed(self, chat_id: str) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def _handle_text(self, chat_id: str, text: str) -> str:
        t = (text or "").strip()

        # URL 감지 — media_handler가 있을 때만 URL capture로 라우팅
        if t and self.media_handler is not None and is_url(t):
            return self.media_handler.handle_url(t)

        low = t.lower()

        # 1) 확인 대기 중이면 예/아니오 처리
        if chat_id in self._pending:
            if low in _YES:
                intent = self._pending.pop(chat_id)
                try:
                    return self.assistant.execute(intent)
                except Exception as e:
                    return f"실행 중 오류: {e}"
            if low in _NO:
                self._pending.pop(chat_id)
                return "취소했습니다."
            # 그 외 입력은 새 요청으로 본다(대기 해제 후 계속)
            self._pending.pop(chat_id)

        # 2) 슬래시 명령은 그대로 실행
        if t.startswith("/"):
            return self.router.handle(t)

        # 3) 자유 문장 → 비서가 있으면 의도 분류 후 확인, 없으면 도움말
        if self.assistant is None:
            return self.router.handle(t)

        try:
            intent = self.assistant.interpret(t)
        except Exception as e:
            return f"이해하지 못했습니다: {e}"

        if intent.command in ("unknown", "help", ""):
            return self.assistant.help_text()

        self._pending[chat_id] = intent
        return f"해석: {self.assistant.describe(intent)}\n실행할까요? (예/아니오)"

    def _build_task_buttons(self) -> list[list[dict]] | None:
        """현재 할 일 목록을 기반으로 인라인 버튼 행을 만든다."""
        try:
            from app.agents.task_agent import TaskAgent
            tasks = TaskAgent().service.list_tasks()
            if not tasks:
                return None
            rows = []
            for t in tasks:
                label = t.text[:20] + ("…" if len(t.text) > 20 else "")
                # ID가 있으면 안정 ID 사용, 구형 태스크(ID 없음)는 번호 폴백
                done_cb = f"/done ^{t.id}" if t.id else f"/done {t.number}"
                del_cb = f"/del ^{t.id}" if t.id else f"/del {t.number}"
                rows.append([
                    {"text": f"✅ {t.number}. {label}", "callback_data": done_cb},
                    {"text": "🗑", "callback_data": del_cb},
                ])
            return rows
        except Exception:
            return None

    # ── 후보 검토 (review) ────────────────────────────────────────────

    def _handle_review(self, chat_id: str, cmd: str) -> None:
        """review 명령을 처리하고 send_with_buttons로 직접 응답한다."""
        if cmd == "/review":
            try:
                from app.agents.curator_agent import CuratorAgent
                items = CuratorAgent().list_candidates()
            except Exception as e:
                self.provider.send(chat_id, f"후보 로딩 실패: {e}")
                return
            if not items:
                self.provider.send(chat_id, "검토할 후보가 없습니다.")
                return
            self._review_queue[chat_id] = list(items)
            self._send_review_card(chat_id)
            return

        if cmd == "/review_stop":
            self._review_queue.pop(chat_id, None)
            self.provider.send(chat_id, "검토를 종료했습니다.")
            return

        # promote / skip / delete
        queue = self._review_queue.get(chat_id)
        if not queue:
            self.provider.send(chat_id, "검토 세션이 없습니다. /review 로 시작하세요.")
            return

        item = queue[0]
        if cmd == "/review_promote":
            try:
                from app.agents.curator_agent import CuratorAgent
                agent = CuratorAgent()
                if item.kind == "memory_patch":
                    result = agent.apply_memory_patch(item.rel_path)
                else:
                    result = agent.promote_candidate(item.rel_path)
                self.provider.send(chat_id, f"✅ 승격 완료: {result.promoted_path}")
            except Exception as e:
                self.provider.send(chat_id, f"승격 실패: {e}")
                return

        elif cmd == "/review_delete":
            try:
                from app.agents.curator_agent import CuratorAgent
                CuratorAgent().delete_candidate(item.rel_path)
                self.provider.send(chat_id, f"🗑 삭제: {item.title}")
            except Exception as e:
                self.provider.send(chat_id, f"삭제 실패: {e}")
                return

        self._review_queue[chat_id] = queue[1:]
        if not self._review_queue[chat_id]:
            self._review_queue.pop(chat_id, None)
            self.provider.send(chat_id, "🎉 모든 후보 검토 완료!")
            return
        self._send_review_card(chat_id)

    def _send_review_card(self, chat_id: str) -> None:
        """현재 큐의 첫 번째 후보를 인라인 버튼 카드로 전송한다.

        본문이 짧으면 카드에 직접 포함, 길면 전문을 먼저 별도 메시지로 보내고
        버튼 카드에는 "(전문은 위 메시지 참조)"만 표시한다.
        """
        queue = self._review_queue.get(chat_id, [])
        if not queue:
            return
        item = queue[0]
        remaining = len(queue)

        body = ""
        try:
            from app.agents.curator_agent import CuratorAgent
            raw = CuratorAgent().preview_candidate(item.rel_path)
            body = _extract_body(raw)
        except Exception:
            pass

        emoji = _KIND_EMOJI.get(item.kind, "📄")
        stale_mark = " ⚠️" if item.is_stale else ""
        meta = item.created_at + (f" · {item.project}" if item.project else "")

        if len(body) > _CARD_BODY_MAX:
            self.provider.send(chat_id, body)
            inline_body = "(전문은 위 메시지 참조)"
        else:
            inline_body = body

        text = (
            f"{emoji} **{item.title}**{stale_mark}\n"
            f"[{item.kind}] {meta}\n\n"
            f"{inline_body}\n\n"
            f"({remaining}개 남음)"
        )
        buttons = [[
            {"text": "✅ 승격", "callback_data": "/review_promote"},
            {"text": "⏭ 건너뛰기", "callback_data": "/review_skip"},
            {"text": "🗑 삭제", "callback_data": "/review_delete"},
            {"text": "⛔ 종료", "callback_data": "/review_stop"},
        ]]
        if hasattr(self.provider, "send_with_buttons"):
            self.provider.send_with_buttons(chat_id, text, buttons)
        else:
            self.provider.send(chat_id, text)

    def process_once(self) -> int:
        """한 번 폴링해 들어온 메시지를 처리한다. 처리한 메시지 수를 반환."""
        messages, next_offset = self.provider.get_updates(self._offset)
        if next_offset != self._offset:
            self._offset = next_offset
            _save_offset(next_offset)
        handled = 0
        for msg in messages:
            if not self._is_allowed(msg.chat_id):
                continue

            # review 명령 — 버튼 포함 응답을 직접 전송하므로 여기서 처리 후 continue
            if not (msg.voice_file_id or msg.photo_file_id) and _is_review_cmd(msg.text):
                self._handle_review(msg.chat_id, msg.text.strip().lower())
                handled += 1
                continue

            if msg.voice_file_id or msg.photo_file_id:
                if self.media_handler is not None:
                    reply = self.media_handler.handle(msg)
                else:
                    reply = "미디어 처리가 설정되지 않았습니다. 텍스트 메시지를 사용해 주세요."
            elif msg.callback_query_id:
                # 버튼 탭은 pending 확인 대화를 취소하지 않고 바로 명령으로 처리
                reply = self.router.handle(msg.text)
            else:
                reply = self._handle_text(msg.chat_id, msg.text)

            # /tasks 명령에는 인라인 버튼을 붙여 보낸다
            if (
                not (msg.voice_file_id or msg.photo_file_id)
                and _is_tasks_cmd(msg.text)
                and hasattr(self.provider, "send_with_buttons")
            ):
                buttons = self._build_task_buttons()
                if buttons:
                    try:
                        self.provider.send_with_buttons(msg.chat_id, reply, buttons)
                        handled += 1
                        continue
                    except Exception:
                        pass  # 버튼 전송 실패 시 일반 메시지로 폴백

            self.provider.send(msg.chat_id, reply)
            handled += 1
        return handled

    def run(self) -> None:  # pragma: no cover - 무한 루프(수동 실행)
        import time
        while True:
            try:
                self.process_once()
            except Exception as exc:
                # ReadTimeout은 long-polling 정상 동작 범위 — 즉시 재시도
                name = type(exc).__name__
                if "Timeout" in name:
                    continue
                print(f"[bot] 오류 발생({name}): {exc}", flush=True)
                time.sleep(3)

    def notify(self, text: str, chat_id: str = "") -> None:
        target = chat_id or self.default_chat_id
        if not target:
            raise ValueError("알림을 보낼 chat_id가 없습니다(TELEGRAM_CHAT_ID 설정).")
        self.provider.send(target, text)
