"""머신별 devtrail 설치·연동 상태 진단과 자동 수리.

이 커맨드가 존재하는 이유: `.claude/settings.json`(훅 활성)과 `.claude/vault.json`
(프로젝트 매핑)은 `.gitignore`의 `.claude/*`에 걸려 git에 없다. 클론만 하면 두 파일이
없고, **없어도 아무 경고가 나오지 않는다.** 2026-08 한 달간 노트북에서 작업했지만
훅이 없어 세션 기록이 0건이었고 그 사실을 아무도 몰랐다 — 조용한 실패다.

점검은 서로 독립적인 함수로 쪼개 둔다. 하나가 예외를 던져도 나머지 진단이 계속돼야
한다: 진단 도구가 진단 대상보다 잘 깨지면 쓸 수 없다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

Severity = str  # "ok" | "warn" | "fail" | "unknown"

OK: Severity = "ok"
WARN: Severity = "warn"
FAIL: Severity = "fail"
UNKNOWN: Severity = "unknown"

MCP_SERVER_NAME = "devtrail-vault"
MCP_ADD_COMMAND = f"claude mcp add {MCP_SERVER_NAME} -- devtrail mcp-serve"


@dataclass(frozen=True)
class CheckResult:
    """점검 하나의 결과.

    fixable=True는 `repair()`가 사람 판단 없이 고칠 수 있다는 뜻이다. `.env` 편집이나
    외부 CLI 상태 변경(claude mcp add)은 fixable이 아니다 — hint로만 안내한다.
    """

    name: str
    severity: Severity
    detail: str
    hint: str = ""
    fixable: bool = False


@dataclass
class DoctorReport:
    repo_dir: Path
    vault_dir: Path | None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == FAIL]

    @property
    def fixable(self) -> list[CheckResult]:
        return [c for c in self.checks if c.fixable]

    @property
    def healthy(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class RepairResult:
    name: str
    changed: bool
    detail: str


# ── 개별 점검 ────────────────────────────────────────────────────────────────


def check_vault_path(vault_root: str) -> CheckResult:
    if not vault_root:
        return CheckResult(
            "vault 경로",
            FAIL,
            ".env의 OBSIDIAN_VAULT_PATH가 비어 있습니다",
            hint=".env에 OBSIDIAN_VAULT_PATH=<vault 경로>를 추가하세요 (install 스크립트가 만드는 값)",
        )
    path = Path(vault_root)
    if not path.is_dir():
        return CheckResult(
            "vault 경로",
            FAIL,
            f"경로가 존재하지 않습니다: {vault_root}",
            hint="Vault repo를 clone했는지, 드라이브가 마운트됐는지 확인하세요",
        )
    return CheckResult("vault 경로", OK, str(path))


def check_hook_settings(repo_dir: Path) -> CheckResult:
    """`.claude/settings.json` 존재 여부 — 이번 사고의 직접 원인.

    severity는 FAIL이 아니라 WARN이다. Mac 봇 서버처럼 Claude Code 세션을 열지 않는
    노드에서는 훅이 불필요하다는 결정이 2026-07-08에 있었다(Decision: "Mac에서는
    Claude Code 훅 활성화를 하지 않기로 함"). 머신 용도를 코드가 알 수 없으므로
    판단은 사람에게 남기고 사실만 보고한다.
    """
    settings = repo_dir / ".claude" / "settings.json"
    example = repo_dir / ".claude" / "settings.example.json"
    if settings.exists():
        return CheckResult("Claude Code 훅", OK, str(settings))
    if not example.exists():
        return CheckResult(
            "Claude Code 훅",
            WARN,
            "settings.json도 settings.example.json도 없습니다",
            hint="repo가 온전한지 확인하세요 (git status)",
        )
    return CheckResult(
        "Claude Code 훅",
        WARN,
        "settings.json 없음 — plan-check · session-start-briefing · stop-process-check가 전부 비활성",
        hint="Claude Code 세션을 여는 머신이면 --fix로 복사하세요 (봇 서버 전용 노드는 불필요)",
        fixable=True,
    )


def check_project_mapping(repo_dir: Path, vault_dir: Path | None) -> CheckResult:
    """`.claude/vault.json`의 project가 Vault에 실재하는지까지 본다.

    파일만 있고 값이 실재하지 않으면 briefing이 조용히 빈 값을 반환한다 — 있는데
    안 맞는 상태가 없는 상태보다 찾기 어렵다.
    """
    config_path = repo_dir / ".claude" / "vault.json"
    if not config_path.exists():
        return CheckResult(
            "프로젝트 매핑",
            FAIL,
            "vault.json 없음 — briefing이 repo 디렉터리명으로 폴백합니다",
            hint="--fix (Vault에 후보가 하나일 때) 또는 devtrail init-project <이름> --repo .",
            fixable=True,
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        project = str(data.get("project", "")).strip() if isinstance(data, dict) else ""
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult(
            "프로젝트 매핑",
            FAIL,
            f"vault.json을 읽을 수 없습니다: {e}",
            hint="파일을 지우고 --fix로 다시 만들거나 직접 고치세요",
        )
    if not project:
        return CheckResult(
            "프로젝트 매핑",
            FAIL,
            "vault.json에 project 키가 없습니다",
            hint="devtrail init-project <이름> --repo .",
            fixable=True,
        )
    if vault_dir is None:
        return CheckResult("프로젝트 매핑", UNKNOWN, f"project={project} (Vault 경로를 몰라 실재 확인 불가)")
    if not (vault_dir / "30_Projects" / project).is_dir():
        return CheckResult(
            "프로젝트 매핑",
            FAIL,
            f"project={project} 인데 30_Projects/{project}/ 가 Vault에 없습니다",
            hint=f"devtrail init-project {project} 로 스캐폴드를 만들거나 vault.json의 이름을 고치세요",
        )
    context = vault_dir / "30_Projects" / project / "Context.md"
    if not context.exists():
        return CheckResult(
            "프로젝트 매핑",
            WARN,
            f"project={project} — 폴더는 있지만 Context.md가 없어 배경이 주입되지 않습니다",
            hint=f"devtrail init-project {project} 실행 후 Context.md의 배경·목표·제약을 채우세요",
        )
    return CheckResult("프로젝트 매핑", OK, f"project={project}")


# 없으면 기능이 실제로 저하되는 경로. 나머지 VAULT_DIRS·AGENT_MEMORY_FILES 결손은
# 쓰기 시점에 자동 생성된다(candidate_writer가 mkdir(parents=True),
# curator_agent.apply_memory_patch가 대상 파일 생성). 무해한 결손을 경고로 올리면
# 진단 자체를 안 믿게 되므로 정보성으로 내린다.
#
# SessionHandoffs만 예외: vault.json이 없을 때 briefing이 repo 디렉터리명으로
# handoff 폴더명을 훑어 프로젝트를 추정하는 폴백이 있고(vault_tools.py의
# handoff_project_dirs), 폴더가 없으면 그 폴백이 조용히 실패한다.
_FUNCTIONAL_DIRS = ("60_Candidates/SessionHandoffs",)


def check_vault_structure(vault_dir: Path | None) -> CheckResult:
    """`VAULT_DIRS`·`AGENT_MEMORY_FILES` 대조로 결손을 찾는다.

    결손 대부분은 자동 복구되므로 정보성(OK)으로 보고하고, 실제로 기능이 저하되는
    `_FUNCTIONAL_DIRS`만 WARN으로 올린다.
    """
    if vault_dir is None:
        return CheckResult("vault 구조", UNKNOWN, "Vault 경로를 몰라 확인하지 않았습니다")

    from app.services.wiki_service import AGENT_MEMORY_FILES, VAULT_DIRS

    missing_dirs = [rel for rel in VAULT_DIRS if not (vault_dir / rel).is_dir()]
    missing_files = [rel for rel in AGENT_MEMORY_FILES if not (vault_dir / rel).exists()]
    missing_total = len(missing_dirs) + len(missing_files)
    if not missing_total:
        return CheckResult("vault 구조", OK, f"폴더 {len(VAULT_DIRS)}개 · AgentMemory {len(AGENT_MEMORY_FILES)}개 정상")

    degraded = [rel for rel in _FUNCTIONAL_DIRS if rel in missing_dirs]
    if degraded:
        return CheckResult(
            "vault 구조",
            WARN,
            f"{', '.join(degraded)} 없음 — vault.json 없이 프로젝트를 추정하는 briefing 폴백이 실패합니다"
            f" (그 외 결손 {missing_total - len(degraded)}개)",
            hint="--fix (devtrail init-vault와 동일 — 기존 노트는 덮어쓰지 않습니다)",
            fixable=True,
        )

    preview = ", ".join((missing_dirs + missing_files)[:3])
    if missing_total > 3:
        preview += " …"
    return CheckResult(
        "vault 구조",
        OK,
        f"결손 {missing_total}개 ({preview}) — 쓰기 시점에 자동 생성되므로 기능 영향 없음",
        hint="구조를 init-vault 기준으로 맞추려면 --fix",
        fixable=True,
    )


def check_mcp_package() -> CheckResult:
    """`mcp` import 가능 여부 — mcp-serve 구동의 전제."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        return CheckResult(
            "mcp 패키지",
            FAIL,
            "mcp를 import할 수 없습니다 — devtrail mcp-serve가 기동하지 않습니다",
            hint='pip install -e ".[dev]" (repo 루트의 .venv에서)',
        )
    return CheckResult("mcp 패키지", OK, "import 가능")


