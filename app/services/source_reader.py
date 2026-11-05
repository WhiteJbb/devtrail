"""structured 원문 구간 읽기 — 검색 발췌와 같은 줄 기준으로 정확한 구간을 돌려준다.

이어 읽기 보장: 한 페이지는 최소 한 줄(빈 줄 포함) 또는 긴 줄의 최소 한 글자를 소비한다. 그래서
`next`를 따라가면 반드시 EOF에서 끝난다(next=None). 버전이 바뀐 파일을 이어 읽으면 앞 페이지와
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
    char_offset: int | None = None,
    expected_version: str = "",
) -> dict:
    start_line = 1 if start_line is None else start_line
    max_lines = DEFAULT_MAX_LINES if max_lines is None else max_lines
    max_chars = DEFAULT_MAX_CHARS if max_chars is None else max_chars
    char_offset = 0 if char_offset is None else char_offset
    for name, value, low, high in (
        ("start_line", start_line, 1, None),
        ("max_lines", max_lines, 1, MAX_LINES),
        ("max_chars", max_chars, MIN_MAX_CHARS, DEFAULT_MAX_CHARS),
        ("char_offset", char_offset, 0, None),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < low or (high is not None and value > high):
            bound = f"{low}~{high}" if high is not None else f"{low} 이상"
            return _error("invalid_argument", f"{name}는 {bound}의 정수입니다.")

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
        if start_line != 1 or char_offset:
            return _error("out_of_range", "빈 파일입니다. start_line=1로 읽으세요.", **base)
        return {"ok": True, **base, "start_line": 1, "end_line": 0, "returned_lines": 0, "content": "",
                "char_offset": 0, "truncated": False, "truncation_reason": None, "line_clip": None,
                "eof": True, "next": None, "warnings": warnings + ["빈 파일입니다."]}
    if start_line > total:
        return _error("out_of_range", f"start_line {start_line}이 전체 줄 수 {total}를 넘습니다.", **base)
    first = source.lines[start_line - 1]
    if char_offset and char_offset >= len(first):
        return _error("out_of_range", f"char_offset {char_offset}이 {start_line}행 길이 {len(first)} 이상입니다.", **base)

    out_lines: list[str] = []
    used = 0
    line_no = start_line
    reason: str | None = None
    clip: dict | None = None
    next_pos: dict | None = None
    while line_no <= total:
        if len(out_lines) >= max_lines:
            reason = "max_lines"
            next_pos = {"start_line": line_no, "char_offset": 0}
            break
        text = source.lines[line_no - 1]
        offset = char_offset if line_no == start_line else 0
        piece = text[offset:]
        cost = len(piece) + (1 if out_lines else 0)
        if used + cost > max_chars:
            if out_lines:
                reason = "max_chars"
                next_pos = {"start_line": line_no, "char_offset": 0}
                break
            # 첫 줄 하나가 상한보다 길다 — 앞부분만 주고 같은 줄의 다음 문자 위치를 알려준다
            take = max_chars
            out_lines.append(piece[:take])
            reason = "long_line"
            clip = {"line": line_no, "char_start": offset, "char_end": offset + take, "line_chars": len(text)}
            next_pos = {"start_line": line_no, "char_offset": offset + take}
            used += take
            break
        out_lines.append(piece)
        used += cost
        line_no += 1

    returned = len(out_lines)
    end_line = start_line + returned - 1
    if next_pos is not None:
        next_pos["expected_version"] = source.version
    eof = next_pos is None
    return {
        "ok": True,
        **base,
        "start_line": start_line,
        "end_line": end_line,
        "returned_lines": returned,
        "content": "\n".join(out_lines),
        "char_offset": char_offset,
        "truncated": reason is not None,
        "truncation_reason": reason,
        "line_clip": clip,
        "eof": eof,
        "next": next_pos,
        "warnings": warnings,
    }
