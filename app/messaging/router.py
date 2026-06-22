"""명령 라우터 — 메시지 텍스트를 BlogAgent 호출로 해석한다(네트워크 무관).

메신저로 받은 한 줄 텍스트를 명령으로 파싱해 실행하고, 답장 문자열을 반환한다.
어떤 명령도 예외로 봇을 죽이지 않도록 친화적 문자열로 변환한다.
"""

from __future__ import annotations

from typing import Callable

from app.agents.blog_agent import BlogAgent
from app.llm.base import LLMError, LLMNotConfiguredError
from app.models import DraftRequest

_HELP = (
    "사용 가능한 명령:\n"
    "/list — 초안 목록\n"
    "/topics — 주제 추천\n"
    "/draft <주제> — 초안 생성\n"
    "/revise [slug] — 초안 다듬기\n"
    "/preview [slug] — 초안 미리보기\n"
    "/export [slug] — 티스토리용 변환\n"
    "/publish <url> — 게시 완료 기록(최신 초안)\n"
    "/sync — Notion 동기화\n"
    "/wiki <질문> — wiki 검색 (예: /wiki vLLM 설정)\n"
    "/lint — wiki 건강 점검\n"
    "/worklog — 작업 회고\n"
    "/todo — 다음 할 일\n"
    "/portfolio — 포트폴리오 초안\n"
    "/resume — 이력서 초안\n"
    "/help — 도움말"
)


class CommandRouter:
    def __init__(self, make_agent: Callable[[], BlogAgent] | None = None):
        self.make_agent = make_agent or (lambda: BlogAgent())

    def handle(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return _HELP

        parts = text.split(maxsplit=1)
        cmd = parts[0].lstrip("/").lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        try:
            return self._dispatch(cmd, arg)
        except LLMNotConfiguredError:
            return "LLM이 연결되어 있지 않습니다. 서버의 .env에서 LLM_PROVIDER를 설정하세요."
        except LLMError as e:
            return f"LLM 호출 실패: {e}"
        except Exception as e:  # 봇이 죽지 않도록 모든 예외를 답장으로
            return f"오류가 발생했습니다: {e}"

    # ----- 개별 명령 -----
    def _dispatch(self, cmd: str, arg: str) -> str:
        agent = self.make_agent()

        if cmd in ("help", "start", ""):
            return _HELP

        if cmd == "list":
            posts = agent.list_drafts()
            if not posts:
                return "저장된 초안이 없습니다."
            lines = [f"· [{p.status.value}] {p.title} ({p.slug})" for p in posts]
            return "초안 목록:\n" + "\n".join(lines)

        if cmd in ("topics", "suggest"):
            suggestions = agent.suggest_topics()
            if not suggestions:
                return "추천할 주제를 찾지 못했습니다."
            blocks = []
            for i, s in enumerate(suggestions, 1):
                title = s.title_candidates[0] if s.title_candidates else "(제목 없음)"
                blocks.append(f"{i}. {title}\n   {s.reason}")
            return "추천 주제:\n" + "\n".join(blocks)

        if cmd in ("draft", "write"):
            if not arg:
                return "주제를 함께 보내주세요. 예: /draft XCoreChat 개발환경 분리"
            post = agent.write_draft(DraftRequest(topic=arg))
            return f"초안 생성 완료: {post.title}\nslug: {post.slug}"

        if cmd == "revise":
            post = agent.revise(arg or "latest")
            if post is None:
                return "다듬을 초안이 없습니다."
            return f"다듬기 완료: {post.title}"

        if cmd == "preview":
            result = agent.preview(arg or "latest")
            if result is None:
                return "초안을 찾지 못했습니다."
            p = result.post
            return f"{p.title} [{p.status.value}]\n\n{result.excerpt}"

        if cmd == "export":
            result = agent.export_tistory(arg or "latest", "html")
            if result is None:
                return "변환할 초안이 없습니다."
            return f"티스토리용 변환 완료: {result.path.name}\n제목: {result.post.title}"

        if cmd == "publish":
            if not arg:
                return "게시한 글 주소를 함께 보내주세요. 예: /publish https://blog.tistory.com/1"
            post = agent.publish_done("latest", url=arg)
            if post is None:
                return "게시 기록할 초안이 없습니다."
            return f"게시 완료 기록: {post.title}\n{post.published_url}"

        if cmd == "sync":
            report = agent.sync_notion(dry_run=False)
            return f"Notion 동기화({report.mode}): 생성 {len(report.created)} · 갱신 {len(report.updated)}"

        if cmd in ("wiki", "w"):
            if not arg:
                return "질문을 함께 보내주세요. 예: /wiki vLLM 설정 방법"
            try:
                from app.agents.wiki_agent import build_wiki_agent
                wiki_agent = build_wiki_agent()
                return wiki_agent.query(arg)
            except RuntimeError as e:
                return f"wiki 검색 실패: {e}"

        if cmd == "lint":
            try:
                from app.agents.wiki_agent import build_wiki_agent
                wiki_agent = build_wiki_agent()
                result = wiki_agent.lint()
                return f"wiki 점검 완료\n\n{result[:1500]}"
            except RuntimeError as e:
                return f"wiki 점검 실패: {e}"

        if cmd == "worklog":
            from app.agents import WorklogAgent
            result = WorklogAgent().generate()
            return f"작업 회고 완료\n\n{result.text[:1500]}"

        if cmd == "todo":
            from app.agents import TodoAgent
            result = TodoAgent().generate()
            return f"할 일 제안\n\n{result.text[:1500]}"

        if cmd == "portfolio":
            from app.agents import PortfolioAgent
            result = PortfolioAgent().generate()
            return f"포트폴리오 초안\n\n{result.text[:1500]}"

        if cmd == "resume":
            from app.agents import ResumeAgent
            result = ResumeAgent().generate()
            return f"이력서 초안\n\n{result.text[:1500]}"

        return f"알 수 없는 명령입니다.\n\n{_HELP}"
