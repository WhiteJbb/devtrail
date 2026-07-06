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
from app.services.json_utils import complete_json
from app.assistant.intent import Intent

# command → 사람이 읽을 설명(확인 메시지용)
DESCRIPTIONS = {
    "capture": "메모 저장",
    "suggest-topics": "블로그 주제 추천",
    "list": "초안 목록 보기",
    "write-draft": "블로그 초안 생성",
    "revise": "초안 다듬기",
    "preview": "초안 미리보기",
    "export-tistory": "티스토리용 변환",
    "publish-done": "게시 완료 기록",
    "worklog": "작업 회고 생성",
    "todo": "다음 할 일 제안",
    "portfolio": "포트폴리오 초안 생성",
    "resume": "이력서/자기소개서 초안 생성",
    "capture-session": "작업 세션 노트 저장",
    "ask-vault": "Vault 검색 기반 답변",
    "task-add": "할 일 추가",
    "task-list": "할 일 목록 조회",
    "task-done": "할 일 완료 처리",
    "task-delete": "할 일 삭제",
    "task-edit": "할 일 수정",
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
}

_HELP = (
    "**Work Agent**\n"
    "안녕하세요. 개인 지식 관리 에이전트입니다.\n"
    "\n"
    "**[ 할 일 ]**\n"
    "/tasks  — 목록 + 완료·삭제 버튼\n"
    "/task <내용>  — 추가  (예: /task 코드리뷰 내일까지)\n"
    "/done <번호> · /del <번호> · /edit <번호> <새내용>\n"
    "\n"
    "**[ 매일 쓰는 요청 ]**\n"
    "\"[내용] 메모해줘\" / \"기록해줘\"\n"
    "URL 붙여넣기 → 자동 요약 저장\n"
    "\"오늘 할 일 알려줘\"\n"
    "\n"
    "**[ 가끔 쓰는 요청 ]**\n"
    "\"작업 회고 써줘\"\n"
    "\"[주제] 초안 써줘\"\n"
    "\"블로그 주제 추천해줘\"\n"
    "\n"
    "슬래시 명령 전체 목록은 /help"
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
            "worklog": WorklogAgent,
            "todo": TodoAgent,
            "portfolio": PortfolioAgent,
            "resume": ResumeAgent,
        }

    # ----- 1) 의도 분류 -----
    def interpret(self, text: str) -> Intent:
        prompt = render_prompt("intent_route", TEXT=text)
        data = complete_json(self.llm, prompt)
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

        if cmd == "capture":
            if not intent.arg:
                return "저장할 내용을 함께 말씀해 주세요."
            from app.agents import CaptureAgent
            try:
                result = CaptureAgent().capture(text=intent.arg)
            except RuntimeError as e:
                return f"저장 실패: {e}"
            verb = "저장" if result.created else "기존 파일 유지"
            return f"메모 {verb} 완료\n{result.rel_path}"

        if cmd == "capture-session":
            from app.agents import CaptureAgent
            project = intent.arg or None
            try:
                agent = CaptureAgent()
                result = agent.capture_session(project=project, from_agent=True)
            except RuntimeError as e:
                return f"실행 실패: {e}\n→ .env에서 OBSIDIAN_VAULT_PATH를 설정하세요."
            proj_label = f" ({project})" if project else ""
            return (
                f"작업 세션 노트 저장 완료{proj_label}\n"
                f"vault: {result.rel_path}\n\n"
                "현재 세션 작업 내용을 --summary-file로 전달하면 노트에 자동 포함됩니다."
            )

        if cmd == "ask-vault":
            if not intent.arg:
                return "무엇을 찾고 싶은지 함께 말씀해 주세요."
            from app import vault_tools
            try:
                hits = vault_tools.search_vault(intent.arg, limit=5)
            except RuntimeError as e:
                return f"검색 실패: {e}\n→ .env에서 OBSIDIAN_VAULT_PATH를 설정하세요."
            if not hits:
                return "관련된 노트를 찾지 못했습니다."
            lines = ["Vault 검색 결과:"]
            for h in hits:
                label = "초안에 따르면" if h.status == "candidate" else "확정 지식"
                lines.append(f"· [{label}] {h.title} ({h.path})")
            return "\n".join(lines)

        if cmd in self.doc_agents:
            try:
                agent = self.doc_agents[cmd]()
                result = agent.generate()
            except RuntimeError as e:
                return f"실행 실패: {e}\n→ .env에서 OBSIDIAN_VAULT_PATH를 설정하세요."
            head = DESCRIPTIONS.get(cmd, cmd)
            return f"{head} 완료: {result.path.name}\n\n{result.text[:1500]}"

        if cmd == "task-add":
            if not intent.arg:
                return "추가할 할 일 내용을 말씀해 주세요."
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().add(intent.arg)
            except RuntimeError as e:
                return f"태스크 추가 실패: {e}"
            return result.message

        if cmd == "task-list":
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().list_tasks()
            except RuntimeError as e:
                return f"목록 조회 실패: {e}"
            return result.message

        if cmd == "task-done":
            if not intent.arg:
                return "완료할 번호를 말씀해 주세요. 예: '2번 완료'"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().done(intent.arg)
            except RuntimeError as e:
                return f"완료 처리 실패: {e}"
            return result.message

        if cmd == "task-delete":
            if not intent.arg:
                return "삭제할 번호를 말씀해 주세요. 예: '2번 삭제'"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().delete(intent.arg)
            except RuntimeError as e:
                return f"삭제 실패: {e}"
            return result.message

        if cmd == "task-edit":
            if not intent.arg:
                return "번호와 새 내용을 말씀해 주세요. 예: '2번 코드 리뷰 내일까지로 바꿔'"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().edit(intent.arg)
            except RuntimeError as e:
                return f"수정 실패: {e}"
            return result.message

        if cmd in _ROUTER_CMD:
            slash = f"/{_ROUTER_CMD[cmd]} {intent.arg}".strip()
            return self.command_router.handle(slash)

        return self.help_text()
