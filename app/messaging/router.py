"""명령 라우터 — 메시지 텍스트를 명령으로 해석한다(네트워크 무관).

메신저로 받은 한 줄 텍스트를 명령으로 파싱해 실행하고, 답장 문자열을 반환한다.
어떤 명령도 예외로 봇을 죽이지 않도록 친화적 문자열로 변환한다.
"""

from __future__ import annotations

from app.llm.base import LLMError, LLMNotConfiguredError

_HELP = (
    "**Devtrail**\n"
    "안녕하세요, 당신의 기록을 지식으로 바꾸는 에이전트예요.\n"
    "메모·링크·음성·사진을 던져두시면 제가 정리하고, 밤마다 지식 후보로 정제해둘게요.\n"
    "\n"
    "**사용 가능한 명령**\n"
    "\n"
    "**📋 할 일**\n"
    "/task <내용>  — 추가  (예: /task 코드리뷰 내일까지)\n"
    "/tasks  — 목록 + 완료·삭제 버튼\n"
    "/done <번호> · /del <번호> · /edit <번호> <새내용>\n"
    "  날짜 키워드(오늘·내일·이번 주·요일·날짜)를 알아듣고 섹션을 자동 배정해요\n"
    "\n"
    "**✍️ 기록 — 매일 이것만 해주세요**\n"
    "/capture <내용>  — 메모 저장 (슬래시 없이 그냥 말 걸어도 알아들어요)\n"
    "URL 붙여넣기  — 저장하면서 요약까지 해드려요\n"
    "음성·사진 전송  — 자동으로 캡처해요\n"
    "/todo  — 오늘 할 일 추천\n"
    "/search <검색어>  — Vault 전체 검색\n"
    "/briefing  — 지금 포커스·Open Loops 요약\n"
    "/sync  — Vault 수동 동기화\n"
    "\n"
    "**🔁 기록 → 지식 — 밤마다 제가 자동으로 해두는 일이에요**\n"
    "/distill  — 오늘 기록에서 후보 뽑기 (기다리기 싫을 때 수동 실행)\n"
    "/review  — 후보를 카드로 하나씩 검토 (✅ 승격 / ⏭ 건너뛰기 / 🗑 삭제)\n"
    "/candidates  — 쌓인 후보 목록\n"
    "/promote <경로>  — 후보를 공식 지식으로 승격\n"
    "/worklog  — 오늘 작업 회고\n"
    "\n"
    "**📝 블로그 · 문서**\n"
    "/write <주제> → /revise 다듬기 → /export 티스토리 변환 → /publish <URL> 기록\n"
    "/list — 초안 목록 · /preview — 미리보기\n"
    "/resume · /portfolio  — 이력서·포트폴리오 초안\n"
    "\n"
    "코드를 새로 배포했다면 /restart 로 저를 재시작할 수 있어요."
)


