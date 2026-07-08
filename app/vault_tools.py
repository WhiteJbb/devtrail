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
from app.services.candidate_writer import (
    SESSION_HANDOFF_DIR,
    CandidateSpec,
    CandidateWriter,
    CandidateWriteResult,
    handoff_project_dir,
)
from app.services.review_question import HEADING_AI_LED, HEADING_QUESTIONS, HEADING_RELATED, HEADING_UNCLEAR
from app.services.wiki_service import WikiService

_STABLE_PREFIXES = ("20_Knowledge/", "30_Projects/", "40_AgentMemory/")
_CANDIDATE_PREFIX = "60_Candidates/"
_ALLOWED_READ_PREFIXES = _STABLE_PREFIXES + (_CANDIDATE_PREFIX,)

_RECORD_NOTE_KINDS = {"knowledge", "decision", "blog_idea", "career_bullet"}

_SECTION_MAX_CHARS = 1200
_CONTEXT_MAX_CHARS = 600  # 인덱스 우선: 요약만 주입하고 전문은 read_note로 당겨 읽게 한다
_CONTEXT_STALE_DAYS = 30  # Context.md updated_at이 이보다 오래되면 briefing에 경고
_RECENT_HANDOFF_LIMIT = 3
_RECENT_DECISION_LIMIT = 5
# 세션마다 달라지는 운영 메모리만 briefing 본문에 넣는다. 나머지(Profile/ProjectMap/
# WritingStyle/CareerContext)는 정적이라 참고 노트(read_note) 목록으로만 안내한다 —
# 7개 파일 전체를 이어붙여 앞에서 자르면 목록 맨 앞의 Profile이 예산을 다 쓰고
# 정작 OpenLoops/Lessons는 briefing에 도달하지 못한다.
_MEMORY_PRIORITY_FILES = (
    "40_AgentMemory/01_CurrentFocus.md",
    "40_AgentMemory/05_OpenLoops.md",
    "40_AgentMemory/06_Lessons.md",
)
# apply-memory-patch가 끝에 append하는 파일 — briefing에서 tail을 남겨야 최신이 보인다
_MEMORY_APPEND_FILES = (
    "40_AgentMemory/05_OpenLoops.md",
    "40_AgentMemory/06_Lessons.md",
)
_MEMORY_FILE_MAX_CHARS = 700
_MEMORY_STALE_DAYS = 30  # CurrentFocus/OpenLoops가 이보다 오래되면 briefing에 경고
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


