"""프로젝트 식별 — 명시적 근거로만 프로젝트를 확정한다.

인정하는 근거 (이 순서로 본다):
- canonical: 30_Projects/<dir>/Context.md가 선언한 프로젝트명 (frontmatter project, 없으면 폴더명)과 대소문자 무시 일치
- handoff_folder: 60_Candidates/SessionHandoffs/<P>/ 폴더명과 일치 (Context.md 없이 세션 기록만 있는 프로젝트)
- alias: 식별 매핑 파일(DEVTRAIL_PROJECT_MAP)의 aliases
- local_mapping: repo 디렉터리의 `.claude/vault.json` {"project": ...}
- repo_mapping: owner/repo (직접 입력 또는 repo의 .git/config remote URL) → 매핑 파일의 repos

인정하지 않는 것: repo 디렉터리 basename이 프로젝트명과 같다는 사실. basename은 `hint`로만 돌려준다 —
같은 이름의 다른 저장소(fork, 동명 개인 repo)를 그 프로젝트로 확정하면 다른 프로젝트 근거가 섞인다.

매핑 파일은 식별 전용이다. 프로젝트 상태·설명을 복제하지 않는다 (docs/examples/project-map.example.json).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from app.services.vault_source import real_scoped_rel

_HANDOFF_ROOT = "60_Candidates/SessionHandoffs"
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")
_REMOTE_URL_RE = re.compile(r"(?:[:/])([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")
_GIT_REMOTE_RE = re.compile(r'^\s*\[remote\s+"([^"]+)"\]\s*$')
_GIT_URL_RE = re.compile(r"^\s*url\s*=\s*(\S+)\s*$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ProjectResolution:
    """식별 결과. status가 resolved일 때만 project를 검색 범위로 쓴다."""

    input: str
    status: str  # resolved | unresolved | ambiguous | conflict | unregistered | invalid
    project: str = ""
    method: str = ""  # canonical | handoff_folder | alias | local_mapping | repo_mapping
    evidence: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    hint: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProjectRegistry:
    """vault와 매핑 파일에서 읽은 식별 근거 모음 (요청마다 새로 읽는다 — 서버가 오래 살아 있다)."""

    # casefold 이름 → 그 이름을 선언한 Context.md rel_path 목록 (2개 이상이면 동명)
    canonical: dict[str, list[str]] = field(default_factory=dict)
    display: dict[str, str] = field(default_factory=dict)  # casefold → 표기
    dir_to_project: dict[str, str] = field(default_factory=dict)  # 30_Projects 폴더명 → 표기
    dir_display: dict[str, str] = field(default_factory=dict)  # casefold 폴더명 → 그 Context.md가 선언한 표기
    handoff_folders: dict[str, list[str]] = field(default_factory=dict)  # casefold → 폴더명들
    aliases: dict[str, set[str]] = field(default_factory=dict)  # casefold alias → canonical 표기들
    repos: dict[str, set[str]] = field(default_factory=dict)  # casefold owner/repo → canonical 표기들
    warnings: list[str] = field(default_factory=list)

    def canonical_name(self, name: str) -> str:
        """등록 표기로 바꾼다. 등록이 없으면 입력 표기 그대로 — 소속 비교는 casefold로 한다."""
        key = name.strip().casefold()
        if key in self.display:
            return self.display[key]
        folders = self.handoff_folders.get(key)
        if folders and len(folders) == 1:
            return folders[0]
        return name.strip()

    def attribution_name(self, name: str) -> str:
        """문서가 선언한 프로젝트 이름(frontmatter·marker)을 소속 비교용 표기로 바꾼다.

        식별(resolve_project)이 인정하는 근거와 맞춘다: 등록 표기 → 30_Projects 폴더명(그 Context.md가 선언한 이름) →
        SessionHandoffs 폴더 → 매핑 별칭(가리키는 프로젝트가 하나일 때만). 어느 것도 아니면 입력 그대로다.
        """
        key = name.strip().casefold()
        if key in self.display:
            return self.display[key]
        if key in self.dir_display:
            return self.dir_display[key]
        folders = self.handoff_folders.get(key)
        if folders and len(folders) == 1:
            return folders[0]
        targets = self.aliases.get(key, set())
        if len(targets) == 1:
            return next(iter(targets))
        return name.strip()

    def is_known(self, name: str) -> bool:
        key = name.strip().casefold()
        return key in self.canonical or key in self.handoff_folders

    def same_name_sources(self, name: str) -> list[str]:
        """같은 이름(대소문자 무시)을 선언한 근거가 둘 이상이면 그 목록 — 어느 경로로 가리켜도 하나로 확정할 수 없다."""
        key = name.strip().casefold()
        if key in self.canonical:
            rels = self.canonical[key]
            return [f"context:{r}" for r in rels] if len(rels) > 1 else []
        folders = self.handoff_folders.get(key, [])
        return [f"handoff_folder:{_HANDOFF_ROOT}/{f}" for f in folders] if len(folders) > 1 else []

    def known_projects(self) -> list[str]:
        names = {self.display[k] for k in self.canonical}
        names.update(f for folders in self.handoff_folders.values() for f in folders)
        return sorted(names, key=str.casefold)


def load_registry(vault_dir: Path, map_path: str = "") -> ProjectRegistry:
    reg = ProjectRegistry()
    projects_dir = vault_dir / "30_Projects"
    if projects_dir.is_dir():
        for ctx_path in sorted(projects_dir.glob("*/Context.md")):
            if ctx_path.parent.name.startswith("."):
                continue  # 숨김 폴더(.trash 등)는 검색 스캔도 보지 않는다 — 링크 경고로 오인하게 하지 않는다
            rel = ctx_path.relative_to(vault_dir).as_posix()
            # 검색 스캔과 같은 읽기 경계 — 링크로 금지 prefix·vault 밖을 가리키면 내용을 읽지 않는다.
            # 범위 안 다른 위치로의 링크도 읽지 않는다(스캔도 링크 폴더·파일을 따라가지 않으니 소속 근거가 어긋난다).
            if real_scoped_rel(vault_dir, ctx_path) != rel:
                reg.warnings.append(f"{rel}: 실제 경로가 다른 곳(링크)이라 프로젝트 등록부에서 뺐습니다.")
                continue
            name = ctx_path.parent.name
            try:
                meta = frontmatter.loads(ctx_path.read_text(encoding="utf-8")).metadata
                value = meta.get("project") if isinstance(meta, dict) else None
                declared = value.strip() if isinstance(value, str) else ""
                if value not in (None, "") and not isinstance(value, str):
                    reg.warnings.append(f"{rel}: frontmatter project가 문자열이 아니라 폴더명으로 식별합니다.")
            except Exception:
                declared = ""
                reg.warnings.append(f"{rel}: frontmatter를 읽지 못해 폴더명으로 식별합니다.")
            name = declared or name
            key = name.casefold()
            reg.canonical.setdefault(key, []).append(rel)
            reg.display.setdefault(key, name)
            reg.dir_to_project[ctx_path.parent.name] = name
            reg.dir_display.setdefault(ctx_path.parent.name.casefold(), name)
    handoff_root = vault_dir / _HANDOFF_ROOT
    if handoff_root.is_dir():
        for d in sorted(handoff_root.iterdir()):
            if d.is_dir() and not d.name.startswith((".", "_")):
                rel = d.relative_to(vault_dir).as_posix()
                if real_scoped_rel(vault_dir, d) != rel:
                    reg.warnings.append(f"{rel}/: 실제 경로가 다른 곳(링크)이라 프로젝트 등록부에서 뺐습니다.")
                    continue
                reg.handoff_folders.setdefault(d.name.casefold(), []).append(d.name)
    if map_path.strip():
        _load_map(reg, Path(map_path.strip()).expanduser())
    return reg


def _load_map(reg: ProjectRegistry, path: Path) -> None:
    """식별 매핑 파일을 읽는다. 형식이 틀리면 무시하고 경고만 남긴다 — 매핑 없이 canonical 식별은 계속된다."""
    if not path.is_file():
        reg.warnings.append(f"프로젝트 식별 매핑 파일이 없습니다: {path}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reg.warnings.append(f"프로젝트 식별 매핑 파일을 읽지 못했습니다: {exc}")
        return
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        reg.warnings.append("프로젝트 식별 매핑 파일에 projects 객체가 없습니다.")
        return
    for project, spec in projects.items():
        if not isinstance(spec, dict):
            reg.warnings.append(f"매핑 {project!r}: 객체가 아니라 무시합니다.")
            continue
        canonical = reg.canonical_name(str(project))
        if not reg.is_known(canonical):
            reg.warnings.append(f"매핑 {project!r}: vault에 등록되지 않은 프로젝트입니다 (Context.md·SessionHandoffs 없음).")
        aliases, repos = _str_list(reg, project, spec, "aliases"), _str_list(reg, project, spec, "repos")
        for alias in aliases:
            reg.aliases.setdefault(alias.casefold(), set()).add(canonical)
        for repo in repos:
            owner_repo = _owner_repo(repo)
            if owner_repo:
                reg.repos.setdefault(owner_repo, set()).add(canonical)
            else:
                reg.warnings.append(f"매핑 {project!r}: owner/repo 형식이 아닌 repos 항목 {repo!r}를 무시합니다.")


def _str_list(reg: ProjectRegistry, project: str, spec: dict, key: str) -> list[str]:
    """매핑의 aliases/repos는 문자열 목록만 받는다. 문자열 하나를 글자 단위 별칭으로 펼치는 일을 막는다."""
    value = spec.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        reg.warnings.append(f"매핑 {project!r}: {key}는 문자열 목록이어야 해서 무시합니다.")
        return []
    return [v.strip() for v in value if v.strip()]


def _owner_repo(value: str) -> str:
    """'owner/repo', https/ssh remote URL을 casefold된 'owner/repo'로. 형식이 아니면 빈 문자열."""
    value = value.strip()
    if _OWNER_REPO_RE.match(value):
        owner, repo = value.split("/", 1)
        return f"{owner}/{repo.removesuffix('.git')}".casefold()
    if "://" in value or value.startswith("git@"):
        m = _REMOTE_URL_RE.search(value)
        if m:
            return f"{m.group(1)}/{m.group(2)}".casefold()
    return ""


def _git_config_path(repo_dir: Path) -> Path | None:
    git = repo_dir / ".git"
    if git.is_dir():
        return git / "config"
    if git.is_file():  # worktree: "gitdir: <path>" → commondir/config
        try:
            line = git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            gitdir = Path(line[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (repo_dir / gitdir).resolve()
            common = gitdir / "commondir"
            if common.is_file():
                try:
                    gitdir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve()
                except OSError:
                    return None
            return gitdir / "config"
    return None


def repo_remotes(repo_dir: Path) -> list[str]:
    """repo의 remote URL들을 owner/repo로. git 실행 없이 .git/config만 읽는다."""
    config = _git_config_path(repo_dir)
    if config is None or not config.is_file():
        return []
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    in_remote = False
    for line in text.splitlines():
        if line.strip().startswith("["):
            in_remote = bool(_GIT_REMOTE_RE.match(line))
            continue
        m = _GIT_URL_RE.match(line) if in_remote else None
        if m:
            owner_repo = _owner_repo(m.group(1))
            if owner_repo and owner_repo not in found:
                found.append(owner_repo)
    return found


def _local_mapping(repo_dir: Path) -> tuple[str, str]:
    """(project, 경고)."""
    path = repo_dir / ".claude" / "vault.json"
    if not path.is_file():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ".claude/vault.json을 해석하지 못했습니다."
    if not isinstance(data, dict):
        return "", ".claude/vault.json이 객체가 아닙니다."
    return str(data.get("project") or "").strip(), ""


def _resolve_name(reg: ProjectRegistry, name: str) -> tuple[str, list[str], set[str]]:
    """이름 하나를 (method, evidence, 후보 표기 집합)으로. 후보가 2개 이상이면 동명/충돌."""
    key = name.strip().casefold()
    hits: dict[str, list[str]] = {}
    methods: list[str] = []
    if key in reg.canonical:
        rels = reg.canonical[key]
        if len(rels) > 1:
            # 같은 이름(대소문자 무시)을 선언한 Context.md가 둘 이상 — 어느 쪽인지 고를 근거가 없다
            return "canonical", [f"context:{r}" for r in rels], {f"{reg.display[key]} ({r})" for r in rels}
        hits.setdefault(reg.display[key], []).append(f"context:{rels[0]}")
        methods.append("canonical")
    elif key in reg.handoff_folders:
        folders = reg.handoff_folders[key]
        if len(folders) > 1:
            return "handoff_folder", [f"handoff_folder:{f}" for f in folders], set(folders)
        hits.setdefault(folders[0], []).append(f"handoff_folder:{_HANDOFF_ROOT}/{folders[0]}")
        methods.append("handoff_folder")
    for target in sorted(reg.aliases.get(key, set())):
        hits.setdefault(target, []).append(f"alias:{name.strip()}→{target}")
        if "alias" not in methods:
            methods.append("alias")
    if not hits:
        return "", [], set()
    return (methods[0] if len(hits) == 1 else "+".join(methods)), [e for v in hits.values() for e in v], set(hits)


def _finalize(reg: ProjectRegistry, raw: str, target: str, method: str, evidence: list[str], warnings: list[str],
              unregistered_hint: str) -> ProjectResolution:
    """후보 하나로 좁혀진 뒤의 공통 판정 — 별칭·매핑 경로도 직접 이름 입력과 같은 동명·미등록 검사를 거친다."""
    target = reg.canonical_name(target)
    same = reg.same_name_sources(target)
    if same:
        return ProjectResolution(input=raw, status="ambiguous", method=method, evidence=[*evidence, *same],
                                 candidates=sorted(f"{target} ({s.split(':', 1)[1]})" for s in same), warnings=warnings)
    if not reg.is_known(target):
        return ProjectResolution(input=raw, status="unregistered", project=target, method=method, evidence=evidence,
                                 warnings=warnings, hint=unregistered_hint)
    return ProjectResolution(input=raw, status="resolved", project=target, method=method, evidence=evidence, warnings=warnings)


def resolve_project(
    vault_dir: Path, identifier: str, map_path: str = "", registry: ProjectRegistry | None = None
) -> ProjectResolution:
    """identifier(프로젝트명 / 별칭 / owner/repo / repo 디렉터리 경로)를 명시적 근거로만 확정한다.

    registry를 주면 그것을 쓴다 — 검색이 같은 등록부로 식별과 소속 판정을 하게 하려는 것이다.
    """
    raw = identifier or ""
    text = raw.strip()
    if not text:
        return ProjectResolution(input=raw, status="invalid", warnings=["project가 비어 있습니다."])
    reg = registry if registry is not None else load_registry(vault_dir, map_path)
    warnings = list(reg.warnings)

    path = Path(text).expanduser()
    # 경로로 보는 것은 절대·~·./·../ 형태뿐이다. 맨 이름을 서버 cwd 기준 상대경로로 보면 cwd에 같은 이름
    # 디렉터리가 있을 때 canonical 이름 판정을 가로챈다.
    looks_like_path = text.startswith(("/", "~", "./", "../", ".\\", "..\\")) or text in (".", "..") or _DRIVE_PATH_RE.match(text) is not None
    if looks_like_path:
        if not path.is_dir():
            return ProjectResolution(input=raw, status="unresolved", warnings=warnings + [f"디렉터리가 아닙니다: {text}"])
        return _resolve_repo_dir(reg, raw, path, warnings)

    owner_repo = _owner_repo(text)
    if owner_repo and ("/" in text):
        targets = reg.repos.get(owner_repo, set())
        if len(targets) == 1:
            target = next(iter(targets))
            return _finalize(reg, raw, target, "repo_mapping", [f"repo:{owner_repo}→{target}"], warnings,
                             "매핑은 있지만 vault에 Context.md·SessionHandoffs가 없는 프로젝트입니다.")
        if len(targets) > 1:
            return ProjectResolution(
                input=raw, status="conflict", candidates=sorted(targets), method="repo_mapping",
                evidence=[f"repo:{owner_repo}→{t}" for t in sorted(targets)], warnings=warnings,
            )
        return ProjectResolution(
            input=raw, status="unresolved", candidates=reg.known_projects(), warnings=warnings,
            hint="owner/repo가 식별 매핑(DEVTRAIL_PROJECT_MAP)의 repos에 없습니다.",
        )

    method, evidence, targets = _resolve_name(reg, text)
    if len(targets) == 1:
        # 별칭이 가리키는 프로젝트가 vault에 없거나 동명이면 확정하지 않는다
        return _finalize(reg, raw, next(iter(targets)), method, evidence, warnings,
                         "식별 매핑이 가리키는 프로젝트가 vault에 없습니다 (Context.md·SessionHandoffs 없음).")
    if len(targets) > 1:
        return ProjectResolution(
            input=raw, status="ambiguous", candidates=sorted(targets), method=method, evidence=evidence, warnings=warnings
        )
    return ProjectResolution(input=raw, status="unresolved", candidates=reg.known_projects(), warnings=warnings)


def _resolve_repo_dir(reg: ProjectRegistry, raw: str, repo_dir: Path, warnings: list[str]) -> ProjectResolution:
    found: dict[str, list[str]] = {}
    local, local_warning = _local_mapping(repo_dir)
    if local_warning:
        warnings.append(local_warning)
    if local:
        method, evidence, targets = _resolve_name(reg, local)
        if len(targets) > 1:
            return ProjectResolution(
                input=raw, status="ambiguous", candidates=sorted(targets), method="local_mapping",
                evidence=[f"local_mapping:{local}", *evidence], warnings=warnings,
            )
        target = next(iter(targets)) if targets else local
        found.setdefault(target, []).append(f"local_mapping:.claude/vault.json project={local}")
    for owner_repo in repo_remotes(repo_dir):
        for target in sorted(reg.repos.get(owner_repo, set())):
            found.setdefault(target, []).append(f"repo:{owner_repo}→{target}")

    evidence = [e for v in found.values() for e in v]
    # 같은 프로젝트를 다른 표기로 가리키는 경우는 충돌이 아니다
    distinct = {name.casefold(): name for name in found}
    if len(distinct) > 1:
        return ProjectResolution(
            input=raw, status="conflict", candidates=sorted(distinct.values()), evidence=evidence, warnings=warnings,
        )
    if len(distinct) == 1:
        return _finalize(reg, raw, next(iter(distinct.values())), "local_mapping" if local else "repo_mapping",
                         evidence, warnings, "매핑은 있지만 vault에 Context.md·SessionHandoffs가 없는 프로젝트입니다.")

    hint = ""
    basename_key = repo_dir.resolve().name.casefold()
    if basename_key in reg.canonical or basename_key in reg.handoff_folders:
        hint = (
            f"디렉터리 이름이 프로젝트 '{reg.canonical_name(repo_dir.resolve().name)}'와 같지만 이름만으로는 확정하지 않습니다. "
            ".claude/vault.json 또는 식별 매핑의 repos에 등록하거나 프로젝트명을 직접 넘기세요."
        )
    return ProjectResolution(
        input=raw, status="unresolved", candidates=reg.known_projects(), warnings=warnings, hint=hint,
    )
