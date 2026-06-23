"""WikiBlogAgent — ContextPack 기반 블로그 초안 생성·수정·관리 에이전트.

50_Outputs/Blog/Drafts/ 에 저장하며, 모든 초안에 source_refs frontmatter를 포함한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter
import markdown as md

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_task_llm_provider
from app.memory.context_pack_builder import ContextPackBuilder
from app.models.context_pack import ContextPack
from app.prompts import render_prompt
from app.services.json_utils import complete_json
from app.services.wiki_service import WikiService


_DRAFTS_REL = "50_Outputs/Blog/Drafts"
_MAX_SLUG_CHARS = 60


@dataclass(frozen=True)
class WikiBlogDraft:
    title: str
    slug: str
    tags: list[str]
    source_refs: list[str]
    rel_path: str
    path: Path
    body: str
    status: str = "draft"
    created_at: str = ""
    published_url: str = ""


@dataclass(frozen=True)
class WikiBlogExportResult:
    draft: WikiBlogDraft
    path: Path
    fmt: str


class WikiBlogAgent:
    """ContextPack → writer LLM → 50_Outputs/Blog/Drafts/ 저장."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.now = now
        if not self.settings.obsidian_vault_root:
            raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
        self.vault_dir = Path(self.settings.obsidian_vault_root)
        self.wiki_service = WikiService(self.vault_dir, wiki_folder=self.settings.wiki_folder)
        self.builder = ContextPackBuilder(self.vault_dir, wiki_service=self.wiki_service)

    # ── 초안 생성 ─────────────────────────────────────────────────────

    def write_blog(self, topic: str, project: str = "") -> WikiBlogDraft:
        """topic으로 Context Pack을 만들고 블로그 초안을 생성한다."""
        pack = self.builder.build(topic)
        return self._generate_and_save(topic, project, pack)

    def _generate_and_save(self, topic: str, project: str, pack: ContextPack) -> WikiBlogDraft:
        prompt = render_prompt("write_wiki_blog", CONTEXT_PACK=pack.render())
        data = complete_json(self._llm(), prompt)

        title = str(data.get("title") or topic).strip()
        tags_raw = data.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
        tags = [str(t) for t in tags_raw]
        body = str(data.get("body") or "").strip()

        slug = self._slug(title)
        stamp = (self.now or datetime.now()).strftime("%Y%m%d")
        rel_path = f"{_DRAFTS_REL}/{stamp}-{slug}.md"
        path = self.vault_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)

        today = (self.now or datetime.now()).strftime("%Y-%m-%d")
        metadata: dict[str, Any] = {
            "type": "draft",
            "output": "blog",
            "project": project,
            "status": "draft",
            "tags": tags,
            "source_refs": pack.source_refs,
            "created_at": today,
        }
        full_body = f"# {title}\n\n{body}" if body and not body.startswith("# ") else body
        post = frontmatter.Post(full_body, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        self.wiki_service.append_vault_log("write-blog", title, [rel_path])

        return WikiBlogDraft(
            title=title,
            slug=slug,
            tags=tags,
            source_refs=pack.source_refs,
            rel_path=rel_path,
            path=path,
            body=full_body,
            status="draft",
            created_at=today,
        )

    # ── 초안 수정 ─────────────────────────────────────────────────────

    def revise_blog(self, vault_rel_path: str) -> WikiBlogDraft:
        """50_Outputs/Blog/Drafts/ 아래 초안을 읽어 문장·구조를 다듬는다."""
        path = self.vault_dir / vault_rel_path
        if not path.exists():
            raise ValueError(f"초안을 찾지 못했습니다: {vault_rel_path}")

        raw = path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        original_body = post.content.strip()
        metadata = dict(post.metadata)

        prompt = render_prompt(
            "revise_wiki_blog",
            ORIGINAL=original_body,
            TOPIC=str(metadata.get("title") or vault_rel_path),
        )
        revised_body = self._llm().complete(prompt)

        metadata["status"] = "review"
        revised_post = frontmatter.Post(revised_body, **metadata)
        path.write_text(frontmatter.dumps(revised_post), encoding="utf-8")

        self.wiki_service.append_vault_log(
            "revise-blog", str(metadata.get("title") or path.stem), [vault_rel_path]
        )

        title = str(metadata.get("title") or path.stem)
        return WikiBlogDraft(
            title=title,
            slug=self._slug(title),
            tags=metadata.get("tags") or [],
            source_refs=metadata.get("source_refs") or [],
            rel_path=vault_rel_path,
            path=path,
            body=revised_body,
            status="review",
            created_at=str(metadata.get("created_at") or ""),
        )

    # ── 게시 준비 ─────────────────────────────────────────────────────

    def publish_ready(self, vault_rel_path: str) -> WikiBlogDraft:
        """초안 status를 review로 변경해 게시 준비 완료를 기록한다."""
        path = self.vault_dir / vault_rel_path
        if not path.exists():
            raise ValueError(f"초안을 찾지 못했습니다: {vault_rel_path}")

        raw = path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        metadata = dict(post.metadata)
        metadata["status"] = "review"
        updated_post = frontmatter.Post(post.content, **metadata)
        path.write_text(frontmatter.dumps(updated_post), encoding="utf-8")

        title = str(metadata.get("title") or path.stem)
        self.wiki_service.append_vault_log("publish-ready", title, [vault_rel_path])

        return WikiBlogDraft(
            title=title,
            slug=self._slug(title),
            tags=metadata.get("tags") or [],
            source_refs=metadata.get("source_refs") or [],
            rel_path=vault_rel_path,
            path=path,
            body=post.content,
            status="review",
            created_at=str(metadata.get("created_at") or ""),
        )

    # ── 목록 / 조회 ───────────────────────────────────────────────────

    def list_drafts(self) -> list[WikiBlogDraft]:
        """50_Outputs/Blog/Drafts/ 아래 초안을 최신순으로 반환한다."""
        drafts_dir = self.vault_dir / _DRAFTS_REL
        if not drafts_dir.exists():
            return []
        files = sorted(drafts_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [self._read_draft(f) for f in files]

    def preview_draft(self, target: str = "latest") -> tuple[WikiBlogDraft, str] | None:
        """초안 메타데이터와 본문 일부(800자)를 반환한다."""
        draft = self._resolve_target(target)
        if draft is None:
            return None
        excerpt = draft.body[:800].rstrip()
        if len(draft.body) > 800:
            excerpt += "\n..."
        return draft, excerpt

    # ── 내보내기 / 게시 ───────────────────────────────────────────────

    def export_tistory(self, target: str = "latest", fmt: str = "html") -> WikiBlogExportResult | None:
        """Vault 초안을 티스토리용 HTML/MD로 변환해 50_Outputs/Blog/Export/에 저장한다."""
        fmt = fmt.lower()
        if fmt not in ("html", "md"):
            raise ValueError("format은 'html' 또는 'md'여야 합니다.")

        draft = self._resolve_target(target)
        if draft is None:
            return None

        export_dir = self.vault_dir / "50_Outputs/Blog/Export"
        export_dir.mkdir(parents=True, exist_ok=True)
        ext = "html" if fmt == "html" else "md"
        out_path = export_dir / f"{draft.slug}.{ext}"

        if fmt == "html":
            content = md.markdown(draft.body, extensions=["fenced_code", "tables", "nl2br", "sane_lists"])
        else:
            content = draft.body.strip() + "\n"
        out_path.write_text(content, encoding="utf-8")

        if draft.status in ("draft", "idea"):
            self._update_status(draft.path, "review")

        self.wiki_service.append_vault_log("export-tistory", draft.title, [draft.rel_path])
        return WikiBlogExportResult(draft=draft, path=out_path, fmt=fmt)

    def publish_done(self, target: str = "latest", url: str = "") -> WikiBlogDraft | None:
        """게시 완료를 기록한다 (status=published, published_url 저장)."""
        draft = self._resolve_target(target)
        if draft is None:
            return None

        raw = draft.path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        metadata = dict(post.metadata)
        metadata["status"] = "published"
        if url:
            metadata["published_url"] = url
        draft.path.write_text(frontmatter.dumps(frontmatter.Post(post.content, **metadata)), encoding="utf-8")

        self.wiki_service.append_vault_log("publish-done", draft.title, [draft.rel_path])
        return WikiBlogDraft(
            title=draft.title,
            slug=draft.slug,
            tags=draft.tags,
            source_refs=draft.source_refs,
            rel_path=draft.rel_path,
            path=draft.path,
            body=draft.body,
            status="published",
            created_at=draft.created_at,
            published_url=url or draft.published_url,
        )

    # ── 내부 헬퍼 ────────────────────────────────────────────────────

    def _resolve_target(self, target: str) -> WikiBlogDraft | None:
        """'latest' 또는 vault rel_path로 초안을 찾아 반환한다."""
        if target == "latest":
            drafts = self.list_drafts()
            return drafts[0] if drafts else None
        path = self.vault_dir / target
        return self._read_draft(path) if path.exists() else None

    def _read_draft(self, path: Path) -> WikiBlogDraft:
        raw = path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        meta = dict(post.metadata)
        title = str(meta.get("title") or path.stem)
        return WikiBlogDraft(
            title=title,
            slug=self._slug(title),
            tags=meta.get("tags") or [],
            source_refs=meta.get("source_refs") or [],
            rel_path=str(path.relative_to(self.vault_dir)),
            path=path,
            body=post.content,
            status=str(meta.get("status") or "draft"),
            created_at=str(meta.get("created_at") or ""),
            published_url=str(meta.get("published_url") or ""),
        )

    def _update_status(self, path: Path, status: str) -> None:
        raw = path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        meta = dict(post.metadata)
        meta["status"] = status
        path.write_text(frontmatter.dumps(frontmatter.Post(post.content, **meta)), encoding="utf-8")

    def _llm(self) -> LLMProvider:
        return self.llm or get_task_llm_provider("writer", self.settings)

    def _slug(self, value: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^0-9a-z가-힣_-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-_")
        return text[:_MAX_SLUG_CHARS] or "blog"