def check_mcp_registration(timeout: float = 10.0) -> CheckResult:
    """`claude mcp list`에 devtrail-vault가 있는지.

    fail-open: claude CLI가 없거나 출력 형식이 바뀌면 UNKNOWN으로 떨어뜨린다. 외부
    도구의 출력 파싱을 근거로 사용자에게 "고장났다"고 말하지 않는다.
    """
    exe = shutil.which("claude")
    if not exe:
        return CheckResult("MCP 등록", UNKNOWN, "claude CLI가 PATH에 없어 확인하지 않았습니다")
    try:
        proc = subprocess.run(
            [exe, "mcp", "list"], capture_output=True, timeout=timeout, text=True, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError) as e:
        return CheckResult("MCP 등록", UNKNOWN, f"claude mcp list 실행 실패: {e}")
    if proc.returncode != 0:
        return CheckResult("MCP 등록", UNKNOWN, f"claude mcp list가 exit {proc.returncode}로 끝났습니다")
    if MCP_SERVER_NAME in (proc.stdout or ""):
        return CheckResult("MCP 등록", OK, f"{MCP_SERVER_NAME} 등록됨")
    return CheckResult(
        "MCP 등록",
        FAIL,
        f"{MCP_SERVER_NAME}가 등록돼 있지 않습니다",
        hint=MCP_ADD_COMMAND,
    )


