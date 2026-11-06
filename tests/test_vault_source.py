"""app/services/vault_source.py — 줄 기준·실제 경로 범위·내용 버전."""

from __future__ import annotations

import os

import pytest

from app.services.vault_source import (
    VaultNotFoundError,
    VaultScopeError,
    content_version,
    decode_source,
    real_scoped_rel,
    resolve_scoped_file,
    split_source_lines,
)


@pytest.mark.parametrize("text, lines, ending", [
    ("", [], "none"),
    ("a", ["a"], "none"),
    ("a\n", ["a"], "lf"),
    ("a\r\nb\r\n", ["a", "b"], "crlf"),
    ("a\r\nb\nc", ["a", "b", "c"], "mixed"),
    ("a\x0bb\u2028c\n", ["a\x0bb\u2028c"], "lf"),  # \x0b·\u2028은 줄 끝이 아니다
    ("\n\n", ["", ""], "lf"),
])
def test_split_source_lines(text, lines, ending):
    assert split_source_lines(text) == (lines, ending)


def test_frontmatter_range_and_bom():
    src = decode_source("\ufeff---\ntitle: x\n----  \n본문\n".encode("utf-8"))
    assert src.has_bom and src.frontmatter_lines == (1, 3) and src.body_start_line == 4
    assert src.version == content_version("\ufeff---\ntitle: x\n----  \n본문\n".encode("utf-8"))


def test_real_scoped_rel_checks_real_path_and_hidden(tmp_path):
    (tmp_path / "00_Inbox").mkdir()
    (tmp_path / "00_Inbox" / "s.md").write_text("x", encoding="utf-8")
    (tmp_path / "20_Knowledge" / ".hidden").mkdir(parents=True)
    (tmp_path / "20_Knowledge" / ".hidden" / "h.md").write_text("x", encoding="utf-8")
    os.symlink(tmp_path / "00_Inbox" / "s.md", tmp_path / "20_Knowledge" / "link.md")
    assert real_scoped_rel(tmp_path, tmp_path / "20_Knowledge" / "link.md") is None
    assert real_scoped_rel(tmp_path, tmp_path / "20_Knowledge" / ".hidden" / "h.md") is None
    assert real_scoped_rel(tmp_path, tmp_path / "20_Knowledge" / ".hidden" / "h.md", allow_hidden=True) == "20_Knowledge/.hidden/h.md"


def test_resolve_scoped_file_errors(tmp_path):
    with pytest.raises(VaultNotFoundError):
        resolve_scoped_file(tmp_path, "20_Knowledge/none.md")
    for bad in ("../x.md", "/etc/passwd", "00_Inbox/a.md", "C:/x.md", ""):
        with pytest.raises(VaultScopeError) as info:
            resolve_scoped_file(tmp_path, bad)
        assert not isinstance(info.value, VaultNotFoundError)
