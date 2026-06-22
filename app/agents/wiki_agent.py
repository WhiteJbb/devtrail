"""LLM Wiki 에이전트.

Obsidian 볼트 소스 문서를 읽어 wiki 페이지를 생성·갱신하고(ingest),
wiki를 탐색해 질문에 답한다(query).

흐름:
  ingest:
    1. 소스 파일 목록(경로만) → LLM이 생성할 페이지 계획(JSON)
    2. 각 페이지별로 소스 내용 로드 → LLM이 페이지 본문 생성(plain markdown)
    3. index.md / log.md 갱신

  query:
    1. index.md + 질문 → LLM이 관련 페이지 선택(JSON)
    2. 해당 페이지 로드 → LLM이 답변 합성(plain text)
"""

from __future__ import annotations

from pathlib import Path

from app.llm.base import LLMProvider
from app.prompts import render_prompt
from app.services.json_utils import complete_json
from app.services.wiki_service import WikiService


class WikiAgent:
    MAX_PAGES_PER_INGEST = 10  # 한 번에 생성할 최대 페이지 수
    MAX_UPDATE_PER_INGEST = 5  # 한 번에 갱신할 최대 기존 페이지 수
    MAX_ANSWER_PAGES = 5       # 답변에 사용할 최대 페이지 수
    MAX_LINT_PAGES = 10        # lint 시 샘플링할 최대 페이지 수

    def __init__(
        self,
        llm: LLMProvider,
        wiki_service: WikiService,
        char_budget: int = 12_000,
    ) -> None:
        self.llm = llm
        self.svc = wiki_service
        self.char_budget = char_budget

    # ── ingest ───────────────────────────────────────────────────

    def ingest(self, folder_filter: str = "") -> str:
        grouped = self.svc.list_source_files_grouped(folder_filter)
        if not grouped.strip():
            return "소스 파일을 찾지 못했습니다. OBSIDIAN_VAULT_DIR을 확인하세요."

        existing_index = self.svc.get_index()

        # Step 1: 신규 생성 + 기존 갱신 계획
        plan_prompt = render_prompt(
            "wiki_ingest_plan",
            SOURCES=grouped,
            INDEX=existing_index or "(아직 없음)",
        )
        plan_data = complete_json(self.llm, plan_prompt)

        to_create = plan_data.get("create", [])[: self.MAX_PAGES_PER_INGEST]
        to_update = plan_data.get("update", [])[:self.MAX_UPDATE_PER_INGEST]
        # 이전 포맷("pages" 키) 하위 호환
        if not to_create and not to_update:
            to_create = plan_data.get("pages", [])[: self.MAX_PAGES_PER_INGEST]

        if not to_create and not to_update:
            return "생성하거나 갱신할 wiki 페이지가 없습니다."

        new_summaries: dict[str, str] = {}
        written: list[str] = []

        # Step 2: 신규 페이지 생성
        existing_pages = self.svc.list_pages()
        wiki_pages_list = "\n".join(f"- {p}" for p in existing_pages) or "(아직 없음)"

        for page in to_create:
            path: str = page.get("path", "").strip()
            title: str = page.get("title", path)
            summary: str = page.get("summary", "")
            source_paths: list[str] = page.get("sources", [])

            if not path:
                continue

            parts = self._load_sources(source_paths)
            if not parts:
                continue

            page_prompt = render_prompt(
                "wiki_page",
                TITLE=title,
                SOURCES="\n\n".join(parts),
                WIKI_PAGES=wiki_pages_list,
            )
            content = self.llm.complete(page_prompt).strip()
            self.svc.write_page(path, content)
            new_summaries[path] = summary
            written.append(path)

        # Step 3: 기존 페이지 갱신
        for page in to_update:
            path = page.get("path", "").strip()
            reason: str = page.get("reason", "")
            source_paths = page.get("sources", [])

            if not path:
                continue

            existing_content = self.svc.read_page(path)
            if not existing_content:
                continue

            parts = self._load_sources(source_paths)
            if not parts:
                continue

            update_prompt = render_prompt(
                "wiki_page_update",
                PATH=path,
                EXISTING=existing_content,
                SOURCES="\n\n".join(parts),
                REASON=reason,
            )
            content = self.llm.complete(update_prompt).strip()
            self.svc.write_page(path, content)
            written.append(f"{path} (갱신)")

        if not written:
            return "작성된 페이지가 없습니다."

        self.svc.rebuild_index(new_summaries)
        self.svc.append_log(written)

        return f"{len(written)}개 wiki 페이지 생성/갱신 완료\n" + "\n".join(f"  · {p}" for p in written)

    def _load_sources(self, source_paths: list[str]) -> list[str]:
        parts: list[str] = []
        used = 0
        for sp in source_paths:
            remaining = self.char_budget - used
            if remaining <= 0:
                break
            text = self.svc.read_source(sp, max_chars=remaining)
            if text:
                parts.append(f"### {sp}\n{text}")
                used += len(text)
        return parts

    # ── query ────────────────────────────────────────────────────

    def query(self, question: str) -> str:
        index = self.svc.get_index()
        if not index:
            return "아직 wiki가 없습니다. `wiki-ingest`를 먼저 실행하세요."

        # Step 1: 관련 페이지 선택
        route_prompt = render_prompt(
            "wiki_query_route",
            QUESTION=question,
            INDEX=index,
        )
        route_data = complete_json(self.llm, route_prompt)
        page_paths: list[str] = route_data.get("pages", [])[: self.MAX_ANSWER_PAGES]

        if not page_paths:
            return "관련 wiki 페이지를 찾지 못했습니다. wiki-ingest로 내용을 더 추가해보세요."

        # Step 2: 페이지 로드 후 답변 합성
        pages_text_parts: list[str] = []
        for path in page_paths:
            content = self.svc.read_page(path)
            if content:
                pages_text_parts.append(f"## {path}\n{content}")

        if not pages_text_parts:
            return "wiki 페이지를 읽지 못했습니다."

        answer_prompt = render_prompt(
            "wiki_query_answer",
            QUESTION=question,
            PAGES="\n\n".join(pages_text_parts),
        )
        return self.llm.complete(answer_prompt).strip()

    # ── lint ─────────────────────────────────────────────────────

    def lint(self) -> str:
        index = self.svc.get_index()
        if not index:
            return "wiki가 비어 있습니다. wiki-ingest를 먼저 실행하세요."

        pages = self.svc.list_pages()[: self.MAX_LINT_PAGES]
        pages_text_parts: list[str] = []
        for p in pages:
            content = self.svc.read_page(p)
            if content:
                pages_text_parts.append(f"## {p}\n{content[:800]}")

        lint_prompt = render_prompt(
            "wiki_lint",
            INDEX=index,
            PAGES="\n\n".join(pages_text_parts) or "(없음)",
        )
        return self.llm.complete(lint_prompt).strip()

    # ── file_answer ───────────────────────────────────────────────

    def file_answer(self, question: str, answer: str, path: str) -> str:
        """질문·답변을 wiki 페이지로 저장한다."""
        content = f"# {question}\n\n_쿼리 결과 자동 저장_\n\n{answer}"
        self.svc.write_page(path, content)
        self.svc.rebuild_index({path: question[:80]})
        self.svc.append_log([f"{path} (쿼리 저장)"])
        return f"wiki 페이지로 저장: {path}"


def build_wiki_agent(char_budget: int = 12_000) -> WikiAgent:
    """설정에서 WikiAgent를 조립한다."""
    from app.config import get_settings
    from app.llm.factory import get_llm_provider

    settings = get_settings()
    if not settings.wiki_enabled:
        raise RuntimeError("OBSIDIAN_VAULT_DIR이 설정되지 않았습니다.")

    vault_dir = Path(settings.obsidian_vault_root)
    svc = WikiService(vault_dir, wiki_folder=settings.wiki_folder)
    llm = get_llm_provider(settings)
    return WikiAgent(llm=llm, wiki_service=svc, char_budget=char_budget)
