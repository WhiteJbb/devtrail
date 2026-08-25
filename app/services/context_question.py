"""Context Gap Recovery — 기록에서 빠진 맥락을 질문 1~2개로 회수한다.

docs/devtrail-improvement-roadmap.md Phase 2. Learning Recovery
(`review_question.py`)와 목적이 다르다 — 저쪽은 "내가 이해 못한 개념"을 다시
설명하게 하고, 이쪽은 "왜 했는지 / 뭐가 달라졌는지"라는 기록의 빈칸을 메운다.
인프라(세션 노트에 상태를 함께 저장, Telegram으로 회수)는 그대로 따른다.

저장 위치는 세션 노트 자신이다:
- `## Context Questions` — 체크박스 줄이 곧 pending/answered 상태
- `## Context Recovery` — 회수한 답변이 쌓이는 곳 (다시 증류 대상이 된다)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import frontmatter

from app.services.review_question import _sorted_sessions  # 세션 노트 최신순 열거 재사용

HEADING_QUESTIONS = "## Context Questions"
HEADING_RECOVERY = "## Context Recovery"

# 질문 타입은 5개로 고정한다 — 자유 생성을 허용하면 매일 다른 축으로 물어
# 회수한 답변끼리 비교가 안 된다.
QUESTION_TYPES: dict[str, str] = {
    "WHY": "왜 이렇게 했어?",
    "PROBLEM": "처음 해결하려던 문제가 뭐였어?",
    "FAILURE": "이 시도는 왜 실패했어?",
    "DECISION": "A 대신 B를 선택한 이유가 뭐였어?",
    "OUTCOME": "최종적으로 뭐가 달라졌어?",
}

MAX_QUESTIONS_PER_DAY = 2

_MAX_SESSIONS_TO_SCAN = 10
_MAX_CONTEXT_CHARS = 6000
_Q_LINE = re.compile(r"^- \[(?P<mark>[ xX])\]\s*(?:\[(?P<type>[A-Z_]+)\]\s*)?(?P<text>.+?)\s*$")


@dataclass(frozen=True)
class ContextQuestion:
    project: str
    qtype: str
    question: str
    source_rel_path: str
    answered: bool = False


def _parse_questions(body: str) -> list[tuple[str, str, bool]]:
    """`## Context Questions` 섹션에서 (타입, 질문, answered)를 순서대로 뽑는다."""
    results: list[tuple[str, str, bool]] = []
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == HEADING_QUESTIONS
            continue
        if not in_section or not stripped:
            continue
        m = _Q_LINE.match(stripped)
        if m:
            results.append((m.group("type") or "", m.group("text"), m.group("mark").lower() == "x"))
    return results


def list_context_questions(
    vault_dir: Path, max_sessions: int = _MAX_SESSIONS_TO_SCAN
) -> list[ContextQuestion]:
    """최근 세션 노트의 context 질문을 최신 세션 순으로 반환한다."""
    questions: list[ContextQuestion] = []
    for _created, md_path, post in _sorted_sessions(vault_dir)[:max_sessions]:
        rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
        project = str(post.metadata.get("project", "") or "")
        for qtype, text, answered in _parse_questions(post.content):
            questions.append(ContextQuestion(project, qtype, text, rel, answered))
    return questions


def pick_context_question(vault_dir: Path) -> ContextQuestion | None:
    """가장 최근 세션부터 훑어 첫 번째 미답 context 질문을 찾는다."""
    for q in list_context_questions(vault_dir):
        if not q.answered:
            return q
    return None


def generate_context_questions(
    vault_dir: Path,
    llm=None,
    settings=None,
    now: datetime | None = None,
) -> list[ContextQuestion]:
    """그날 세션 노트를 보고 빠진 맥락 질문을 최대 2개 생성해 노트에 기록한다.

    이미 미답 질문이 있으면 새로 만들지 않는다 — 답하지 않은 질문이 쌓이면
    그 순간부터 아무도 읽지 않는다.
    """
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    todays = [
        (path, post)
        for created, path, post in _sorted_sessions(vault_dir)
        if created[:10] == today
    ]
    if not todays:
        return []
    if any(not answered for _p, post in todays for *_x, answered in _parse_questions(post.content)):
        return []

    # 질문은 그날의 가장 최신 세션 노트에 붙인다 — 하루 상한이 2개라 여러 노트에
    # 나눠 붙일 이유가 없고, 답변도 한 곳에 모이는 편이 다시 읽기 좋다.
    path, post = todays[0]
    rel = str(path.relative_to(vault_dir)).replace("\\", "/")
    project = str(post.metadata.get("project", "") or "")

    from app.prompts import render_prompt
    from app.services.json_utils import complete_json

    if llm is None:
        from app.config import get_settings
        from app.llm.factory import get_task_llm_provider

        llm = get_task_llm_provider("light", settings or get_settings())

    prompt = render_prompt(
        "context_questions",
        DATE=today,
        PROJECT=project,
        MAX=str(MAX_QUESTIONS_PER_DAY),
        QUESTION_TYPES="\n".join(f"- {k}: {v}" for k, v in QUESTION_TYPES.items()),
        SESSION_NOTE=post.content[:_MAX_CONTEXT_CHARS],
    )
    data = complete_json(llm, prompt)

    questions: list[ContextQuestion] = []
    for item in (data or {}).get("questions", []) or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question", "") or "").strip()
        if not text:
            continue
        qtype = str(item.get("type", "") or "").strip().upper()
        if qtype not in QUESTION_TYPES:
            qtype = "WHY"
        questions.append(ContextQuestion(project, qtype, text, rel))
        # 상한은 프롬프트 지시가 아니라 코드에서 자른다.
        if len(questions) >= MAX_QUESTIONS_PER_DAY:
            break
    if not questions:
        return []

    _append_questions(path, questions)
    return questions


def _append_questions(path: Path, questions: list[ContextQuestion]) -> None:
    """세션 노트 끝에 `## Context Questions` 섹션(또는 항목)을 덧붙인다."""
    raw = path.read_text(encoding="utf-8").rstrip("\n")
    lines = [f"- [ ] [{q.qtype}] {q.question}" for q in questions]
    if HEADING_QUESTIONS in raw:
        raw = raw.replace(HEADING_QUESTIONS, HEADING_QUESTIONS + "\n\n" + "\n".join(lines), 1)
    else:
        raw = raw + "\n\n" + HEADING_QUESTIONS + "\n\n" + "\n".join(lines)
    path.write_text(raw + "\n", encoding="utf-8")


def extract_context_sections(body: str) -> str:
    """본문에서 Context Questions/Recovery 섹션만 떼어 반환한다.

    write_session_process 재기록이 본문을 통째로 교체할 때 이 두 섹션(특히
    사람이 직접 답한 Recovery)을 잃지 않도록 보존용으로 쓴다.
    """
    kept: list[str] = []
    keeping = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            keeping = stripped in (HEADING_QUESTIONS, HEADING_RECOVERY)
        if keeping:
            kept.append(line)
    return "\n".join(kept).strip()


def mark_context_answered(
    vault_dir: Path, source_rel_path: str, question: str, answer: str, now: datetime | None = None
) -> bool:
    """답변을 `## Context Recovery`에 기록하고 질문을 완료 처리한다. 성공 여부 반환.

    답변으로 노트 본문이 늘었으므로 `needs_distill`을 되살린다 — 이미 증류가
    지나간 노트라도 회수한 맥락이 후보에 반영되게 (vault_tools의 재기록과 같은 취지).
    """
    path = vault_dir / source_rel_path
    if not path.exists():
        return False
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    target = question.strip()
    qtype = ""
    lines = post.content.splitlines()
    in_section = False
    hit = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == HEADING_QUESTIONS
            continue
        if not in_section:
            continue
        m = _Q_LINE.match(stripped)
        if m and m.group("text") == target and m.group("mark").lower() != "x":
            qtype = m.group("type") or ""
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            hit = True
            break
    if not hit:
        return False

    date = (now or datetime.now()).strftime("%Y-%m-%d")
    label = f"[{qtype}] {target}" if qtype else target
    bullet = f"- **{label}** ({date}) — {answer.strip()}"
    body = "\n".join(lines).rstrip("\n")
    if HEADING_RECOVERY in body:
        body = body.replace(HEADING_RECOVERY, HEADING_RECOVERY + "\n\n" + bullet, 1)
    else:
        body = body + "\n\n" + HEADING_RECOVERY + "\n\n" + bullet

    post.content = body + "\n"
    post.metadata["needs_distill"] = True
    try:
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
    except Exception:
        return False
    return True


def format_context_block(vault_dir: Path) -> str:
    """미답 context 질문을 digest 본문에 붙일 Markdown 블록으로 만든다.

    조회에 문제가 있으면 빈 문자열 — digest 생성을 막아선 안 된다.
    """
    try:
        pending = [q for q in list_context_questions(vault_dir) if not q.answered]
    except Exception:
        pending = []
    if not pending:
        return ""

    lines = ["**맥락 회수 질문**"]
    if pending[0].project:
        lines.append(f"프로젝트: {pending[0].project}")
    for i, q in enumerate(pending[:MAX_QUESTIONS_PER_DAY], start=1):
        lines.append(f"{i}. [{q.qtype}] {q.question}" if q.qtype else f"{i}. {q.question}")
    lines.append("/gap <답변> 으로 답하면 세션 노트 Context Recovery에 기록해둘게요.")
    return "\n".join(lines)
