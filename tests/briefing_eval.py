"""고정 평가 Vault로 기본 briefing과 structured briefing을 비교한다.

실행: `python -m tests.briefing_eval [결과.json]` — markdown 표를 출력한다 (docs/project-briefing.md에 기록).
회귀 검사는 tests/test_briefing_eval.py가 같은 함수를 부른다.

평가 Vault는 Devtrail vault 구조(Context.md·SessionHandoffs·Decisions·AgentMemory marker)를 본뜬 합성 문서다.
실제 사용자 vault 분포와 다를 수 있다 — 한계는 문서에 적는다.

측정 정의 (사례마다 "목표 줄" = 반드시 전달돼야 하는 제약·후속 항목 원문 줄):
- text_chars: 응답 text 본문 길이
- response_chars: 응답 전체 JSON 직렬화 길이 (기본 briefing은 dataclass asdict)
- targets_in_text: 목표 줄 문구가 text에 그대로 있는 수
- located: 목표 줄의 경로·줄 번호·source_version을 응답만으로 아는 수 (기본 briefing은 줄 번호·버전을 주지 않는다)
- confirm_calls: 모든 목표 줄을 경로·줄 번호와 함께 확보하기까지의 호출 수 — briefing 1회 + 추가 읽기.
  기본: 목표 줄이 있는 파일마다 read_note 전문 1회(줄 번호는 호출자가 직접 센다, 버전은 얻을 수 없다).
  structured: 발췌에 없는 목표 줄만 omissions의 read 인자로 read_note(structured=True) 1회씩.
- confirm_chars: 그 호출들의 응답 문자 수 합
- ms: briefing 1회 소요 시간 중앙값(5회) + 추가 읽기 시간. 실행 환경에 크게 좌우된다.
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

_TEMPLATE = (
    "# Devtrail — Project Context\n\n"
    "> 이 파일은 `get_project_briefing`이 세션 시작 시 자동 주입하는 프로젝트 정본 컨텍스트다.\n"
    "> 배경·목표·제약이 바뀔 때마다 갱신한다.\n\n"
    "## 배경\n\n_(이 프로젝트가 왜 존재하는지, 어떤 문제를 푸는지)_\n\n## 목표\n\n- \n\n"
    "## 제약 / 원칙\n\n- 사용자의 결정이 필요한 부분은 진행하지 말고 질문한다\n\n"
    "## 관련 문서\n\n- 구현 계획: [[Plans/]]\n"
)


def _fm(**meta) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in meta.items()) + "---\n"


def _context(body: str) -> str:
    return _fm(type="project_context", project="Devtrail", status="active", updated_at="2099-01-01") + body


def _process(sid: str, at: str, next_session: str, what_changed: str = "- 변경 기록") -> str:
    return (_fm(type="candidate", candidate_type="session_handoff", title=f"Process {sid}", project="Devtrail",
                status="candidate", created_at=at, handoff_type="process", session_id=sid)
            + f"# Process\n\n## What Changed\n\n{what_changed}\n\n## Next Session\n\n{next_session}\n")


def _plan(sid: str, at: str, goal: str) -> str:
    return (_fm(type="candidate", candidate_type="session_handoff", title=f"Plan {sid}", project="Devtrail",
                status="candidate", created_at=at, handoff_type="plan", session_id=sid)
            + f"# Plan\n\n## Goal\n\n{goal}\n")


def _decision(i: int) -> str:
    return (_fm(type="decision", title=f"결정 {i}", project="Devtrail", status="accepted", created_at=f"2026-10-{i + 10:02d}")
            + f"# 결정 {i}\n\n## 결정\n\n결정 내용 {i}: " + "근거 설명 " * 15 + "\n\n## 이유\n\n이유 본문\n")


_MEMORY = {
    "40_AgentMemory/05_OpenLoops.md": _fm(updated_at="2099-01-01") + "# OpenLoops\n\n- 전역 루프\n\n"
    '<!-- devtrail-memory-patch: {"scope": "project", "project": "Devtrail"} -->\n## Devtrail\n\n'
    "### 실효 확인\n\n- (2026-11-01) OPENLOOP_TARGET 운영 반영 실측\n\n"
    '<!-- devtrail-memory-patch: {"scope": "project", "project": "rpg"} -->\n## rpg\n\n- rpg 할 일\n',
    "40_AgentMemory/06_Lessons.md": _fm(updated_at="2099-01-01") + "# Lessons\n\n전역: 먼저 측정한다.\n\n"
    + "".join(f'<!-- devtrail-memory-patch: {{"scope": "project", "project": "Devtrail"}} -->\n'
              f"- (2026-10-{i + 10:02d}) 교훈 {i}: " + "확인 순서 설명 " * 12 + "\n\n" for i in range(12)),
    "40_AgentMemory/01_CurrentFocus.md": _fm(updated_at="2099-01-01") + "# Current Focus\n\n- 브리핑 개선\n",
}


def _sessions(long_older: bool = False) -> dict[str, str]:
    files: dict[str, str] = {}
    for i, (sid, at) in enumerate((("s3", "2026-11-03T10:00:00"), ("s2", "2026-11-02T10:00:00"),
                                   ("s1", "2026-11-01T10:00:00"))):
        # 기본 briefing은 최신 Process 밖의 발췌를 400자로 자른다 — 그보다 긴 Next Session(약 900자)
        filler = "".join(f"- 세부 후속 {k}: " + "설명 " * 12 + "\n" for k in range(18)) if long_older and i else ""
        files[f"60_Candidates/SessionHandoffs/Devtrail/plan-{sid}.md"] = _plan(sid, at.replace("10:", "09:"), f"- {sid} 목표")
        files[f"60_Candidates/SessionHandoffs/Devtrail/process-{sid}.md"] = _process(
            sid, at, filler + f"- NEXT_TARGET_{sid} 후속 항목")
    return files


@dataclass(frozen=True)
class Scenario:
    name: str
    files: dict[str, str]
    targets: tuple[tuple[str, str], ...]  # (경로, 그 줄에 있는 문구)
    note: str


def _scenarios() -> tuple[Scenario, ...]:
    typical_ctx = ("# Devtrail — Project Context\n\n## 배경\n\n" + "Obsidian vault 기반 지식 OS. " * 30 + "\n\n"
                   "## 목표\n\n- 세션 간 맥락 유지\n\n## 제약\n\n- CONSTRAINT_A 공식 영역 직접 쓰기 금지\n"
                   "- CONSTRAINT_B 비밀값 커밋 금지\n\n## 운영 메모\n\n- dev 브랜치 경유\n")
    long_ctx = ("# Devtrail — Project Context\n\n## 배경\n\n"
                + "".join(f"- 배경 기록 {i}: " + "설명 " * 20 + "\n" for i in range(300))
                + "\n## 제약\n\n- CONSTRAINT_LATE 공식 영역 직접 쓰기 금지\n")
    huge_ctx = ("# Devtrail — Project Context\n\n## 원칙\n\n"
                + "".join(f"- 원칙 {i:03d}: " + "지켜야 할 내용 " * 10 + "\n" for i in range(250))
                + "- CONSTRAINT_TAIL 마지막 원칙\n")
    decisions = {f"30_Projects/Devtrail/Decisions/d{i}.md": _decision(i) for i in range(7)}
    ctx = "30_Projects/Devtrail/Context.md"
    nxt = "60_Candidates/SessionHandoffs/Devtrail/process-%s.md"
    loops = "40_AgentMemory/05_OpenLoops.md"
    return (
        Scenario("일반", {ctx: _context(typical_ctx), **decisions, **_sessions(), **_MEMORY},
                 ((ctx, "CONSTRAINT_A"), (ctx, "CONSTRAINT_B"), (nxt % "s3", "NEXT_TARGET_s3"),
                  (nxt % "s2", "NEXT_TARGET_s2"), (loops, "OPENLOOP_TARGET")),
                 "Context 3천 자대, 세션 3개, 결정 7건, 메모리 3파일"),
        Scenario("긴 Context 후반 제약", {ctx: _context(long_ctx), **_sessions(), **_MEMORY},
                 ((ctx, "CONSTRAINT_LATE"), (nxt % "s3", "NEXT_TARGET_s3")),
                 "배경 약 3만 자 뒤에 제약 절"),
        Scenario("이전 세션의 긴 Next Session", {ctx: _context(typical_ctx), **_sessions(long_older=True), **_MEMORY},
                 ((nxt % "s2", "NEXT_TARGET_s2"), (nxt % "s1", "NEXT_TARGET_s1")),
                 "두 번째·세 번째 세션 Next Session 끝 줄"),
        Scenario("제약만 2만 자 초과", {ctx: _context(huge_ctx), **_sessions()},
                 ((ctx, "원칙 000"), (ctx, "CONSTRAINT_TAIL")),
                 "제약 절 약 3만 자 — 예산 초과"),
        Scenario("init-project 템플릿", {ctx: _context(_TEMPLATE)},
                 ((ctx, "사용자의 결정이 필요한 부분은"),),
                 "빈 틀만 있는 Context"),
    )


def build_vault(root: Path, scenario: Scenario) -> Path:
    for rel, text in scenario.files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    for rel, needle in scenario.targets:
        assert needle in (root / rel).read_text(encoding="utf-8"), (scenario.name, rel, needle)
    return root


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def _median_ms(fn, repeats: int = 5) -> tuple[float, object]:
    samples, result = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return round(sorted(samples)[len(samples) // 2], 1), result


def _target_line(root: Path, rel: str, needle: str) -> int:
    lines = (root / rel).read_bytes().decode("utf-8").split("\n")
    return next(i for i, line in enumerate(lines, 1) if needle in line)


def run_scenario(root: Path, scenario: Scenario) -> dict:
    settings = SimpleNamespace(obsidian_vault_root=str(root), devtrail_project_map="")
    out: dict = {"scenario": scenario.name, "note": scenario.note, "targets": len(scenario.targets)}

    ms, legacy = _median_ms(lambda: vault_tools.get_project_briefing("Devtrail", settings=settings))
    payload = asdict(legacy)
    in_text = sum(1 for _, needle in scenario.targets if needle in legacy.text)
    files = sorted({rel for rel, _ in scenario.targets})
    t0 = time.perf_counter()
    confirm_chars = _size(payload) + sum(len(vault_tools.read_note(rel, settings=settings)) for rel in files)
    out["legacy"] = {"text_chars": len(legacy.text), "response_chars": _size(payload), "targets_in_text": in_text,
                     "located": 0, "confirm_calls": 1 + len(files), "confirm_chars": confirm_chars,
                     "ms": round(ms + (time.perf_counter() - t0) * 1000, 1), "critical_omission": None}

    ms, resp = _median_ms(lambda: vault_tools.get_structured_project_briefing("Devtrail", settings=settings))
    items = [i for s in resp["sections"] if s["key"] != "gaps" for i in s["items"]]
    located = 0
    reads: list[dict] = []
    for rel, needle in scenario.targets:
        line = _target_line(root, rel, needle)
        if any(i["path"] == rel and any(s["start_line"] <= line <= s["end_line"] for s in i["segments"]) for i in items):
            located += 1
            continue
        om = next((o for o in resp["omissions"] if o["path"] == rel and o["lines"][0] <= line <= o["lines"][1]), None)
        if om is not None and om["read"] not in reads:
            reads.append(om["read"])
    t0 = time.perf_counter()
    confirm_chars = resp["budget"]["response_chars"]
    for r in reads:
        # read는 MCP read_note 인자 그대로다 — structured면 구간 읽기, 아니면 전문
        args = {k: v for k, v in r.items() if k not in ("rel_path", "structured")}
        page = (vault_tools.read_source(r["rel_path"], **args, settings=settings) if r.get("structured")
                else vault_tools.read_note(r["rel_path"], settings=settings))
        confirm_chars += _size(page)
    out["structured"] = {"text_chars": resp["budget"]["text_chars"], "response_chars": resp["budget"]["response_chars"],
                         "sources_meta_chars": resp["budget"]["sources_meta_chars"],
                         "targets_in_text": sum(1 for _, needle in scenario.targets if needle in resp["text"]),
                         "located": located, "confirm_calls": 1 + len(reads), "confirm_chars": confirm_chars,
                         "ms": round(ms + (time.perf_counter() - t0) * 1000, 1),
                         "critical_omission": resp["critical_omission"], "follow_ups_state":
                         next(s for s in resp["sections"] if s["key"] == "follow_ups")["state"]}
    return out


def run_eval() -> list[dict]:
    rows = []
    for scenario in _scenarios():
        root = Path(tempfile.mkdtemp(prefix="devtrail-briefing-eval-"))
        try:
            rows.append(run_scenario(build_vault(root, scenario), scenario))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return rows


def to_markdown(rows: list[dict]) -> str:
    head = ("| 사례 | 목표 줄 | text 문자 기본→새 | 응답 문자 기본→새 | text에 목표 줄 기본→새 | 위치·버전 확보 기본→새 | "
            "확인 호출 기본→새 | 확인 문자 기본→새 | ms 기본→새 | critical_omission |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for r in rows:
        lg, st = r["legacy"], r["structured"]
        lines.append(
            f"| {r['scenario']} | {r['targets']} | {lg['text_chars']}→{st['text_chars']} | "
            f"{lg['response_chars']}→{st['response_chars']} | {lg['targets_in_text']}→{st['targets_in_text']} | "
            f"{lg['located']}→{st['located']} | {lg['confirm_calls']}→{st['confirm_calls']} | "
            f"{lg['confirm_chars']}→{st['confirm_chars']} | {lg['ms']}→{st['ms']} | {st['critical_omission']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    results = run_eval()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(to_markdown(results))
