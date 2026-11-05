"""structured 근거 검색 — 프로젝트 범위·관련도 그룹·원문 줄 발췌.

legacy `search_vault`(WikiService 점수 + stable→candidate→raw 정렬 + raw 예약)는 그대로 두고, 이 모듈은
`search_vault(structured=True)`만 쓴다. 기존 점수와 다른 점:

1. 범위 필터를 점수화 **전에** 적용한다. 소속은 파일 단위(경로·frontmatter project)와 블록 단위
   (40_AgentMemory의 `devtrail-memory-patch` marker)로 따로 판정하고, 범위 밖 블록은 점수·발췌 모두에서 뺀다.
2. 순위는 관련도 그룹이 먼저다: 토큰 충족도 → 같은 근거 창(연속 줄)에서의 충족도 → 구절 일치.
   같은 그룹 안에서만 정본(stable) → 후보(candidate) → 원문(raw)을 우대한다. 단어 반복은 토큰당
   _FREQ_CAP까지만 센다. 종류별 고정 자리(raw 예약)는 두지 않는다.
3. 발췌는 요약 첫 줄이 아니라 일치가 모인 원문 줄 구간이며, 줄 번호는 frontmatter 포함 파일 전체 기준이다
   (`read_note(structured=True)`와 같은 기준 — app/services/vault_source.py).

문서 status는 선언된 값을 그대로 돌려줄 뿐 "현재 유효"를 판정하지 않는다. superseded/archived만 이력으로
분류해 기본 제외하고, 모르는 값은 unknown으로 표시한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.services.project_identity import ProjectRegistry, ProjectResolution, load_registry, resolve_project
from app.services.vault_source import (
    ALLOWED_READ_PREFIXES,
    SourceText,
    read_source_text,
    real_scoped_rel,
    record_tier,
)
from app.services.wiki_service import _INLINE_TAG_RE, _TOKEN_RE

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
DEFAULT_MAX_CHARS = 12000
MIN_MAX_CHARS = 3000  # 응답 고정부(최대 약 1.9천 자: 질의 300자·토큰 32개 포함)와 압축형 결과 1건이 들어가는 크기
MAX_QUERY_CHARS = 300  # 질의는 응답에 되돌려 싣는다 — 길이가 무제한이면 고정부만으로 예산을 넘는다
MAX_QUERY_TOKENS = 32
EXCERPTS_PER_DOC = 2
EXCERPT_MAX_CHARS = 800
_WINDOW_LINES = 5  # "같은 근거 창" — 연속 5줄 안에 함께 나온 토큰 수
_FREQ_CAP = 3  # 토큰당 반복 인정 상한 — 같은 단어를 많이 쓴 긴 원문이 정확한 근거를 밀어내지 않게
_TIER_RANK = {"stable": 0, "candidate": 1, "raw": 2}
_WARNINGS_CAP = 20
_DOC_WARNINGS_CAP = 5
_DUPLICATES_CAP = 10
_TITLE_MAX_CHARS = 200
_BLOCKS_CAP = 10  # attribution.blocks — marker가 수백 개인 문서도 결과 크기가 무한히 커지지 않게
_EVIDENCE_MAX_CHARS = 160  # marker JSON의 project 값처럼 문서에서 온 문자열은 길이 상한을 둔다
_CURSOR_VERSION = 2  # 2: cursor가 범위 안 스캔 대상 전체·소속·읽기 실패를 묶는다

# 코드가 실제로 쓰는 status 값 (2026-11-05 조사 — docs/evidence-search.md "상태 값 근거").
# 이 목록은 "알려진 값"일 뿐 유효성 인증이 아니다.
KNOWN_STATUSES = frozenset({
    "candidate",  # candidate_writer
    "accepted", "stable",  # curator promote (decision / 그 외)
    "applied", "promoted",  # curator apply-memory-patch / retention이 읽는 승격 표시
    "raw",  # capture_agent 세션 원문
    "generated",  # weekly_review·nightly digest
    "draft", "review", "published",  # wiki_blog_agent
    "active",  # Context.md·AgentMemory 기본 템플릿
})
# superseded: _list_decisions가 이력으로 다룬다. archived: 코드가 쓰는 곳은 없지만 보관을 선언하는 값이라 이력으로 본다.
# 보관 위치(60_Candidates/_Archive/)는 status와 무관하게 이력이다 (retention.CANDIDATE_ARCHIVE_DIR).
HISTORY_STATUSES = frozenset({"superseded", "archived"})
_ARCHIVE_PREFIX = "60_Candidates/_Archive/"

KINDS = (
    "context", "decision", "problem", "plan", "design", "conversation", "prompt_log", "project_doc",
    "knowledge", "agent_memory", "memory_patch", "blog_idea", "career_bullet", "session_handoff",
    "session_log", "worklog", "output", "task", "other",
)
_PROJECT_SUBKINDS = {
    "Decisions": "decision", "Problems": "problem", "Plans": "plan", "Design": "design",
    "Conversations": "conversation",
}
_CANDIDATE_SUBKINDS = {
    "Knowledge": "knowledge", "Decisions": "decision", "Problems": "problem", "MemoryPatches": "memory_patch",
    "BlogIdeas": "blog_idea", "CareerBullets": "career_bullet", "SessionHandoffs": "session_handoff",
}
_MARKER_RE = re.compile(r"^<!-- devtrail-memory-patch: (.+) -->\s*$")
# 블록 경계는 접두로 감지한다 — 닫는 `-->`가 빠진 marker를 경계로 안 보면 그 아래 블록이 앞 블록 소속에 흡수된다
_MARKER_PREFIX = "<!-- devtrail-memory-patch:"
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # python-frontmatter YAMLHandler와 같은 로더
_TIME_KEYS = ("updated_at", "created_at", "date", "promoted_at")


class SearchArgumentError(ValueError):
    """structured 검색 인자 오류 — code는 응답 error.code로 그대로 나간다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── 내부 타입 ────────────────────────────────────────────────────────────────


@dataclass
class _Unit:
    """소속 판정 단위 — marker가 없는 문서는 본문 전체가 하나."""

    start: int  # 1-based, 포함
    end: int
    scope: str  # project | common | unknown | conflict
    project: str = ""
    evidence: list[str] = field(default_factory=list)
    conflict_with: list[str] = field(default_factory=list)
    invalid_marker: bool = False  # marker가 깨졌거나 scope를 해석할 수 없다 — "근거 없음"과 다른 unknown

    def signature(self) -> list:
        return [self.start, self.end, self.scope, self.project.casefold(), sorted(c.casefold() for c in self.conflict_with),
                self.invalid_marker]


