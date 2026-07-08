"""오늘의 복습 질문 — 10_Worklog/Sessions/의 Learning Recovery 질문을 관리한다.

docs/service-improvement-plan.md P6. 새 커맨드를 만들지 않고 push-digest --daily와
nightly-distill의 daily digest에 값만 얹기 위한 조회 헬퍼로 시작했고, 이후
학습 회수 루프를 닫기 위해 답변 기록(mark_answered)과 미답 질문 나열
(list_questions)이 추가됐다.

답변은 세션 노트의 질문 줄 바로 아래에 `- 답변(YYYY-MM-DD): ...` 불릿으로
기록되며, 답변 불릿이 붙은 질문은 answered로 판정돼 복습 대상에서 빠진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import frontmatter


HEADING_AI_LED = "AI가 주도적으로 처리한 부분"
HEADING_UNCLEAR = "내가 아직 완전히 이해하지 못한 개념"
HEADING_QUESTIONS = "다음에 직접 설명해봐야 할 질문"
HEADING_RELATED = "관련 Vault 후보"

_ANSWER_MARK = "답변("
_NUMBER_PREFIX = re.compile(r"^\d+[.)]\s*")


@dataclass(frozen=True)
class ReviewQuestion:
    project: str
    unclear_concept: str
    question: str
    source_rel_path: str
    answered: bool = False


_MAX_SESSIONS_TO_SCAN = 10


def _normalize_item(text: str) -> str:
    """질문/개념 줄에서 번호·불릿 접두를 제거한다 (레거시 '1. - 질문' 포맷 호환)."""
    text = text.strip()
    text = _NUMBER_PREFIX.sub("", text)
    while text[:2] in ("- ", "* "):
        text = text[2:].strip()
    return text.strip()


def _sorted_sessions(vault_dir: Path) -> list[tuple[str, Path, frontmatter.Post]]:
    """세션 노트를 created_at 최신순으로 반환한다.

    파일명(글롭 열거 순서)이 아니라 실제 created_at 기준 — 파일명 충돌 해소가
    "-2" 접미사를 붙이면 알파벳순이 시간순과 어긋난다.
    """
    sessions_dir = vault_dir / "10_Worklog" / "Sessions"
    if not sessions_dir.exists():
        return []
    entries: list[tuple[str, Path, frontmatter.Post]] = []
    for md_path in sessions_dir.glob("*.md"):
        try:
            post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        created = str(post.metadata.get("created_at", "") or "")
        entries.append((created, md_path, post))
    entries.sort(key=lambda e: e[0], reverse=True)
    return entries


def _extract_questions(body: str) -> list[tuple[str, bool]]:
    """질문 섹션에서 (질문, answered) 목록을 순서대로 뽑는다.

    질문 줄 다음에 오는 들여쓴/대시 불릿 중 `답변(`을 포함한 줄이 있으면
    그 질문은 answered로 본다.
    """
    results: list[tuple[str, bool]] = []
    in_section = False
    current: str | None = None
    current_answered = False

    def _flush() -> None:
        nonlocal current, current_answered
        if current:
            results.append((current, current_answered))
        current, current_answered = None, False

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("###") and HEADING_QUESTIONS in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("#"):
            break
        if not stripped:
            continue
        if stripped[0].isdigit():
            _flush()
            text = _normalize_item(stripped)
            if text and text != "-":
                current = text
            continue
        # 질문에 딸린 부속 줄 (답변 불릿 등)
        if current and _ANSWER_MARK in stripped:
            current_answered = True
    _flush()
    return results


def list_questions(
    vault_dir: Path,
    max_sessions: int = _MAX_SESSIONS_TO_SCAN,
    days: int = 0,
) -> list[ReviewQuestion]:
    """최근 세션들의 Learning Recovery 질문을 최신 세션 순으로 반환한다.

    days > 0이면 created_at이 그 기간 안인 세션만 본다.
    """
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    questions: list[ReviewQuestion] = []
    for created, md_path, post in _sorted_sessions(vault_dir)[:max_sessions]:
        if cutoff and created[:10] < cutoff:
            continue
        extracted = _extract_questions(post.content)
        if not extracted:
            continue
        unclear = _extract_section_first_line(post.content, HEADING_UNCLEAR, numbered=False)
        rel = str(md_path.relative_to(vault_dir)).replace("\\", "/")
        project = str(post.metadata.get("project", "") or "")
        for question, answered in extracted:
            questions.append(ReviewQuestion(
                project=project,
                unclear_concept=unclear,
                question=question,
                source_rel_path=rel,
                answered=answered,
            ))
    return questions


def pick_review_question(vault_dir: Path) -> ReviewQuestion | None:
    """가장 최근 세션부터 훑어 첫 번째 **미답** 복습 질문을 찾는다. 없으면 None."""
    for q in list_questions(vault_dir):
        if not q.answered:
            return q
    return None


def mark_answered(vault_dir: Path, source_rel_path: str, question: str, answer: str) -> bool:
    """세션 노트의 해당 질문 줄 아래에 답변 불릿을 삽입한다. 성공 여부 반환."""
    path = vault_dir / source_rel_path
    if not path.exists():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return False

    target = _normalize_item(question)
    lines = raw.splitlines()
    in_section = False
    insert_at: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("###") and HEADING_QUESTIONS in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("#"):
            break
        if stripped and stripped[0].isdigit() and _normalize_item(stripped) == target:
            insert_at = i + 1
            break
    if insert_at is None:
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    answer_line = f"   - 답변({today}): {answer.strip()}"
    lines.insert(insert_at, answer_line)
    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"
    try:
        path.write_text(content, encoding="utf-8")
    except Exception:
        return False
    return True


def format_review_block(vault_dir: Path) -> str:
    """복습 질문을 digest 본문에 그대로 붙일 수 있는 Markdown 블록으로 만든다.

    질문을 찾지 못하거나 조회 중 문제가 있으면(vault 미구성 등) 빈 문자열을
    반환한다 — digest 생성 자체를 막아서는 안 된다.
    """
    try:
        review_question = pick_review_question(vault_dir)
    except Exception:
        review_question = None
    if not review_question:
        return ""

    lines = ["**오늘의 학습 회수**"]
    if review_question.project:
        lines.append(f"프로젝트: {review_question.project}")
    if review_question.unclear_concept:
        lines.append(f"미해결 개념: {review_question.unclear_concept}")
    lines.append("복습 질문:")
    lines.append(f"1. {review_question.question}")
    lines.append("직접 설명해본 뒤 /answer <설명> 으로 답하면 세션 노트에 기록돼요.")
    return "\n".join(lines)


def _extract_section_first_line(body: str, heading_contains: str, numbered: bool) -> str:
    """`### {heading}` 섹션의 첫 번째 실질 내용 줄을 반환한다."""
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("###") and heading_contains in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("#"):
            break
        if not stripped:
            continue
        text = _normalize_item(stripped) if numbered else stripped
        if not numbered:
            if text.startswith("- "):
                text = text[2:].strip()
            # "- " placeholder만 있는 줄은 strip 후 "-"만 남는다 — 빈 값으로 취급
            while text[:2] in ("- ", "* "):
                text = text[2:].strip()
        if text in ("", "-"):
            continue
        return text
    return ""
