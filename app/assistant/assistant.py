"""자연어 비서 — 의도 분류(interpret) + 설명(describe) + 실행(execute).

실행은 두 갈래로 재사용한다.
- 블로그 관련 명령: 기존 CommandRouter에 위임(슬래시 명령과 동일 로직)
- 확장 Agent(worklog/todo/portfolio/resume): 해당 Agent.generate() 실행
"""

from __future__ import annotations

from typing import Callable

from app.agents import PortfolioAgent, ResumeAgent, TodoAgent, WorklogAgent
from app.llm.base import LLMProvider
from app.messaging.router import CommandRouter
from app.prompts import render_prompt
from app.services.json_utils import extract_json_object
from app.assistant.intent import Intent

# command → 사람이 읽을 설명(확인 메시지용)
DESCRIPTIONS = {
    "suggest-topics": "블로그 주제 추천",
    "list": "초안 목록 보기",
    "write-draft": "블로그 초안 생성",
    "revise": "초안 다듬기",
    "preview": "초안 미리보기",
    "export-tistory": "티스토리용 변환",
    "publish-done": "게시 완료 기록",
    "sync-notion": "Notion 동기화",
    "worklog": "작업 회고 생성",
    "todo": "다음 할 일 제안",
    "portfolio": "포트폴리오 초안 생성",
    "resume": "이력서/자기소개서 초안 생성",
}

# command → CommandRouter 슬래시 토큰(블로그 명령)
_ROUTER_CMD = {
    "suggest-topics": "topics",
    "list": "list",
    "write-draft": "draft",
    "revise": "revise",
    "preview": "preview",
    "export-tistory": "export",
    "publish-done": "publish",
    "sync-notion": "sync",
}

_HELP = (
    "이렇게 자유롭게 말해보세요:\n"
    "· \"쓸만한 주제 추천해줘\"\n"
    "· \"XCoreChat 개발환경 분리로 초안 써줘\"\n"
    "· \"방금 초안 다듬어줘\"\n"
    "· \"오늘 작업 회고 정리해줘\"\n"
    "· \"다음 할 일 알려줘\" / \"포트폴리오 초안\" / \"이력서 초안\""
)

# 확장 Agent 팩토리(테스트에서 주입 가능)
DocFactory = Callable[[], object]


class Assistant:
    def __init__(
        self,
        llm: LLMProvider,
        command_router: CommandRouter | None = None,
        doc_agents: dict[str, DocFactory] | None = None,
    ):
        self.llm = llm
        self.command_router = command_router or CommandRouter()
        self.doc_agents: dict[str, DocFactory] = doc_agents or {
            "worklog": lambda: WorklogAgent(),
            "todo": lambda: TodoAgent(),
            "portfolio": lambda: PortfolioAgent(),
            "resume": lambda: ResumeAgent(),
        }

    # ----- 1) 의도 분류 -----
    def interpret(self, text: str) -> Intent:
        prompt = render_prompt("intent_route", TEXT=text)
        raw = self.llm.complete(prompt)
        data = extract_json_object(raw)
        return Intent(
            command=str(data.get("command", "unknown")),
            arg=str(data.get("arg", "")),
            reason=str(data.get("reason", "")),
        )

    # ----- 2) 확인용 설명 -----
    def describe(self, intent: Intent) -> str:
        base = DESCRIPTIONS.get(intent.command, "알 수 없는 요청")
        return f'{base} ("{intent.arg}")' if intent.arg else base

    def help_text(self) -> str:
        return _HELP

    # ----- 3) 실행 -----
    def execute(self, intent: Intent) -> str:
        cmd = intent.command

        if cmd in self.doc_agents:
            agent = self.doc_agents[cmd]()
            result = agent.generate()
            head = DESCRIPTIONS.get(cmd, cmd)
            return f"{head} 완료: {result.path.name}\n\n{result.text[:1500]}"

        if cmd in _ROUTER_CMD:
            slash = f"/{_ROUTER_CMD[cmd]} {intent.arg}".strip()
            return self.command_router.handle(slash)

        return self.help_text()