@dataclass
class _Doc:
    rel: str
    source: SourceText
    meta: dict[str, Any]
    title: str
    title_line: int  # 제목을 본문 '# ' 줄에서 얻었으면 그 줄 번호, frontmatter·파일명이면 0
    body_start: int  # 점수·발췌 대상이 시작하는 줄 — frontmatter를 해석하지 못하면 1(파일 전체가 본문)
    tags: list[str]
    meta_tags: list[str]  # frontmatter tags만 — marker 문서는 범위 안 블록의 인라인 태그와 합친다
    summary: str
    kind: str
    declared_type: str
    tier: str
    status_declared: str | None
    status_class: str  # known | unknown | absent | history
    status_reason: str
    time_value: str
    time_source: str
    file_unit: _Unit
    units: list[_Unit]
    has_markers: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Scored:
    doc: _Doc
    units: list[_Unit]
    coverage: int
    window: int
    phrase: bool
    freq: int
    matched_fields: dict[str, list[str]]
    excerpts: list[dict]
    title: str = ""  # 응답에 내는 제목 — 범위 밖 블록의 제목 줄이면 파일명으로 바꾼다
    duplicates: list[dict] = field(default_factory=list)

    def sort_key(self) -> tuple:
        is_history = self.doc.status_class == "history"
        return (-self.coverage, -self.window, not self.phrase, is_history, _TIER_RANK[self.doc.tier], -self.freq, self.doc.rel)


# ── 문서 분류 ────────────────────────────────────────────────────────────────


def classify_kind(rel: str) -> str:
    parts = rel.split("/")
    top = parts[0]
    if top == "30_Projects" and len(parts) >= 3:
        if len(parts) == 3 and parts[2] == "Context.md":
            return "context"
        if len(parts) == 3 and parts[2] == "PromptLog.md":
            return "prompt_log"
        return _PROJECT_SUBKINDS.get(parts[2], "project_doc")
    if top == "20_Knowledge":
        return "knowledge"
    if top == "40_AgentMemory":
        return "agent_memory"
    if top == "60_Candidates" and len(parts) >= 3:
        sub = parts[2] if parts[1] == "_Archive" and len(parts) >= 4 else parts[1]
        return _CANDIDATE_SUBKINDS.get(sub, "other")
    if top == "10_Worklog":
        return "session_log" if len(parts) >= 3 and parts[1] == "Sessions" else "worklog"
    if top == "50_Outputs":
        return "output"
    if top == "70_Tasks":
        return "task"
    return "other"


def _str_meta(meta: dict[str, Any], key: str) -> str | None:
    """문자열 메타데이터만 돌려준다. 값이 없으면 None, 문자열이 아니면 빈 문자열(형식 미지원)."""
    if key not in meta or meta[key] is None:
        return None
    value = meta[key]
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return ""


def _path_project(rel: str, reg: ProjectRegistry) -> tuple[str, str] | None:
    parts = rel.split("/")
    if parts[0] == "30_Projects" and len(parts) >= 3:
        return reg.dir_to_project.get(parts[1], parts[1]), f"path:30_Projects/{parts[1]}/"
    handoff_at = None
    if parts[:2] == ["60_Candidates", "SessionHandoffs"]:
        handoff_at = 2
    elif parts[:3] == ["60_Candidates", "_Archive", "SessionHandoffs"]:
        handoff_at = 3
    if handoff_at is not None and len(parts) > handoff_at + 1 and not parts[handoff_at].startswith("_"):
        folder = parts[handoff_at]
        return reg.canonical_name(folder), f"path:{'/'.join(parts[:handoff_at + 1])}/"
    # curator는 프로젝트 knowledge를 20_Knowledge/<P>/에 둔다. 등록된 프로젝트 폴더일 때만 근거로 쓴다
    # (20_Knowledge/AI/ 같은 주제 폴더를 프로젝트로 오인하지 않게).
    # 등록 기준은 프로젝트 식별과 같다(Context.md 또는 SessionHandoffs 폴더).
    if parts[0] == "20_Knowledge" and len(parts) >= 3 and reg.is_known(parts[1]):
        return reg.canonical_name(parts[1]), f"path:20_Knowledge/{parts[1]}/"
    return None


def _file_attribution(rel: str, meta: dict[str, Any], reg: ProjectRegistry, warnings: list[str]) -> _Unit:
    evidence: list[str] = []
    path_hit = _path_project(rel, reg)
    meta_project = _str_meta(meta, "project")
    if meta_project == "" and "project" in meta and meta["project"] not in ("", None):
        warnings.append("frontmatter project가 문자열이 아니라 소속 근거로 쓰지 않았습니다.")
    meta_name = reg.attribution_name(meta_project) if meta_project else ""
    meta_evidence = f"meta:project={meta_project}" + (f"→{meta_name}" if meta_name != meta_project else "")
    scope_value = (_str_meta(meta, "scope") or "").casefold()

    if path_hit and meta_name:
        evidence = [path_hit[1], meta_evidence]
        if path_hit[0].casefold() == meta_name.casefold():
            return _Unit(0, 0, "project", path_hit[0], evidence)
        return _Unit(0, 0, "conflict", "", evidence, conflict_with=sorted({path_hit[0], meta_name}, key=str.casefold))
    if scope_value == "global":
        # memory_patch의 scope=global — 출신 프로젝트가 있어도 적용 범위는 전역이다 (curator가 같은 규칙으로 marker를 쓴다)
        origin = f" (출신 {meta_name})" if meta_name else ""
        return _Unit(0, 0, "common", "", [f"meta:scope=global{origin}"])
    if path_hit:
        return _Unit(0, 0, "project", path_hit[0], [path_hit[1]])
    if meta_name:
        return _Unit(0, 0, "project", meta_name, [meta_evidence])
    if rel.startswith("40_AgentMemory/"):
        return _Unit(0, 0, "common", "", ["path_convention:40_AgentMemory=전역 메모리"])
    return _Unit(0, 0, "unknown", "", ["소속 근거 없음 (프로젝트 경로·frontmatter project·scope 없음)"])


