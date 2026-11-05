"""고정 평가 Vault로 legacy search_vault와 structured 검색을 비교한다.

실행: `python -m tests.evidence_eval [결과.json]` — markdown 표를 출력한다 (docs/evidence-search.md에 기록).
회귀 검사는 tests/test_evidence_eval.py가 같은 함수를 부른다.

평가 Vault는 실제 Devtrail vault의 구조(SessionHandoffs Process, Decisions, AgentMemory marker, Digest)를
본뜬 합성 문서다. 실제 사용자 vault 분포와 다를 수 있다 — 한계는 문서에 적는다.

측정 정의:
- rank: 상위 5개 안 정답 문서 순위 (없으면 None)
- evidence_in_response: 검색 응답만으로 정답 줄이 보이는가 (legacy=summary 문자열, structured=발췌 줄 범위 겹침)
- calls: 정답 줄을 확인하기까지 도구 호출 수 (검색 1 + 필요하면 읽기 1)
- chars: 그 호출들의 응답 문자 수 합 (JSON 직렬화 길이, legacy read_note는 전문 길이)
- ms: 그 호출들의 소요 시간 합 (실행 환경에 크게 좌우된다)
- foreign_in_top5: 상위 5개 중 질의 프로젝트가 아닌 프로젝트 소속 문서 수
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from app import vault_tools
from app.services.evidence_search import load_doc
from app.services.project_identity import load_registry


def _fm(**meta) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in meta.items()) + "---\n"


def _filler(prefix: str, n: int) -> str:
    return "".join(f"- {prefix} 기록 {i}: 테스트 실행과 정리 작업을 이어서 했다.\n" for i in range(1, n + 1))


_PROCESS_LATE = (
    _fm(type="candidate", candidate_type="session_handoff", title="Process — briefing 상한", status="candidate",
        project="Devtrail", handoff_type="process", session_id="s-1027", created_at="2026-10-27T10:00:00")
    + "# Process — briefing 상한\n\n## What Changed\n\n"
    + _filler("briefing", 90)
    + "\n## Agent Execution Notes\n\n"
    + _filler("검토", 20)
    + "- 막힌 점: Context 상한이 600자라 제약 절이 잘렸고 read_note 보완 호출은 0건이었다.\n"
    + "- 해결: Context 상한을 5000자로 올리고 로더 상한도 같이 올렸다.\n"
    + "\n## Next Session\n\n- 실측 확인\n"
)

_FILES: dict[str, str] = {
    "30_Projects/Devtrail/Context.md": _fm(project="Devtrail", status="active", updated_at="2026-10-27")
    + "# Devtrail — Project Context\n\n## 배경\n\nObsidian vault 기반 지식 OS. MCP로 briefing과 read_note를 제공한다.\n\n"
    "## 제약\n\n- Context는 briefing에서 가장 밀도 높은 절이다.\n- read_note는 전문 읽기 도구다.\n",
    "30_Projects/rpg-game-web/Context.md": _fm(project="rpg-game-web", status="active")
    + "# rpg-game-web\n\n## 배경\n\n브라우저 RPG. Context 상한 같은 문서 규칙을 따로 둔다.\n",
    "30_Projects/Devtrail/Decisions/2026-10-18 검토 게이트 제거.md": _fm(
        type="decision", title="사람 검토 게이트 제거", status="accepted", project="Devtrail", created_at="2026-10-18")
    + "# 사람 검토 게이트 제거\n\n## 결정\n\nknowledge·decision·problem 후보는 2일 조용하면 nightly가 자동 승격한다.\n\n"
    "## 이유\n\n사람 검토 CLI를 아무도 쓰지 않았다.\n",
    "30_Projects/Devtrail/Decisions/2026-07-01 수동 승격.md": _fm(
        type="decision", title="후보는 사람이 승격", status="superseded", project="Devtrail", created_at="2026-07-01")
    + "# 후보는 사람이 승격\n\n## 결정\n\nnightly는 후보만 만들고 승격은 사람이 promote-candidate로 2일 안에 한다.\n",
    "30_Projects/Devtrail/Decisions/2026-10-19 Stop 훅 parent_pid.md": _fm(
        type="decision", title="Stop 훅 동시 세션 바인딩", status="accepted", project="Devtrail", created_at="2026-10-19")
    + "# Stop 훅 동시 세션 바인딩\n\n## 결정\n\nStop 훅은 parent_pid로 자기 MCP 마커를 고른다 — 동시 세션에서도 자기 기록만 본다.\n",
    "30_Projects/Devtrail/Problems/mcp 2.x 개명.md": _fm(
        type="problem", title="mcp 2.x에서 서버 import 깨짐", status="stable", project="Devtrail", component="mcp")
    + "# mcp 2.x에서 서버 import 깨짐\n\n## 증상\n\n새 venv에서 mcp-serve가 ImportError.\n\n"
    "## 원인\n\nmcp 2.x는 FastMCP가 MCPServer로 개명됐다.\n\n## 해결\n\npyproject에 mcp<2 핀.\n",
    "20_Knowledge/MCP 개요.md": _fm(type="knowledge", title="MCP 개요", status="stable")
    + "# MCP 개요\n\n" + "MCP 서버는 도구를 노출한다. MCP 클라이언트가 호출한다.\n" * 6,
    "20_Knowledge/FastMCP 사용법.md": _fm(type="knowledge", title="FastMCP 사용법", status="stable")
    + "# FastMCP 사용법\n\nFastMCP 데코레이터로 tool을 등록한다. FastMCP instructions는 시스템 프롬프트에 들어간다.\n",
    "20_Knowledge/Context 창 관리.md": _fm(type="knowledge", title="Context 창 관리", status="stable")
    + "# Context 창 관리\n\nLLM Context 창은 유한하다. Context 예산을 나눠 쓴다.\n",
    "20_Knowledge/read_note 활용.md": _fm(type="knowledge", title="read_note 활용", status="stable")
    + "# read_note 활용\n\nread_note는 전문을 읽는다. 발췌가 잘렸으면 read_note를 부른다.\n",
    "20_Knowledge/상한 설계.md": _fm(type="knowledge", title="상한 설계", status="stable")
    + "# 상한 설계\n\n상한은 근거를 두고 정한다. 5000자 같은 숫자는 실측에서 나온다.\n",
    "20_Knowledge/프로세스 트리.md": _fm(type="knowledge", title="프로세스 트리", status="stable")
    + "# 프로세스 트리\n\n프로세스 조상 관계는 ps로 본다.\n",
    "60_Candidates/SessionHandoffs/Devtrail/2026-10-27 Process.md": _PROCESS_LATE,
    "10_Worklog/Sessions/2026-10-27-devtrail.md": _fm(type="session", project="Devtrail", status="raw", session_id="s-1027")
    + "# 작업 세션\n\n" + _PROCESS_LATE.split("---\n", 2)[2],
    "60_Candidates/SessionHandoffs/rpg-game-web/2026-10-20 Process.md": _fm(
        type="candidate", candidate_type="session_handoff", title="Process — rpg 문서", status="candidate",
        project="rpg-game-web", handoff_type="process", session_id="s-rpg")
    + "# Process — rpg 문서\n\n## What Changed\n\n- rpg Context 상한 300자 규칙을 정했다. read_note는 쓰지 않는다.\n",
    "10_Worklog/Sessions/2026-10-19-stop-hook.md": _fm(type="session", project="Devtrail", status="raw", session_id="s-1019")
    + "# 작업 세션 — Stop 훅\n\n" + _filler("훅", 70)
    + "- 원인: 훅 session_id와 MCP session_id가 달라 마커 매칭이 안 됐다.\n"
    + "- 해결: 훅의 조상 프로세스 pid 중 마커 parent_pid와 같은 것을 고른다.\n",
    "50_Outputs/Digest/2026-W44.md": _fm(type="digest", status="generated")
    + "# Digest W44\n\n" + "nightly 자동 승격 로그. " * 120 + "\n" + "- nightly 실행 완료\n" * 40,
    "40_AgentMemory/06_Lessons.md": _fm(updated_at="2026-10-30")
    + "# Lessons\n\n전역: 먼저 측정한다.\n\n"
    + '<!-- devtrail-memory-patch: {"scope": "project", "project": "rpg-game-web"} -->\n'
    + "- (2026-10-20) rpg: pytest 캐시가 tmp_path 격리를 깨면 캐시 디렉터리를 지운다.\n\n"
    + '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n'
    + "- (2026-10-25) Devtrail: pytest tmp_path 격리는 get_settings 캐시 초기화까지 해야 완성된다.\n",
}


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    project: str
    expected_path: str
    expected_lines: tuple[int, int]  # 정답 근거 줄 (frontmatter 포함 1-based)
    expected_text: str  # 그 줄에 반드시 있는 문구 — fixture가 바뀌면 build_eval_vault가 실패한다
    kind: str  # regression(legacy도 상위 5) | inversion(관련도 역전) | late(후반 발췌) | isolation | history


CASES: tuple[EvalCase, ...] = (
    EvalCase("mcp 개명 문제", "FastMCP MCPServer 개명", "Devtrail",
             "30_Projects/Devtrail/Problems/mcp 2.x 개명.md", (16, 16), "MCPServer로 개명", "regression"),
    EvalCase("Stop 훅 결정", "Stop 훅 parent_pid 동시 세션", "Devtrail",
             "30_Projects/Devtrail/Decisions/2026-10-19 Stop 훅 parent_pid.md", (12, 12), "parent_pid로", "regression"),
    EvalCase("자동 승격 결정", "nightly 자동 승격 2일", "Devtrail",
             "30_Projects/Devtrail/Decisions/2026-10-18 검토 게이트 제거.md", (12, 12), "2일 조용하면", "history"),
    EvalCase("Context 상한 세션 근거", "Context 상한 5000자 read_note 0건", "Devtrail",
             "60_Candidates/SessionHandoffs/Devtrail/2026-10-27 Process.md", (128, 129), "5000자", "inversion"),
    EvalCase("조상 pid 매칭 세션 근거", "조상 프로세스 parent_pid 마커 매칭", "Devtrail",
             "10_Worklog/Sessions/2026-10-19-stop-hook.md", (79, 80), "조상 프로세스", "late"),
    EvalCase("다른 프로젝트 격리", "Context 상한 read_note", "rpg-game-web",
             "60_Candidates/SessionHandoffs/rpg-game-web/2026-10-20 Process.md", (14, 14), "300자", "isolation"),
    EvalCase("Lessons 프로젝트 블록", "pytest tmp_path 격리 캐시", "Devtrail",
             "40_AgentMemory/06_Lessons.md", (12, 12), "get_settings 캐시", "isolation"),
)


def build_eval_vault(root: Path) -> Path:
    """고정 평가 Vault를 만든다. 정답 줄 문구가 어긋나면 AssertionError."""
    for rel, text in _FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for case in CASES:
        lines = (root / case.expected_path).read_text(encoding="utf-8").split("\n")
        start, end = case.expected_lines
        assert any(case.expected_text in lines[i - 1] for i in range(start, end + 1)), (case.name, lines[start - 1:end])
    return root


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def _foreign(vault: Path, paths: list[str], project: str) -> int:
    """경로·frontmatter 소속이 질의 프로젝트가 아닌 문서 수 (legacy 결과에도 같은 판정을 적용)."""
    reg = load_registry(vault)
    count = 0
    for rel in paths:
        doc = load_doc(vault, rel, vault / rel, reg)
        units = [doc.file_unit] if not doc.has_markers else doc.units
        if all(u.scope == "project" and u.project.casefold() != project.casefold() for u in units):
            count += 1
    return count


def run_case(vault: Path, case: EvalCase) -> dict:
    settings = SimpleNamespace(obsidian_vault_root=str(vault), devtrail_project_map="")
    out: dict = {"case": case.name, "kind": case.kind, "query": case.query, "project": case.project,
                 "expected": f"{case.expected_path}:{case.expected_lines[0]}-{case.expected_lines[1]}"}

    # legacy: search_vault(limit=5) → 정답이 보이면 read_note 전문
    t0 = time.perf_counter()
    hits = vault_tools.search_vault(case.query, limit=5, settings=settings)
    t1 = time.perf_counter()
    legacy_payload = [asdict(h) for h in hits]
    paths = [h.path for h in hits]
    rank = paths.index(case.expected_path) + 1 if case.expected_path in paths else None
    calls, chars, ms = 1, _size(legacy_payload), (t1 - t0) * 1000
    visible = bool(rank) and case.expected_text in hits[rank - 1].summary
    if rank and not visible:
        t2 = time.perf_counter()
        full = vault_tools.read_note(case.expected_path, settings=settings)
        ms += (time.perf_counter() - t2) * 1000
        calls, chars = calls + 1, chars + len(full)
    out["legacy"] = {"rank": rank, "evidence_in_response": visible, "calls": calls if rank else None,
                     "chars": chars, "ms": round(ms, 1), "foreign_in_top5": _foreign(vault, paths, case.project),
                     "superseded_in_top5": sum(1 for h in hits if "수동 승격" in h.path)}

    # structured: search_vault(structured=True, project=…) → 발췌가 정답 줄을 덮지 않으면 read_note 구간
    t0 = time.perf_counter()
    resp = vault_tools.search_evidence(case.query, project=case.project, settings=settings)
    ms = (time.perf_counter() - t0) * 1000
    assert resp["ok"], resp
    spaths = [r["path"] for r in resp["results"]]
    srank = spaths.index(case.expected_path) + 1 if case.expected_path in spaths else None
    calls, chars = 1, _size(resp)
    covered = False
    if srank:
        hit = resp["results"][srank - 1]
        lo, hi = case.expected_lines
        covered = any(e["start_line"] <= hi and e["end_line"] >= lo for e in hit["excerpts"])
        if not covered:
            t2 = time.perf_counter()
            page = vault_tools.read_source(case.expected_path, start_line=lo, max_lines=hi - lo + 1,
                                           expected_version=hit["source_version"], settings=settings)
            ms += (time.perf_counter() - t2) * 1000
            calls, chars = calls + 1, chars + _size(page)
    out["structured"] = {"rank": srank, "evidence_in_response": covered, "calls": calls if srank else None,
                         "chars": chars, "ms": round(ms, 1), "foreign_in_top5": _foreign(vault, spaths, case.project),
                         "superseded_in_top5": sum(1 for p in spaths if "수동 승격" in p)}
    return out


def run_eval(root: Path | None = None) -> list[dict]:
    tmp = None
    if root is None:
        tmp = Path(tempfile.mkdtemp(prefix="devtrail-eval-"))
        root = tmp
    try:
        build_eval_vault(root)
        return [run_case(root, case) for case in CASES]
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def to_markdown(rows: list[dict]) -> str:
    head = ("| 사례 | 종류 | 정답 | legacy 순위 | 새 순위 | legacy 응답에 근거 | 새 응답에 근거 | 호출 legacy→새 | "
            "문자 legacy→새 | ms legacy→새 | 타 프로젝트(상위5) legacy→새 | superseded(상위5) legacy→새 |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for r in rows:
        lg, st = r["legacy"], r["structured"]
        lines.append(
            f"| {r['case']} | {r['kind']} | `{r['expected']}` | {lg['rank'] or '없음'} | {st['rank'] or '없음'} | "
            f"{'예' if lg['evidence_in_response'] else '아니오'} | {'예' if st['evidence_in_response'] else '아니오'} | "
            f"{lg['calls'] or '-'}→{st['calls'] or '-'} | {lg['chars']}→{st['chars']} | {lg['ms']}→{st['ms']} | "
            f"{lg['foreign_in_top5']}→{st['foreign_in_top5']} | {lg['superseded_in_top5']}→{st['superseded_in_top5']} |"
        )
    return "\n".join(lines)


def measure_scale(n_docs: int, repeats: int = 3) -> dict:
    """평가 Vault에 세션 원문 n_docs개(각 약 3천 자)를 더해 검색 1회 소요 시간을 잰다 (중앙값, ms)."""
    root = Path(tempfile.mkdtemp(prefix="devtrail-scale-"))
    try:
        build_eval_vault(root)
        for i in range(n_docs):
            path = root / "10_Worklog" / "Sessions" / f"scale-{i:05d}.md"
            path.write_text(_fm(type="session", project="Devtrail" if i % 2 else "rpg-game-web", status="raw")
                            + f"# 세션 {i}\n\n" + _filler(f"세션{i}", 40) + "- Context 상한 메모\n", encoding="utf-8")
        settings = SimpleNamespace(obsidian_vault_root=str(root), devtrail_project_map="")
        query = "Context 상한 5000자 read_note 0건"

        def median(fn) -> float:
            samples = []
            for _ in range(repeats):
                t0 = time.perf_counter()
                fn()
                samples.append((time.perf_counter() - t0) * 1000)
            return round(sorted(samples)[len(samples) // 2], 1)

        return {
            "docs_added": n_docs,
            "legacy_ms": median(lambda: vault_tools.search_vault(query, limit=5, settings=settings)),
            "structured_ms": median(lambda: vault_tools.search_evidence(query, project="Devtrail", settings=settings)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    results = run_eval()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(to_markdown(results))
    if len(sys.argv) > 2:
        print(json.dumps(measure_scale(int(sys.argv[2])), ensure_ascii=False))
