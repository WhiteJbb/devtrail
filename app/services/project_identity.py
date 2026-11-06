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
import os
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


def project_field(mapping: object) -> tuple[str, bool]:
    """frontmatter·marker JSON·.claude/vault.json의 `project` 값을 읽는 **유일한** 규칙 — 식별과 소속 판정이 같이 쓴다.

    문자열만 프로젝트 이름으로 인정한다. 반환은 (이름, 형식 미지원 여부):
    - 키가 없거나 None·빈 문자열 → ("", False)
    - 문자열 → (앞뒤 공백을 뺀 값, False)
    - 숫자·날짜·목록·불리언 등, 짝 없는 surrogate가 든 문자열 → ("", True) — 근거로 쓰지 않는다(호출 측이 경고를 남긴다)
    한쪽은 숫자를 버리고 다른 쪽은 "123"으로 바꾸면, 식별로 확정한 프로젝트가 자기 Context.md를 충돌로 잃는다.
    """
    if not isinstance(mapping, dict):
        return "", False
    value = mapping.get("project")
    if value is None:
        return "", False
    if isinstance(value, str):
        if not is_valid_text(value):
            return "", True
        return value.strip(), False
    return "", True


def is_valid_text(value: str) -> bool:
    """UTF-8로 내보낼 수 있는 문자열인가. JSON `"\\ud800"`·YAML `"\\ud800"` 이스케이프는 짝 없는 surrogate를 만든다 —
    그런 이름을 근거로 쓰면 지문(sha256)·응답 직렬화에서 UnicodeEncodeError로 검색 전체가 멈춘다."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def project_field_issue(mapping: object) -> str:
    """project_field가 형식 미지원으로 본 이유 — 경고 문장에 넣는다 ("project가 <이유> …")."""
    value = mapping.get("project") if isinstance(mapping, dict) else None
    if isinstance(value, str) and not is_valid_text(value):
        return "유효하지 않은 문자(짝 없는 surrogate 등)를 포함해"
    return "문자열이 아니라"


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
    handoff_folders: dict[str, list[str]] = field(default_factory=dict)  # casefold → 폴더명들
    aliases: dict[str, set[str]] = field(default_factory=dict)  # casefold alias → canonical 표기들
    repos: dict[str, set[str]] = field(default_factory=dict)  # casefold owner/repo → canonical 표기들
    warnings: list[str] = field(default_factory=list)
    # 권한 등으로 확인하지 못한 등록부 경로(vault 기준, 폴더는 '/'로 끝난다) → 경고 문장. 이 아래 문서는 경로로 소속을 정하지 않는다
    unreadable: dict[str, str] = field(default_factory=dict)

    def unreadable_prefix(self, rel: str) -> str:
        """rel이 확인하지 못한 등록부 경로 아래면 그 경로, 아니면 빈 문자열."""
        return next((p for p in self.unreadable if rel.startswith(p)), "")

    def may_hide(self, name: str) -> str:
        """등록되지 않은 이름이 확인하지 못한 등록부 경로 때문에 안 보이는 것일 수 있으면 그 경로, 아니면 빈 문자열.

        30_Projects 아래 폴더를 못 읽으면 그 Context.md가 어떤 이름을 선언했는지 모르므로 어떤 이름이든 가릴 수 있다.
        SessionHandoffs는 폴더명이 곧 이름이라, 그 폴더(또는 SessionHandoffs 전체)를 못 읽었을 때만 해당한다.
        """
        key = name.strip().casefold()
        if not self.unreadable or self.is_known(name):
            return ""
        for p in self.unreadable:
            if p.startswith("30_Projects/") or p == f"{_HANDOFF_ROOT}/" or p.casefold() == f"{_HANDOFF_ROOT}/{key}/".casefold():
                return p
        return ""

    def canonical_name(self, name: str) -> str:
        """등록 표기로 바꾼다. 등록이 없으면 입력 표기 그대로 — 소속 비교는 casefold로 한다."""
        key = name.strip().casefold()
        if key in self.display:
            return self.display[key]
        folders = self.handoff_folders.get(key)
        if folders and len(folders) == 1:
            return folders[0]
        return name.strip()

    def attribution_targets(self, name: str) -> list[str]:
        """문서가 선언한 프로젝트 이름(frontmatter·marker·handoff/knowledge 폴더명)의 후보 프로젝트들.

        식별(resolve_project)의 이름 판정(_resolve_name)을 그대로 쓴다 — 등록 표기·SessionHandoffs 폴더·매핑 별칭을
        모두 보고, 같은 이름이 둘 이상을 가리키면(동명 Context.md, 다른 프로젝트의 별칭과 겹침) 후보를 전부 돌려준다.
        빈 목록은 등록 근거가 없는 이름이다. 식별에서는 모호한 이름을 소속 판정에서만 하나로 확정하면, 다른 근거로
        확정한 프로젝트 검색에 모호한 문서가 섞인다.
        """
        _, _, targets = _resolve_name(self, name)
        return sorted(targets, key=str.casefold)

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


def _mark_unreadable(reg: ProjectRegistry, rel: str, exc: OSError, what: str) -> None:
    message = (f"{rel}: {what} 읽지 못해({exc.strerror or exc}) 프로젝트 등록부에서 뺐습니다 — "
               "이 경로 아래 문서는 경로로 소속을 정하지 않습니다.")
    reg.unreadable[rel] = message
    reg.warnings.append(message)


def _list_dir(reg: ProjectRegistry, vault_dir: Path, path: Path) -> list[Path]:
    """등록부 폴더의 항목들(이름순). 권한 등으로 목록을 못 읽으면 경고·미확인 표시를 남기고 빈 목록 —
    폴더 하나 때문에 등록부 전체(그리고 검색 전체)가 멈추지 않게 한다."""
    try:
        if not path.is_dir():
            return []
        with os.scandir(path) as it:
            return sorted((Path(e.path) for e in it), key=lambda p: p.name)
    except OSError as exc:
        _mark_unreadable(reg, path.relative_to(vault_dir).as_posix() + "/", exc, "폴더를")
        return []


def load_registry(vault_dir: Path, map_path: str = "") -> ProjectRegistry:
    reg = ProjectRegistry()
    # 30_Projects/*/Context.md — glob은 하위 폴더의 PermissionError를 경고 없이 삼키거나(3.11 pathlib) 그대로 올린다.
    # 폴더마다 직접 확인해 못 읽은 폴더를 등록부 미확인으로 남긴다.
    for child in _list_dir(reg, vault_dir, vault_dir / "30_Projects"):
        if child.name.startswith("."):
            continue  # 숨김 폴더(.trash 등)는 검색 스캔도 보지 않는다 — 링크 경고로 오인하게 하지 않는다
        ctx_path = child / "Context.md"
        rel = ctx_path.relative_to(vault_dir).as_posix()
        try:
            if not ctx_path.exists():
                continue
        except OSError as exc:
            _mark_unreadable(reg, child.relative_to(vault_dir).as_posix() + "/", exc, "폴더를")
            continue
        # 검색 스캔과 같은 읽기 경계 — 링크로 금지 prefix·vault 밖을 가리키면 내용을 읽지 않는다.
        # 범위 안 다른 위치로의 링크도 읽지 않는다(스캔도 링크 폴더·파일을 따라가지 않으니 소속 근거가 어긋난다).
        if real_scoped_rel(vault_dir, ctx_path) != rel:
            reg.warnings.append(f"{rel}: 실제 경로가 다른 곳(링크)이라 프로젝트 등록부에서 뺐습니다.")
            continue
        name = child.name
        try:
            meta = frontmatter.loads(ctx_path.read_text(encoding="utf-8")).metadata
            declared, unsupported = project_field(meta)
            if unsupported:
                reg.warnings.append(f"{rel}: frontmatter project가 {project_field_issue(meta)} 폴더명으로 식별합니다.")
        except PermissionError as exc:
            # 선언명을 모르는 채 폴더명으로 등록하면 다른 이름을 선언한 프로젝트의 문서를 폴더명 프로젝트로 확정하게 된다.
            # 그 밖의 읽기 실패(Context.md가 폴더 등)는 전처럼 아래에서 폴더명으로 식별한다
            _mark_unreadable(reg, child.relative_to(vault_dir).as_posix() + "/", exc, "Context.md를")
            continue
        except Exception:
            declared = ""
            reg.warnings.append(f"{rel}: frontmatter를 읽지 못해 폴더명으로 식별합니다.")
        name = declared or name
        key = name.casefold()
        reg.canonical.setdefault(key, []).append(rel)
        reg.display.setdefault(key, name)
        reg.dir_to_project[child.name] = name
    for d in _list_dir(reg, vault_dir, vault_dir / _HANDOFF_ROOT):
        if d.name.startswith((".", "_")):
            continue
        rel = d.relative_to(vault_dir).as_posix()
        try:
            if not d.is_dir():
                continue
        except OSError as exc:
            _mark_unreadable(reg, rel + "/", exc, "폴더를")
            continue
        if real_scoped_rel(vault_dir, d) != rel:
            reg.warnings.append(f"{rel}/: 실제 경로가 다른 곳(링크)이라 프로젝트 등록부에서 뺐습니다.")
            continue
        reg.handoff_folders.setdefault(d.name.casefold(), []).append(d.name)
    if map_path.strip():
        _load_map(reg, Path(map_path.strip()).expanduser())
    return reg


def _load_map(reg: ProjectRegistry, path: Path) -> None:
    """식별 매핑 파일을 읽는다. 형식이 틀리면 무시하고 경고만 남긴다 — 매핑 없이 canonical 식별은 계속된다."""
    try:
        if not path.is_file():
            reg.warnings.append(f"프로젝트 식별 매핑 파일이 없습니다: {path}")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        # 다른 인코딩을 추정해 읽지 않는다 — 잘못 읽은 별칭·repo가 프로젝트를 잘못 확정할 수 있다
        reg.warnings.append(f"프로젝트 식별 매핑 파일이 UTF-8이 아니라 무시합니다 ({exc.start}바이트 위치): {path}")
        return
    except (OSError, json.JSONDecodeError) as exc:
        reg.warnings.append(f"프로젝트 식별 매핑 파일을 읽지 못했습니다: {exc}")
        return
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        reg.warnings.append("프로젝트 식별 매핑 파일에 projects 객체가 없습니다.")
        return
    for project, spec in projects.items():
        if not is_valid_text(project):
            reg.warnings.append(f"매핑 {project!r}: 프로젝트 이름에 유효하지 않은 문자(짝 없는 surrogate 등)가 있어 무시합니다.")
            continue
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
    if not all(is_valid_text(v) for v in value):
        # 이름 하나만 빼면 나머지로 다른 프로젝트를 확정할 수 있다 — 그 목록 전체를 쓰지 않는다
        reg.warnings.append(f"매핑 {project!r}: {key}에 유효하지 않은 문자(짝 없는 surrogate 등)가 있어 무시합니다.")
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
    except UnicodeDecodeError:
        return "", ".claude/vault.json이 UTF-8이 아니라 무시합니다."
    except (OSError, json.JSONDecodeError):
        return "", ".claude/vault.json을 해석하지 못했습니다."
    if not isinstance(data, dict):
        return "", ".claude/vault.json이 객체가 아닙니다."
    project, unsupported = project_field(data)
    if unsupported:
        return "", f".claude/vault.json의 project가 {project_field_issue(data)} 식별 근거로 쓰지 않았습니다."
    return project, ""


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