def _marker_units(doc_lines: list[str], body_start: int, file_unit: _Unit, reg: ProjectRegistry, warnings: list[str]) -> list[_Unit]:
    """40_AgentMemory 문서를 marker 블록으로 나눈다. marker 앞은 파일 소속(AgentMemory는 전역)."""
    total = len(doc_lines)
    marks: list[tuple[int, str | None]] = []
    for idx in range(body_start - 1, total):
        line = doc_lines[idx]
        if not line.startswith(_MARKER_PREFIX):
            continue
        m = _MARKER_RE.match(line)
        marks.append((idx + 1, m.group(1) if m else None))  # None = 형식이 깨진 marker
    if not marks:
        return []
    units: list[_Unit] = []
    if marks[0][0] > body_start:
        units.append(_Unit(body_start, marks[0][0] - 1, file_unit.scope, file_unit.project,
                           [*file_unit.evidence, "block:marker 앞"], list(file_unit.conflict_with)))
    for i, (line_no, payload) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else total
        try:
            data = json.loads(payload) if payload is not None else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            warnings.append(f"{line_no}행 marker를 해석하지 못해 그 블록 소속을 unknown으로 둡니다.")
            units.append(_Unit(line_no, end, "unknown", "", [f"marker:{line_no}행 해석 실패"], invalid_marker=True))
            continue
        scope = str(data.get("scope") or "").strip().casefold()
        project = str(data.get("project") or "").strip()
        if scope == "project" and project and isinstance(data.get("project"), str):
            name = reg.attribution_name(project)
            units.append(_Unit(line_no, end, "project", name,
                               [f"marker:{line_no}행 project={project}" + (f"→{name}" if name != project else "")]))
        elif scope == "global":
            units.append(_Unit(line_no, end, "common", "", [f"marker:{line_no}행 scope=global"]))
        else:
            warnings.append(f"{line_no}행 marker의 scope/project를 해석할 수 없어(scope는 project+문자열 project 또는 global) unknown으로 둡니다.")
            units.append(_Unit(line_no, end, "unknown", "", [f"marker:{line_no}행 scope={scope or '없음'}"], invalid_marker=True))
    return units


def _status(rel: str, meta: dict[str, Any]) -> tuple[str | None, str, str]:
    declared = _str_meta(meta, "status")
    if rel.startswith(_ARCHIVE_PREFIX):
        return declared, "history", "path:60_Candidates/_Archive/"
    if declared is None:
        return None, "absent", "status 없음"
    if declared == "":
        return "", "unknown", "status 형식 미지원(문자열 아님)"
    low = declared.casefold()
    if low in HISTORY_STATUSES:
        return declared, "history", f"meta:status={declared}"
    if low in KNOWN_STATUSES:
        return declared, "known", f"meta:status={declared}"
    return declared, "unknown", f"meta:status={declared} (알려지지 않은 값 — 유효성 미인증)"


def _time(meta: dict[str, Any], path: Path) -> tuple[str, str]:
    for key in _TIME_KEYS:
        value = _str_meta(meta, key)
        if value:
            return value, f"meta:{key}"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "file_mtime"
    except OSError:
        return "", "none"


def _title(meta: dict[str, Any], lines: list[str], body_start: int, rel: str) -> tuple[str, int]:
    title = _str_meta(meta, "title")
    if title:
        return title, 0
    for n in range(body_start, len(lines) + 1):
        if lines[n - 1].strip().startswith("# "):
            return lines[n - 1].strip()[2:].strip(), n
    return Path(rel).stem, 0


def _tags(meta: dict[str, Any], body: str) -> list[str]:
    raw = meta.get("tags") or []
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.split(",")]
    if not isinstance(raw, list):
        raw = []
    tags = {str(t).lstrip("#").lower() for t in raw if str(t).strip()}
    tags.update(t.lower() for t in _INLINE_TAG_RE.findall(body))
    return sorted(tags)


def load_doc(vault_dir: Path, rel: str, path: Path, reg: ProjectRegistry) -> _Doc:
    """파일 하나를 읽어 분류한다. 읽기 실패는 OSError로 올린다."""
    source = read_source_text(path)
    warnings = list(source.warnings)
    meta: dict[str, Any] = {}
    body_start = source.body_start_line
    if source.frontmatter_lines:
        # 해석에 실패하거나 결과가 매핑이 아니면 '---' 사이 줄도 본문으로 본다 — 수평선으로 시작하는 노트의 앞줄이
        # 검색에서 사라지지 않게 (legacy WikiService도 해석 실패 시 원문 전체를 본문으로 본다)
        # python-frontmatter는 YAML이 매핑이 아니면(문자열 한 줄 등) 조용히 빈 dict를 준다 — 그래서 YAML 값 자체로 판정한다.
        # 비었거나 주석뿐(None)·매핑이면 정상 frontmatter, 문법 오류·스칼라·목록이면 해석 실패다.
        fm_text = "\n".join(source.lines[1:source.frontmatter_lines[1] - 1])
        # 한 번만 해석한다(문서마다 YAML 이중 해석은 1000문서 규모에서 1.5배 느렸다). 로더는 python-frontmatter와 같다.
        try:
            data = yaml.load(fm_text, Loader=_YAML_LOADER)
        except Exception:
            data = False
        if data is None or isinstance(data, dict):
            meta = dict(data or {})
        else:
            body_start = 1
            warnings.append("frontmatter를 해석하지 못해 메타데이터 없이 파일 전체를 본문으로 봅니다.")
    elif source.lines and source.lines[0].strip() == "---":
        warnings.append("frontmatter가 닫히지 않아 파일 전체를 본문으로 봅니다.")
    body_text = "\n".join(source.lines[body_start - 1:])
    file_unit = _file_attribution(rel, meta, reg, warnings)
    total = source.total_lines
    units: list[_Unit] = []
    has_markers = False
    if rel.startswith("40_AgentMemory/"):
        units = _marker_units(source.lines, body_start, file_unit, reg, warnings)
        has_markers = bool(units)
    if not units:
        whole = _Unit(body_start, total, file_unit.scope, file_unit.project, list(file_unit.evidence), list(file_unit.conflict_with))
        units = [whole] if total >= body_start else []
    title, title_line = _title(meta, source.lines, body_start, rel)
    status_declared, status_class, status_reason = _status(rel, meta)
    if status_class == "unknown":
        warnings.append(f"status '{status_declared}'는 알려진 값이 아닙니다 — 유효한 문서로 인증하지 않습니다.")
    time_value, time_source = _time(meta, path)
    summary = (_str_meta(meta, "summary") or _str_meta(meta, "description") or "")[:160]
    declared_type = _str_meta(meta, "candidate_type") or _str_meta(meta, "type") or ""
    return _Doc(
        rel=rel, source=source, meta=meta, title=title, title_line=title_line, body_start=body_start,
        tags=_tags(meta, body_text), meta_tags=_tags(meta, ""), summary=summary, kind=classify_kind(rel), declared_type=declared_type,
        tier=record_tier(rel), status_declared=status_declared, status_class=status_class,
        status_reason=status_reason, time_value=time_value, time_source=time_source,
        file_unit=file_unit, units=units, has_markers=has_markers, warnings=warnings,
    )