def check_hook_runtime(repo_dir: Path) -> CheckResult:
    """훅 디스패처와 python 해석기 존재 확인.

    `run-hook.sh`는 python을 못 찾으면 조용히 exit 0한다(훅 실패가 세션을 막지 않게).
    그 설계 때문에 python이 없어도 아무 증상이 없으므로 여기서 대신 본다.
    """
    dispatcher = repo_dir / "scripts" / "hooks" / "run-hook.sh"
    if not dispatcher.exists():
        return CheckResult("훅 실행 전제", FAIL, f"디스패처가 없습니다: {dispatcher}", hint="repo가 온전한지 확인 (git status)")

    candidates = [repo_dir / ".venv" / "bin" / "python", repo_dir / ".venv" / "Scripts" / "python.exe"]
    found = next((p for p in candidates if p.exists()), None)
    if found is None and not (shutil.which("python3") or shutil.which("python")):
        return CheckResult(
            "훅 실행 전제",
            FAIL,
            "repo .venv에도 PATH에도 python이 없습니다 — 훅이 조용히 통과됩니다",
            hint="install 스크립트로 .venv를 만드세요",
        )
    return CheckResult("훅 실행 전제", OK, str(found) if found else "PATH의 python 사용")


# ── 진단 · 수리 ──────────────────────────────────────────────────────────────