class CommandRouter:
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
            return (
                "이 기능은 LLM이 필요한데 아직 연결돼 있지 않아요.\n"
                "서버 .env에서 LLM_PROVIDER를 설정해주시면 요약·정제를 해드릴 수 있어요."
            )
        except LLMError as e:
            return f"LLM 호출이 실패했어요. 잠시 뒤 다시 시도해주세요.\n({e})"
        except Exception as e:
            return f"처리 중 오류가 발생했습니다: {e}"

    def _dispatch(self, cmd: str, arg: str) -> str:
        if cmd in ("help", "start", ""):
            return _HELP

        if cmd == "restart":
            import os
            import threading
            threading.Timer(1.5, lambda: os._exit(0)).start()
            return "🔄 재시작할게요. 10초 안에 돌아올게요."

        # ── 태스크 관리 ───────────────────────────────────────────────
        if cmd == "task":
            if not arg:
                return "어떤 할 일인가요? 내용을 함께 보내주세요.\n예: /task 코드 리뷰 내일까지"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().add(arg)
            except RuntimeError as e:
                return f"태스크 추가 실패: {e}"
            return result.message

        if cmd in ("tasks", "할일", "할_일"):
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().list_tasks()
            except RuntimeError as e:
                return f"목록 조회 실패: {e}"
            return result.message

        if cmd == "done":
            if not arg:
                return "몇 번을 완료 처리할까요? 번호를 함께 보내주세요.\n예: /done 2"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().done(arg)
            except RuntimeError as e:
                return f"완료 처리 실패: {e}"
            return result.message

        if cmd in ("del", "delete", "rm"):
            if not arg:
                return "몇 번을 삭제할까요? 번호를 함께 보내주세요.\n예: /del 2"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().delete(arg)
            except RuntimeError as e:
                return f"삭제 실패: {e}"
            return result.message

        if cmd == "edit":
            if not arg:
                return "어떻게 바꿀까요? 번호와 새 내용을 함께 보내주세요.\n예: /edit 2 코드 리뷰 내일까지"
            from app.agents.task_agent import TaskAgent
            try:
                result = TaskAgent().edit(arg)
            except RuntimeError as e:
                return f"수정 실패: {e}"
            return result.message

        # ── 블로그 (WikiBlogAgent) ────────────────────────────────────
        if cmd == "list":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            drafts = WikiBlogAgent().list_drafts()
            if not drafts:
                return "아직 초안이 없어요. /write <주제> 로 첫 초안을 만들어볼까요?"
            lines = [f"· [{d.status}] {d.title} ({d.rel_path})" for d in drafts]
            return (
                f"지금까지 쌓인 초안 {len(drafts)}건이에요:\n" + "\n".join(lines)
                + "\n\n/preview 로 내용을 보고 /revise 로 다듬을 수 있어요."
            )

        if cmd in ("write", "draft", "wb"):
            if not arg:
                return "어떤 주제로 쓸까요? 주제를 함께 보내주세요.\n예: /write XCoreChat 개발환경 분리"
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().write_blog(arg)
            return (
                f"✍️ 초안을 써뒀어요: **{draft.title}**\n"
                f"└ {draft.rel_path}\n\n"
                "Vault의 작업 기록을 근거로 썼어요. /preview 로 확인하고 /revise 로 다듬어보세요."
            )

        if cmd == "revise":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().revise_blog(arg or "latest")
            return (
                f"✨ 문장과 구조를 다듬었어요: {draft.title}\n"
                "게시할 준비가 되면 /export 로 티스토리용으로 변환해드릴게요."
            )

        if cmd == "preview":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            result = WikiBlogAgent().preview_draft(arg or "latest")
            if result is None:
                return "그 초안을 찾지 못했어요. /list 로 경로를 확인해주세요."
            draft, excerpt = result
            return f"{draft.title} [{draft.status}]\n\n{excerpt}"

        if cmd == "export":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            result = WikiBlogAgent().export_tistory(arg or "latest", "html")
            if result is None:
                return "변환할 초안이 없어요. /write <주제> 로 먼저 초안을 만들어주세요."
            return (
                f"티스토리용 HTML로 변환해뒀어요: {result.path.name}\n"
                f"제목: {result.draft.title}\n\n"
                "붙여넣고 게시한 뒤 /publish <URL> 로 알려주시면 기록해둘게요."
            )

        if cmd == "publish":
            if not arg:
                return "게시한 글 주소를 함께 보내주세요.\n예: /publish https://blog.tistory.com/1"
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().publish_done("latest", url=arg)
            if draft is None:
                return "게시로 기록할 초안이 없어요. /list 로 초안을 먼저 확인해주세요."
            return f"🎉 게시 완료로 기록했어요: {draft.title}\n{draft.published_url}"

        # ── 검색 ─────────────────────────────────────────────────────
        if cmd == "search":
            if not arg:
                return "무엇을 찾을까요? 검색어를 함께 보내주세요.\n예: /search RAG"
            from app.config import get_settings
            from app.services.wiki_service import WikiService
            from pathlib import Path
            settings = get_settings()
            if not settings.obsidian_vault_root:
                return "Vault 경로가 아직 설정되지 않았어요. 서버 .env의 OBSIDIAN_VAULT_PATH를 확인해주세요."
            service = WikiService(Path(settings.obsidian_vault_root), wiki_folder=settings.wiki_folder)
            results = service.search(arg, limit=5)
            if not results:
                return f"'{arg}'에 맞는 노트를 못 찾았어요. 다른 키워드로 시도해볼까요?"
            lines = [f"'{arg}' 관련 노트 {len(results)}건을 찾았어요:"]
            for r in results:
                lines.append(f"· {r.note.title} ({r.note.path})")
            return "\n".join(lines)

        # ── Vault Sync ────────────────────────────────────────────────
        if cmd == "sync":
            import subprocess
            import sys
            from pathlib import Path

            repo_root = Path(__file__).parent.parent.parent
            script = repo_root / "scripts" / "sync-vault.ps1"

            if not script.exists():
                return f"동기화 스크립트(sync-vault.ps1)를 찾지 못했어요.\n{script}"

            if sys.platform != "win32":
                return "/sync 는 Windows 서버에서만 지원해요. Mac은 launchd가 10분마다 자동 동기화하고 있어요."

            try:
                proc = subprocess.run(
                    [
                        "powershell.exe",
                        "-NonInteractive",
                        "-ExecutionPolicy", "Bypass",
                        "-File", str(script),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    encoding="utf-8",
                    errors="replace",
                )
                out = proc.stdout + proc.stderr

                if "Nothing to sync" in out:
                    return "✅ Vault는 이미 최신 상태예요. 동기화할 게 없었어요."

                if proc.returncode != 0 or "ERROR:" in out:
                    errors = [l for l in out.splitlines() if "ERROR:" in l]
                    err_msg = "\n".join(errors)[:400] if errors else out[-400:]
                    return f"❌ 동기화에 실패했어요:\n{err_msg}"

                lines = [l for l in out.splitlines() if any(k in l for k in ("commit:", "pull:", "push:", "Committed", "done"))]
                summary = "\n".join(l.split("  ", 1)[-1] for l in lines[-6:])
                return f"✅ Vault 동기화 끝냈어요\n{summary}"

            except subprocess.TimeoutExpired:
                return "⏱ 동기화가 120초를 넘겨서 멈췄어요. 잠시 후 다시 시도해주세요."
            except Exception as e:
                return f"❌ 동기화 중 문제가 생겼어요: {e}"

        # ── Vault Briefing ────────────────────────────────────────────
        if cmd == "briefing":
            from app import vault_tools
            try:
                text = vault_tools.get_briefing()
            except RuntimeError as e:
                return f"브리핑을 가져오지 못했어요: {e}\n→ 서버 .env의 OBSIDIAN_VAULT_PATH를 설정해주세요."
            if not text.strip():
                return (
                    "아직 브리핑할 내용이 없어요 — 40_AgentMemory/가 비어 있어요.\n"
                    "세션 기록이 몇 번 쌓이면 여기서 포커스와 Open Loops를 요약해드릴게요."
                )
            return text[:1500]

        # ── Session ───────────────────────────────────────────────────
        if cmd == "session":
            from app.agents import CaptureAgent
            try:
                agent = CaptureAgent()
            except RuntimeError as e:
                return f"세션 노트를 만들지 못했어요: {e}"
            result = agent.capture_session(project=arg or None, from_agent=False, from_repo=False)
            proj_label = f" ({arg})" if arg else ""
            return (
                f"📓 작업 세션 노트를 만들어뒀어요{proj_label}\n"
                f"└ {result.rel_path}\n\n"
                "이어서 문제·해결·다음 할 일을 보내주시면 더 풍부하게 남길 수 있어요."
            )

        # ── Capture / Distill ─────────────────────────────────────────
        if cmd == "capture":
            if not arg:
                return "저장할 메모 내용을 함께 보내주세요.\n예: /capture 오늘 RAG 작업함"
            from app.agents import CaptureAgent
            result = CaptureAgent().capture(text=arg)
            verb = "저장했어요" if result.created else "같은 노트가 있어서 그대로 뒀어요"
            return (
                f"📝 메모 {verb}\n└ {result.rel_path}\n\n"
                "오늘 밤에 제가 지식 후보로 정제해둘게요. 기다리기 싫으면 /distill"
            )

        if cmd == "distill":
            from app.agents import DistillAgent
            result = DistillAgent().distill_today()
            if not result.written:
                return (
                    "오늘 기록을 훑어봤는데 아직 정제할 만한 게 없네요.\n"
                    "메모나 링크를 먼저 남겨주시면 후보로 만들어드릴게요."
                )
            lines = [f"오늘 기록에서 후보 {len(result.written)}개를 뽑았어요:"]
            for item in result.written:
                lines.append(f"· [{item.spec.kind}] {item.spec.title}")
            lines.append("\n/review 로 하나씩 검토해보세요 — 버튼으로 승격/건너뛰기/삭제할 수 있어요.")
            return "\n".join(lines)

        if cmd in ("context", "ctx"):
            if not arg:
                return "어떤 주제의 컨텍스트를 모을까요? 주제를 함께 보내주세요.\n예: /context XCoreChat RAG"
            from app.config import get_settings
            from app.memory.context_pack_builder import ContextPackBuilder
            from pathlib import Path
            settings = get_settings()
            if not settings.obsidian_vault_root:
                return "Vault 경로가 아직 설정되지 않았어요. 서버 .env의 OBSIDIAN_VAULT_PATH를 확인해주세요."
            builder = ContextPackBuilder(Path(settings.obsidian_vault_root))
            pack = builder.build(arg)
            preview = pack.render()[:1500]
            return f"'{arg}' 컨텍스트를 모아봤어요 (source {len(pack.source_refs)}개)\n\n{preview}"

        if cmd == "candidates":
            from app.agents.curator_agent import CuratorAgent
            items = CuratorAgent().list_candidates()
            if not items:
                return "지금은 대기 중인 후보가 없어요.\n/distill 로 오늘 기록을 정제하면 후보가 생겨요."
            lines = [f"· [{i.kind}] {i.title}" for i in items[:10]]
            return (
                f"검토를 기다리는 후보 {len(items)}건이에요:\n" + "\n".join(lines)
                + "\n\n/review 로 검토를 시작해볼까요?"
            )

        if cmd == "promote":
            if not arg:
                return (
                    "승격할 후보 경로를 보내주세요.\n예: /promote 60_Candidates/Knowledge/foo.md\n"
                    "(경로는 /candidates 에서 확인할 수 있어요)"
                )
            from app.agents.curator_agent import CuratorAgent
            result = CuratorAgent().promote_candidate(arg)
            return f"✅ 공식 지식으로 승격했어요\n└ {result.promoted_path}"

        # ── 개인 문서 ─────────────────────────────────────────────────
        if cmd == "worklog":
            from app.agents import WorklogAgent
            result = WorklogAgent().generate()
            return f"오늘 작업을 회고로 정리했어요 📝\n\n{result.text[:1500]}"

        if cmd == "todo":
            from app.agents import TodoAgent
            result = TodoAgent().generate()
            return f"기록을 보고 다음 할 일을 뽑아봤어요 ✅\n\n{result.text[:1500]}"

        if cmd == "portfolio":
            from app.agents import PortfolioAgent
            result = PortfolioAgent().generate()
            return f"프로젝트 기록으로 포트폴리오 초안을 만들었어요 💼\n\n{result.text[:1500]}"

        if cmd == "resume":
            from app.agents import ResumeAgent
            result = ResumeAgent().generate()
            return f"이력서 초안을 만들었어요 📄\n\n{result.text[:1500]}"

        return f"알 수 없는 명령이에요: /{cmd}\n혹시 아래에서 찾으시는 게 있을까요?\n\n{_HELP}"