# ── 스캔 ─────────────────────────────────────────────────────────────────────


@dataclass
class _Scan:
    docs: list[_Doc]
    warnings: list[dict]
    partial: bool


def scan_vault(vault_dir: Path, reg: ProjectRegistry) -> _Scan:
    """read_scope 안의 .md를 읽는다. 심볼릭 링크는 실제 경로가 허용 prefix 안일 때만 읽는다."""
    docs: list[_Doc] = []
    warnings: list[dict] = []
    partial = False
    tops = sorted({p.split("/")[0] for p in ALLOWED_READ_PREFIXES})
    for top in tops:
        top_path = vault_dir / top
        if not top_path.is_dir():
            continue
        if top_path.is_symlink() and real_scoped_rel(vault_dir, top_path) is None:
            warnings.append({"code": "outside_scope_link", "path": top + "/", "message": "실제 경로가 read_scope 밖인 링크라 읽지 않았습니다."})
            continue

        def _walk_error(exc: OSError, _top: str = top) -> None:
            nonlocal partial
            partial = True
            warnings.append({"code": "read_failed", "path": _rel_of(vault_dir, exc.filename) or _top + "/", "message": f"디렉터리를 읽지 못했습니다: {exc.strerror or exc}"})

        for dirpath, dirnames, filenames in os.walk(top_path, onerror=_walk_error):
            here = Path(dirpath)
            for d in list(dirnames):
                if d.startswith("."):
                    dirnames.remove(d)
                elif (here / d).is_symlink():
                    warnings.append({"code": "symlink_dir_skipped", "path": _rel_of(vault_dir, here / d) + "/", "message": "링크된 디렉터리는 따라가지 않습니다."})
            dirnames.sort()
            for name in sorted(filenames):
                if not name.endswith(".md") or name.startswith("."):
                    continue
                path = here / name
                rel = _rel_of(vault_dir, path)
                if not rel.startswith(ALLOWED_READ_PREFIXES):
                    continue
                if path.is_symlink() or real_scoped_rel(vault_dir, path) != rel:
                    # 링크 파일은 경로 소속이 실제 위치와 달라 읽지 않는다. 대상이 범위 안이면 대상 경로로 따로 검색된다.
                    if real_scoped_rel(vault_dir, path) is None:
                        warnings.append({"code": "outside_scope_link", "path": rel, "message": "실제 경로가 read_scope 밖인 링크라 읽지 않았습니다."})
                    else:
                        warnings.append({"code": "symlink_file_skipped", "path": rel, "message": "링크 파일은 읽지 않습니다 — 대상 파일이 자기 경로로 검색됩니다."})
                    continue
                try:
                    docs.append(load_doc(vault_dir, rel, path, reg))
                except OSError as exc:
                    partial = True
                    warnings.append({"code": "read_failed", "path": rel, "message": f"파일을 읽지 못했습니다: {exc.strerror or exc}"})
    return _Scan(docs=docs, warnings=warnings, partial=partial)


def _rel_of(vault_dir: Path, path: Any) -> str:
    try:
        return Path(path).relative_to(vault_dir).as_posix()
    except (TypeError, ValueError):
        return ""


# ── 범위 필터 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchScope:
    project: str = ""  # 확정된 프로젝트 표기. 비면 vault 전체
    include_common: bool = False
    include_unattributed: bool = False
    include_history: bool = False
    kinds: tuple[str, ...] = ()

    def unit_reason(self, unit: _Unit) -> str:
        """unit을 빼는 이유. 포함이면 빈 문자열."""
        if not self.project:
            return ""
        key = self.project.casefold()
        if unit.scope == "project":
            return "" if unit.project.casefold() == key else "other_project"
        if unit.scope == "common":
            return "" if self.include_common else "common"
        if unit.scope == "conflict":
            if self.include_unattributed and key in {c.casefold() for c in unit.conflict_with}:
                return ""
            return "conflict"
        if self.include_unattributed:
            return ""
        return "invalid_marker" if unit.invalid_marker else "unknown"


def _filter(docs: list[_Doc], scope: SearchScope) -> tuple[list[tuple[_Doc, list[_Unit]]], dict[str, dict[str, int]]]:
    kept: list[tuple[_Doc, list[_Unit]]] = []
    filtered: dict[str, dict[str, int]] = {"documents": {}, "blocks": {}}

    def bump(group: str, reason: str) -> None:
        filtered[group][reason] = filtered[group].get(reason, 0) + 1

    for doc in docs:
        if scope.kinds and doc.kind not in scope.kinds:
            bump("documents", "kind")
            continue
        if doc.status_class == "history" and not scope.include_history:
            bump("documents", "history")
            continue
        units: list[_Unit] = []
        reasons: list[str] = []
        for unit in doc.units:
            reason = scope.unit_reason(unit)
            if reason:
                reasons.append(reason)
            else:
                units.append(unit)
        # 본문이 없는 문서(frontmatter만)는 파일 소속으로 판정한다
        if not doc.units:
            reason = scope.unit_reason(doc.file_unit)
            if reason:
                bump("documents", reason)
                continue
        elif not units:
            bump("documents", reasons[0] if len(set(reasons)) == 1 else "mixed")
            continue
        if doc.has_markers:
            for reason in reasons:
                bump("blocks", reason)
        kept.append((doc, units))
    return kept, filtered


# ── 점수·발췌 ────────────────────────────────────────────────────────────────