def diagnose(repo_dir: Path, vault_root: str, *, check_mcp: bool = True) -> DoctorReport:
    """점검을 모두 돌린다. 개별 점검의 예외는 UNKNOWN으로 흡수한다."""
    vault_check = check_vault_path(vault_root)
    vault_dir = Path(vault_root) if vault_check.severity == OK else None

    runners = [
        ("vault 경로", lambda: vault_check),
        ("mcp 패키지", check_mcp_package),
        ("Claude Code 훅", lambda: check_hook_settings(repo_dir)),
        ("훅 실행 전제", lambda: check_hook_runtime(repo_dir)),
        ("프로젝트 매핑", lambda: check_project_mapping(repo_dir, vault_dir)),
        ("vault 구조", lambda: check_vault_structure(vault_dir)),
    ]
    if check_mcp:
        runners.append(("MCP 등록", check_mcp_registration))

    checks: list[CheckResult] = []
    for name, runner in runners:
        try:
            checks.append(runner())
        except Exception as e:  # 진단 도구가 진단 대상보다 잘 깨지면 안 된다
            checks.append(CheckResult(name, UNKNOWN, f"점검 중 예외: {e}"))

    return DoctorReport(repo_dir=repo_dir, vault_dir=vault_dir, checks=checks)


def repair(report: DoctorReport, *, project: str = "") -> list[RepairResult]:
    """fixable 항목만 고친다. 기존 파일은 절대 덮어쓰지 않는다."""
    results: list[RepairResult] = []
    fixable = {c.name for c in report.fixable}

    if "Claude Code 훅" in fixable:
        results.append(_fix_hook_settings(report.repo_dir))
    if "프로젝트 매핑" in fixable:
        results.append(_fix_project_mapping(report.repo_dir, report.vault_dir, project))
    if "vault 구조" in fixable and report.vault_dir is not None:
        results.append(_fix_vault_structure(report.vault_dir))

    return results


def _fix_hook_settings(repo_dir: Path) -> RepairResult:
    settings = repo_dir / ".claude" / "settings.json"
    example = repo_dir / ".claude" / "settings.example.json"
    if settings.exists():
        return RepairResult("Claude Code 훅", False, "이미 존재 — 건드리지 않았습니다")
    if not example.exists():
        return RepairResult("Claude Code 훅", False, f"템플릿이 없습니다: {example}")
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_bytes(example.read_bytes())
    return RepairResult("Claude Code 훅", True, f"생성: {settings}")


def _fix_project_mapping(repo_dir: Path, vault_dir: Path | None, project: str) -> RepairResult:
    """project를 확정할 수 있을 때만 쓴다.

    후보가 여럿이면 자동 선택하지 않는다 — 잘못 매핑되면 briefing이 남의 프로젝트
    컨텍스트를 주입하고, 그건 파일이 없는 것보다 나쁘다.
    """
    resolved = project.strip()
    if not resolved:
        if vault_dir is None:
            return RepairResult("프로젝트 매핑", False, "Vault 경로를 몰라 프로젝트를 고를 수 없습니다 — --project로 지정하세요")
        candidates = candidate_projects(vault_dir)
        if len(candidates) != 1:
            listed = ", ".join(candidates) if candidates else "(없음)"
            return RepairResult(
                "프로젝트 매핑",
                False,
                f"후보가 {len(candidates)}개라 자동 선택하지 않았습니다: {listed} — --project로 지정하세요",
            )
        resolved = candidates[0]

    config_path = repo_dir / ".claude" / "vault.json"
    config: dict = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config = loaded
        except (OSError, json.JSONDecodeError):
            config = {}
    config["project"] = resolved
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return RepairResult("프로젝트 매핑", True, f"project={resolved} 저장: {config_path}")


def _fix_vault_structure(vault_dir: Path) -> RepairResult:
    from app.services.wiki_service import WikiService

    result = WikiService(vault_dir).init_vault()
    created = len(result.created_dirs) + len(result.created_files)
    if not created:
        return RepairResult("vault 구조", False, "생성할 것이 없었습니다")
    return RepairResult(
        "vault 구조", True, f"폴더 {len(result.created_dirs)}개 · 파일 {len(result.created_files)}개 생성"
    )


def candidate_projects(vault_dir: Path) -> list[str]:
    """`30_Projects/` 하위에서 Context.md를 가진 프로젝트 이름."""
    projects_dir = vault_dir / "30_Projects"
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if p.is_dir() and (p / "Context.md").exists())
