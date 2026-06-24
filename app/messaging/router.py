"""명령 라우터 — 메시지 텍스트를 명령으로 해석한다(네트워크 무관).

메신저로 받은 한 줄 텍스트를 명령으로 파싱해 실행하고, 답장 문자열을 반환한다.
어떤 명령도 예외로 봇을 죽이지 않도록 친화적 문자열로 변환한다.
"""

from __future__ import annotations

from app.llm.base import LLMError, LLMNotConfiguredError

_HELP = (
    "📥 캡처\n"
    "/capture <메모> — 빠른 메모 저장\n"
    "\n"
    "🔍 분석 · 검색\n"
    "/distill — 오늘 기록 → 후보 생성\n"
    "/candidates — 후보 목록 보기\n"
    "/search <검색어> — Vault 검색\n"
    "\n"
    "📝 정리 · 출력\n"
    "/todo — 다음 할 일\n"
    "/worklog — 오늘 작업 회고\n"
    "/write <주제> — 블로그 초안 작성\n"
    "\n"
    "기타: /list /promote /context /resume /portfolio /sync"
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
            return "LLM이 연결되어 있지 않습니다. 서버의 .env에서 LLM_PROVIDER를 설정하세요."
        except LLMError as e:
            return f"LLM 호출 실패: {e}"
        except Exception as e:
            return f"오류가 발생했습니다: {e}"

    def _dispatch(self, cmd: str, arg: str) -> str:
        if cmd in ("help", "start", ""):
            return _HELP

        # ── 블로그 (WikiBlogAgent) ────────────────────────────────────
        if cmd == "list":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            drafts = WikiBlogAgent().list_drafts()
            if not drafts:
                return "저장된 초안이 없습니다."
            lines = [f"· [{d.status}] {d.title} ({d.rel_path})" for d in drafts]
            return "초안 목록:\n" + "\n".join(lines)

        if cmd in ("write", "draft", "wb"):
            if not arg:
                return "주제를 함께 보내주세요. 예: /write XCoreChat 개발환경 분리"
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().write_blog(arg)
            return f"블로그 초안 생성 완료: {draft.title}\nvault: {draft.rel_path}"

        if cmd == "revise":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().revise_blog(arg or "latest")
            return f"다듬기 완료: {draft.title}"

        if cmd == "preview":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            result = WikiBlogAgent().preview_draft(arg or "latest")
            if result is None:
                return "초안을 찾지 못했습니다."
            draft, excerpt = result
            return f"{draft.title} [{draft.status}]\n\n{excerpt}"

        if cmd == "export":
            from app.agents.wiki_blog_agent import WikiBlogAgent
            result = WikiBlogAgent().export_tistory(arg or "latest", "html")
            if result is None:
                return "변환할 초안이 없습니다."
            return f"티스토리용 변환 완료: {result.path.name}\n제목: {result.draft.title}"

        if cmd == "publish":
            if not arg:
                return "게시한 글 주소를 함께 보내주세요. 예: /publish https://blog.tistory.com/1"
            from app.agents.wiki_blog_agent import WikiBlogAgent
            draft = WikiBlogAgent().publish_done("latest", url=arg)
            if draft is None:
                return "게시 기록할 초안이 없습니다."
            return f"게시 완료 기록: {draft.title}\n{draft.published_url}"

        # ── 검색 ─────────────────────────────────────────────────────
        if cmd == "search":
            if not arg:
                return "검색어를 함께 보내주세요. 예: /search RAG"
            from app.config import get_settings
            from app.services.wiki_service import WikiService
            from pathlib import Path
            settings = get_settings()
            if not settings.obsidian_vault_root:
                return "OBSIDIAN_VAULT_PATH가 설정되지 않았습니다."
            service = WikiService(Path(settings.obsidian_vault_root), wiki_folder=settings.wiki_folder)
            results = service.search(arg, limit=5)
            if not results:
                return "검색 결과가 없습니다."
            lines = [f"검색 결과 ({len(results)}건):"]
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
                return f"sync-vault.ps1 를 찾을 수 없습니다.\n{script}"

            if sys.platform != "win32":
                return "sync 커맨드는 Windows 서버에서만 지원됩니다."

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
                    return "✅ Vault 이미 최신 상태"

                if proc.returncode != 0 or "ERROR:" in out:
                    errors = [l for l in out.splitlines() if "ERROR:" in l]
                    err_msg = "\n".join(errors)[:400] if errors else out[-400:]
                    return f"❌ 동기화 실패\n{err_msg}"

                lines = [l for l in out.splitlines() if any(k in l for k in ("commit:", "pull:", "push:", "Committed", "done"))]
                summary = "\n".join(l.split("  ", 1)[-1] for l in lines[-6:])
                return f"✅ Vault 동기화 완료\n{summary}"

            except subprocess.TimeoutExpired:
                return "⏱ 동기화 타임아웃 (120초 초과)"
            except Exception as e:
                return f"❌ 동기화 실패: {e}"

        # ── Session ───────────────────────────────────────────────────
        if cmd == "session":
            from app.agents import CaptureAgent
            try:
                agent = CaptureAgent()
            except RuntimeError as e:
                return f"Session 저장 실패: {e}"
            result = agent.capture_session(project=arg or None, from_agent=False, from_repo=False)
            proj_label = f" ({arg})" if arg else ""
            return (
                f"작업 세션 노트 생성 완료{proj_label}\n"
                f"vault: {result.rel_path}\n\n"
                "더 자세히 남기려면 이어서 문제/해결/다음 할 일을 보내줘."
            )

        # ── Capture / Distill ─────────────────────────────────────────
        if cmd == "capture":
            if not arg:
                return "메모 내용을 함께 보내주세요. 예: /capture 오늘 RAG 작업함"
            from app.agents import CaptureAgent
            result = CaptureAgent().capture(text=arg)
            verb = "저장" if result.created else "기존 파일 유지"
            return f"메모 {verb} 완료\n{result.rel_path}"

        if cmd == "distill":
            from app.agents import DistillAgent
            result = DistillAgent().distill_today()
            if not result.written:
                return "오늘 생성된 후보가 없습니다."
            lines = [f"후보 {len(result.written)}개 생성:"]
            for item in result.written:
                lines.append(f"· [{item.spec.kind}] {item.spec.title}")
            return "\n".join(lines)

        if cmd in ("context", "ctx"):
            if not arg:
                return "주제를 함께 보내주세요. 예: /context XCoreChat RAG"
            from app.config import get_settings
            from app.memory.context_pack_builder import ContextPackBuilder
            from pathlib import Path
            settings = get_settings()
            if not settings.obsidian_vault_root:
                return "OBSIDIAN_VAULT_PATH가 설정되지 않았습니다."
            builder = ContextPackBuilder(Path(settings.obsidian_vault_root))
            pack = builder.build(arg)
            preview = pack.render()[:1500]
            return f"Context Pack ({len(pack.source_refs)}개 source)\n\n{preview}"

        if cmd == "candidates":
            from app.agents.curator_agent import CuratorAgent
            items = CuratorAgent().list_candidates()
            if not items:
                return "60_Candidates/ 에 후보가 없습니다."
            lines = [f"· [{i.kind}] {i.title}" for i in items[:10]]
            return f"후보 목록 ({len(items)}건):\n" + "\n".join(lines)

        if cmd == "promote":
            if not arg:
                return "승격할 후보 경로를 보내주세요. 예: /promote 60_Candidates/Knowledge/foo.md"
            from app.agents.curator_agent import CuratorAgent
            result = CuratorAgent().promote_candidate(arg)
            return f"승격 완료: {result.promoted_path}"

        # ── 개인 문서 ─────────────────────────────────────────────────
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

        return f"알 수 없는 명령: /{cmd}\n\n{_HELP}"