def query_tokens(query: str) -> list[str]:
    """legacy WikiService와 같은 토큰 규칙(2글자 이상, 소문자). 중복은 한 번만."""
    seen: dict[str, None] = {}
    for token in _TOKEN_RE.findall(query):
        if len(token.strip()) > 1:
            seen.setdefault(token.lower(), None)
    return list(seen)


def _phrase(query: str) -> str:
    return " ".join(query.lower().split())


def _score(doc: _Doc, units: list[_Unit], tokens: list[str], phrase: str) -> _Scored | None:
    lines = doc.source.lines
    title, tags = doc.title, doc.tags
    if doc.has_markers:
        # 파일 단위 필드도 범위 밖 블록에서 온 것은 쓰지 않는다 — 제목 줄·인라인 태그가 다른 프로젝트 블록에 있을 수 있다
        if doc.title_line and not any(u.start <= doc.title_line <= u.end for u in units):
            title = Path(doc.rel).stem
        inline = "\n".join(lines[n - 1] for u in units for n in range(u.start, u.end + 1))
        tags = sorted(set(doc.meta_tags) | {t.lower() for t in _INLINE_TAG_RE.findall(inline)})
    title_l, path_l = title.lower(), doc.rel.lower()
    tags_l, summary_l = " ".join(tags), doc.summary.lower()
    # (unit 번호, 줄 번호, 소문자 줄) — 범위 밖 블록 줄은 아예 들어오지 않는다
    body: list[tuple[int, int, str]] = [
        (ui, n, lines[n - 1].lower()) for ui, u in enumerate(units) for n in range(u.start, u.end + 1)
    ]
    matched_fields: dict[str, list[str]] = {}
    freq = 0
    line_hits: list[set[int]] = []
    for _, _, text in body:
        line_hits.append({ti for ti, t in enumerate(tokens) if t in text})
    for ti, token in enumerate(tokens):
        fields = []
        if token in title_l:
            fields.append("title")
        if token in path_l:
            fields.append("path")
        if token in tags_l:
            fields.append("tags")
        if token in summary_l:
            fields.append("summary")
        count = sum(text.count(token) for _, _, text in body)
        if count:
            fields.append("body")
        if fields:
            matched_fields[token] = fields
            freq += min(count, _FREQ_CAP) + (2 if "title" in fields else 0)
    coverage = len(matched_fields)
    if coverage == 0:
        return None

    windows: list[tuple[int, int, int, bool]] = []  # (distinct, start_idx, end_idx, phrase)
    for i, hits in enumerate(line_hits):
        if not hits:
            continue
        unit_i = body[i][0]
        acc: set[int] = set()
        last = i
        for j in range(i, min(i + _WINDOW_LINES, len(body))):
            if body[j][0] != unit_i or body[j][1] - body[i][1] >= _WINDOW_LINES:
                break
            if line_hits[j]:
                acc |= line_hits[j]
                last = j
        has_phrase = any(phrase in body[k][2] for k in range(i, last + 1)) if len(tokens) > 1 else True
        windows.append((len(acc), i, last, has_phrase))
    window_best = max((w[0] for w in windows), default=0)
    if len(tokens) > 1:
        has_phrase = phrase in title_l or any(w[3] for w in windows)
    else:
        has_phrase = True  # 토큰 하나면 구절 일치는 토큰 일치와 같다 — 그룹을 가르지 않는다
    excerpts = _excerpts(doc, body, line_hits, windows, tokens)
    return _Scored(doc, units, coverage, window_best, has_phrase, freq, matched_fields, excerpts, title=title)


def _excerpts(doc: _Doc, body, line_hits, windows, tokens) -> list[dict]:
    """좋은 창부터 발췌한다. 겹침은 창이 아니라 **실제로 낸 줄 범위**로 판정한다 — 800자에 맞추려고 덜어낸
    뒷줄(omitted_lines)의 근거가 다음 발췌로 살아남게 하려는 것이다."""
    out: list[dict] = []
    spans: list[tuple[int, int]] = []
    for distinct, start, end, has_phrase in sorted(windows, key=lambda w: (-w[0], not w[3], w[1])):
        first_no = body[start][1]
        if any(s <= first_no <= e for s, e in spans):
            continue
        excerpt = _render_excerpt(doc, body, line_hits, start, end, tokens)
        span = (excerpt["start_line"], excerpt["end_line"])
        if any(not (span[1] < s or span[0] > e) for s, e in spans):
            continue
        out.append(excerpt)
        spans.append(span)
        if len(out) >= EXCERPTS_PER_DOC:
            break
    return sorted(out, key=lambda e: e["start_line"])


def _render_excerpt(doc: _Doc, body, line_hits, start: int, end: int, tokens: list[str]) -> dict:
    lines = doc.source.lines
    first_no, last_no = body[start][1], body[end][1]
    terms = sorted({tokens[t] for k in range(start, end + 1) for t in line_hits[k]}, key=tokens.index)
    texts = [lines[n - 1] for n in range(first_no, last_no + 1)]
    text = "\n".join(texts)
    if len(text) <= EXCERPT_MAX_CHARS:
        return {"start_line": first_no, "end_line": last_no, "text": text, "matched_terms": terms, "truncated": False}
    # 여러 줄이면 뒤 줄부터 덜어낸다 — 첫 일치 줄은 남긴다
    while len(texts) > 1 and len("\n".join(texts)) > EXCERPT_MAX_CHARS:
        texts.pop()
    if len("\n".join(texts)) <= EXCERPT_MAX_CHARS:
        kept_last = first_no + len(texts) - 1
        kept_terms = sorted({t for t in terms if any(t in s.lower() for s in texts)}, key=tokens.index)
        return {"start_line": first_no, "end_line": kept_last, "text": "\n".join(texts),
                "matched_terms": kept_terms, "truncated": True, "omitted_lines": [kept_last + 1, last_no]}
    # 첫 줄 하나가 상한보다 길다 — 줄 일부를 근거처럼 내지 않는다(완전한 줄 단위). 위치·길이만 알리고
    # 원문은 read_note(structured=True, start_line=그 줄, max_chars>=line_chars)로 통째로 읽는다.
    line = texts[0]
    kept_terms = sorted({t for t in terms if t in line.lower()}, key=tokens.index)
    out = {"start_line": first_no, "end_line": first_no, "text": None, "matched_terms": kept_terms,
           "truncated": True, "line_too_long": {"line": first_no, "line_chars": len(line)}}
    if last_no > first_no:
        out["omitted_lines"] = [first_no + 1, last_no]  # 같은 창의 뒷줄 근거 — 다음 발췌나 read_note로 본다
    return out


