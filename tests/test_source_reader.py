"""app/services/source_reader.py — structured 원문 구간 읽기."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.source_reader import read_range
from app.services.vault_source import content_version, split_source_lines


def _w(vault: Path, rel: str, data: str | bytes) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_bytes(data.encode("utf-8"))
    else:
        path.write_bytes(data)
    return path


def _follow(vault: Path, rel: str, **kwargs) -> list[dict]:
    """next를 끝까지 따라간다. 무한 이어읽기면 실패한다."""
    pages = [read_range(vault, rel, **kwargs)]
    while pages[-1].get("ok") and pages[-1]["next"]:
        nxt = pages[-1]["next"]
        pages.append(read_range(vault, rel, start_line=nxt["start_line"], char_offset=nxt["char_offset"],
                                expected_version=nxt["expected_version"],
                                **{k: v for k, v in kwargs.items() if k in ("max_lines", "max_chars")}))
        assert len(pages) < 500, "continuation이 끝나지 않는다"
    return pages


def test_line_numbers_include_frontmatter(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "---\ntitle: 가\n---\n# 제목\n\n본문 줄\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", start_line=6, max_lines=1)
    assert r["ok"] and r["content"] == "본문 줄"
    assert r["total_lines"] == 6 and r["frontmatter_lines"] == [1, 3]
    assert (r["start_line"], r["end_line"], r["returned_lines"]) == (6, 6, 1)
    assert r["eof"] and r["next"] is None and not r["truncated"]


def test_exact_range_and_next_position(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "".join(f"줄{i}\n" for i in range(1, 11)))
    r = read_range(tmp_path, "20_Knowledge/a.md", start_line=3, max_lines=4)
    assert r["content"] == "줄3\n줄4\n줄5\n줄6"
    assert (r["end_line"], r["truncation_reason"]) == (6, "max_lines")
    assert r["next"] == {"start_line": 7, "char_offset": 0, "expected_version": r["source_version"]}
    assert not r["eof"]


def test_crlf_and_hangul_lines(tmp_path):
    raw = "---\r\ntitle: 한글\r\n---\r\n첫 줄 한글\r\n둘째 줄\r\n"
    _w(tmp_path, "20_Knowledge/crlf.md", raw)
    r = read_range(tmp_path, "20_Knowledge/crlf.md")
    assert r["line_ending"] == "crlf" and r["total_lines"] == 5
    assert r["content"].split("\n")[3] == "첫 줄 한글"
    assert "\r" not in r["content"]
    assert r["source_version"] == content_version(raw.encode("utf-8"))


def test_mixed_line_endings_and_vertical_tab_not_split(tmp_path):
    lines, ending = split_source_lines("a\r\nb\x0bc\nd")
    assert lines == ["a", "b\x0bc", "d"] and ending == "mixed"


def test_empty_file(tmp_path):
    _w(tmp_path, "20_Knowledge/empty.md", "")
    r = read_range(tmp_path, "20_Knowledge/empty.md")
    assert r["ok"] and r["total_lines"] == 0 and r["content"] == "" and r["eof"] and r["next"] is None
    assert any("빈 파일" in w for w in r["warnings"])
    bad = read_range(tmp_path, "20_Knowledge/empty.md", start_line=2)
    assert not bad["ok"] and bad["error"]["code"] == "out_of_range"


def test_start_beyond_eof_is_error_not_empty_success(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "하나\n둘\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", start_line=3)
    assert not r["ok"] and r["error"]["code"] == "out_of_range" and r["error"]["total_lines"] == 2


def test_no_trailing_newline_last_line(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "하나\n둘")
    pages = _follow(tmp_path, "20_Knowledge/a.md", max_lines=1)
    assert [p["content"] for p in pages] == ["하나", "둘"]
    assert pages[-1]["eof"] and pages[-1]["next"] is None


def test_max_chars_stops_before_line_that_does_not_fit(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "가" * 150 + "\n" + "나" * 150 + "\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", max_chars=200)
    assert r["returned_lines"] == 1 and r["truncation_reason"] == "max_chars"
    assert r["next"]["start_line"] == 2 and r["next"]["char_offset"] == 0


def test_long_single_line_continues_by_char_offset_and_terminates(tmp_path):
    line = "".join(chr(0xAC00 + (i % 50)) for i in range(1000))
    _w(tmp_path, "20_Knowledge/long.md", line + "\n끝\n")
    pages = _follow(tmp_path, "20_Knowledge/long.md", max_chars=300)
    first = pages[0]
    assert first["truncation_reason"] == "long_line" and first["truncated"] and not first["eof"]
    assert first["line_clip"] == {"line": 1, "char_start": 0, "char_end": 300, "line_chars": 1000}
    # 긴 줄 조각은 이어 붙이면 원문 그대로다 — 마지막 조각 페이지에는 다음 줄이 함께 올 수 있다
    assert "".join(p["content"] for p in pages) == line + "\n끝"
    assert [p["char_offset"] for p in pages] == [0, 300, 600, 900]
    assert pages[-1]["eof"] and pages[-1]["next"] is None


def test_version_mismatch_returns_no_content(tmp_path):
    path = _w(tmp_path, "20_Knowledge/a.md", "".join(f"{i}\n" for i in range(10)))
    first = read_range(tmp_path, "20_Knowledge/a.md", max_lines=3)
    path.write_text("바뀜\n" * 10, encoding="utf-8")
    nxt = first["next"]
    r = read_range(tmp_path, "20_Knowledge/a.md", start_line=nxt["start_line"], expected_version=nxt["expected_version"])
    assert not r["ok"] and r["error"]["code"] == "version_mismatch"
    assert "content" not in r and r["error"]["source_version"] != nxt["expected_version"]


@pytest.mark.parametrize("kwargs", [
    {"start_line": 0}, {"max_lines": 401}, {"max_lines": 0}, {"max_chars": 16001}, {"char_offset": -1},
    {"start_line": True},
])
def test_invalid_arguments(tmp_path, kwargs):
    _w(tmp_path, "20_Knowledge/a.md", "a\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", **kwargs)
    assert not r["ok"] and r["error"]["code"] == "invalid_argument"


def test_char_offset_beyond_line_is_out_of_range(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "abc\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", char_offset=3)
    assert not r["ok"] and r["error"]["code"] == "out_of_range"


def test_defaults_are_120_lines_16000_chars(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "x\n" * 500)
    r = read_range(tmp_path, "20_Knowledge/a.md")
    assert r["returned_lines"] == 120 and r["next"]["start_line"] == 121
    _w(tmp_path, "20_Knowledge/b.md", ("y" * 99 + "\n") * 300)
    r = read_range(tmp_path, "20_Knowledge/b.md", max_lines=400)
    assert len(r["content"]) <= 16000 and r["truncation_reason"] == "max_chars"


def test_bom_is_stripped_but_line_numbers_kept(tmp_path):
    _w(tmp_path, "20_Knowledge/bom.md", b"\xef\xbb\xbf---\ntitle: x\n---\nbody\n")
    r = read_range(tmp_path, "20_Knowledge/bom.md")
    assert r["content"].startswith("---") and r["frontmatter_lines"] == [1, 3]
    assert any("BOM" in w for w in r["warnings"])


def test_non_utf8_is_read_with_warning(tmp_path):
    _w(tmp_path, "20_Knowledge/cp949.md", "한글".encode("cp949") + b"\n")
    r = read_range(tmp_path, "20_Knowledge/cp949.md")
    assert r["ok"] and any("UTF-8" in w for w in r["warnings"])


@pytest.mark.parametrize("rel", ["00_Inbox/x.md", "../etc/passwd", "/etc/passwd", "20_Knowledge/../00_Inbox/x.md"])
def test_scope_violation(tmp_path, rel):
    _w(tmp_path, "00_Inbox/x.md", "비밀\n")
    r = read_range(tmp_path, rel)
    assert not r["ok"] and r["error"]["code"] == "scope_violation"


def test_symlink_to_forbidden_prefix_is_rejected(tmp_path):
    _w(tmp_path, "00_Inbox/secret.md", "비밀\n")
    (tmp_path / "20_Knowledge").mkdir()
    os.symlink(tmp_path / "00_Inbox" / "secret.md", tmp_path / "20_Knowledge" / "link.md")
    r = read_range(tmp_path, "20_Knowledge/link.md")
    assert not r["ok"] and r["error"]["code"] == "scope_violation"


def test_symlink_outside_vault_is_rejected(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("밖\n", encoding="utf-8")
    vault = tmp_path / "vault"
    (vault / "30_Projects").mkdir(parents=True)
    os.symlink(tmp_path, vault / "30_Projects" / "escape")
    r = read_range(vault, "30_Projects/escape/outside.md")
    assert not r["ok"] and r["error"]["code"] == "scope_violation"


def test_missing_file(tmp_path):
    (tmp_path / "20_Knowledge").mkdir()
    r = read_range(tmp_path, "20_Knowledge/없음.md")
    assert not r["ok"] and r["error"]["code"] == "not_found"


def test_hidden_folder_file_is_still_readable(tmp_path):
    """기존 read_note 범위는 숨김 폴더를 막지 않았다 — 링크 검사가 그 범위를 줄이면 안 된다."""
    from app import vault_tools

    _w(tmp_path, "20_Knowledge/.drafts/h.md", "숨김 초안\n")
    settings = type("S", (), {"obsidian_vault_root": str(tmp_path)})()
    assert vault_tools.read_note("20_Knowledge/.drafts/h.md", settings=settings) == "숨김 초안\n"
    assert read_range(tmp_path, "20_Knowledge/.drafts/h.md")["content"] == "숨김 초안"