def _truncate_tail(text: str, limit: int = _SECTION_MAX_CHARS) -> str:
    """앞이 아니라 뒤를 남기는 truncate — append형 파일(OpenLoops/Lessons)용.

    이 파일들은 apply-memory-patch가 끝에 붙이는 구조라 최신 내용이 항상 꼬리에
    있다. head 절단이면 파일이 한도를 넘는 순간 최신 교훈이 영영 안 보인다.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    return "...(앞부분 생략)\n" + text[-limit:].lstrip()


def _render_memory_briefing(agent_memory) -> str:
    """운영 메모리(CurrentFocus/OpenLoops/Lessons)를 파일별 예산으로 렌더한다.

    append형 파일(OpenLoops/Lessons)은 최신 내용이 꼬리에 쌓이므로 tail을 남긴다.
    사람이 위에서부터 관리하는 CurrentFocus는 head를 남긴다.
    """
    parts: list[str] = []
    blocks = {b.rel_path: b for b in agent_memory.blocks}
    for rel in _MEMORY_PRIORITY_FILES:
        block = blocks.get(rel)
        if block is None or not block.body.strip():
            continue
        cut = _truncate_tail if rel in _MEMORY_APPEND_FILES else _truncate
        parts.append(f"### {block.title}\n\n{cut(block.body, _MEMORY_FILE_MAX_CHARS)}")
    return "\n\n".join(parts)


def _memory_staleness_warning(agent_memory) -> str:
    """CurrentFocus/OpenLoops가 _MEMORY_STALE_DAYS를 넘게 방치됐으면 경고를 반환한다.

    Context.md 신선도 경고와 같은 원칙 — 매 세션 주입되는 메모리는 '작성 시점의
    사실'이므로, 오래된 채로 조용히 주입되는 것을 막는다. 날짜가 없으면 경고하지
    않는다 (오탐 방지).
    """
    stale_lines: list[str] = []
    blocks = {b.rel_path: b for b in agent_memory.blocks}
    for rel in ("40_AgentMemory/01_CurrentFocus.md", "40_AgentMemory/05_OpenLoops.md"):
        block = blocks.get(rel)
        if block is None or not block.updated_at:
            continue
        try:
            updated = datetime.strptime(block.updated_at[:10], "%Y-%m-%d")
        except ValueError:
            continue
        age_days = (datetime.now() - updated).days
        if age_days > _MEMORY_STALE_DAYS:
            stale_lines.append(f"- {block.title}: {age_days}일 전({block.updated_at[:10]}) 마지막 갱신")
    if not stale_lines:
        return ""
    return (
        "## ⚠ AgentMemory 신선도 경고\n\n"
        + "\n".join(stale_lines)
        + "\n\n내용이 여전히 유효한지 확인하고 필요하면 apply-memory-patch로 갱신을 제안하세요."
    )


def _canonicalize_project(vault_dir: Path, project: str) -> str:
    """등록된 ProjectMemory와 대소문자 무시로 일치하면 레지스트리 표기로 치환한다.

    쓰기(project 원본 표기)와 읽기(get_project_briefing의 레지스트리 확정 표기)가
    다른 대소문자/철자로 slug되면 SessionHandoffs 폴더가 갈린다(Linux는 대소문자를
    구분하므로 실제로 분리됨). 항상 같은 표기로 쓰도록 정규화한다.
    """
    if not project.strip():
        return project
    match = ProjectMemoryLoader(vault_dir).load().find(project)
    return match.project if match else project


def _list_session_handoffs(vault_dir: Path, project: str) -> list[dict]:
    """60_Candidates/SessionHandoffs/<project>/의 candidate를 frontmatter와 함께 반환한다."""
    handoff_dir = vault_dir / handoff_project_dir(project)
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
    """body에서 지정된 '## Heading' 섹션만 headings 순서대로 발췌한다.

    문서 순서가 아니라 headings 인자 순서를 따른다 — excerpt는 뒤에서 truncate되므로
    다음 세션에 가장 필요한 섹션(Next Session)을 앞에 둬야 잘려도 덜 아프다.
    """
    lines = body.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            current = heading if heading in headings else None
            if current is not None:
                sections.setdefault(current, []).append(line)
            continue
        if current is not None:
            sections[current].append(line)
    ordered = ["\n".join(sections[h]).strip() for h in headings if h in sections]
    return "\n\n".join(part for part in ordered if part).strip()


def _find_session_handoff(vault_dir: Path, project: str, session_id: str, handoff_type: str) -> dict | None:
    """같은 session_id·handoff_type의 기존 handoff를 찾는다 (재기록 = 갱신 판정용)."""
    for h in _list_session_handoffs(vault_dir, project):
        if h["session_id"] == session_id and h["handoff_type"] == handoff_type:
            return h
    return None


def _rewrite_handoff(vault_dir: Path, rel_path: str, spec: CandidateSpec) -> CandidateWriteResult:
    """기존 handoff 파일의 body를 교체한다 (created_at 보존, updated_at 갱신).

    같은 세션이 Plan/Process를 다시 기록하면 새 파일을 만들지 않고 갱신한다 —
    '(2)' 파일이 쌓이면 briefing의 최근 handoff 창을 같은 세션 산출물이 잠식하고,
    낡은 스냅샷이 최신 기록과 나란히 남는다.
    """
    path = vault_dir / rel_path
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    post.metadata["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    post.content = spec.body.strip() + "\n"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return CandidateWriteResult(spec=spec, path=path, rel_path=rel_path)


def _update_worklog_note(vault_dir: Path, session_id: str, body: str) -> str | None:
    """같은 session_id의 10_Worklog/Sessions 노트 본문을 갱신한다. 없으면 None."""
    sessions_dir = vault_dir / "10_Worklog" / "Sessions"
    if not sessions_dir.exists() or not session_id:
        return None
    for md_path in sorted(sessions_dir.glob("*.md")):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(post.metadata.get("session_id", "")).strip() != session_id:
            continue
        first_line = post.content.strip().splitlines()[0] if post.content.strip() else ""
        title_line = first_line if first_line.startswith("# ") else "# 작업 세션"
        post.metadata["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
        # 재기록으로 본문이 바뀌었으니 distill 대상으로 되살린다 — 이미 distill이 지나간
        # 노트(needs_distill=False)에 새 내용이 들어와도 다시 증류되도록.
        post.metadata["needs_distill"] = True
        post.metadata.setdefault("distill_kinds", ["knowledge", "blog_idea"])
        post.content = f"{title_line}\n\n{body.strip()}\n"
        md_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return str(md_path.relative_to(vault_dir)).replace("\\", "/")
    return None


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
        # ProjectMemory 등록이 없어도 write_work_plan이 이미 SessionHandoffs 폴더를
        # 만들어둔 프로젝트라면 그 폴더명으로 매칭한다 — 그렇지 않으면 등록 없이
        # write_work_plan만 호출된 프로젝트의 handoff가 briefing에 영원히 안 보인다.
        handoffs_root = vault_dir / SESSION_HANDOFF_DIR
        handoff_project_dirs = (
            [d.name for d in handoffs_root.iterdir() if d.is_dir() and d.name != "_Unassigned"]
            if handoffs_root.exists()
            else []
        )
        folder_match = next((d for d in handoff_project_dirs if d.lower() == probe_name.lower()), None)
        if folder_match:
            resolved_project = folder_match
        else:
            registered = [ctx.project for ctx in project_memory.contexts]
            candidates = registered + [d for d in handoff_project_dirs if d not in registered]
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
        sections.append(f"## Current Focus / Open Loops\n\n{_render_memory_briefing(agent_memory)}")
        return ProjectBriefing(
            project=resolved_project, matched=True, candidates=[], text="\n\n".join(sections), source_refs=source_refs
        )

    memory_section = _render_memory_briefing(agent_memory)
    if memory_section:
        sections.append(f"## Current Focus\n\n{memory_section}")

    memory_staleness = _memory_staleness_warning(agent_memory)
    if memory_staleness:
        sections.append(memory_staleness)

    if project_ctx:
        # 인덱스 우선: 요약만 넣고 전문은 필요할 때 read_note로 조회하게 한다 —
        # 매 세션 전체를 밀어넣으면 대부분 안 쓰는 내용이 토큰만 차지한다.
        context_section = _truncate(project_ctx.body, _CONTEXT_MAX_CHARS)
        if len(project_ctx.body.strip()) > _CONTEXT_MAX_CHARS:
            context_section += f"\n\n_전문: read_note(\"{project_ctx.rel_path}\")_"
        sections.append(f"## Project Context\n\n{context_section}")
        source_refs.append(project_ctx.rel_path)

        staleness = _context_staleness_warning(project_ctx.updated_at)
        if staleness:
            sections.append(staleness)

    # 결정 이력은 검토 대기 후보(60_Candidates/Decisions)와 승격된 정본
    # (30_Projects/<P>/Decisions)을 함께 읽는다 — 후보만 읽으면 promote하는 순간
    # briefing에서 결정이 사라져, 검토를 성실히 할수록 컨텍스트를 잃는다.
    decision_entries: list[tuple[float, str, str]] = []

    def _collect_decisions(dir_path: Path, *, project_filter: bool, tag: str) -> None:
        if not dir_path.exists():
            return
        for md_path in dir_path.glob("*.md"):
            try:
                post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if project_filter and str(post.metadata.get("project", "")).strip().lower() != resolved_project.lower():
                continue
            rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
            title = post.metadata.get("title", md_path.stem)
            decision_entries.append((md_path.stat().st_mtime, f"- {title} ({rel}){tag}", rel))

    _collect_decisions(vault_dir / "60_Candidates" / "Decisions", project_filter=True, tag=" — 검토 대기")
    _collect_decisions(vault_dir / "30_Projects" / resolved_project / "Decisions", project_filter=False, tag="")
    decision_entries.sort(key=lambda e: e[0], reverse=True)
    recent_entries = decision_entries[:_RECENT_DECISION_LIMIT]
    source_refs.extend(rel for _, _, rel in recent_entries)
    if recent_entries:
        sections.append("## Recent Decisions\n\n" + _truncate("\n".join(line for _, line, _ in recent_entries)))

    # 미해결 학습 질문 — Learning Recovery 루프를 세션 시작 시점에 노출한다.
    # AI가 답을 대신 말해버리면 학습 회수가 안 되므로 지시문을 함께 넣는다.
    try:
        from app.services.review_question import list_questions

        unanswered = [q for q in list_questions(vault_dir) if not q.answered]
        scoped = [q for q in unanswered if q.project.lower() == resolved_project.lower()] or unanswered
        if scoped:
            question_lines = "\n".join(f"- {q.question} ({q.source_rel_path})" for q in scoped[:3])
            sections.append(
                "## 미해결 학습 질문 (Learning Recovery)\n\n"
                "작업 중 아래 주제를 다루게 되면 답을 대신 설명하지 말고, 사용자가 직접 "
                "설명해보도록 권한다. 사용자가 설명하면 맞는지 확인해주고, 세션 기록의 "
                "해당 질문에 답변이 기록되도록 안내한다.\n\n" + question_lines
            )
    except Exception:
        pass

    plans = [h for h in handoffs if h["handoff_type"] == "plan"]
    processes = [h for h in handoffs if h["handoff_type"] == "process"]
    paired_ids = {p["session_id"] for p in processes}
    recent = handoffs[:_RECENT_HANDOFF_LIMIT]
    if recent:
        excerpt_parts = []
        for h in recent:
            # Next Session을 맨 앞에 — excerpt는 400자에서 잘리므로 다음 세션에
            # 가장 필요한 정보가 먼저 살아남아야 한다 (Goal은 Plan 전용 섹션)
            excerpt = _excerpt_sections(h["body"], ("Next Session", "Goal", "What Changed"))
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

    # 오늘 Plan이 아직 없으면 리마인더 — 사후 "미짝 Plan 경고"의 대칭.
    today = datetime.now().strftime("%Y-%m-%d")
    has_todays_plan = any(p["created_at"][:10] == today for p in plans)
    if not has_todays_plan:
        sections.append(
            "## 리마인더\n\n구현을 시작하기 전에 `write_work_plan`으로 이 세션의 Plan을 먼저 기록하세요."
        )

    # 인덱스 우선: 주입하지 않은 전문은 필요할 때 read_note로 조회
    unique_refs = list(dict.fromkeys(source_refs))
    if unique_refs:
        sections.append(
            "## 참고 노트 (필요 시 read_note로 전문 조회)\n\n"
            + "\n".join(f"- {ref}" for ref in unique_refs)
        )

    return ProjectBriefing(
        project=resolved_project,
        matched=True,
        candidates=[],
        text="\n\n".join(sections),
        source_refs=source_refs,
    )


def _context_staleness_warning(updated_at: str) -> str:
    """Context.md의 updated_at이 _CONTEXT_STALE_DAYS를 넘었으면 경고 섹션을 반환한다.

    메모리는 '작성 시점의 사실'이다 — 오래된 배경으로 조용히 작업하는 것을 막는다.
    updated_at이 없거나 파싱 불가면 경고하지 않는다 (오탐 방지).
    """
    raw = updated_at.strip()
    if not raw:
        return ""
    try:
        updated = datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    age_days = (datetime.now() - updated).days
    if age_days <= _CONTEXT_STALE_DAYS:
        return ""
    return (
        "## ⚠ Context 신선도 경고\n\n"
        f"Context.md가 {age_days}일 전({raw[:10]})에 마지막으로 갱신됐습니다. "
        "배경·목표·제약이 여전히 유효한지 확인하고 필요하면 갱신을 제안하세요."
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
    # 제목은 파일명이 된다 — issue 전문을 그대로 쓰면 Windows 260자 경로 제한에
    # 걸릴 수 있으므로 60자로 자르고, 전문은 본문 '## 이슈'에 남긴다.
    issue_title = " ".join(issue.split())
    if len(issue_title) > 60:
        issue_title = issue_title[:60].rstrip() + "…"
    title = f"{project} — {issue_title}" if project.strip() else issue_title
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
    project = _canonicalize_project(vault_dir, project)
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
    # 같은 세션이 Plan을 다시 쓰면 갱신한다 — '(2)' 파일이 생기면 briefing의
    # 최근 handoff 창을 같은 세션 산출물이 잠식한다.
    existing = _find_session_handoff(vault_dir, project, session_id, "plan")
    if existing:
        return _rewrite_handoff(vault_dir, existing["rel_path"], spec)
    return writer.write(spec)


def _normalize_bullet_items(value) -> list[str]:
    """str/list 값을 불릿 항목 리스트로 정규화한다.

    호출자가 이미 markdown 불릿("- x\n- y")으로 넘겨도 접두를 벗겨 항목만 남긴다 —
    렌더 단계에서 "- "를 다시 붙이므로, 여기서 안 벗기면 "- - x" 이중 불릿이 된다.
    """
    if value is None:
        return []
    if isinstance(value, str):
        items = [l.strip() for l in value.splitlines() if l.strip()]
    else:
        items = [str(v).strip() for v in value if str(v).strip()]
    out: list[str] = []
    for item in items:
        item = re.sub(r"^\d+[.)]\s*", "", item)
        while item[:2] in ("- ", "* "):
            item = item[2:].strip()
        if item and item != "-":
            out.append(item)
    return out


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
    questions = _normalize_bullet_items(recovery.get("questions"))
    related = _normalize_bullet_items(recovery.get("related_candidates"))
    ai_led = _normalize_bullet_items(recovery.get("ai_led"))
    unclear = _normalize_bullet_items(recovery.get("unclear_concepts"))

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
        f"### {HEADING_AI_LED}",
    ]
    lines += [f"- {a}" for a in ai_led] if ai_led else ["- "]
    lines += ["", f"### {HEADING_UNCLEAR}"]
    lines += [f"- {u}" for u in unclear] if unclear else ["- "]
    lines += ["", f"### {HEADING_QUESTIONS}"]
    lines += [f"{i + 1}. {q}" for i, q in enumerate(questions)] if questions else ["1. "]
    lines += ["", f"### {HEADING_RELATED}"]
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
    project = _canonicalize_project(vault_dir, project)
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
    process_spec = CandidateSpec(
        kind="session_handoff",
        title=title,
        body=body,
        project=project,
        handoff_type="process",
        session_id=session_id,
    )
    # 같은 세션이 Process를 다시 쓰면(기록 후 작업이 이어진 경우) 갱신한다 —
    # 안 그러면 낡은 중간 스냅샷과 최신 기록이 나란히 남아 다음 세션 briefing이
    # 이미 끝난 Next Session 항목을 지시한다.
    existing_process = _find_session_handoff(vault_dir, project, session_id, "process")
    if existing_process:
        process_result = _rewrite_handoff(vault_dir, existing_process["rel_path"], process_spec)
        worklog_rel_path = _update_worklog_note(vault_dir, session_id, body)
    else:
        process_result = writer.write(process_spec)
        worklog_rel_path = None

    if worklog_rel_path is None:
        worklog_result: CaptureResult = capture_agent.capture_session(
            project=project,
            summary_text=body,
            session_id=session_id,
            from_agent=True,
            source="mcp_session_process",
            # Decision/MemoryPatch는 이 함수가 구조화 필드에서 직접 추출하므로 distill이
            # 다시 만들면 중복이다. 하지만 knowledge/blog_idea는 여기서 추출하지 않으므로
            # 노트를 통째로 빼면(과거 needs_distill=False) 세션 기록에서 지식 후보가
            # 영원히 나오지 않는다 — distill_kinds로 부분 허용한다.
            needs_distill=True,
            distill_kinds=["knowledge", "blog_idea"],
        )
        worklog_rel_path = worklog_result.rel_path

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
    # Lessons에는 일반화 가능한 "일하는 방식" 교훈만 증류해 보낸다. 막힌 점·실수 같은
    # 세션 한정 사실은 Process 기록에 이미 남아 있고, 통째로 append하면 Lessons가
    # 세션 보일러플레이트로 비대해져 briefing 예산을 낭비한다.
    lesson_lines: list[str] = []
    next_checks = str(notes.get("next_checks", "")).strip()
    better_approach = str(notes.get("better_approach", "")).strip()
    if next_checks:
        lesson_lines.append(f"- ({date}) 다음부터 먼저 확인: {next_checks}")
    if better_approach:
        lesson_lines.append(f"- ({date}) 더 나은 방식: {better_approach}")
    if lesson_lines:
        memory_patch_result = writer.upsert_exact(
            CandidateSpec(
                kind="memory_patch",
                title=f"{project or '미지정'} — Agent Execution Notes — {date}",
                body="\n".join(lesson_lines) + "\n",
                project=project,
                evidence=str(notes.get("evidence", "")),
                scope=str(notes.get("scope", "project")),
                confidence=str(notes.get("confidence", "unspecified")),
                requires_user_review=bool(notes.get("requires_user_review", True)),
                source_refs=[process_result.rel_path],
                # 실행 노트는 "일하는 방식" 교훈이므로 OpenLoops(할 일)가 아니라
                # Lessons에 반영한다 — apply 시 이 파일로 append된다.
                target_file="40_AgentMemory/06_Lessons.md",
            )
            # upsert_exact: 제목이 정확히 같은(=같은 날 같은 프로젝트 재기록) 후보만
            # 갱신하고, 날짜만 다른 이전 세션 후보는 유사도 dedup에 걸리지 않게 한다.
        )

    return SessionProcessResult(
        session_id=session_id,
        process=process_result,
        worklog_rel_path=worklog_rel_path,
        decision=decision_result,
        memory_patch=memory_patch_result,
    )