# ── 중복 출처 ────────────────────────────────────────────────────────────────


def _dup_keys(doc: _Doc) -> list[tuple[str, ...]]:
    """명시적 동일 출처 키. 같은 키를 가진 문서는 대표 하나만 결과로 내고 나머지는 duplicates에 근거째 남긴다.

    - same_content: 본문 바이트·파일명·소속(파일 단위)이 모두 같다 — curator 승격·_Archive 보관은 파일명을
      유지하므로 사본은 이 키가 같다. 파일명이 다르면 본문이 같아도(빈 템플릿 결정 등) 다른 문서로 본다 —
      서로 다른 결정을 한 건으로 숨기지 않기 위해서다. 소속이 다르면 다른 프로젝트의 문서다.
    - same_session_id: 같은 프로젝트·session_id의 세션 원문(10_Worklog/Sessions)과 Process handoff —
      write_session_process가 같은 내용을 두 곳에 쓴다. Plan·결정 후보는 내용이 달라 묶지 않는다.
    """
    keys: list[tuple[str, ...]] = []
    fu = doc.file_unit
    owner = (fu.scope, fu.project.casefold(), "|".join(sorted(c.casefold() for c in fu.conflict_with)))
    body = "\n".join(doc.source.lines[doc.body_start - 1:]).strip()
    if body:
        keys.append(("same_content", hashlib.sha256(body.encode("utf-8")).hexdigest(), Path(doc.rel).name.casefold(), *owner))
    session_id = _str_meta(doc.meta, "session_id") or ""
    if session_id and fu.scope == "project":
        handoff = (_str_meta(doc.meta, "handoff_type") or "").casefold()
        if doc.kind == "session_log" or (doc.kind == "session_handoff" and handoff == "process"):
            keys.append(("same_session_id", session_id, fu.project.casefold()))
    return keys


def _duplicate_entry(item: _Scored, reason: str) -> dict:
    """묶인 사본도 자기 근거(위치·버전·등급·상태·소속·발췌 줄)를 남긴다 — 대표만 보고 사본의 상태를 오인하지 않게."""
    doc = item.doc
    return {
        "path": doc.rel, "reason": reason, "source_version": doc.source.version, "record_tier": doc.tier,
        "status": {"declared": doc.status_declared, "class": doc.status_class},
        "attribution": {"scope": doc.file_unit.scope, "project": _clip(doc.file_unit.project, _EVIDENCE_MAX_CHARS)},
        "excerpt_lines": [[e["start_line"], e["end_line"]] for e in item.excerpts],
    }


def _collapse_duplicates(ranked: list[_Scored]) -> list[_Scored]:
    owner: dict[tuple[str, ...], _Scored] = {}
    out: list[_Scored] = []
    for item in ranked:
        keys = _dup_keys(item.doc)
        hit = next((k for k in keys if k in owner), None)
        if hit is not None:
            owner[hit].duplicates.append(_duplicate_entry(item, hit[0]))
            continue
        for k in keys:
            owner.setdefault(k, item)
        out.append(item)
    return out


# ── 커서 ─────────────────────────────────────────────────────────────────────


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _corpus_digest(kept: list[tuple[_Doc, list[_Unit]]], scan: "_Scan") -> str:
    """cursor가 묶는 스캔 상태 — 범위 필터를 통과한 **모든** 문서(일치 여부와 무관)의 경로·내용 버전·
    상태 class·파일/블록 소속, 그리고 읽기 실패 목록.

    일치 문서만 묶으면 범위 안 다른 문서가 새로 일치하게 되는 변화는 잡지만, 소속 등록부(Context.md·매핑)나
    상태 분류만 바뀐 경우와 앞 페이지가 partial이었다가 회복된 경우를 놓친다. 범위 밖(다른 프로젝트 등) 문서의
    변화는 넣지 않는다 — 그 문서가 범위 안으로 들어오면 이 목록 자체가 바뀐다.
    """
    docs = [[d.rel, d.source.version, d.status_class, d.file_unit.signature(), [u.signature() for u in units]]
            for d, units in kept]
    failed = sorted(w.get("path", "") for w in scan.warnings if w.get("code") == "read_failed")
    return _digest({"docs": docs, "failed": failed, "partial": scan.partial})


