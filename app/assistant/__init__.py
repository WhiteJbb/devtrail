"""자연어 의도 라우팅 — '개인 비서처럼' 자유 문장으로 지시.

자유 텍스트를 LLM으로 정해진 명령에 매핑(intent)하고, 확인 후 실행한다.
실행은 기존 CommandRouter(블로그 명령)와 확장 Agent를 재사용한다.
"""

from app.assistant.assistant import Assistant
from app.assistant.intent import Intent

__all__ = ["Assistant", "Intent"]
