"""structured 프로젝트 briefing — `get_project_briefing(structured=True)`.

기본 briefing(app/vault_tools.get_project_briefing)은 그대로 두고, 같은 창(최근 결정 5건·최근 세션 3개)과
같은 정렬 위에 다음을 더한다 (사용법·계약: docs/project-briefing.md):

- 구분: 제약 / 프로젝트 맥락 / 기록된 최근 결과·결정 / 명시적 후속 항목 / 정보 부족·경고·근거.
  분류 근거는 **명시적 제목과 메타데이터뿐**이다 — 내용을 읽고 중요도·해결 여부·현재 상태를 추론하지 않는다.
- 근거 위치: 모든 발췌는 원문 줄 그대로이며 경로·1-based 줄(frontmatter 포함 파일 전체 기준)·source_version을
  단다. `read_note(structured=True, start_line, max_lines, expected_version)`로 그대로 다시 읽힌다.
- 예산: text 본문 상한 TEXT_MAX_CHARS(JSON 전체 크기 상한이 아니다). 줄 중간에서 자르지 않는다.
  예산은 제약부터 배정하고(BUDGET_ORDER), 표시 순서(DISPLAY_ORDER)와 다르다. 못 넣은 구간은 omissions에
  정확한 줄 범위와 이어읽기 인자로 남기고, 제약이 빠지면 critical_omission/requires_read로 드러낸다.

원문은 로더(ProjectMemoryLoader·AgentMemoryLoader)가 아니라 evidence_search.load_doc으로 직접 읽는다 —
로더의 사전 잘림(Context 5000자 등)이 긴 Context 후반의 제약을 숨기지 않게, 그리고 검색과 같은
줄 기준·버전·marker 블록 귀속을 쓰게 하려는 것이다. 로더와 기본 briefing은 바꾸지 않는다.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services import evidence_search
from app.services.evidence_search import load_doc
from app.services.project_identity import ProjectRegistry, ProjectResolution, load_registry, resolve_project
from app.services.source_reader import DEFAULT_MAX_CHARS as READ_MAX_CHARS
from app.services.source_reader import MAX_LINES as READ_MAX_LINES
from app.services.vault_source import VaultNotFoundError, VaultScopeError, resolve_scoped_file

SCHEMA_VERSION = "1"
TEXT_MAX_CHARS = 20000
# 응답 전체(JSON)는 상한이 없다 — 대신 재고 이 크기를 넘으면 경고로 드러낸다 (숨기거나 자르지 않는다)
RESPONSE_WARN_CHARS = 60000
STALE_DAYS = 30  # 기본 briefing의 Context·AgentMemory 신선도 경고와 같은 값

DISPLAY_ORDER = ("constraints", "context", "recent", "follow_ups", "gaps")
SECTION_TITLES = {
    "constraints": "제약",
    "context": "프로젝트 맥락",
    "recent": "기록된 최근 결과·결정",
    "follow_ups": "명시적 후속 항목",
    "gaps": "정보 부족·경고·근거",
}
# 예산 배정 순서 (확정 설계 #7): 제약 → 프로젝트 맥락 → 명시된 후속 항목 → 최근 결과·결정.
# 표시 순서(DISPLAY_ORDER)와 다르다 — 후속 항목은 맥락 뒤에 표시되지만 최근 결과·결정보다 먼저 예산을 받는다.
# 고정부(머리말·상태 줄·세션/결정 목록 줄·후속 기록 위치 목록·gaps·경고·출처 목록)는 text 상한 안에서 먼저 잡히지만,
# 발췌 본문은 미리 잡는 자리 없이 이 순서대로만 배정된다. 맥락 안에서는 Context.md 절 → CurrentFocus → Lessons → 공통
# OpenLoops, 최근 결과·결정 안에서는 기존 구현의 결정 → What Changed → Plan Goal 순서를 유지한다(설계가 하위 순서를 정하지 않음).
BUDGET_ORDER = (
    "constraint",
    "context_section", "current_focus", "lessons", "common_open_loops",
    "next_session", "project_open_loops",
    "decision", "session_result", "plan_goal",
)
# 예산 단계(설계 #7의 네 단계)와 BUDGET_ORDER 묶음의 대응. 응답에는 budget_order만 싣는다(같은 정보를 두 번 싣지 않는다)
BUDGET_STAGES = (
    ("constraints", ("constraint",)),
    ("context", ("context_section", "current_focus", "lessons", "common_open_loops")),
    ("follow_ups", ("next_session", "project_open_loops")),
    ("recent", ("decision", "session_result", "plan_goal")),
)
# 묶음별 본문 상한(발췌 줄 글자 수). None은 전체 예산만 적용. 기본 briefing의 값에서 가져왔다:
# Context 5000자·CurrentFocus 2000자(앞)·OpenLoops/Lessons 6000자(뒤)·최신 Process 1200자.
GROUP_CAPS: dict[str, int | None] = {
    "constraint": None,
    "next_session": None,
    "project_open_loops": 6000,
    "decision": None,
    "session_result": None,
    "plan_goal": None,
    "context_section": 6000,
    "current_focus": 2000,
    "lessons": 6000,
    "common_open_loops": 2000,
}
ITEM_CAPS: dict[str, int | None] = {
    "constraint": None,
    "next_session": 1500,
    "project_open_loops": None,
    "decision": 600,
    "session_result": 1200,
    "plan_goal": 400,
    "context_section": None,
    "current_focus": None,
    "lessons": None,
    "common_open_loops": None,
}
# 꼬리부터 배정하는 묶음 — append형 파일이라 최신 블록이 뒤에 있다 (기본 briefing의 tail 절단과 같은 이유)
_TAIL_GROUPS = frozenset({"lessons", "common_open_loops"})
_RECENT_DECISIONS = 5  # 기본 briefing과 같은 창
_GAPS_TEXT_CAP = 20
_FIELD_CHARS = 200  # 본문 고정부에 싣는 문서 유래 문자열(제목·session_id 등) 상한

_MEMORY_FILES = {
    "current_focus": "40_AgentMemory/01_CurrentFocus.md",
    "open_loops": "40_AgentMemory/05_OpenLoops.md",
    "lessons": "40_AgentMemory/06_Lessons.md",
}

# 알려진 빈 틀 — init-project·init-vault·write_session_process가 만드는 자리표시 줄. 이 목록에 없는 줄은 지우지 않는다.
_SCAFFOLD_LINES = frozenset({
    "> 이 파일은 `get_project_briefing`이 세션 시작 시 자동 주입하는 프로젝트 정본 컨텍스트다.",
    "> 배경·목표·제약이 바뀔 때마다 갱신한다.",
    "_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_",
    "_Fill this note with durable context that future agents should know._",
})
_EMPTY_BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])$")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
# 제목만 본다. 이 단어가 없는 제목 아래의 제약성 문장은 "맥락"으로 남기고, 제약으로 승격하지 않는다.
_CONSTRAINT_HEADING_RE = re.compile(
    r"제약|원칙|규칙|금지|불변식|(?<![a-z])(?:constraints?|principles?|rules?|guardrails?|invariants?)(?![a-z])",
    re.IGNORECASE,
)
# 명시적 "없음"으로 인정하는 내용 — 이 값 하나만 적힌 경우만. "없음 — 단 X 확인" 같은 문장은 항목으로 본다.
_EXPLICIT_NONE = frozenset({"없음", "없다", "해당 없음", "none", "n/a", "na"})
_DECISION_HEADINGS = frozenset({"결정", "decision"})


# ── 내부 타입 ────────────────────────────────────────────────────────────────


@dataclass
class _Item:
    id: str
    section: str  # constraints | context | recent | follow_ups
    group: str  # BUDGET_ORDER의 한 값
    label: str
    doc: Any  # evidence_search._Doc
    span: tuple[int, int]  # 이 항목이 덮는 원문 줄 범위 (제목 줄 포함, 1-based)
    candidates: list[int]  # 정리 후 보여줄 후보 줄 번호 (오름차순)
    cleaned: list[tuple[int, str]]
    scope: str
    project: str
    extra: dict[str, Any] = field(default_factory=dict)
    shown: list[int] = field(default_factory=list)
    omission: dict[str, Any] | None = None
    stub: bool = False
    skipped: list[int] = field(default_factory=list)  # 원문 읽기 상한을 넘어 발췌하지 않고 건너뛴 줄(한 줄 안내만 낸다)
    tail: bool = False  # 뒤쪽 줄부터 넣었다 — 생략은 앞쪽 구간이고 본문에서 발췌 앞에 붙는다  # 전부 생략됐고 본문에 한 줄 안내를 냈다

    @property
    def lines(self) -> list[str]:
        return self.doc.source.lines


@dataclass
class _Build:
    vault_dir: Path
    project: str
    reg: ProjectRegistry
    now: datetime
    items: list[_Item] = field(default_factory=list)
    docs: dict[str, Any] = field(default_factory=dict)  # rel → _Doc (응답 sources 순서 = 처음 읽은 순서)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    partial: bool = False
    fixed: dict[str, list[str]] = field(default_factory=dict)  # 섹션별 고정 안내 줄 (예산 전에 잡는다)
    excluded: dict[str, int] = field(default_factory=dict)
    states: dict[str, Any] = field(default_factory=dict)
    follow_sources: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)  # 소속 검증에 실패한 문서 rel → 사유 (내용 유래 값을 싣지 않는다)
    _seq: int = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    def gap(self, code: str, message: str, **extra: Any) -> None:
        self.gaps.append({"code": code, "message": message, **extra})

    def warn(self, code: str, message: str, **extra: Any) -> None:
        self.warnings.append({"code": code, "message": message, **extra})

    def load(self, rel: str) -> Any | None:
        """read_scope·실제 경로 검증(read_note와 같은 경계)을 거쳐 문서를 읽는다. 없으면 None, 못 읽으면 partial."""
        if rel in self.docs:
            return self.docs[rel]
        try:
            normalized, path = resolve_scoped_file(self.vault_dir, rel)
        except VaultNotFoundError:
            return None
        except VaultScopeError as exc:
            self.partial = True
            self.warn("scope_violation", str(exc), path=rel)
            return None
        except OSError as exc:  # 권한 없는 폴더 안 경로의 stat 등 — briefing 전체를 멈추지 않고 읽기 실패로 드러낸다
            self.partial = True
            self.warn("read_failed", f"경로를 확인하지 못했습니다: {exc.strerror or exc}", path=rel)
            return None
        try:
            doc = load_doc(self.vault_dir, normalized, path, self.reg)
        except OSError as exc:
            self.partial = True
            self.warn("read_failed", f"파일을 읽지 못했습니다: {exc.strerror or exc}", path=rel)
            return None
        self.docs[normalized] = doc  # 문서 경고는 소속 검증 뒤 사용한 문서에만 붙인다 (build 끝)
        return doc

    def reject(self, rel: str, reason: str) -> None:
        self.rejected[rel] = reason


# ── 줄 단위 도구 ─────────────────────────────────────────────────────────────


def _heading(text: str) -> tuple[int, str] | None:
    m = _HEADING_RE.match(text)
    return (len(m.group(1)), m.group(2).strip()) if m else None


def _norm(text: str) -> str:
    return " ".join(text.replace("—", "-").split()).casefold()


def _fence_map(lines: list[str], start: int, end: int) -> tuple[set[int], int | None]:
    """[start, end]에서 코드 블록에 속한 줄(여닫는 펜스 줄 포함)과, 닫히지 않은 블록의 여는 줄 번호.

    CommonMark 펜스 규칙을 따른다: 여는 펜스는 들여쓰기 0~3칸에 ` 또는 ~ 3개 이상(` 펜스의 정보 문자열에는 `가 없어야
    한다). 닫는 펜스는 **같은 문자**로 **여는 길이 이상**, 뒤에 공백 말고는 없어야 한다. 종류·길이를 보지 않고 펜스마다
    상태를 뒤집으면 `~~~markdown` 블록 안의 단독 ``` 줄 때문에 블록 밖의 실제 제목(제약 절 포함)을 코드로 오인한다.
    제목 탐지·정리·미종료 판정이 모두 이 함수를 쓴다.
    """
    fenced: set[int] = set()
    char = ""
    length = 0
    opened: int | None = None
    for n in range(start, end + 1):
        text = lines[n - 1]
        if not char:
            m = _FENCE_OPEN_RE.match(text)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                char, length, opened = m.group(1)[0], len(m.group(1)), n
                fenced.add(n)
            continue
        fenced.add(n)
        m = _FENCE_CLOSE_RE.match(text)
        if m and m.group(1)[0] == char and len(m.group(1)) >= length:
            char, length, opened = "", 0, None
    return fenced, opened


def _headings(lines: list[str], start: int, end: int) -> list[tuple[int, int, str]]:
    """[start, end] 안의 제목 줄 (줄 번호, 단계, 제목). 코드 블록 안 '#' 줄은 제목이 아니다."""
    out: list[tuple[int, int, str]] = []
    fenced, _ = _fence_map(lines, start, end)
    for n in range(start, end + 1):
        if n in fenced:
            continue
        text = lines[n - 1]
        h = _heading(text)
        if h:
            out.append((n, h[0], h[1]))
    return out


def _clean(lines: list[str], start: int, end: int, drop_titles: set[str]) -> tuple[list[int], list[tuple[int, str]]]:
    """[start, end]에서 보여줄 줄과 정리한 줄(줄, 이유). 줄 내용은 바꾸지 않고 줄을 빼기만 한다 — 번호가 그대로다.

    정리 대상은 알려진 것뿐이다: memory marker 줄, 알려진 빈 틀 줄·빈 불릿, 이미 항목 이름으로 드러난 반복 제목,
    내용 없이 제목만 남은 절. 그 밖의 줄(모르는 제목 포함)은 남긴다.
    """
    keep: list[int] = []
    cleaned: list[tuple[int, str]] = []
    fenced, _ = _fence_map(lines, start, end)  # 코드 블록 안 줄 — 제목·빈 틀로 보지 않는다
    for n in range(start, end + 1):
        text = lines[n - 1]
        s = text.strip()
        if n in fenced:
            keep.append(n)
            continue
        if text.startswith(evidence_search._MARKER_PREFIX):
            cleaned.append((n, "memory_marker"))
            continue
        if s in _SCAFFOLD_LINES or _EMPTY_BULLET_RE.match(s):
            cleaned.append((n, "empty_scaffolding"))
            continue
        h = _heading(text)
        if h and _norm(h[1]) in drop_titles:
            cleaned.append((n, "repeated_title"))
            continue
        keep.append(n)
    # 내용 없이 제목만 남은 절 — 같거나 높은 단계 제목 전까지 내용 줄이 없으면 그 제목도 뺀다
    heads = {n: h for n in keep if n not in fenced and (h := _heading(lines[n - 1]))}
    drop: set[int] = set()
    for i, n in enumerate(keep):
        if n not in heads:
            continue
        level = heads[n][0]
        has_content = False
        for m in keep[i + 1:]:
            if m in heads:
                if heads[m][0] <= level:
                    break
                continue
            if lines[m - 1].strip():
                has_content = True
                break
        if not has_content:
            drop.add(n)
    if drop:
        cleaned.extend((n, "empty_section") for n in sorted(drop))
        keep = [n for n in keep if n not in drop]
    # 구간 가장자리의 빈 줄은 뺀다 (번호가 바뀌지 않는다 — 보고하지 않는 공백 정리)
    out: list[int] = []
    for seg in _segments(keep):
        s, e = seg
        while s <= e and not lines[s - 1].strip():
            s += 1
        while e >= s and not lines[e - 1].strip():
            e -= 1
        out.extend(range(s, e + 1))
    cleaned.sort()
    return out, cleaned


def _segments(nums: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def _has_content(lines: list[str], nums: list[int]) -> bool:
    return any(lines[n - 1].strip() and not _heading(lines[n - 1]) for n in nums)


def _explicit_none(lines: list[str], nums: list[int]) -> bool:
    content = [lines[n - 1].strip() for n in nums if lines[n - 1].strip() and not _heading(lines[n - 1])]
    if len(content) != 1:
        return False
    text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", content[0]).strip().rstrip(".").strip()
    return text.casefold() in _EXPLICIT_NONE


def _sections_named(doc: Any, names: set[str], level: int = 2) -> list[tuple[int, int]]:
    """'## 이름' 절들 (제목 줄, 절 끝 줄). 절은 같거나 높은 단계의 다음 제목 전까지 — 기본 briefing의 excerpt와 같은 경계."""
    lines = doc.source.lines
    total = doc.source.total_lines
    heads = _headings(lines, doc.body_start, total)
    out: list[tuple[int, int]] = []
    for i, (n, lv, text) in enumerate(heads):
        if lv != level or _norm(text) not in names:
            continue
        end = next((m - 1 for m, lv2, _ in heads[i + 1:] if lv2 <= level), total)
        out.append((n, end))
    return out


def _time_of(doc: Any, keys: tuple[str, ...]) -> dict[str, str]:
    for key in keys:
        value = evidence_search._str_meta(doc.meta, key)
        if value:
            return {"value": value, "source": f"meta:{key}"}
    return {"value": "", "source": "none"}


def _days_old(value: str, now: datetime) -> int | None:
    try:
        return (now - datetime.strptime(value.strip()[:10], "%Y-%m-%d")).days
    except ValueError:
        return None


# ── 항목 수집 ────────────────────────────────────────────────────────────────


def _add_item(b: _Build, section: str, group: str, label: str, doc: Any, span: tuple[int, int],
              drop_titles: set[str], scope: str, **extra: Any) -> _Item:
    keep, cleaned = _clean(doc.source.lines, span[0], span[1], drop_titles)
    item = _Item(id=b.next_id({"constraints": "c", "context": "x", "recent": "r", "follow_ups": "f"}[section]),
                 section=section, group=group, label=evidence_search._clip(label, _FIELD_CHARS), doc=doc, span=span,
                 candidates=keep, cleaned=cleaned,
                 scope=scope, project=b.project if scope == "project" else "", extra=extra)
    b.items.append(item)
    return item


def _safe_title(doc: Any, project: str) -> str:
    """응답에 싣는 문서 제목. marker 블록으로 나뉜 문서(40_AgentMemory)는 본문 '# ' 제목 줄이 이 프로젝트·공통 블록에
    있을 때만 그 제목을 쓰고, 다른 프로젝트·소속 불명 블록에 있으면 파일명으로 대체한다 — 근거 검색(evidence_search._score)과
    같은 규칙. 본문만 블록으로 거르고 제목은 문서 전체 값을 쓰면 다른 프로젝트 블록의 제목이 섞인다."""
    if doc.has_markers and doc.title_line:
        key = project.casefold()
        allowed = [u for u in doc.units if u.scope == "common" or (u.scope == "project" and u.project.casefold() == key)]
        if not any(u.start <= doc.title_line <= u.end for u in allowed):
            return Path(doc.rel).stem
    return doc.title


def _attributed_to(doc: Any, project: str) -> bool:
    fu = doc.file_unit
    return fu.scope == "project" and fu.project.casefold() == project.casefold()


def _context_rel(reg: ProjectRegistry, project: str) -> str:
    rels = reg.canonical.get(project.casefold(), [])
    return rels[0] if len(rels) == 1 else ""


def _collect_context(b: _Build) -> None:
    rel = _context_rel(b.reg, b.project)
    if not rel:
        blocked = sorted(p for p in b.reg.unreadable if p.startswith("30_Projects/"))
        if blocked:
            # 못 읽은 폴더가 이 프로젝트의 Context.md일 수 있다 — "Context 없음"으로 보고하면 제약 확인 불가가 숨는다
            b.states["constraints"] = "unknown"
            for path in blocked:
                b.gap("context_unverifiable", f"프로젝트 등록부가 {path}를 읽지 못해 이 프로젝트의 Context.md(제약)가 "
                      "그 안에 있는지 확인할 수 없다.", path=f"{path}Context.md", critical=True, unverified=True)
            return
        b.states["constraints"] = "no_context"
        b.gap("no_context", "Context.md가 없다(세션 기록만 있는 프로젝트) — 제약·배경을 확인할 수 없다.")
        return
    doc = b.load(rel)
    if doc is None:
        b.states["constraints"] = "unknown"
        b.gap("context_unreadable", "Context.md를 읽지 못해 제약 존재 여부를 확인할 수 없다.", path=rel, critical=True)
        return
    lines = doc.source.lines
    total = doc.source.total_lines
    drop = {_norm(_safe_title(doc, b.project)), _norm(b.project), _norm(f"{b.project} - Project Context"), _norm("Project Context")}
    heads = _context_blocks(_headings(lines, doc.body_start, total))
    _, unclosed = _fence_map(lines, doc.body_start, total)
    if unclosed is not None:
        b.gap("unclosed_code_fence", f"Context.md {unclosed}행의 코드 블록이 닫히지 않아 그 뒤 제목(제약 절 포함)을 "
              "제목으로 보지 않았다 — 그 뒤 내용은 맥락 항목의 코드로 남는다.", path=doc.rel, lines=[unclosed, total])
    starts: list[tuple[int, int, str, bool]] = []
    if not heads or heads[0][0] > doc.body_start:
        starts.append((doc.body_start, 0, "", False))  # 첫 제목 앞 머리말
    starts += heads
    constraint_heads = 0
    constraint_items = 0
    for i, (n, level, text, is_constraint) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else total
        if is_constraint:
            constraint_heads += 1
        section, group = ("constraints", "constraint") if is_constraint else ("context", "context_section")
        label = text or "(첫 제목 앞 머리말)"
        keep, _ = _clean(lines, n, end, drop)
        if not _has_content(lines, keep):
            if not any(lines[m - 1].strip() for m in range(n, end + 1)):
                continue  # 빈 줄뿐인 머리말
            # 빈 틀·제목만 있는 절은 항목을 만들지 않고 정리 목록에만 남긴다
            b.states.setdefault("cleaned_sections", []).append({"path": doc.rel, "lines": [n, end], "heading": label,
                                                                "reason": "empty_section"})
            continue
        if is_constraint:
            constraint_items += 1
        _add_item(b, section, group, label, doc, (n, end), drop, "project", heading_line=n if level else None,
                  heading_level=level or None)
    if constraint_items:
        b.states["constraints"] = "items"
    elif constraint_heads:
        b.states["constraints"] = "heading_empty"
        b.gap("constraint_section_empty", "Context.md에 제약 제목 절은 있지만 내용이 비어 있다(빈 틀).", path=doc.rel)
    else:
        b.states["constraints"] = "none_found"
        b.gap("no_constraint_heading",
              "Context.md에 제약 제목(제약·원칙·규칙·금지·불변식·constraints 등) 절이 없다. 다른 제목 아래 제약성 문장이 "
              "있는지는 판정하지 않았다 — 맥락 항목을 읽어 확인한다.", path=doc.rel)
    updated = evidence_search._str_meta(doc.meta, "updated_at") or ""
    age = _days_old(updated, b.now) if updated else None
    if age is not None and age > STALE_DAYS:
        b.gap("context_stale", f"Context.md가 {age}일 전({updated[:10]})에 마지막으로 갱신됐다 — 발췌는 그 시점의 기록이다.",
              path=doc.rel)


def _context_blocks(heads: list[tuple[int, int, str]]) -> list[tuple[int, int, str, bool]]:
    """Context.md 제목들(코드 블록 밖, 모든 단계)로 항목 경계와 제약 여부를 정한다. (줄, 단계, 제목, 제약 여부).

    제약 여부는 **모든 제목**의 계층으로 계산한다 — 자기 제목에 제약 단어가 있거나 상위 제목 중 하나가 제약이면 제약이다.
    상위는 자기보다 낮은 단계 번호의 가장 가까운 앞 제목들이다(같거나 깊은 단계 제목이 나오면 그 범위가 끝난다).
    항목 경계는 1~3단계 제목, 그리고 앞 줄과 제약 여부가 **바뀌는** 제목이다. 그래서 한 항목 안의 줄은 모두 같은 분류다:
    `#### 제약` → `##### 금지` → `##### 세부 설명` → `#### 결과`에서 `#### 결과`는 제약 범위 밖이라 맥락 항목으로 갈린다.
    깊은 제약 절을 맥락 항목 안에 묻지 않아야 맥락 상한에 잘릴 때도 제약 생략으로 드러난다(critical).
    """
    stack: list[tuple[int, bool]] = []
    out: list[tuple[int, int, str, bool]] = []
    current: bool | None = None
    for n, lv, text in heads:
        while stack and stack[-1][0] >= lv:
            stack.pop()
        is_constraint = bool(_CONSTRAINT_HEADING_RE.search(text)) or any(c for _, c in stack)
        stack.append((lv, is_constraint))
        if lv <= 3 or current is None or is_constraint != current:
            out.append((n, lv, text, is_constraint))
            current = is_constraint
    return out


def _memory_pieces(lines: list[str], start: int, end: int) -> list[tuple[int, int, bool, str, int | None]]:
    """메모리 블록 [start, end]를 규칙 절과 나머지로 나눈다. (시작, 끝, 규칙 여부, 규칙 제목, 제목 줄).

    제약 여부는 Context.md와 같은 _context_blocks(제목 계층)로 정한다. 규칙이 아닌 이웃 구간은 하나로 합쳐 블록 단위
    맥락 항목을 유지한다 — 규칙 제목이 없는 블록은 예전과 같은 항목 하나다.
    """
    blocks = _context_blocks(_headings(lines, start, end))
    marks: list[tuple[int, bool, str]] = []
    if not blocks or blocks[0][0] > start:
        marks.append((start, False, ""))
    marks += [(n, rule, text) for n, _, text, rule in blocks]
    out: list[tuple[int, int, bool, str, int | None]] = []
    for i, (n, rule, text) in enumerate(marks):
        e = marks[i + 1][0] - 1 if i + 1 < len(marks) else end
        if out and not rule and not out[-1][2]:
            out[-1] = (out[-1][0], e, False, "", None)
        else:
            out.append((n, e, rule, text if rule else "", n if rule else None))
    return out


def _memory_units(b: _Build, key: str) -> list[tuple[Any, Any]]:
    """AgentMemory 파일 하나의 (문서, 블록) 중 이 프로젝트·공통 블록. 다른 프로젝트·귀속 불명 블록은 넣지 않는다."""
    rel = _MEMORY_FILES[key]
    doc = b.load(rel)
    if doc is None:
        if any(w.get("path") == rel for w in b.warnings):
            b.states[f"{key}_unreadable"] = True
        return []
    out: list[tuple[Any, Any]] = []
    for unit in doc.units:
        if unit.scope == "project":
            if unit.project.casefold() == b.project.casefold():
                out.append((doc, unit))
            else:
                b.excluded["other_project_blocks"] = b.excluded.get("other_project_blocks", 0) + 1
        elif unit.scope == "common":
            out.append((doc, unit))
        else:
            b.excluded["unattributed_blocks"] = b.excluded.get("unattributed_blocks", 0) + 1
            if key == "open_loops":
                # 이 프로젝트 블록일 수 있다 — 후속 항목이 "없다"고 말할 수 없게 출처로 남긴다
                b.follow_sources.append({"source": "project_open_loops", "path": rel, "lines": [unit.start, unit.end],
                                         "state": "unattributed"})
            why = "conflict(후보: " + ", ".join(unit.conflict_with) + ")" if unit.scope == "conflict" else "unknown"
            b.gap("unattributed_block_excluded",
                  f"{rel} {unit.start}-{unit.end}행 블록은 소속이 {why}라 넣지 않았다 — 이 프로젝트 것인지 판정하지 않았다.",
                  path=rel, lines=[unit.start, unit.end])
    if key in ("current_focus", "open_loops"):
        t = _time_of(doc, ("updated_at",))
        value = t["value"] if t["value"] else (doc.time_value if doc.time_source == "file_mtime" else "")
        age = _days_old(value, b.now) if value else None
        if age is not None and age > STALE_DAYS:
            b.gap("memory_stale", f"{_safe_title(doc, b.project)}: {age}일 전({value[:10]}) 마지막 갱신 — 발췌는 그 시점의 기록이다.", path=rel)
    return out


def _collect_memory(b: _Build) -> None:
    project_key = _norm(b.project)
    for key, group in (("current_focus", "current_focus"), ("lessons", "lessons")):
        for doc, unit in _memory_units(b, key):
            title = _safe_title(doc, b.project)
            drop = {_norm(title), project_key, "current focus", "currentfocus", "lessons", "openloops", "open loops"}
            label = title + (" — 프로젝트 블록" if unit.scope == "project" else " — 공통")
            lines = doc.source.lines
            _, unclosed = _fence_map(lines, unit.start, unit.end)
            if unclosed is not None:
                # 펜스는 블록 단위로 본다 — 닫히지 않은 펜스 뒤의 규칙 제목은 제목으로 보지 않으므로 숨기지 않고 알린다
                b.gap("unclosed_code_fence", f"{doc.rel} {unclosed}행의 코드 블록이 이 메모리 블록 안에서 닫히지 않아 그 뒤 "
                      "제목(규칙 절 포함)을 제목으로 보지 않았다 — 그 뒤 내용은 맥락 항목의 코드로 남는다.",
                      path=doc.rel, lines=[unclosed, unit.end])
            # 블록 안의 명시적 규칙 제목 절(제약·원칙·규칙·금지·불변식…)은 제약으로 — Context.md와 같은 제목 계층 규칙.
            # 공통/프로젝트 귀속은 그대로 두고, Context 제약과 충돌해도 어느 쪽을 우선하거나 합치지 않는다(둘 다 싣는다).
            for start, end, is_rule, heading, hline in _memory_pieces(lines, unit.start, unit.end):
                keep, _ = _clean(lines, start, end, drop)
                if not _has_content(lines, keep):
                    continue
                if is_rule:
                    b.states["memory_rule_items"] = b.states.get("memory_rule_items", 0) + 1
                    _add_item(b, "constraints", "constraint", f"{label} · 적용 규칙: {heading}", doc, (start, end), drop,
                              unit.scope, block_evidence=list(unit.evidence), heading_line=hline, memory_rule=True)
                else:
                    _add_item(b, "context", group, label, doc, (start, end), drop, unit.scope,
                              block_evidence=list(unit.evidence))
    open_units = _memory_units(b, "open_loops")
    project_blocks = 0
    for doc, unit in open_units:
        drop = {_norm(_safe_title(doc, b.project)), project_key, "openloops", "open loops"}
        if unit.scope == "project":
            project_blocks += 1
            keep, cleaned = _clean(doc.source.lines, unit.start, unit.end, drop)
            # 빈 틀(빈 불릿)만 남은 블록은 확인 불가, 제목만 있는 블록(항목을 다 지운 상태)은 기록된 항목 없음.
            # 내용이 "없음" 한 줄뿐이면 Next Session과 같이 명시적 없음 — 이 블록에만 해당하고, 원문 발췌는 남긴다.
            state = ("explicit_none" if _explicit_none(doc.source.lines, keep)
                     else "items" if _has_content(doc.source.lines, keep)
                     else "empty" if any(r == "empty_scaffolding" for _, r in cleaned) else "block_empty")
            item = _add_item(b, "follow_ups", "project_open_loops", "프로젝트 Open Loops", doc, (unit.start, unit.end),
                             drop, "project", follow_up_state=state, block_evidence=list(unit.evidence))
            shown_item = state in ("items", "explicit_none")
            b.follow_sources.append({"source": "project_open_loops", "path": doc.rel, "lines": [unit.start, unit.end],
                                     "state": state, "item": item.id if shown_item else None})
            if not shown_item:
                b.items.remove(item)
            if state == "empty":
                b.gap("follow_up_section_empty", "OpenLoops의 이 프로젝트 블록이 빈 틀뿐이다(데이터 부족) — '없음'으로 보지 않았다.",
                      path=doc.rel, lines=[unit.start, unit.end])
        else:
            keep, _ = _clean(doc.source.lines, unit.start, unit.end, drop)
            if _has_content(doc.source.lines, keep):
                # 공통(전역) Open Loops는 이 프로젝트의 후속 항목이 아니다 — 맥락으로만 둔다
                _add_item(b, "context", "common_open_loops", "Open Loops — 공통(이 프로젝트 후속 항목으로 보지 않음)",
                          doc, (unit.start, unit.end), drop, "common", block_evidence=list(unit.evidence))
    if b.states.get("open_loops_unreadable"):
        b.follow_sources.append({"source": "project_open_loops", "path": _MEMORY_FILES["open_loops"], "state": "unreadable"})
    elif not project_blocks:
        b.follow_sources.append({"source": "project_open_loops", "path": _MEMORY_FILES["open_loops"], "state": "no_block"})


_SHARED_DECISIONS_DIR = "60_Candidates/Decisions/"


def _note_unlisted(b: _Build, unlisted: list[dict], follow_source: str = "") -> None:
    """기본 목록이 건너뛴 파일. 읽기 경계 밖 링크(skip_only)는 정책상 제외라 partial이 아니지만 경고로 드러낸다.

    공유 후보 폴더(shared)의 파일은 소속을 확인하지 못했다 — 다른 프로젝트 것일 수 있으므로 파일명을 응답 어디에도 싣지
    않고 사유별 건수만 폴더 경로와 함께 남긴다. 이 프로젝트 것일 수도 있어 partial 판정은 그대로 한다.
    """
    shared: dict[str, int] = {}
    for w in unlisted:
        if not w.get("skip_only"):
            b.partial = True
        if w.get("shared") and not w["path"].endswith("/"):  # 폴더 자체를 못 읽은 경우는 파일명이 없다 — 사유를 그대로 둔다
            shared[w["code"]] = shared.get(w["code"], 0) + 1
            continue
        b.warn(w["code"], w["message"], path=w["path"])
        if follow_source:
            b.follow_sources.append({"source": follow_source, "path": w["path"],
                                     "state": "link_skipped" if w.get("skip_only") else "unreadable"})
    for code, n in shared.items():
        b.warn(code, f"공유 후보 결정 폴더에서 {n}개 파일이 기본 목록에서 빠졌다({code}). 소속(이 프로젝트 여부)을 확인하지 "
               "못해 파일명은 싣지 않는다.", path=_SHARED_DECISIONS_DIR, count=n, attribution="unverified")


def _collect_decisions(b: _Build, decisions: list[dict], unlisted: list[dict]) -> None:
    _note_unlisted(b, unlisted)
    for d in decisions[:_RECENT_DECISIONS]:
        doc = b.load(d["rel_path"])
        # 후보/승격 구분은 경로(폴더)에서 온다. 제목·날짜 같은 내용 유래 값은 읽기 경계·소속을 통과한 뒤에만 싣는다
        entry: dict[str, Any] = {"path": d["rel_path"], "status": d["status"], "item": None}
        b.decisions.append(entry)
        if doc is None:
            entry["state"] = "unreadable"
            continue
        if not _attributed_to(doc, b.project):
            entry["state"] = "attribution_mismatch"
            b.reject(doc.rel, "attribution_mismatch")
            b.gap("attribution_mismatch", "결정 문서의 소속이 이 프로젝트로 확정되지 않아 제목·내용을 넣지 않았다.",
                  path=d["rel_path"])
            continue
        title = evidence_search._clip(_safe_title(doc, b.project), _FIELD_CHARS)
        recorded = _time_of(doc, ("updated_at", "created_at"))
        entry.update(title=title, date=recorded["value"][:10], recorded_at=recorded)
        meta = {"decision_status": d["status"], "recorded_at": recorded}
        spans = _sections_named(doc, _DECISION_HEADINGS)
        if spans:
            n, end = spans[0]
            item = _add_item(b, "recent", "decision", f"결정: {title}", doc, (n, end),
                             {"결정", "decision"}, "project", **meta)
            entry["item"] = item.id
            entry["state"] = "excerpt" if item.candidates else "section_empty"
            if not item.candidates:
                b.items.remove(item)
            continue
        line = _summary_line(doc)
        if line:
            item = _add_item(b, "recent", "decision", f"결정: {title}", doc, (line, line), set(), "project",
                             excerpt_basis="frontmatter summary", **meta)
            entry["item"] = item.id
            entry["state"] = "excerpt"
        else:
            entry["state"] = "no_excerpt"


def _summary_line(doc: Any) -> int:
    """frontmatter의 한 줄짜리 `summary:` 줄 번호. 여러 줄 값이면 0 — 줄 일부를 발췌로 내지 않는다."""
    fm = doc.source.frontmatter_lines
    if not fm or not doc.meta.get("summary"):
        return 0
    lines = doc.source.lines
    for n in range(fm[0] + 1, fm[1]):
        if lines[n - 1].startswith("summary:"):
            nxt = lines[n] if n < fm[1] - 1 else ""
            value = lines[n - 1][len("summary:"):].strip()
            if value and value[0] not in "|>" and not nxt.startswith((" ", "\t")):
                return n
            return 0
    return 0


def _collect_sessions(b: _Build, groups: list[list[dict]], unlisted: list[dict],
                      timestamp: Callable[[dict], float]) -> None:
    """최근 세션 창(기본 briefing과 같은 묶음·순서)의 Plan/Process.

    목록 함수가 읽은 메타데이터는 순서를 정하는 데만 쓴다. session_id·host·agent·제목·유형처럼 응답에 싣는 값은
    읽기 경계·소속 검증을 통과한 문서(load_doc)에서 다시 꺼낸다 — 검증에 실패한 문서는 경로와 상태만 남는다.
    """
    _note_unlisted(b, unlisted, "session_handoff")
    if not groups:
        if unlisted:
            b.gap("sessions_unverifiable", "읽은 SessionHandoff 기록이 없지만 읽지 못한(또는 읽기 경계 밖) 파일·폴더가 있어 "
                  "기록이 없다고 말할 수 없다.")
        else:
            b.gap("no_sessions", "이 프로젝트의 SessionHandoff(Plan/Process) 기록이 없다.")
    meta_of = evidence_search._str_meta
    for rank, group in enumerate(groups, 1):
        ordered = sorted(group, key=timestamp, reverse=True)
        session: dict[str, Any] = {"rank": rank, "session_id": None, "host": None, "agent": None, "handoffs": []}
        b.sessions.append(session)
        valid: list[tuple[Any, dict[str, Any]]] = []
        for h in ordered:
            doc = b.load(h["rel_path"])
            entry: dict[str, Any] = {"path": h["rel_path"], "items": []}
            session["handoffs"].append(entry)
            if doc is None:
                entry["state"] = "unreadable"
                b.follow_sources.append({"source": "session_handoff", "path": h["rel_path"], "state": "unreadable"})
                continue
            if not _attributed_to(doc, b.project):
                entry["state"] = "attribution_mismatch"
                b.reject(doc.rel, "attribution_mismatch")
                b.gap("attribution_mismatch", "세션 기록의 소속이 이 프로젝트로 확정되지 않아 제목·내용을 넣지 않았다.",
                      path=h["rel_path"])
                b.follow_sources.append({"source": "session_handoff", "path": h["rel_path"], "state": "attribution_mismatch"})
                continue
            valid.append((doc, entry))
        kinds = [(meta_of(doc.meta, "handoff_type") or "").casefold() for doc, _ in valid]
        main = next((doc for (doc, _), k in zip(valid, kinds) if k == "process"), valid[0][0] if valid else None)
        if main is not None:
            session.update(session_id=evidence_search._clip(meta_of(main.meta, "session_id") or "", _FIELD_CHARS),
                           host=evidence_search._clip(meta_of(main.meta, "host") or "", 80),
                           agent=evidence_search._clip(meta_of(main.meta, "agent") or "", 80))
        for (doc, entry), kind in zip(valid, kinds):
            recorded = _time_of(doc, ("updated_at", "created_at"))
            entry.update(handoff_type=kind, title=evidence_search._clip(_safe_title(doc, b.project), _FIELD_CHARS), recorded_at=recorded)
            sid = evidence_search._clip(meta_of(doc.meta, "session_id") or "", _FIELD_CHARS)
            meta = {"session_id": sid, "handoff_type": kind, "recorded_at": recorded,
                    "host": evidence_search._clip(meta_of(doc.meta, "host") or "", 80),
                    "agent": evidence_search._clip(meta_of(doc.meta, "agent") or "", 80), "session_rank": rank}
            if kind == "process":
                for name, group_key, section, label in (
                    ("what changed", "session_result", "recent", "What Changed (기록된 결과)"),
                    ("next session", "next_session", "follow_ups", "Next Session"),
                ):
                    spans = _sections_named(doc, {name})
                    if not spans:
                        entry.setdefault("missing", []).append(name)
                        if section == "follow_ups":
                            b.follow_sources.append({"source": "next_session", "path": doc.rel, "state": "missing",
                                                     "session_id": sid})
                            b.gap("follow_up_section_missing", "Process에 Next Session 절이 없다(데이터 부족) — 그 세션의 "
                                  "후속 작업 유무는 판정하지 않았다.", path=doc.rel)
                        continue
                    for n, end in spans:
                        drop = {name}
                        keep, _ = _clean(doc.source.lines, n, end, drop)
                        if section == "follow_ups":
                            state = ("explicit_none" if _explicit_none(doc.source.lines, keep)
                                     else "items" if _has_content(doc.source.lines, keep) else "empty")
                            if state == "empty":
                                b.follow_sources.append({"source": "next_session", "path": doc.rel, "lines": [n, end],
                                                         "state": "empty", "session_id": sid})
                                b.gap("follow_up_section_empty", "Next Session 절이 비었거나 빈 틀뿐이다(데이터 부족) — "
                                      "'없음'으로 보지 않았다.", path=doc.rel, lines=[n, end])
                                continue
                            item = _add_item(b, section, group_key, label, doc, (n, end), drop, "project",
                                             follow_up_state=state, **meta)
                            b.follow_sources.append({"source": "next_session", "path": doc.rel, "lines": [n, end],
                                                     "state": state, "session_id": sid, "item": item.id})
                        else:
                            if not _has_content(doc.source.lines, keep):
                                entry.setdefault("empty", []).append(name)
                                continue
                            item = _add_item(b, section, group_key, label, doc, (n, end), drop, "project", **meta)
                        entry["items"].append(item.id)
            elif kind == "plan":
                for n, end in _sections_named(doc, {"goal"}):
                    keep, _ = _clean(doc.source.lines, n, end, {"goal"})
                    if not _has_content(doc.source.lines, keep):
                        continue
                    item = _add_item(b, "recent", "plan_goal", "Plan Goal (기록 당시 목표 — 완료 여부는 판정하지 않음)",
                                     doc, (n, end), {"goal"}, "project", **meta)
                    entry["items"].append(item.id)
        # 검증을 통과한 문서가 모두 있고 그중 Process가 없을 때만 "Plan만 있다"고 말한다 (실패한 문서가 Process였을 수 있다)
        if valid and len(valid) == len(ordered) and "process" not in kinds:
            path = valid[0][0].rel
            b.follow_sources.append({"source": "next_session", "path": path, "state": "no_process",
                                     "session_id": session["session_id"]})
            b.gap("orphan_plan", f"세션 {session['session_id'] or path}에 Plan만 있고 Process가 없다 — "
                  "그 세션의 결과·후속 항목은 확인할 수 없다.", path=path)


# 후속 항목 판단 표현 — 확정 설계 #7 문구 그대로
FOLLOW_UP_NONE = "이 브리핑에 포함된 기록에는 명시된 후속 작업 없음"
FOLLOW_UP_UNKNOWN = "후속 작업 유무를 확인하지 못한 기록 있음"
# 확인하지 못한 출처의 두 갈래: 읽기 실패·생략(읽기 경계 밖·소속 불명 포함)과 데이터 부족(절 없음·빈 틀·Process 없음)
_UNREAD_STATES = frozenset({"unreadable", "unattributed", "attribution_mismatch", "link_skipped"})
_DATA_GAP_STATES = frozenset({"missing", "empty", "no_process"})


def _follow_up_state(b: _Build) -> dict[str, Any]:
    states = [s["state"] for s in b.follow_sources]
    sessions_checked = [s for s in b.follow_sources if s["source"] in ("next_session", "session_handoff")]
    unread = [s for s in b.follow_sources if s["state"] in _UNREAD_STATES]
    data_gap = [s for s in b.follow_sources if s["state"] in _DATA_GAP_STATES]
    reasons = {"read_failed_or_skipped": len(unread), "partial": b.partial,
               "data_insufficient": len(data_gap), "no_sessions": not sessions_checked}
    detail = []
    if unread:
        detail.append(f"읽기 실패·읽기 경계 밖·소속 불명 {len(unread)}건")
    if b.partial:
        detail.append("일부 기록을 읽지 못함(partial)")
    if data_gap:
        detail.append(f"후속 항목 절 없음·빈 틀·Process 없음(데이터 부족) {len(data_gap)}건")
    if not sessions_checked:
        detail.append("세션 인계 기록 없음(데이터 부족)")
    unknown = bool(unread or data_gap or b.partial or not sessions_checked)
    if "items" in states:
        state = "has_items"
        message = "아래는 기록에 명시된 후속 항목이다(기록 당시). 완료 여부·현재 유효성은 판정하지 않았다."
        if unknown:
            message += f" 단 {FOLLOW_UP_UNKNOWN} — " + ", ".join(detail) + " (아래 목록)."
    elif unknown:
        state = "unknown"
        message = f"{FOLLOW_UP_UNKNOWN} — " + ", ".join(detail) + ". 후속 항목이 없다고 말할 수 없다."
    else:
        state = "none_in_scope"
        message = (f"{FOLLOW_UP_NONE} (범위: 최근 세션 Next Session·프로젝트 Open Loops 블록. 명시적 '없음'은 그 기록에만 "
                   "해당한다. 범위 밖 기록·현재 작업 상태는 판정하지 않았다).")
    return {"state": state, "message": message, "complete": not unknown, "unknown_reasons": reasons}


def _with_text_omissions(follow: dict[str, Any], omitted: int) -> dict[str, Any]:
    """예산 때문에 본문에서 일부·전부 빠진 후속 기록(omitted건)을 판단에 반영한다.

    본문만 읽는 쪽은 빠진 후속 기록을 확인하지 못하므로 FOLLOW_UP_UNKNOWN을 함께 표시하고 complete=False로 둔다. 명시된
    후속 항목이 있다는 판단(has_items)은 유지하고, '없음'으로 판단했던 경우(none_in_scope)는 확인 불가(unknown)로 바꾼다 —
    빠진 기록이 명시적 '없음'이어도 본문으로는 그것을 확인할 수 없다. 원문은 omissions의 read로 읽는다.
    """
    if not omitted or follow["state"] == "not_evaluated":
        return follow
    out = {**follow, "complete": False,
           "unknown_reasons": {**(follow.get("unknown_reasons") or {}), "omitted_from_text": omitted}}
    note = f"본문에서 생략된 후속 기록 {omitted}건 — omissions의 read로 원문을 확인한다"
    if follow["state"] == "none_in_scope":
        out["state"] = "unknown"
        out["message"] = (f"{FOLLOW_UP_UNKNOWN} — {note}. 읽은 기록은 모두 명시적 '없음'이거나 비어 있었지만, 생략된 기록은 "
                          "본문으로 확인할 수 없다.")
    else:
        out["message"] = follow["message"] + f" 단 {FOLLOW_UP_UNKNOWN} — {note}."
    return out


# ── 예산 배정 ────────────────────────────────────────────────────────────────


def _read_args(doc: Any, start: int, end: int) -> dict[str, Any]:
    """생략 구간을 다시 읽는 MCP `read_note` 인자 — 이 dict를 그대로 `read_note(**read)`에 넘긴다.

    안내 정보(구간 끝·이어읽기 필요 여부·structured로 읽을 수 있는지)는 섞지 않는다 — `_read_info`가 따로 준다.
    max_chars는 기본값(=최대)이라 넣지 않는다. 16000자를 넘는 줄이 있으면 structured로는 그 줄을 받을 수 없어
    전문 읽기(`{"rel_path": …}`)를 준다 — 이때는 버전 확인이 없다.
    """
    if _read_info(doc, start, end)["structured_readable"]:
        return {"rel_path": doc.rel, "structured": True, "start_line": start,
                "max_lines": min(end - start + 1, READ_MAX_LINES), "expected_version": doc.source.version}
    return {"rel_path": doc.rel}


def _first_read_end(doc: Any, start: int, end: int) -> int:
    """`read_note(structured=True, start_line=start, max_lines=min(구간, MAX_LINES))` 한 번이 돌려주는 마지막 줄 번호.

    source_reader.read_source의 페이지 규칙을 그대로 따른다: max_lines, max_chars(기본=최대 16000, 줄 사이 개행 포함),
    max_chars보다 긴 줄 앞에서 멈춤. 첫 줄부터 못 읽으면 start - 1.
    """
    max_lines = min(end - start + 1, READ_MAX_LINES)
    used = 0
    last = start - 1
    for n in range(start, end + 1):
        if n - start >= max_lines:
            break
        text = doc.source.lines[n - 1]
        if len(text) > READ_MAX_CHARS:
            break
        cost = len(text) + (1 if n > start else 0)
        if used + cost > READ_MAX_CHARS:
            break
        used += cost
        last = n
    return last


def _read_info(doc: Any, start: int, end: int) -> dict[str, Any]:
    first_end = _first_read_end(doc, start, end)
    return {
        # read 한 번으로 구간 끝까지 못 읽는다(400줄·16000자 상한, 또는 긴 줄) — 응답의 next(start_line·expected_version)로 이어 읽는다
        "read_continues": first_end < end,
        "first_read_end_line": first_end,  # 첫 read가 돌려주는 마지막 줄 (start - 1이면 첫 줄부터 structured로 못 읽는다)
        "structured_readable": not any(len(doc.source.lines[n - 1]) > READ_MAX_CHARS for n in range(start, end + 1)),
    }


def _omission(doc: Any, rng: list[int], reason: str) -> dict[str, Any]:
    return {"lines": rng, "reason": reason, "read": _read_args(doc, *rng), **_read_info(doc, *rng)}


def _call(args: dict[str, Any]) -> str:
    if not args.get("structured"):
        return f'read_note("{args["rel_path"]}")'
    return (f'read_note("{args["rel_path"]}", structured=True, start_line={args["start_line"]}, '
            f'max_lines={args["max_lines"]}, expected_version="{args["expected_version"]}")')


def _header(item: _Item) -> str:
    tier = {"stable": "정본", "candidate": "후보", "raw": "원문"}.get(item.doc.tier, item.doc.tier)
    scope = {"project": "프로젝트", "common": "공통"}.get(item.scope, item.scope)
    bits = [item.label, f"{tier}·{scope}"]
    if "decision_status" in item.extra:
        bits.append({"candidate": "결정 후보", "promoted": "승격된 결정"}.get(item.extra["decision_status"],
                                                                          item.extra["decision_status"]))
    rec = item.extra.get("recorded_at")
    if rec:
        bits.append(f"기록 {evidence_search._clip(rec['value'], 60) if rec['value'] else '시각 없음'} ({rec['source']})")
    if item.extra.get("follow_up_state") == "explicit_none":
        bits.append("명시적 없음 — 이 기록 범위 한정")
    bits.append(item.doc.rel)
    return "▸ " + " · ".join(bits)


def _seg_label(s: int, e: int) -> str:
    return f"  @L{s}-L{e}"


def _omission_line(item: _Item, om: dict[str, Any]) -> str:
    r = om["lines"]
    return f"  ⋯ 생략 L{r[0]}-L{r[1]} ({om['reason']}) → {_call(om['read'])}"


def _omission_reserve(item: _Item) -> int:
    """생략 안내 줄의 최대 길이(+줄바꿈). 줄 번호를 전체 줄 수 자릿수로 잡아 실제 줄은 이보다 짧거나 같다."""
    t = item.doc.source.total_lines
    worst = {"rel_path": item.doc.rel, "structured": True, "start_line": t, "max_lines": READ_MAX_LINES,
             "expected_version": item.doc.source.version}
    return len(_omission_line(item, {"lines": [t, t], "reason": "line_too_long", "read": worst})) + 1


def _skip_omission(item: _Item, n: int) -> dict[str, Any]:
    """원문 읽기 상한(READ_MAX_CHARS)을 넘는 줄 하나의 생략 — 전문 읽기 인자(버전 확인 없음)."""
    return {**_omission(item.doc, [n, n], "line_too_long"), "line_chars": len(item.lines[n - 1])}


def _full_cost(item: _Item) -> int:
    """항목 전체를 생략 없이 실을 때의 본문 비용(_allocate와 같은 계산: 머리줄+항목 사이 빈 줄, 구간 표시 줄, 발췌 줄)."""
    width = len(_seg_label(item.doc.source.total_lines, item.doc.source.total_lines)) + 1
    return (len(_header(item)) + 1 + 2 + width * len(_segments(item.candidates))
            + sum(len(item.lines[n - 1]) + 1 for n in item.candidates))


def _render_item(item: _Item) -> str:
    if item.stub:
        return f"▸ {item.label} · {item.doc.rel} · 본문 생략 L{item.omission['lines'][0]}-L{item.omission['lines'][1]} " \
               f"({item.omission['reason']}) → {_call(item.omission['read'])}"
    out = [_header(item)]
    if item.omission and item.tail:
        out.append(_omission_line(item, item.omission))
    parts: list[tuple[int, list[str]]] = [(s, [_seg_label(s, e), *item.lines[s - 1:e]]) for s, e in _segments(item.shown)]
    parts += [(n, [_omission_line(item, _skip_omission(item, n))]) for n in item.skipped]
    for _, rendered in sorted(parts, key=lambda p: p[0]):
        out.extend(rendered)
    if item.omission and not item.tail:
        out.append(_omission_line(item, item.omission))
    return "\n".join(out)


def _allocate(b: _Build, remaining: int) -> tuple[int, int]:
    """BUDGET_ORDER대로 완전한 줄만 배정한다. (남은 예산, 본문에서 한 줄 안내도 못 낸 생략 수)."""
    group_used: dict[str, int] = {}
    aggregated = 0
    # 미리 잡아 두는 자리(예약)는 없다 — 발췌 본문은 BUDGET_ORDER 그대로 앞 묶음부터 남은 예산을 쓴다. 뒤 묶음의 위치는
    # 고정부(후속 기록 위치 목록·결정/세션 목록)와 JSON omissions가 맡는다. 예약을 두면 그만큼 뒤 묶음의 발췌가 제약보다
    # 먼저 예산을 갖게 된다(설계 #7 예산 순서 위반).
    order = {g: i for i, g in enumerate(BUDGET_ORDER)}
    by_group: dict[str, list[_Item]] = {}
    for item in b.items:
        by_group.setdefault(item.group, []).append(item)
    for group in sorted(by_group, key=order.__getitem__):
        items = by_group[group]
        if group in _TAIL_GROUPS:
            items = list(reversed(items))
        gcap = GROUP_CAPS.get(group)
        for item in items:
            lines = item.lines
            width = len(_seg_label(item.doc.source.total_lines, item.doc.source.total_lines)) + 1
            header = len(_header(item)) + 1 + 2  # 항목 사이 빈 줄 몫
            icap = ITEM_CAPS.get(group)
            om_reserve = _omission_reserve(item)
            cost = header
            text_used = 0
            chosen: list[int] = []
            reason = ""
            prev = None
            # append형 파일(Lessons·공통 OpenLoops)은 최신이 아래에 쌓인다 — 항목 안에서도 뒤쪽 줄부터 넣는다
            item.tail = group in _TAIL_GROUPS
            seq = list(reversed(item.candidates)) if item.tail else item.candidates
            step = -1 if item.tail else 1
            # 항목 전체가 남은 예산·상한 안에 들어가면 생략 안내 줄 자리 없이 통째로 넣는다(아래 줄 단위 판정은 줄마다 생략 줄
            # 자리를 남겨, 딱 들어가는 항목도 꼬리를 잃는다). 원문 읽기로 회수할 수 없는 줄(READ_MAX_CHARS 초과)이 있으면 안 된다.
            full_text = sum(len(lines[n - 1]) + 1 for n in seq)
            if (_full_cost(item) <= remaining and (icap is None or full_text <= icap)
                    and not any(len(lines[n - 1]) > READ_MAX_CHARS for n in seq)
                    and (gcap is None or group_used.get(group, 0) + full_text <= gcap)):
                seq = []
                chosen = list(item.candidates)
                cost = _full_cost(item)
                text_used = full_text
            skipped: list[int] = []
            stop: int | None = None  # seq에서 멈춘 위치 — 그 줄부터 끝까지(꼬리 묶음은 처음까지)가 생략 구간

            def exact_reserve(idx: int, used: int) -> int:
                """seq[idx]까지 넣고(본문 used자) 바로 다음 줄에서 멈출 때 실제로 붙을 생략 줄 길이(+줄바꿈).

                멈춤 이유도 다음 줄에 아래 판정을 그대로 적용해 정한다. 다음 줄이 들어간다면 멈춤은 더 뒤에서 일어나고 그때
                다시 판정하므로, 여기서는 '다음 줄에서 멈춘다'고 가정한 길이만 맞으면 된다.
                """
                nxt = seq[idx + 1]
                rng = [item.candidates[0], nxt] if item.tail else [nxt, item.candidates[-1]]
                nxt_chars = len(lines[nxt - 1])
                caps = [c for c in (icap, gcap, TEXT_MAX_CHARS) if c is not None]
                if nxt_chars <= READ_MAX_CHARS and nxt_chars > min(caps):
                    why = "line_too_long"
                elif nxt_chars <= READ_MAX_CHARS and icap is not None and used + nxt_chars + 1 > icap:
                    why = "item_cap"
                elif nxt_chars <= READ_MAX_CHARS and gcap is not None and group_used.get(group, 0) + used + nxt_chars + 1 > gcap:
                    why = "group_cap"
                else:
                    why = "budget"
                return len(_omission_line(item, _omission(item.doc, rng, why))) + 1

            for idx, n in enumerate(seq):
                text = lines[n - 1]
                is_last = idx == len(seq) - 1
                if len(text) > READ_MAX_CHARS:
                    # read_note(structured)로 회수할 수 없는 줄은 발췌하지 않고 한 줄 안내로 건너뛴 뒤 다음 줄을 계속 넣는다 —
                    # 이 줄 때문에 뒤의 읽을 수 있는 줄(제약 포함)까지 생략하지 않는다
                    note = len(_omission_line(item, _skip_omission(item, n))) + 1
                    if cost + note + (0 if is_last else exact_reserve(idx, text_used)) > remaining:
                        reason, stop = "budget", idx
                        break
                    skipped.append(n)
                    cost += note
                    prev = None
                    continue
                line_cost = len(text) + 1
                seg_cost = width if prev is None or n != prev + step else 0
                need = cost + seg_cost + line_cost
                limits = []
                if icap is not None and text_used + line_cost > icap:
                    limits.append("item_cap")
                if gcap is not None and group_used.get(group, 0) + text_used + line_cost > gcap:
                    limits.append("group_cap")
                # 뒤에 줄이 남으면 생략 줄 자리도 있어야 한다. 최악 길이로 먼저 보고, 모자라면 실제 길이로 다시 본다
                if need + (0 if is_last else om_reserve) > remaining and (
                        is_last or need + exact_reserve(idx, text_used + line_cost) > remaining):
                    limits.append("budget")
                if limits:
                    caps = [c for c in (icap, gcap, TEXT_MAX_CHARS) if c is not None]
                    reason = "line_too_long" if len(text) > min(caps) else limits[0]
                    stop = idx
                    break
                chosen.append(n)
                cost += seg_cost + line_cost
                text_used += line_cost
                prev = n
            item.shown = sorted(chosen)
            item.skipped = sorted(skipped)
            if stop is not None:
                first = seq[stop]  # 처음 못 넣은 줄
                rng = ([item.candidates[0], first] if item.tail else [first, item.candidates[-1]])
                item.omission = _omission(item.doc, rng, reason or "budget")
                if reason == "line_too_long":
                    item.omission["line_chars"] = len(lines[first - 1])
                if not chosen and not skipped:
                    stub = len(_render_item(_Item(**{**item.__dict__, "stub": True}))) + 2
                    if stub <= remaining:
                        item.stub = True
                        remaining -= stub
                    else:
                        aggregated += 1
                    continue
                cost += len(_omission_line(item, item.omission)) + 1
            remaining -= cost
            group_used[group] = group_used.get(group, 0) + text_used
    return remaining, aggregated


# ── 렌더 ─────────────────────────────────────────────────────────────────────


def _render(b: _Build, matching: dict[str, Any], follow: dict[str, Any], generated_at: str, *,
            critical: bool, aggregated: int, include_items: bool, list_cap: int = _GAPS_TEXT_CAP) -> str:
    """include_items=False면 고정부만 렌더한다 — 예산 계산용 (최악 길이 줄을 포함한다).

    list_cap: 본문에 줄로 내는 목록(gaps·확인 못 한 출처·세션 파일 안내·출처)의 최대 줄 수. 넘는 몫은 개수만 적는다.
    문서에서 온 문자열(제목·session_id 등)은 _FIELD_CHARS로 자른다 — 고정부가 상한을 넘지 않게.
    """
    c = lambda v, n=_FIELD_CHARS: evidence_search._clip(str(v), n)  # noqa: E731
    out: list[str] = [f"# Project Briefing (structured) — {evidence_search._clip(b.project or matching['input'], 200)}", ""]
    m_ev = c("; ".join(matching.get("evidence") or []) or "-", 400)
    out.append(f"- 생성 {generated_at} · schema {SCHEMA_VERSION} · 매칭 {matching['status']}"
               f"{' (' + matching['method'] + ')' if matching.get('method') else ''} · 근거 {m_ev}")
    out.append("- 발췌는 원문 줄 그대로다 (경로 @L시작-L끝, 1부터, frontmatter 포함). 기록 당시 내용이며 "
               "현재 유효성·완료 여부·중요도는 판정하지 않았다.")
    if b.partial or not include_items:
        out.append("- ⚠ partial: 일부 기록을 읽지 못했다 — warnings 참조.")
    if critical or not include_items:
        out.append("- ⚠ critical_omission: 제약 일부가 본문에 없다 — requires_read의 구간을 먼저 읽는다.")

    def items_of(section: str, group: str | None = None) -> list[_Item]:
        return [i for i in b.items if i.section == section and (group is None or i.group == group)
                and (i.shown or i.stub or i.skipped)]

    def add_items(items: list[_Item]) -> None:
        for item in items:
            out.extend(["", _render_item(item)])

    n = 0
    for key in DISPLAY_ORDER:
        n += 1
        out.extend(["", f"## {n}. {SECTION_TITLES[key]}"])
        if key == "constraints":
            state = b.states.get("constraints", "not_evaluated")
            if state != "items":
                rules = b.states.get("memory_rule_items", 0)
                out.append(f"- 상태(Context.md): {state} — 정보 부족 절 참조"
                           + (f" · 기억의 적용 규칙 {rules}건은 아래에 있다" if rules else ""))
            if include_items:
                add_items(items_of("constraints"))
        elif key == "context":
            if include_items:
                add_items(items_of("context"))
        elif key == "recent":
            out.extend(["", f"### 결정 (최근 최대 {_RECENT_DECISIONS}건, 기본 briefing과 같은 순서)"])
            if not b.decisions:
                out.append("- 기록된 결정 없음")
            for d in b.decisions:
                if d.get("state") != "excerpt":
                    out.append(f"- {c(d.get('title') or '(제목 미표시 — 검증 전)')} · {d['status']} · "
                               f"{c(d.get('date') or '날짜 없음', 40)} · {d['path']} · "
                               f"발췌 없음({d.get('state')}) → read_note(\"{d['path']}\")")
            if include_items:
                add_items(items_of("recent", "decision"))
            out.extend(["", "### 세션 결과 (최근 최대 3세션, 기본 briefing과 같은 순서)"])
            for s in b.sessions:
                out.extend(["", f"- 세션 {s['rank']}: {c(s['session_id'] or '(session_id 없음)')} · "
                           f"host {c(s['host'] or '-', 80)} · agent {c(s['agent'] or '-', 80)}"])
                noted = 0
                for h in s["handoffs"]:
                    notes = [f"{k} 절 없음" for k in h.get("missing", []) if k != "next session"]
                    notes += [f"{k} 빈 틀" for k in h.get("empty", [])]
                    if h.get("state"):
                        notes.append(h["state"])
                    if notes:
                        noted += 1
                        if noted <= list_cap:
                            out.append(f"  - {c(h.get('handoff_type') or 'handoff', 40)} {h['path']}: {', '.join(notes)}")
                if noted > list_cap:
                    out.append(f"  - 그 밖에 {noted - list_cap}개 파일 — JSON sections.recent.sessions 참조")
                if include_items:
                    for item in [i for i in b.items if i.section == "recent" and i.group != "decision"
                                 and i.extra.get("session_rank") == s["rank"] and (i.shown or i.stub or i.skipped)]:
                        out.extend(["", _render_item(item)])
        elif key == "follow_ups":
            out.append(f"- 상태: {follow['state']} — {follow['message']}")
            unchecked = [src for src in b.follow_sources if src["state"] not in ("items", "explicit_none")]
            for src in unchecked[:list_cap]:
                where = f" L{src['lines'][0]}-L{src['lines'][1]}" if src.get("lines") else ""
                out.append(f"- {src['source']} {src['path']}{where}: {src['state']}")
            if len(unchecked) > list_cap:
                out.append(f"- 그 밖에 {len(unchecked) - list_cap}개 출처 — JSON sources_checked 참조")
            # 고정부: 후속 기록 위치 — 발췌가 예산 때문에 빠져도 어디 있는지는 본문에 남는다(예약 없이)
            follow_items = [i for i in b.items if i.section == "follow_ups"]
            if follow_items:
                out.append("- 후속 기록 위치 (발췌가 빠져도 남는다 — 원문은 read_note):")
                for i in follow_items[:list_cap]:
                    where = f"세션 {i.extra['session_rank']} " if i.extra.get("session_rank") else ""
                    state = " · 명시적 없음" if i.extra.get("follow_up_state") == "explicit_none" else ""
                    out.append(f"  - {i.id} {where}{i.group}{state} · {i.doc.rel} L{i.span[0]}-L{i.span[1]}")
                if len(follow_items) > list_cap:
                    out.append(f"  - 그 밖에 {len(follow_items) - list_cap}건 — JSON sections.follow_ups.items 참조")
            if include_items:
                add_items(items_of("follow_ups"))
        elif key == "gaps":
            if not b.gaps:
                out.append("- 기록된 정보 부족 없음 (판단 한계: 이 briefing은 기록만 읽는다 — 현재 상태는 확인하지 않았다)")
            for g in b.gaps[:list_cap]:
                out.append(f"- [{g['code']}] {c(g['message'], 400)}" + (f" ({g['path']})" if g.get("path") else ""))
            if len(b.gaps) > list_cap:
                out.append(f"- 그 밖에 {len(b.gaps) - list_cap}건 — JSON gaps 참조")
            if b.warnings:
                # 본문에는 코드별 건수만 — 메시지·경로는 JSON warnings에 있다. 공유 후보 폴더의 다른 프로젝트 파일 경로(파일명이
                # 제목 구실을 한다)가 본문에 실리지 않게, 그리고 경고 수가 늘어도 고정부가 제약 발췌를 밀어내지 않게 한다.
                counts: dict[str, int] = {}
                for w in b.warnings:
                    counts[w["code"]] = counts.get(w["code"], 0) + int(w.get("count", 1))
                out.extend(["", "### 경고 (코드별 건수 — 내용·경로는 JSON warnings)"])
                out.append("- " + ", ".join(f"{c(code, 60)} {n}" for code, n in counts.items()))
    if aggregated or not include_items:
        out.extend(["", f"… 그 밖에 본문에 안내도 못 낸 생략 {aggregated if include_items else 99999}건 — JSON omissions 참조"])
    if b.docs:
        out.extend(["", "### 근거 출처 (source_version — read_note expected_version)"])
        docs = [(rel, doc) for rel, doc in b.docs.items() if rel not in b.rejected]
        for rel, doc in docs[:list_cap * 2]:
            out.append(f"- {rel} · {doc.source.version} · {doc.source.total_lines}줄")
        if len(docs) > list_cap * 2:
            out.append(f"- 그 밖에 {len(docs) - list_cap * 2}개 — JSON sources 참조 (각 항목의 source_version에도 있다)")
    return "\n".join(out).rstrip() + "\n"


# ── 응답 조립 ────────────────────────────────────────────────────────────────


def _source_dict(doc: Any, project: str) -> dict[str, Any]:
    fu = doc.file_unit
    return {
        "path": doc.rel,
        "title": evidence_search._clip(_safe_title(doc, project), 200),
        "kind": doc.kind,
        "record_tier": doc.tier,
        "status": {"declared": doc.status_declared, "class": doc.status_class},
        "time": {"value": doc.time_value, "source": doc.time_source},
        "attribution": {"scope": fu.scope, "project": fu.project, "evidence": evidence_search._ev(fu.evidence),
                        **({"conflict_with": fu.conflict_with} if fu.conflict_with else {})},
        "source_version": doc.source.version,
        "total_lines": doc.source.total_lines,
        "frontmatter_lines": list(doc.source.frontmatter_lines) if doc.source.frontmatter_lines else None,
    }


def _item_dict(item: _Item) -> dict[str, Any]:
    segs = [{"start_line": s, "end_line": e, "text": "\n".join(item.lines[s - 1:e])} for s, e in _segments(item.shown)]
    shown = ("full" if item.shown and not item.omission and not item.skipped
             else "partial" if item.shown or item.skipped else "omitted")
    out: dict[str, Any] = {
        "id": item.id, "kind": item.group, "label": item.label, "path": item.doc.rel,
        "span": list(item.span), "segments": segs, "shown": shown,
        "contiguous": len(segs) <= 1,
        "scope": item.scope, "project": item.project, "record_tier": item.doc.tier,
        "source_version": item.doc.source.version,
    }
    if item.cleaned:
        out["cleaned"] = [{"lines": [s, e], "reason": r} for s, e, r in _cleaned_ranges(item.cleaned)]
    if item.omission:
        out["omission"] = {"lines": item.omission["lines"], "reason": item.omission["reason"]}
    if item.skipped:
        out["unreadable_lines"] = list(item.skipped)  # 원문 읽기 상한 초과로 발췌하지 않은 줄 — omissions에 줄마다 있다
    for key in ("follow_up_state", "decision_status", "recorded_at", "session_rank", "session_id", "handoff_type", "host", "agent",
                "heading_line", "excerpt_basis", "block_evidence", "memory_rule"):
        if item.extra.get(key) not in (None, ""):
            out[key] = item.extra[key]
    return out


def _cleaned_ranges(cleaned: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for n, reason in sorted(cleaned):
        if out and out[-1][2] == reason and out[-1][1] == n - 1:
            out[-1] = (out[-1][0], n, reason)
        else:
            out.append((n, n, reason))
    return out


def _matching(res: ProjectResolution, reg: ProjectRegistry) -> dict[str, Any]:
    return {
        "input": res.input, "status": res.status, "project": res.project, "method": res.method,
        "evidence": evidence_search._ev(res.evidence), "candidates": res.candidates, "hint": res.hint,
        "basis": "명시적 근거만 (등록 표기·SessionHandoffs 폴더·별칭·.claude/vault.json·owner/repo 매핑). "
                 "repo 디렉터리 이름만으로는 확정하지 않는다.",
        # 확정하지 못했을 때만 고를 수 있는 이름을 준다 (확정된 응답에는 쓸모없는 크기다)
        **({} if res.status == "resolved" else {"registered_projects": reg.known_projects()[:50]}),
    }


def _size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def build(
    vault_dir: Path,
    project_or_repo: str,
    *,
    project_map: str = "",
    list_decisions: Callable[[str, str], list[dict]],
    list_handoffs: Callable[[str], list[dict]],
    recent_groups: Callable[[list[dict]], list[list[dict]]],
    handoff_timestamp: Callable[[dict], float],
    unlisted_decisions: Callable[[str, str, list[dict]], list[dict]],
    unlisted_handoffs: Callable[[str, list[dict]], list[dict]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """structured briefing 응답. 결정·세션 목록과 정렬은 기본 briefing 함수를 받아 그대로 쓴다(순환 import 회피)."""
    started = time.perf_counter()
    now = now or datetime.now()
    generated_at = now.astimezone().isoformat(timespec="seconds")
    reg = load_registry(vault_dir, project_map)
    res = resolve_project(vault_dir, project_or_repo, project_map, registry=reg)
    matching = _matching(res, reg)
    b = _Build(vault_dir=vault_dir, project=res.project if res.status in ("resolved", "unregistered") else "",
               reg=reg, now=now)
    for rel, msg in reg.unreadable.items():
        b.warn("registry_unreadable", msg, path=rel)
    if reg.unreadable:
        b.partial = True
    unreadable_msgs = set(reg.unreadable.values())
    for w in reg.warnings:
        if w not in unreadable_msgs:
            b.warn("registry", w)
    for w in res.warnings:
        if w not in reg.warnings:
            b.warn("project_resolution", w)

    if res.status == "resolved":
        _collect_context(b)
        _collect_memory(b)
        # 승격 결정은 Context.md가 있는 실제 폴더에서 읽는다 (선언 이름과 폴더명이 다를 수 있다)
        ctx_rel = _context_rel(reg, b.project)
        folder = ctx_rel.split("/")[1] if ctx_rel else b.project
        decisions = list_decisions(b.project, folder)
        unlisted_d = unlisted_decisions(b.project, folder, decisions)
        _collect_decisions(b, decisions, unlisted_d)
        handoffs = list_handoffs(b.project)
        _collect_sessions(b, recent_groups(handoffs), unlisted_handoffs(b.project, handoffs), handoff_timestamp)
        if not decisions:
            if unlisted_d:
                b.gap("decisions_unverifiable", "읽은 결정이 없지만 읽지 못한 파일·폴더가 있어 결정이 없다고 말할 수 없다.")
            else:
                b.gap("no_decisions", "기록된 결정(후보·승격)이 없다.")
    elif res.status == "unregistered":
        b.states["constraints"] = "no_context"
        b.gap("unregistered", f"'{res.project}'은 매핑으로 가리켜지지만 vault에 Context.md·SessionHandoffs가 없다. "
              "공통 메모리와 이 이름으로 표시된 메모리 블록만 넣었다.")
        _collect_memory(b)
    else:
        b.states["constraints"] = "not_evaluated"
        if not reg.known_projects():
            b.gap("vault_empty", "vault에 등록된 프로젝트가 없다(Context.md·SessionHandoffs 폴더 없음).")
        b.gap(f"project_{res.status}",
              "프로젝트를 명시적 근거로 확정하지 못해 어떤 프로젝트 기록도 넣지 않았다. 다른 프로젝트 근거로 채우지 않는다 — "
              "matching.candidates·hint를 보고 프로젝트명을 직접 넘긴다." + (f" ({res.hint})" if res.hint else ""))
    for rel, doc in b.docs.items():
        if rel not in b.rejected:
            for w in doc.warnings[:5]:
                b.warn("document", w, path=rel)
    follow = _follow_up_state(b) if res.status in ("resolved", "unregistered") else {
        "state": "not_evaluated", "message": "프로젝트가 확정되지 않아 확인하지 않았다.", "complete": False,
        "unknown_reasons": None}

    # 고정부(최악 길이 안내 줄 포함)를 먼저 잡고 남은 예산을 BUDGET_ORDER대로 나눈다
    # 목록이 길어 고정부만으로 상한을 넘으면 목록 줄 수를 줄인다(넘는 몫은 개수만) — 상한을 넘는 응답을 내지 않는다
    # 원문 읽기 상한보다 긴 줄은 어떤 예산에서도 발췌하지 않는다(회수 불가) — 고정부를 재기 전에 정보 부족으로 남긴다
    for item in b.items:
        for n in item.candidates:
            if len(item.lines[n - 1]) > READ_MAX_CHARS:
                b.gap("line_exceeds_read_limit",
                      f"{n}행이 {len(item.lines[n - 1])}자라 read_note(structured)의 줄 상한 {READ_MAX_CHARS}자를 넘는다 — 회수할 수 "
                      "없어 발췌하지 않았다. 전문 읽기(read_note(rel_path))로만 확인할 수 있고 버전 확인이 없다."
                      + (" 제약 줄이다(critical_omission)." if item.section == "constraints" else ""),
                      path=item.doc.rel, lines=[n, n])
    # 후속 항목 판단은 예산 배정 뒤 본문 생략까지 반영해 다시 정한다(_with_text_omissions). 고정부 크기는 생략이 가장 많을 때의
    # 메시지로 잡는다 — 배정 뒤 메시지가 길어져 상한을 넘지 않게.
    n_follow = sum(1 for i in b.items if i.section == "follow_ups")
    worst_follow = max((follow, _with_text_omissions(follow, n_follow)),
                       key=lambda f: len(f["state"]) + len(f["message"]))  # 본문 상태 줄 = 상태 + 메시지
    for list_cap in (_GAPS_TEXT_CAP, 5, 0):
        skeleton = _render(b, matching, worst_follow, generated_at, critical=True, aggregated=0, include_items=False,
                           list_cap=list_cap)
        if len(skeleton) <= TEXT_MAX_CHARS:
            break
    remaining = TEXT_MAX_CHARS - len(skeleton)
    aggregated = 0
    if remaining > 0:
        remaining, aggregated = _allocate(b, remaining)
    else:
        for item in b.items:
            item.omission = _omission(item.doc, [item.span[0], item.span[1]], "budget")
            aggregated += 1

    follow = _with_text_omissions(follow, sum(1 for i in b.items if i.section == "follow_ups" and (i.omission or i.skipped)))

    omissions = []
    for item in b.items:
        # read는 MCP read_note에 그대로 넘기는 인자, 나머지는 안내 정보. 건너뛴 긴 줄은 줄마다 따로 남는다(비연속 생략)
        for om_ in [_skip_omission(item, n) for n in item.skipped] + ([item.omission] if item.omission else []):
            omissions.append({"item": item.id, "section": item.section, "kind": item.group, "path": item.doc.rel,
                              "critical": item.section == "constraints", **om_})
    critical_gaps = [g for g in b.gaps if g.get("critical")]
    requires_read = [{"path": om["path"], "lines": om["lines"], "reason": "critical_omission", "item": om["item"],
                      "read": om["read"]} for om in omissions if om["critical"]]
    requires_read += [{"path": g["path"], "reason": g["code"], "read": {"rel_path": g["path"]},
                       **({"unverified": True} if g.get("unverified") else {})}
                      for g in critical_gaps if g.get("path")]
    critical = bool(requires_read) or bool(critical_gaps)

    text = _render(b, matching, follow, generated_at, critical=critical, aggregated=aggregated, include_items=True,
                   list_cap=list_cap)
    if len(text) > TEXT_MAX_CHARS:  # 구성상 일어나지 않는다 — 일어나면 숨기지 않고 실패로 드러낸다
        raise RuntimeError(f"structured briefing text가 상한을 넘었습니다: {len(text)} > {TEXT_MAX_CHARS}")

    sections = []
    for key in DISPLAY_ORDER:
        sec: dict[str, Any] = {"key": key, "title": SECTION_TITLES[key],
                               "display_rank": DISPLAY_ORDER.index(key) + 1}
        if key == "gaps":
            sec["items"] = b.gaps
        else:
            sec["items"] = [_item_dict(i) for i in b.items if i.section == key]
        if key == "constraints":
            sec["state"] = b.states.get("constraints", "not_evaluated")  # Context.md 기준 상태
            sec["memory_rule_items"] = b.states.get("memory_rule_items", 0)
        elif key == "follow_ups":
            sec.update(follow)
            sec["sources_checked"] = b.follow_sources
        elif key == "recent":
            sec["decisions"] = b.decisions
            sec["sessions"] = b.sessions
        elif key == "context":
            sec["excluded"] = dict(b.excluded)
            sec["cleaned_sections"] = b.states.get("cleaned_sections", [])
        sections.append(sec)

    response: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "project": b.project,
        "matched": res.status == "resolved",
        # 기본 호출과 같은 키 — candidates는 확정하지 못했을 때 고를 이름(기본 호출처럼 등록 프로젝트로 채운다),
        # source_refs는 소속 검증을 통과해 실제로 쓴 문서 경로(읽은 순서)
        "candidates": [] if res.status == "resolved" else list(res.candidates or reg.known_projects()[:50]),
        "source_refs": [rel for rel in b.docs if rel not in b.rejected],
        "matching": matching,
        "partial": b.partial,
        "critical_omission": critical,
        "requires_read": requires_read,
        "sections": sections,
        "omissions": omissions,
        "warnings": b.warnings,
        # 소속 검증에 실패한 문서는 경로와 제외 사유만 — 제목·버전·귀속 근거(문서 내용에서 온 값)를 싣지 않는다
        "sources": [{"path": rel, "excluded": b.rejected[rel]} if rel in b.rejected else _source_dict(d, b.project)
                    for rel, d in b.docs.items()],
        "text": text,
        "budget": {
            "text_max_chars": TEXT_MAX_CHARS, "text_chars": len(text),
            "display_order": list(DISPLAY_ORDER), "budget_order": list(BUDGET_ORDER),
            "group_caps": GROUP_CAPS, "item_caps": ITEM_CAPS,
            "recent_decisions": _RECENT_DECISIONS, "recent_sessions": len(b.sessions),
            "response_chars": 0, "sources_meta_chars": 0, "sections_meta_chars": 0,
        },
        "elapsed_ms": 0,
    }
    response["budget"]["sources_meta_chars"] = _size(response["sources"])
    response["budget"]["sections_meta_chars"] = _size(response["sections"])
    response["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    used = 0
    for _ in range(4):
        response["budget"]["response_chars"] = used
        size = _size(response)
        if size == used:
            break
        used = size
    if used > RESPONSE_WARN_CHARS:
        response["warnings"].append({"code": "response_large",
                                     "message": f"응답 전체가 {used}자다(text 상한 {TEXT_MAX_CHARS}자와 별개). 줄이지 않고 그대로 냈다."})
        used = 0
        for _ in range(4):
            response["budget"]["response_chars"] = used
            size = _size(response)
            if size == used:
                break
            used = size
    return response
