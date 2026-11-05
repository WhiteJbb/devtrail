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


def _next_of(page: dict) -> dict | None:
    if page.get("ok"):
        return page["next"]
    if page["error"]["code"] == "line_too_long":
        return page["error"]["next"]
    return None


def _follow(vault: Path, rel: str, **kwargs) -> list[dict]:
    """next(성공 페이지)와 error.next(line_too_long)를 끝까지 따라간다. 무한 이어읽기면 실패한다."""
    pages = [read_range(vault, rel, **kwargs)]
    while (nxt := _next_of(pages[-1])) is not None:
        prev = pages[-1]
        prev_start = prev["start_line"] if prev.get("ok") else prev["error"]["line"]
        assert nxt["start_line"] > prev_start, "next가 앞으로 나아가지 않는다"
        if prev.get("ok"):
            assert prev["returned_lines"] >= 1 and nxt["start_line"] == prev["end_line"] + 1
        pages.append(read_range(vault, rel, start_line=nxt["start_line"], expected_version=nxt["expected_version"],
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
    assert r["next"] == {"start_line": 7, "expected_version": r["source_version"]}
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
    assert r["next"] == {"start_line": 2, "expected_version": r["source_version"]}
    assert "char_offset" not in r and "line_clip" not in r


def test_long_first_line_is_line_too_long_not_a_partial_line(tmp_path):
    """긴 줄은 잘라 주지 않는다 — 내용 없는 line_too_long 결과, 다음 줄로 넘어가는 next."""
    line = "".join(chr(0xAC00 + (i % 50)) for i in range(1000))
    _w(tmp_path, "20_Knowledge/long.md", line + "\n끝\n")
    r = read_range(tmp_path, "20_Knowledge/long.md", max_chars=300)
    assert not r["ok"] and "content" not in r
    err = r["error"]
    assert err["code"] == "line_too_long" and (err["line"], err["line_chars"], err["max_chars"]) == (1, 1000, 300)
    assert err["readable_with_max_chars"] is True and err["total_lines"] == 2
    assert err["next"] == {"start_line": 2, "expected_version": err["source_version"]}
    # 상한 안 길이면 max_chars를 올려 통째로 받는다
    whole = read_range(tmp_path, "20_Knowledge/long.md", max_chars=1000, max_lines=1)
    assert whole["ok"] and whole["content"] == line and whole["end_line"] == 1


def test_long_line_in_middle_stops_before_it_and_terminates(tmp_path):
    long_line = "가" * 500
    _w(tmp_path, "20_Knowledge/m.md", "첫\n" + long_line + "\n셋\n" + long_line + "\n")
    pages = _follow(tmp_path, "20_Knowledge/m.md", max_chars=300)
    p1, e2, p3, e4 = pages
    assert p1["content"] == "첫" and p1["truncation_reason"] == "line_too_long"
    assert p1["long_line"] == {"line": 2, "line_chars": 500} and p1["next"]["start_line"] == 2 and not p1["eof"]
    assert e2["error"]["code"] == "line_too_long" and e2["error"]["next"]["start_line"] == 3
    assert p3["content"] == "셋" and p3["next"]["start_line"] == 4
    # 마지막 줄이 긴 줄이면 next가 없다 — 같은 줄을 다시 가리키지 않는다
    assert e4["error"]["line"] == 4 and e4["error"]["next"] is None


def test_line_longer_than_absolute_cap_points_to_legacy_full_read(tmp_path):
    _w(tmp_path, "20_Knowledge/huge.md", "x" * 16001 + "\n")
    err = read_range(tmp_path, "20_Knowledge/huge.md")["error"]
    assert err["code"] == "line_too_long" and err["readable_with_max_chars"] is False and err["next"] is None
    assert "structured=False" in err["message"]


def test_pages_hold_only_whole_lines_and_cover_file_in_order(tmp_path):
    """임의 길이 줄로 이어 읽기 — 모든 페이지의 content는 원문 줄 그대로이고, 건너뛴 줄은 line_too_long으로 드러난다."""
    import random

    rng = random.Random(7)
    lines = ["".join(rng.choice("가나다abc ") for _ in range(rng.choice([0, 1, 5, 40, 150, 260, 420]))) for _ in range(120)]
    _w(tmp_path, "20_Knowledge/r.md", "\r\n".join(lines) + "\r\n")
    pages = _follow(tmp_path, "20_Knowledge/r.md", max_chars=300, max_lines=7)
    seen: list[str] = []
    for p in pages:
        if p["ok"]:
            assert p["content"].split("\n") == lines[p["start_line"] - 1:p["end_line"]]
            assert len(p["content"]) <= 300
            seen += lines[p["start_line"] - 1:p["end_line"]]
        else:
            assert p["error"]["code"] == "line_too_long" and len(lines[p["error"]["line"] - 1]) > 300
            seen.append(lines[p["error"]["line"] - 1])
    assert seen == lines


def test_version_mismatch_returns_no_content(tmp_path):
    path = _w(tmp_path, "20_Knowledge/a.md", "".join(f"{i}\n" for i in range(10)))
    first = read_range(tmp_path, "20_Knowledge/a.md", max_lines=3)
    path.write_text("바뀜\n" * 10, encoding="utf-8")
    nxt = first["next"]
    r = read_range(tmp_path, "20_Knowledge/a.md", start_line=nxt["start_line"], expected_version=nxt["expected_version"])
    assert not r["ok"] and r["error"]["code"] == "version_mismatch"
    assert "content" not in r and r["error"]["source_version"] != nxt["expected_version"]


@pytest.mark.parametrize("kwargs", [
    {"start_line": 0}, {"max_lines": 401}, {"max_lines": 0}, {"max_chars": 16001}, {"max_chars": 199},
    {"start_line": True},
])
def test_invalid_arguments(tmp_path, kwargs):
    _w(tmp_path, "20_Knowledge/a.md", "a\n")
    r = read_range(tmp_path, "20_Knowledge/a.md", **kwargs)
    assert not r["ok"] and r["error"]["code"] == "invalid_argument"


def test_char_offset_is_not_part_of_the_contract(tmp_path):
    _w(tmp_path, "20_Knowledge/a.md", "abc\n")
    with pytest.raises(TypeError):
        read_range(tmp_path, "20_Knowledge/a.md", char_offset=3)


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
