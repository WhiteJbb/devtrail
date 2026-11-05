"""structured 원문 구간 읽기 — 검색 발췌와 같은 줄 기준으로 정확한 구간을 돌려준다.

content는 언제나 **완전한 줄**만 담는다. 줄 중간에서 자르거나 줄 안 문자 위치로 이어 읽지 않는다
(char_offset 방식은 쓰지 않는다). 한 줄이 max_chars보다 길면:

- 페이지 중간: 그 줄 앞에서 멈추고 truncation_reason="line_too_long", long_line에 줄 번호·길이를 알린다.
  next는 그 줄을 가리킨다.
- 페이지 첫 줄: 내용 없이 ok=False, error.code="line_too_long"을 돌려준다. error.next는 **다음 줄**이다 —
  같은 줄을 다시 가리키지 않으므로 next를 따라가는 호출이 같은 자리에서 맴돌지 않는다.

이어 읽기 보장: 성공 페이지는 최소 한 줄을 소비하고, line_too_long 결과의 next는 그 줄을 건너뛴다.
그래서 next를 따라가면 반드시 EOF에서 끝난다(next=None). 버전이 바뀐 파일을 이어 읽으면 앞 페이지와
섞이므로 expected_version이 다르면 내용 없이 version_mismatch를 돌려준다.
"""

from __future__ import annotations

from pathlib import Path

from app.services.vault_source import VaultScopeError, read_source_text, record_tier, resolve_scoped_file

DEFAULT_MAX_LINES = 120
MAX_LINES = 400
DEFAULT_MAX_CHARS = 16000
MIN_MAX_CHARS = 200


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def read_range(
    vault_dir: Path,
    rel_path: str,
    *,
    start_line: int | None = None,
    max_lines: int | None = None,
    max_chars: int | None = None,
    expected_version: str = "",
) -> dict:
    start_line = 1 if start_line is None else start_line
    max_lines = DEFAULT_MAX_LINES if max_lines is None else max_lines
    max_chars = DEFAULT_MAX_CHARS if max_chars is None else max_chars
    for name, value, low, high in (
        ("start_line", start_line, 1, None),
        ("max_lines", max_lines, 1, MAX_LINES),
        ("max_chars", max_chars, MIN_MAX_CHARS, DEFAULT_MAX_CHARS),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < low or (high is not None and value > high):
            bound = f"{low}~{high}" if high is not None else f"{low} 이상"
            return _error("invalid_argument", f"{name}는 {bound}의 정수입니다.")
    if not isinstance(expected_version, str):
        return _error("invalid_argument", "expected_version은 문자열입니다.")

    try:
        normalized, path = resolve_scoped_file(vault_dir, rel_path)
    except VaultScopeError as exc:
        code = "not_found" if "찾지 못했습니다" in str(exc) else "scope_violation"
        return _error(code, str(exc))
    try:
        source = read_source_text(path)
    except OSError as exc:
        return _error("read_failed", f"파일을 읽지 못했습니다: {exc.strerror or exc}", path=normalized)

    base = {
        "path": normalized,
        "record_tier": record_tier(normalized),
        "source_version": source.version,
        "total_lines": source.total_lines,
        "line_ending": source.line_ending,
        "frontmatter_lines": list(source.frontmatter_lines) if source.frontmatter_lines else None,
        "line_basis": "frontmatter 포함 파일 전체, 1부터",
    }
    warnings = list(source.warnings)
    if source.has_bom:
        warnings.append("파일 앞 UTF-8 BOM은 content에서 뺐습니다 (줄 번호는 그대로).")
    if expected_version and expected_version != source.version:
        return _error(
            "version_mismatch",
            "읽기 시작한 뒤 파일 내용이 바뀌었습니다. 앞 페이지와 섞이지 않도록 내용을 돌려주지 않습니다 — "
            "expected_version 없이 처음부터 다시 읽으세요.",
            expected_version=expected_version, **base,
        )

    total = source.total_lines
    if total == 0:
        if start_line != 1:
            return _error("out_of_range", "빈 파일입니다. start_line=1로 읽으세요.", **base)
        return {"ok": True, **base, "start_line": 1, "end_line": 0, "returned_lines": 0, "content": "",
                "truncated": False, "truncation_reason": None, "long_line": None,
                "eof": True, "next": None, "warnings": warnings + ["빈 파일입니다."]}
    if start_line > total:
        return _error("out_of_range", f"start_line {start_line}이 전체 줄 수 {total}를 넘습니다.", **base)

    first_chars = len(source.lines[start_line - 1])
    if first_chars > max_chars:
        return _line_too_long(base, start_line, first_chars, max_chars, total, source.version)

    out_lines: list[str] = []
    used = 0
    line_no = start_line
    reason: str | None = None
    long_line: dict | None = None
    while line_no <= total:
        if len(out_lines) >= max_lines:
            reason = "max_lines"
            break
        text = source.lines[line_no - 1]
        if len(text) > max_chars:
            # 이 줄은 어떤 페이지에도 통째로 안 들어간다 — 앞에서 멈추고 알린다 (다음 호출이 line_too_long 결과)
            reason = "line_too_long"
            long_line = {"line": line_no, "line_chars": len(text)}
            break
        cost = len(text) + (1 if out_lines else 0)
        if used + cost > max_chars:
            reason = "max_chars"
            break
        out_lines.append(text)
        used += cost
        line_no += 1

    returned = len(out_lines)
    next_pos = {"start_line": line_no, "expected_version": source.version} if reason is not None else None
    return {
        "ok": True,
        **base,
        "start_line": start_line,
        "end_line": start_line + returned - 1,
        "returned_lines": returned,
        "content": "\n".join(out_lines),
        "truncated": reason is not None,
        "truncation_reason": reason,
        "long_line": long_line,
        "eof": next_pos is None,
        "next": next_pos,
        "warnings": warnings,
    }


def _line_too_long(base: dict, line_no: int, line_chars: int, max_chars: int, total: int, version: str) -> dict:
    """첫 줄이 max_chars보다 긴 경우 — 줄 일부를 성공처럼 내지 않는다. next는 그 다음 줄이다."""
    if line_chars <= DEFAULT_MAX_CHARS:
        how = f"max_chars={line_chars} 이상으로 다시 읽으면 이 줄을 통째로 받습니다."
    else:
        how = (f"이 줄은 structured 읽기 상한({DEFAULT_MAX_CHARS}자)보다 길어 줄 단위로 줄 수 없습니다 — "
               "전문이 필요하면 read_note(structured=False)로 읽으세요.")
    next_pos = {"start_line": line_no + 1, "expected_version": version} if line_no < total else None
    return _error(
        "line_too_long",
        f"{line_no}행이 {line_chars}자라 max_chars {max_chars}에 들어가지 않습니다. 줄을 잘라 주지 않습니다. {how}",
        line=line_no, line_chars=line_chars, max_chars=max_chars,
        readable_with_max_chars=line_chars <= DEFAULT_MAX_CHARS, next=next_pos, **base,
    )
