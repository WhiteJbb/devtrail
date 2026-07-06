"""Vault tool 레이어 — CLI/MCP/Telegram이 공유하는 Agent Session Lifecycle 서비스.

docs/service-improvement-plan.md P1/P2의 정본 함수를 제공한다. 새 로직은 최소화하고
기존 WikiService/CandidateWriter/CaptureAgent/AgentMemoryLoader/ProjectMemoryLoader/
ContextPackBuilder를 조합만 한다.

read_scope: 20_Knowledge/, 30_Projects/, 40_AgentMemory/(stable), 60_Candidates/(candidate).
write_scope: record_note는 knowledge/decision/blog_idea/career_bullet만, write_work_plan과
write_session_process는 60_Candidates/SessionHandoffs/<Project>/만, record_agent_improvement는
60_Candidates/MemoryPatches/만 기록한다. 공식 영역(20_Knowledge/, 30_Projects/, 40_AgentMemory/)은
이 모듈에서 절대 직접 쓰지 않는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import frontmatter

from app.agents.capture_agent import CaptureAgent, CaptureResult
from app.config import Settings, get_settings
from app.memory.agent_memory_loader import AgentMemoryLoader
from app.memory.context_pack_builder import ContextPackBuilder
from app.memory.project_memory_loader import ProjectMemoryLoader
from app.models.context_pack import ContextPack
from app.services.candidate_writer import CandidateSpec, CandidateWriter, CandidateWriteResult, slug_component
from app.services.wiki_service import WikiService

_STABLE_PREFIXES = ("20_Knowledge/", "30_Projects/", "40_AgentMemory/")
_CANDIDATE_PREFIX = "60_Candidates/"
_ALLOWED_READ_PREFIXES = _STABLE_PREFIXES + (_CANDIDATE_PREFIX,)

_RECORD_NOTE_KINDS = {"knowledge", "decision", "blog_idea", "career_bullet"}

_SECTION_MAX_CHARS = 1200
_RECENT_HANDOFF_LIMIT = 3
_ORPHAN_REATTACH_WINDOW_HOURS = 24
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class VaultScopeError(ValueError):
    """read_scope/write_scope를 벗어난 요청."""


# ── 공용 데이터 타입 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchHit:
    path: str
    title: str
    status: str  # "stable" | "candidate"
    score: int
    summary: str


@dataclass(frozen=True)
class ProjectBriefing:
    project: str
    matched: bool
    candidates: list[str] = field(default_factory=list)
    text: str = ""
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SessionProcessResult:
    session_id: str
    process: CandidateWriteResult
    worklog_rel_path: str
    decision: CandidateWriteResult | None = None
    memory_patch: CandidateWriteResult | None = None


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────


def _vault_dir(settings: Settings | None) -> Path:
    s = settings or get_settings()
    if not s.obsidian_vault_root:
        raise RuntimeError("OBSIDIAN_VAULT_PATH is not configured.")
    return Path(s.obsidian_vault_root)


def _normalize_scoped_path(rel_path: str) -> str:
    """rel_path를 vault 기준 상대경로로 정규화하고 read_scope를 벗어나면 거부한다."""
    if not rel_path or not rel_path.strip():
        raise VaultScopeError("rel_path가 비어 있습니다.")
    candidate = rel_path.strip().replace("\\", "/")
    if candidate.startswith("/") or _DRIVE_RE.match(candidate):
        raise VaultScopeError(f"절대경로는 허용되지 않습니다: {rel_path}")
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise VaultScopeError(f"vault를 벗어나는 경로는 허용되지 않습니다: {rel_path}")
    normalized = "/".join(parts)
    if not any(normalized.startswith(prefix) for prefix in _ALLOWED_READ_PREFIXES):
        raise VaultScopeError(f"read_scope 밖의 경로입니다: {rel_path}")
    return normalized


def _status_of(rel_path: str) -> str:
    return "candidate" if rel_path.startswith(_CANDIDATE_PREFIX) else "stable"


def _truncate(text: str, limit: int = _SECTION_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...(생략)"


def _project_dir_slug(project: str) -> str:
    return slug_component(project) if project.strip() else "_Unassigned"


def _list_session_handoffs(vault_dir: Path, project: str) -> list[dict]:
    """60_Candidates/SessionHandoffs/<project>/의 candidate를 frontmatter와 함께 반환한다."""
    handoff_dir = vault_dir / "60_Candidates" / "SessionHandoffs" / _project_dir_slug(project)
    if not handoff_dir.exists():
        return []
    items: list[dict] = []
    for md_path in sorted(handoff_dir.glob("*.md")):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = post.metadata
        items.append(
            {
                "rel_path": str(md_path.relative_to(vault_dir)).replace("\\", "/"),
                "title": str(meta.get("title", "")),
                "created_at": str(meta.get("created_at", "")),
                "handoff_type": str(meta.get("handoff_type", "")),
                "session_id": str(meta.get("session_id", "")),
                "body": post.content,
            }
        )
    items.sort(key=lambda h: h["created_at"], reverse=True)
    return items


def _excerpt_sections(body: str, headings: tuple[str, ...]) -> str:
    """body에서 지정된 '## Heading' 섹션만 발췌한다."""
    lines = body.splitlines()
    out: list[str] = []
    capture = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            capture = heading in headings
            if capture:
                out.append(line)
            continue
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def _reattach_orphan_plan_if_needed(vault_dir: Path, project: str, session_id: str) -> str:
    """이 session_id의 Plan이 없으면, 같은 프로젝트의 최근 미짝 Plan에 재귀속한다.

    MCP 서버 재시작 등으로 Plan 때와 다른 session_id가 생성된 경우를 위한 안전망이다.
    재귀속 후보는 최근 _ORPHAN_REATTACH_WINDOW_HOURS 이내에 생성된 미짝 Plan으로
    제한한다 — "같은 세션 중 서버 재시작" 복구에는 이 정도면 충분하고, 제한이 없으면
    이번 세션이 write_work_plan을 그냥 안 불렀을 뿐인데 몇 주 전 무관한 세션의 미짝
    Plan에 오늘의 Process가 잘못 엮여 정당한 "미짝 Plan 경고"도 사라지게 된다.
    """
    handoffs = _list_session_handoffs(vault_dir, project)
    plans = [h for h in handoffs if h["handoff_type"] == "plan"]
    processes = [h for h in handoffs if h["handoff_type"] == "process"]
    paired_ids = {p["session_id"] for p in processes}

    if any(p["session_id"] == session_id for p in plans):
        return session_id

    cutoff = (datetime.now() - timedelta(hours=_ORPHAN_REATTACH_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%S")
    orphan_plans = [
        p
        for p in plans
        if p["session_id"] and p["session_id"] not in paired_ids and p["created_at"] >= cutoff
    ]
    if not orphan_plans:
        return session_id

    orphan_plans.sort(key=lambda p: p["created_at"], reverse=True)
    return orphan_plans[0]["session_id"]


# ── 조회 ─────────────────────────────────────────────────────────────────────


def search_vault(query: str, limit: int = 10, settings: Settings | None = None) -> list[SearchHit]:
    """read_scope 안의 노트를 검색하고 status=stable/candidate를 함께 반환한다.

    stable 결과가 candidate보다 먼저 정렬된다.
    """
    vault_dir = _vault_dir(settings)
    wiki = WikiService(vault_dir)
    # 점수화·절단 전에 read_scope로 필터링한다 — 사후 필터링하면 00_Inbox/10_Worklog처럼
    # 노트가 많은 폴더가 전역 top-N을 채워 스코프 안 결과가 아예 안 보일 수 있다.
    raw = wiki.search(query, limit=limit, prefixes=_ALLOWED_READ_PREFIXES)

    hits = [
        SearchHit(path=r.note.path, title=r.note.title, status=_status_of(r.note.path), score=r.score, summary=r.note.summary)
        for r in raw
    ]

    hits.sort(key=lambda h: (0 if h.status == "stable" else 1, -h.score, h.path))
    return hits[:limit]


def read_note(rel_path: str, settings: Settings | None = None) -> str:
    """scope 안의 노트 전문을 읽는다. scope 밖, 절대경로, `..` 탈출은 거부한다."""
    vault_dir = _vault_dir(settings)
    normalized = _normalize_scoped_path(rel_path)
    path = vault_dir / normalized
    resolved = path.resolve()
    if not resolved.is_relative_to(vault_dir.resolve()):
        raise VaultScopeError(f"vault를 벗어나는 경로입니다: {rel_path}")
    if not resolved.exists() or not resolved.is_file():
        raise VaultScopeError(f"노트를 찾지 못했습니다: {rel_path}")
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 외부 도구가 UTF-8이 아닌 인코딩으로 저장한 노트도 있을 수 있다
        # (WikiService._parse_note는 이미 이 폴백을 쓴다).
        return resolved.read_text(encoding="utf-8", errors="replace")


def get_briefing(settings: Settings | None = None) -> str:
    """40_AgentMemory/ 기반 현재 프로필/포커스/Open Loops 요약을 반환한다."""
    vault_dir = _vault_dir(settings)
    return AgentMemoryLoader(vault_dir).load().render()


def build_context(topic: str, settings: Settings | None = None) -> ContextPack:
    """기존 ContextPackBuilder를 그대로 재사용한다."""
    vault_dir = _vault_dir(settings)
    return ContextPackBuilder(vault_dir).build(topic)


def _load_project_config(repo_dir: Path) -> str:
    """repo의 `.claude/vault.json`에서 명시적 project 매핑을 읽는다. 없으면 빈 문자열."""
    config_path = repo_dir / ".claude" / "vault.json"
    if not config_path.exists():
        return ""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("project", "")).strip()


def get_project_briefing(project_or_repo: str, settings: Settings | None = None) -> ProjectBriefing:
    """세션 시작 시 프로젝트 컨텍스트/최근 handoff/decision/open loops를 반환한다.

    project_or_repo는 명시적 프로젝트명이거나 repo 디렉터리 경로일 수 있다. 매칭에
    실패하거나 확신이 낮으면 컨텍스트를 주입하지 않고 후보 프로젝트 목록만 반환한다.
    """
    vault_dir = _vault_dir(settings)
    project_memory = ProjectMemoryLoader(vault_dir).load()
    agent_memory = AgentMemoryLoader(vault_dir).load()

    candidate_path = Path(project_or_repo)
    explicit_project = ""
    if candidate_path.exists() and candidate_path.is_dir():
        explicit_project = _load_project_config(candidate_path)

    resolved_project = explicit_project
    if not resolved_project:
        # repo 디렉터리명 또는 입력값 자체를 프로젝트명과 대소문자 무시 매칭 시도
        probe_name = candidate_path.name if candidate_path.exists() else project_or_repo
        exact = project_memory.find(probe_name)
        if exact:
            resolved_project = exact.project
        else:
            resolved_project = ""

    if not resolved_project:
        candidates = [ctx.project for ctx in project_memory.contexts]
        return ProjectBriefing(
            project=project_or_repo,
            matched=False,
            candidates=candidates,
            text=(
                "확신할 수 있는 프로젝트 매칭이 없습니다. 아래 후보 중 하나를 확정하면 "
                "`.claude/vault.json`에 저장해 다음 세션에서 같은 질문을 반복하지 않을 수 있습니다.\n\n"
                + ("\n".join(f"- {c}" for c in candidates) if candidates else "(등록된 프로젝트 없음)")
            ),
            source_refs=[],
        )

    project_ctx = project_memory.find(resolved_project)
    handoffs = _list_session_handoffs(vault_dir, resolved_project)
    is_cold_start = project_ctx is None and not handoffs

    source_refs: list[str] = list(agent_memory.source_refs)
    sections: list[str] = [f"# Project Briefing — {resolved_project}"]

    if is_cold_start:
        sections.append(
            "## 미등록 프로젝트\n\n"
            f"`{resolved_project}`은(는) Vault에 아직 등록되지 않았습니다. 전역 Agent Memory만 "
            "반환합니다. `write_work_plan`을 처음 호출하면 SessionHandoffs 폴더가 생성됩니다."
        )
        sections.append(f"## Current Focus / Open Loops\n\n{_truncate(agent_memory.render())}")
        return ProjectBriefing(
            project=resolved_project, matched=True, candidates=[], text="\n\n".join(sections), source_refs=source_refs
        )

    sections.append(f"## Current Focus\n\n{_truncate(agent_memory.render())}")

    if project_ctx:
        sections.append(f"## Project Context\n\n{_truncate(project_ctx.body)}")
        source_refs.append(project_ctx.rel_path)

    decisions_dir = vault_dir / "60_Candidates" / "Decisions"
    recent_decisions: list[str] = []
    if decisions_dir.exists():
        for md_path in sorted(decisions_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(post.metadata.get("project", "")).strip().lower() != resolved_project.lower():
                continue
            rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
            recent_decisions.append(f"- {post.metadata.get('title', md_path.stem)} ({rel})")
            source_refs.append(rel)
            if len(recent_decisions) >= 5:
                break
    if recent_decisions:
        sections.append("## Recent Decisions\n\n" + _truncate("\n".join(recent_decisions)))

    plans = [h for h in handoffs if h["handoff_type"] == "plan"]
    processes = [h for h in handoffs if h["handoff_type"] == "process"]
    paired_ids = {p["session_id"] for p in processes}
    recent = handoffs[:_RECENT_HANDOFF_LIMIT]
    if recent:
        excerpt_parts = []
        for h in recent:
            excerpt = _excerpt_sections(h["body"], ("Next Session", "What Changed", "Goal"))
            excerpt_parts.append(f"### {h['title']} ({h['handoff_type']})\n\n{_truncate(excerpt, 400)}")
            source_refs.append(h["rel_path"])
        sections.append("## Recent Session Handoff / Latest Plan-Process\n\n" + "\n\n".join(excerpt_parts))

    orphan_plans = [p for p in plans if p["session_id"] not in paired_ids]
    if orphan_plans:
        latest_orphan = max(orphan_plans, key=lambda p: p["created_at"])
        sections.append(
            "## ⚠ 미짝 Plan 경고\n\n"
            f"'{latest_orphan['title']}'에 대응하는 Process가 없습니다. 컴팩팅/종료 전에 "
            "write_session_process를 호출했는지 확인하세요."
        )

    next_actions: list[str] = []
    if processes:
        next_excerpt = _excerpt_sections(processes[0]["body"], ("Next Session",))
        if next_excerpt:
            next_actions.append(next_excerpt)
    if next_actions:
        sections.append("## Suggested Next Actions\n\n" + _truncate("\n\n".join(next_actions)))

    return ProjectBriefing(
        project=resolved_project,
        matched=True,
        candidates=[],
        text="\n\n".join(sections),
        source_refs=source_refs,
    )


# ── 기록 ─────────────────────────────────────────────────────────────────────


def record_note(kind: str, title: str, body: str, project: str = "", settings: Settings | None = None) -> CandidateWriteResult:
    """작업 중 결정/지식/아이디어를 60_Candidates/에 후보로 기록한다.

    허용 kind: knowledge, decision, blog_idea, career_bullet. memory_patch와
    session_handoff은 각각 record_agent_improvement/write_work_plan/write_session_process
    전용이다.
    """
    normalized_kind = kind.strip().lower().replace("-", "_")
    if normalized_kind not in _RECORD_NOTE_KINDS:
        raise VaultScopeError(f"record_note는 다음 kind만 허용합니다: {sorted(_RECORD_NOTE_KINDS)}")
    vault_dir = _vault_dir(settings)
    writer = CandidateWriter(vault_dir)
    spec = CandidateSpec(kind=normalized_kind, title=title, body=body, project=project)
    return writer.write(spec)


def record_agent_improvement(
    project: str,
    issue: str,
    improvement: str,
    evidence: str = "",
    *,
    scope: str = "project",
    confidence: str = "unspecified",
    requires_user_review: bool = True,
    settings: Settings | None = None,
) -> CandidateWriteResult:
    """반복 실수/개선할 작업 방식/프로젝트별 주의사항을 MemoryPatch 후보로 기록한다."""
    vault_dir = _vault_dir(settings)
    writer = CandidateWriter(vault_dir)
    title = f"{project} — {issue}" if project.strip() else issue
    body = f"## 이슈\n\n{issue}\n\n## 개선\n\n{improvement}\n"
    spec = CandidateSpec(
        kind="memory_patch",
        title=title,
        body=body,
        project=project,
        evidence=evidence,
        scope=scope,
        confidence=confidence,
        requires_user_review=requires_user_review,
    )
    return writer.write(spec)


def write_work_plan(
    project: str,
    goal: str,
    context_read: str,
    scope: str,
    approach: str,
    risks: str,
    session_id: str,
    settings: Settings | None = None,
) -> CandidateWriteResult:
    """작업 시작 전 Plan을 session_handoff candidate로 기록한다."""
    vault_dir = _vault_dir(settings)
    writer = CandidateWriter(vault_dir)
    date = datetime.now().strftime("%Y-%m-%d")
    title = f"Plan — {project or '미지정'} — {date} — {session_id[:8]}"
    body = (
        "# Plan\n\n"
        f"## Goal\n\n{goal}\n\n"
        f"## Context Read\n\n{context_read}\n\n"
        f"## Scope\n\n{scope}\n\n"
        f"## Approach\n\n{approach}\n\n"
        f"## Risks\n\n{risks}\n"
    )
    spec = CandidateSpec(
        kind="session_handoff",
        title=title,
        body=body,
        project=project,
        handoff_type="plan",
        session_id=session_id,
    )
    return writer.write(spec)


def _render_process_body(
    what_changed: str,
    files_touched: str,
    decisions: dict,
    implementation_trace: str,
    notes: dict,
    docs_update_candidates: str,
    next_session: str,
    recovery: dict,
) -> str:
    questions = recovery.get("questions") or []
    if isinstance(questions, str):
        questions = [q.strip() for q in questions.splitlines() if q.strip()]
    related = recovery.get("related_candidates") or []
    if isinstance(related, str):
        related = [r.strip() for r in related.splitlines() if r.strip()]

    lines = [
        "# Process",
        "",
        "## What Changed",
        what_changed.strip() or "- ",
        "",
        "## Files Touched",
        files_touched.strip() or "- ",
        "",
        "## Project Decisions",
        f"- 결정: {decisions.get('decision', '')}",
        f"- 이유: {decisions.get('reason', '')}",
        f"- 고려한 대안: {decisions.get('alternatives', '')}",
        f"- 최종 판단자: {decisions.get('final_judge', 'unresolved')}",
        "",
        "## Implementation Trace",
        implementation_trace.strip() or "- ",
        "",
        "## Agent Execution Notes",
        f"- 막힌 점: {notes.get('blocked', '')}",
        f"- 에이전트가 한 실수: {notes.get('mistakes', '')}",
        f"- 다음부터 먼저 확인할 점: {notes.get('next_checks', '')}",
        f"- 더 나은 작업 방식: {notes.get('better_approach', '')}",
        f"- evidence: {notes.get('evidence', '')}",
        f"- scope: {notes.get('scope', 'project')}",
        f"- confidence: {notes.get('confidence', 'unspecified')}",
        f"- requires_user_review: {notes.get('requires_user_review', True)}",
        "",
        "## Docs Update Candidates",
        docs_update_candidates.strip() or "- ",
        "",
        "## Next Session",
        next_session.strip() or "- ",
        "",
        "## Learning Recovery",
        "### AI가 주도적으로 처리한 부분",
        f"- {recovery.get('ai_led', '')}",
        "",
        "### 내가 아직 완전히 이해하지 못한 개념",
        f"- {recovery.get('unclear_concepts', '')}",
        "",
        "### 다음에 직접 설명해봐야 할 질문",
    ]
    lines += [f"{i + 1}. {q}" for i, q in enumerate(questions)] if questions else ["1. "]
    lines += ["", "### 관련 Vault 후보"]
    lines += [f"- {r}" for r in related] if related else ["- "]
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_session_process(
    project: str,
    what_changed: str,
    files_touched: str,
    project_decisions: dict,
    implementation_trace: str,
    agent_execution_notes: dict,
    docs_update_candidates: str,
    next_session: str,
    learning_recovery: dict,
    session_id: str,
    settings: Settings | None = None,
) -> SessionProcessResult:
    """컴팩팅 전/세션 종료 시 Process를 기록하고 10_Worklog/Sessions/에 이중 기록한다.

    project_decisions/agent_execution_notes에 실질 내용이 있으면 Decisions/MemoryPatches
    candidate로 분리 생성한다. 서버 재시작 등으로 이 session_id의 Plan이 없으면 같은
    프로젝트의 최근 미짝 Plan에 재귀속한다.
    """
    vault_dir = _vault_dir(settings)
    writer = CandidateWriter(vault_dir)
    capture_agent = CaptureAgent(settings=settings)

    session_id = _reattach_orphan_plan_if_needed(vault_dir, project, session_id)

    decisions = project_decisions or {}
    notes = agent_execution_notes or {}
    recovery = learning_recovery or {}

    body = _render_process_body(
        what_changed=what_changed,
        files_touched=files_touched,
        decisions=decisions,
        implementation_trace=implementation_trace,
        notes=notes,
        docs_update_candidates=docs_update_candidates,
        next_session=next_session,
        recovery=recovery,
    )

    date = datetime.now().strftime("%Y-%m-%d")
    title = f"Process — {project or '미지정'} — {date} — {session_id[:8]}"
    process_result = writer.write(
        CandidateSpec(
            kind="session_handoff",
            title=title,
            body=body,
            project=project,
            handoff_type="process",
            session_id=session_id,
        )
    )

    worklog_result: CaptureResult = capture_agent.capture_session(
        project=project,
        summary_text=body,
        session_id=session_id,
        from_agent=True,
        source="mcp_session_process",
        # Decision/MemoryPatch 분리를 이미 이 함수가 수행했으므로 nightly distill이
        # 같은 내용을 다시 LLM에 넣어 중복 후보를 만들지 않도록 재증류 대상에서 뺀다.
        needs_distill=False,
    )

    decision_result: CandidateWriteResult | None = None
    decision_text = str(decisions.get("decision", "")).strip()
    final_judge = str(decisions.get("final_judge", "")).strip().lower()
    if decision_text and final_judge not in ("", "unresolved"):
        decision_body = (
            f"## 결정\n\n{decision_text}\n\n"
            f"## 이유\n\n{decisions.get('reason', '')}\n\n"
            f"## 고려한 대안\n\n{decisions.get('alternatives', '')}\n\n"
            f"## 최종 판단자\n\n{decisions.get('final_judge', '')}\n"
        )
        decision_result = writer.write(
            CandidateSpec(
                kind="decision",
                title=f"{project or '미지정'} — {decision_text[:60]}",
                body=decision_body,
                project=project,
                source_refs=[process_result.rel_path],
            )
        )

    memory_patch_result: CandidateWriteResult | None = None
    has_notes_content = any(str(notes.get(k, "")).strip() for k in ("blocked", "mistakes", "next_checks", "better_approach"))
    if has_notes_content:
        patch_body = (
            f"## 막힌 점\n\n{notes.get('blocked', '')}\n\n"
            f"## 에이전트가 한 실수\n\n{notes.get('mistakes', '')}\n\n"
            f"## 다음부터 먼저 확인할 점\n\n{notes.get('next_checks', '')}\n\n"
            f"## 더 나은 작업 방식\n\n{notes.get('better_approach', '')}\n"
        )
        memory_patch_result = writer.write(
            CandidateSpec(
                kind="memory_patch",
                title=f"{project or '미지정'} — Agent Execution Notes — {date}",
                body=patch_body,
                project=project,
                evidence=str(notes.get("evidence", "")),
                scope=str(notes.get("scope", "project")),
                confidence=str(notes.get("confidence", "unspecified")),
                requires_user_review=bool(notes.get("requires_user_review", True)),
                source_refs=[process_result.rel_path],
            ),
            # 제목이 "{project} — Agent Execution Notes — {date}" 고정 형식이라 날짜만
            # 다른 이전 세션 제목과 유사도가 임계값을 넘는다. dedup을 켜두면 write()가
            # 새 본문을 쓰지 않고 기존 파일 경로만 반환해 이번 세션의 노트가 유실된다.
            dedup=False,
        )

    return SessionProcessResult(
        session_id=session_id,
        process=process_result,
        worklog_rel_path=worklog_result.rel_path,
        decision=decision_result,
        memory_patch=memory_patch_result,
    )