def _encode_cursor(fingerprint: str, corpus: str, offset: int) -> str:
    raw = json.dumps({"v": _CURSOR_VERSION, "f": fingerprint, "c": corpus, "o": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeError):
        raise SearchArgumentError("cursor_invalid", "cursor를 해석하지 못했습니다. cursor 없이 다시 검색하세요.")
    if not isinstance(data, dict) or data.get("v") != _CURSOR_VERSION or not isinstance(data.get("o"), int) or data["o"] < 0:
        raise SearchArgumentError("cursor_invalid", "지원하지 않는 cursor입니다. cursor 없이 다시 검색하세요.")
    return data


# ── 응답 조립 ────────────────────────────────────────────────────────────────


def _ev(items: list[str]) -> list[str]:
    return [_clip(e, _EVIDENCE_MAX_CHARS) for e in items]


def _attribution_dict(doc: _Doc, units: list[_Unit], blocks_cap: int = _BLOCKS_CAP) -> dict:
    fu = doc.file_unit
    out: dict[str, Any] = {"scope": fu.scope, "project": _clip(fu.project, _EVIDENCE_MAX_CHARS), "evidence": _ev(fu.evidence)}
    if fu.conflict_with:
        out["conflict_with"] = [_clip(c, _EVIDENCE_MAX_CHARS) for c in fu.conflict_with]
    if doc.has_markers:
        shown = units[:blocks_cap]
        out["blocks"] = [
            {"lines": [u.start, u.end], "scope": u.scope, "project": _clip(u.project, _EVIDENCE_MAX_CHARS), "evidence": _ev(u.evidence),
             **({"invalid_marker": True} if u.invalid_marker else {})}
            for u in shown
        ]
        if len(units) > len(shown):
            rest = units[len(shown):]
            # 생략한 포함 블록의 개수와 줄 범위 — 목록 대신 범위만 남겨 크기를 고정한다
            out["blocks_omitted"] = {"count": len(rest), "first_line": rest[0].start, "last_line": rest[-1].end}
        out["blocks_excluded"] = len(doc.units) - len(units)
    return out


def _result_dict(rank: int, item: _Scored, tokens: list[str]) -> dict:
    doc = item.doc
    out = {
        "rank": rank,
        "path": doc.rel,
        "title": _clip(item.title, _TITLE_MAX_CHARS),
        "kind": doc.kind,
        "kind_source": "path",
        "declared_type": doc.declared_type,
        "record_tier": doc.tier,
        "status": {"declared": doc.status_declared, "class": doc.status_class, "reason": doc.status_reason},
        "attribution": _attribution_dict(doc, item.units),
        "time": {"value": doc.time_value, "source": doc.time_source},
        "relevance": {
            "token_coverage": f"{item.coverage}/{len(tokens)}",
            "window_coverage": f"{item.window}/{len(tokens)}",
            "phrase": item.phrase,
            "group": [item.coverage, item.window, int(item.phrase)],
        },
        "matched_terms": list(item.matched_fields),
        "matched_fields": item.matched_fields,
        "excerpts": item.excerpts,
        "source_version": doc.source.version,
        "total_lines": doc.source.total_lines,
    }
    if item.duplicates:
        out["duplicates"] = item.duplicates[:_DUPLICATES_CAP]
        if len(item.duplicates) > _DUPLICATES_CAP:
            out["duplicates_omitted"] = len(item.duplicates) - _DUPLICATES_CAP
    if doc.warnings:
        out["warnings"] = doc.warnings[:_DOC_WARNINGS_CAP]
        if len(doc.warnings) > _DOC_WARNINGS_CAP:
            out["warnings_omitted"] = len(doc.warnings) - _DOC_WARNINGS_CAP
    return out


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _minimal(entry: dict) -> dict:
    """예산에 안 들어가는 결과의 최소형 — 발췌·중복 목록·문서 경고를 빼고 개수만 남긴다."""
    out = dict(entry, excerpts=[], excerpts_trimmed=True)
    if "duplicates" in out:
        out["duplicates_omitted"] = len(out.pop("duplicates")) + entry.get("duplicates_omitted", 0)
    if "warnings" in out:
        out["warnings_omitted"] = len(out.pop("warnings")) + entry.get("warnings_omitted", 0)
    return out


def _compact(entry: dict, item: "_Scored") -> dict:
    """최소형도 예산에 안 들어갈 때의 압축형 — 위치·버전·소속만 남긴다. 나머지는 read_note로 본다."""
    att = entry["attribution"]
    out = {
        "rank": entry["rank"], "path": entry["path"], "title": _clip(entry["title"], 80), "kind": entry["kind"],
        "record_tier": entry["record_tier"], "status": {"class": entry["status"]["class"]},
        "attribution": {"scope": att["scope"], "project": att["project"]},
        "relevance": {"group": entry["relevance"]["group"]},
        "excerpts": [], "excerpt_lines": [[e["start_line"], e["end_line"]] for e in item.excerpts],
        "source_version": entry["source_version"], "total_lines": entry["total_lines"], "compacted": True,
    }
    if item.doc.has_markers:
        out["attribution"]["blocks_count"] = len(item.units)
    return out


def _size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def search(
    vault_dir: Path,
    query: str,
    *,
    project: str = "",
    include_common: bool = False,
    include_unattributed: bool = False,
    include_history: bool = False,
    kinds: list[str] | None = None,
    limit: int | None = None,
    cursor: str = "",
    max_chars: int | None = None,
    project_map: str = "",
) -> dict:
    """structured 검색. 인자 오류·식별 실패·cursor 무효는 ok=False 응답으로 돌려준다 (예외로 숨기지 않는다)."""
    started = time.perf_counter()
    project, cursor = project or "", cursor or ""
    try:
        limit = DEFAULT_LIMIT if limit is None else limit
        max_chars = DEFAULT_MAX_CHARS if max_chars is None else max_chars
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise SearchArgumentError("invalid_argument", f"limit은 1~{MAX_LIMIT}입니다 (기본 {DEFAULT_LIMIT}).")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not MIN_MAX_CHARS <= max_chars <= DEFAULT_MAX_CHARS:
            raise SearchArgumentError("invalid_argument", f"max_chars는 {MIN_MAX_CHARS}~{DEFAULT_MAX_CHARS}입니다 (기본 {DEFAULT_MAX_CHARS}).")
        wanted_kinds = tuple(sorted({k.strip() for k in (kinds or []) if k and k.strip()}))
        unknown_kinds = [k for k in wanted_kinds if k not in KINDS]
        if unknown_kinds:
            raise SearchArgumentError("invalid_argument", f"알 수 없는 kinds: {unknown_kinds}. 허용: {list(KINDS)}")
        if not project.strip() and (include_common or include_unattributed):
            raise SearchArgumentError(
                "invalid_argument", "include_common/include_unattributed는 project를 줄 때만 의미가 있습니다 (project 없으면 vault 전체)."
            )
        if len(query or "") > MAX_QUERY_CHARS or len(project) > MAX_QUERY_CHARS:
            raise SearchArgumentError("invalid_argument", f"query·project는 {MAX_QUERY_CHARS}자 이하입니다.")
        tokens = query_tokens(query or "")
        if not tokens:
            raise SearchArgumentError("invalid_argument", "검색어에 2글자 이상인 단어가 없습니다.")
        if len(tokens) > MAX_QUERY_TOKENS:
            raise SearchArgumentError("invalid_argument", f"검색어 단어는 {MAX_QUERY_TOKENS}개 이하입니다.")
        cursor_data = _decode_cursor(cursor) if cursor.strip() else None
    except SearchArgumentError as exc:
        return _error(exc.code, str(exc))

    # 등록부는 한 번만 읽는다 — 식별과 소속 판정이 서로 다른 시점의 등록부를 보면 범위와 보고가 어긋난다
    reg = load_registry(vault_dir, project_map)
    resolution: ProjectResolution | None = None
    resolved_project = ""
    if project.strip():
        resolution = resolve_project(vault_dir, project, project_map, registry=reg)
        if resolution.status != "resolved":
            return _error(
                f"project_{resolution.status}",
                "프로젝트를 명시적 근거로 확정하지 못해 검색하지 않았습니다. 범위를 넓혀 대신 검색하지 않습니다.",
                project_resolution=_resolution_dict(resolution),
            )
        resolved_project = resolution.project
    scope = SearchScope(resolved_project, include_common, include_unattributed, include_history, wanted_kinds)

    scan = scan_vault(vault_dir, reg)
    kept, filtered = _filter(scan.docs, scope)
    phrase = _phrase(query)
    scored = [s for doc, units in kept if (s := _score(doc, units, tokens, phrase)) is not None]
    scored.sort(key=_Scored.sort_key)
    ranked = _collapse_duplicates(scored)

    fingerprint = _digest({"q": " ".join(query.split()), "p": resolved_project.casefold(), "c": include_common,
                           "u": include_unattributed, "h": include_history, "k": list(wanted_kinds)})
    corpus = _corpus_digest(kept, scan)
    offset = 0
    if cursor_data is not None:
        if cursor_data.get("f") != fingerprint:
            return _error("cursor_mismatch", "cursor가 만들어진 검색 조건(query·project·include_*·kinds)과 다릅니다. 같은 조건으로 넘기거나 cursor 없이 다시 검색하세요.")
        if cursor_data.get("c") != corpus:
            return _error("cursor_stale", "cursor 이후 일치 문서 집합이나 내용 버전이 바뀌었습니다. 순위가 달라졌을 수 있어 이어 주지 않습니다 — cursor 없이 다시 검색하세요.")
        offset = cursor_data["o"]

    warnings = list(scan.warnings) + [{"code": "registry", "message": w} for w in reg.warnings]
    if resolution is not None:
        warnings += [{"code": "project_resolution", "message": w} for w in resolution.warnings if w not in reg.warnings]
    if not ranked:
        warnings.append({"code": "no_match_in_scope", "message": "적용 범위 안에 일치하는 문서가 없습니다. 범위를 자동으로 넓히지 않았습니다 — filtered를 보고 include_* 를 직접 정하세요."})
    omitted_warnings = max(0, len(warnings) - _WARNINGS_CAP)
    warnings = warnings[:_WARNINGS_CAP]

    response: dict[str, Any] = {
        "ok": True,
        "query": query,
        "tokens": tokens,
        "scope": {
            "project": resolved_project,
            "project_resolution": _resolution_dict(resolution) if resolution else None,
            "include_common": include_common,
            "include_unattributed": include_unattributed,
            "include_history": include_history,
            "kinds": list(wanted_kinds),
            "read_prefixes": list(ALLOWED_READ_PREFIXES),
        },
        "filtered": filtered,
        "offset": offset,
        "returned": 0,
        # 스캔이 완전하지 않으면(읽기 실패) 전체 일치 수를 모른다 — 숫자를 만들지 않는다
        "total_matches": None if scan.partial else len(ranked),
        "has_more": False,
        "next_cursor": None,
        "partial": scan.partial,
        "warnings": warnings,
        "warnings_omitted": omitted_warnings,
        "budget": {"max_chars": max_chars, "used_chars": 0, "stopped_by": "end", "excerpt_max_chars": EXCERPT_MAX_CHARS,
                   "excerpts_per_doc": EXCERPTS_PER_DOC},
        "results": [],
        "elapsed_ms": 0,
    }
    page = ranked[offset:offset + limit]
    results: list[dict] = response["results"]
    stopped_by = "end" if offset + limit >= len(ranked) else "limit"
    # 예산은 최종 응답 크기로 잰다 — 나중에 채울 cursor·숫자 칸을 최대 길이로 먼저 채워 둔다
    response["next_cursor"] = _encode_cursor(fingerprint, corpus, 10**9)
    response["elapsed_ms"] = response["budget"]["used_chars"] = 10**9

    def fits() -> bool:
        return _size(response) <= max_chars

    for i, item in enumerate(page):
        entry = _result_dict(offset + i + 1, item, tokens)
        results.append(entry)
        if fits():
            continue
        # 넘치면 발췌를 줄여 본다. 첫 결과는 발췌를 비워서라도 낸다 — 0건 페이지가 무한 이어읽기를 만들지 않게
        results.pop()
        trimmed = dict(entry, excerpts=entry["excerpts"][:1], excerpts_trimmed=True)
        results.append(trimmed)
        if fits():
            stopped_by = "budget"
            break
        results.pop()
        if not results:
            # 첫 결과는 줄여서라도 낸다 — 0건 페이지가 무한 이어받기를 만들지 않게. 최소형 → 압축형 순으로 줄인다
            warnings.insert(0, {"code": "budget_exceeded", "message": "결과 1건이 예산 안에 들어가지 않아 줄여서 냈습니다. 발췌 위치(excerpt_lines)나 read_note로 원문을 읽으세요."})
            minimal = _minimal(entry)
            minimal["attribution"] = _attribution_dict(item.doc, item.units, blocks_cap=1)
            results.append(minimal)
            if not fits():
                results[-1] = _compact(entry, item)
        stopped_by = "budget"
        break
    # 응답 공통부(경고)가 길어 넘치면 뒤 경고부터 개수로 바꾼다
    while not fits() and warnings:
        warnings.pop()
        response["warnings_omitted"] += 1
    if not fits():
        # 상한을 넘는 응답을 성공으로 내지 않는다 (압축형 1건 + 고정부도 안 들어가는 아주 작은 max_chars나 비정상 경로 길이)
        return _error("budget_too_small", f"max_chars {max_chars}에 결과 1건도 들어가지 않습니다. max_chars를 늘리세요.",
                      needed_chars=_size(response))
    returned = len(results)
    next_offset = offset + returned
    response["returned"] = returned
    response["has_more"] = next_offset < len(ranked)
    response["next_cursor"] = _encode_cursor(fingerprint, corpus, next_offset) if response["has_more"] else None
    response["budget"]["stopped_by"] = stopped_by if response["has_more"] else "end"
    response["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    # used_chars 자기 자릿수까지 포함한 크기 — 몇 번이면 고정점에 닿는다
    used = 0
    for _ in range(4):
        response["budget"]["used_chars"] = used
        size = _size(response)
        if size == used:
            break
        used = size
    return response


def _resolution_dict(res: ProjectResolution | None) -> dict | None:
    if res is None:
        return None
    return {
        "input": res.input, "status": res.status, "project": res.project, "method": res.method,
        "evidence": _ev(res.evidence), "candidates": res.candidates, "hint": res.hint,
    }
