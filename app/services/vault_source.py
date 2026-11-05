"""Vault 원문 접근의 공통 바닥 — 읽기 범위 검증, 실제 경로 확인, 줄 분할, 내용 버전.

검색 발췌의 줄 번호와 원문 구간 읽기의 줄 번호가 같은 기준이어야 발췌를 보고 바로 그
구간을 읽을 수 있다. 그래서 둘 다 이 모듈의 `split_source_lines`만 쓴다.

줄 기준: frontmatter를 포함한 파일 전체, 1부터. 줄 끝은 `\\r\\n`과 `\\n`만 인정한다
(str.splitlines는 \\x0b·\\x1c·\\u2028 같은 문자도 줄 끝으로 봐 편집기 줄 번호와 어긋난다).
파일 끝 줄바꿈 뒤의 빈 문자열은 줄로 세지 않는다 — 편집기 표시와 같다.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

STABLE_PREFIXES = ("20_Knowledge/", "30_Projects/", "40_AgentMemory/")
CANDIDATE_PREFIX = "60_Candidates/"
RAW_PREFIXES = ("10_Worklog/", "50_Outputs/", "70_Tasks/")
ALLOWED_READ_PREFIXES = STABLE_PREFIXES + (CANDIDATE_PREFIX,) + RAW_PREFIXES

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_LINE_RE = re.compile(r"\r\n|\n")
# python-frontmatter YAMLHandler의 경계(^-{3,}\s*$)와 같게 맞춘다 — 다르면 메타데이터 해석과 본문 줄 범위가 어긋난다
_FM_BOUNDARY_RE = re.compile(r"-{3,}\s*")


class VaultScopeError(ValueError):
    """read_scope/write_scope를 벗어난 요청."""


def record_tier(rel_path: str) -> str:
    """경로가 정하는 기록 등급 — stable(정본) / candidate(후보) / raw(원문). 문서 status와 별개다."""
    if rel_path.startswith(CANDIDATE_PREFIX):
        return "candidate"
    if rel_path.startswith(RAW_PREFIXES):
        return "raw"
    return "stable"


def normalize_scoped_path(rel_path: str) -> str:
    """rel_path를 vault 기준 상대경로로 정규화하고 read_scope를 벗어나면 거부한다 (문자열 검사만)."""
    if not rel_path or not rel_path.strip():
        raise VaultScopeError("rel_path가 비어 있습니다.")
    candidate = rel_path.strip().replace("\\", "/")
    if candidate.startswith("/") or _DRIVE_RE.match(candidate):
        raise VaultScopeError(f"절대경로는 허용되지 않습니다: {rel_path}")
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise VaultScopeError(f"vault를 벗어나는 경로는 허용되지 않습니다: {rel_path}")
    normalized = "/".join(parts)
    if not any(normalized.startswith(prefix) for prefix in ALLOWED_READ_PREFIXES):
        raise VaultScopeError(f"read_scope 밖의 경로입니다: {rel_path}")
    return normalized


def real_scoped_rel(vault_dir: Path, path: Path, *, allow_hidden: bool = False) -> str | None:
    """심볼릭 링크를 모두 푼 실제 경로가 vault 안 허용 prefix에 있으면 그 상대경로, 아니면 None.

    문자열 검사만 하면 `20_Knowledge/x.md -> ../00_Inbox/secret.md` 같은 링크로 금지 영역이나
    vault 밖을 읽을 수 있다. 실제 경로 기준으로 prefix를 다시 본다.
    allow_hidden=False(검색 스캔)면 숨김 폴더·파일도 거부한다 — 검색은 원래 숨김 경로를 보지 않는다.
    읽기는 기존 read_note 범위(숨김 폴더 허용)를 지키려고 allow_hidden=True로 부른다.
    """
    try:
        real_root = Path(os.path.realpath(vault_dir))
        real = Path(os.path.realpath(path))
    except (OSError, ValueError):
        return None
    if not real.is_relative_to(real_root):
        return None
    rel = real.relative_to(real_root).as_posix()
    if not allow_hidden and any(part.startswith(".") for part in rel.split("/")):
        return None
    if not rel.startswith(ALLOWED_READ_PREFIXES):
        return None
    return rel


def resolve_scoped_file(vault_dir: Path, rel_path: str) -> tuple[str, Path]:
    """읽기 요청 경로를 검증해 (정규화 rel_path, 실제 파일 경로)를 반환한다. 범위 밖이면 VaultScopeError."""
    normalized = normalize_scoped_path(rel_path)
    path = vault_dir / normalized
    if real_scoped_rel(vault_dir, path, allow_hidden=True) is None:
        raise VaultScopeError(f"실제 경로가 read_scope 밖입니다(심볼릭 링크 포함): {rel_path}")
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise VaultScopeError(f"노트를 찾지 못했습니다: {rel_path}")
    return normalized, resolved


def content_version(raw: bytes) -> str:
    """원문 바이트의 내용 버전. 같은 바이트면 같은 값 — mtime은 복사·checkout에 흔들려 쓰지 않는다."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class SourceText:
    """디코드·줄 분할을 마친 원문 한 파일."""

    version: str
    lines: list[str]
    line_ending: str  # "lf" | "crlf" | "mixed" | "none"
    has_bom: bool = False
    decode_replaced: bool = False  # UTF-8이 아니어서 대체 문자로 읽었다
    frontmatter_lines: tuple[int, int] | None = None  # (1, 닫는 '---' 줄) — 1-based, 포함
    byte_size: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def total_lines(self) -> int:
        return len(self.lines)

    @property
    def body_start_line(self) -> int:
        """본문이 시작하는 1-based 줄 번호 (frontmatter 바로 다음)."""
        return self.frontmatter_lines[1] + 1 if self.frontmatter_lines else 1


def split_source_lines(text: str) -> tuple[list[str], str]:
    """`\\r\\n`/`\\n` 기준으로 줄을 나눈다. (줄 목록, 줄 끝 종류)."""
    if not text:
        return [], "none"
    endings = _LINE_RE.findall(text)
    lines = _LINE_RE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    kinds = {"crlf" if e == "\r\n" else "lf" for e in endings}
    if not kinds:
        ending = "none"
    elif len(kinds) == 1:
        ending = kinds.pop()
    else:
        ending = "mixed"
    return lines, ending


def _frontmatter_range(lines: list[str]) -> tuple[int, int] | None:
    if not lines or not _FM_BOUNDARY_RE.fullmatch(lines[0]):
        return None
    for i in range(1, len(lines)):
        if _FM_BOUNDARY_RE.fullmatch(lines[i]):
            return (1, i + 1)
    return None


def decode_source(raw: bytes) -> SourceText:
    """원문 바이트를 SourceText로 만든다. 버전은 디코드 전 바이트 기준."""
    warnings: list[str] = []
    replaced = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        replaced = True
        warnings.append("UTF-8이 아닌 바이트가 있어 대체 문자(U+FFFD)로 읽었습니다.")
    has_bom = text.startswith("\ufeff")
    if has_bom:
        text = text[1:]
    lines, ending = split_source_lines(text)
    return SourceText(
        version=content_version(raw),
        lines=lines,
        line_ending=ending,
        has_bom=has_bom,
        decode_replaced=replaced,
        frontmatter_lines=_frontmatter_range(lines),
        byte_size=len(raw),
        warnings=warnings,
    )


def read_source_text(path: Path) -> SourceText:
    """파일을 읽어 SourceText로 만든다. 읽기 실패는 OSError로 그대로 올린다 (호출 측이 partial로 드러낸다)."""
    return decode_source(path.read_bytes())
