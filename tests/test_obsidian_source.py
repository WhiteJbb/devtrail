from pathlib import Path

import pytest

from app.content_sources.obsidian_source import ObsidianSource


def _note(vault: Path, rel: str, content: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── 기본 읽기 ──────────────────────────────────────────────────────────

def test_reads_notes(tmp_path):
    _note(tmp_path, "note.md", "# 제목\n본문 내용")
    chunks = ObsidianSource(tmp_path).fetch()
    assert len(chunks) == 1
    assert chunks[0].source_type == "obsidian"
    assert chunks[0].title == "note"
    assert "본문 내용" in chunks[0].text


def test_missing_vault_returns_empty(tmp_path):
    assert ObsidianSource(tmp_path / "nope").fetch() == []


def test_empty_note_skipped(tmp_path):
    _note(tmp_path, "empty.md", "---\ntags: []\n---\n   \n")
    assert ObsidianSource(tmp_path).fetch() == []


def test_strips_frontmatter(tmp_path):
    _note(tmp_path, "a.md", "---\ntags: [blog-idea]\n---\n본문만")
    chunks = ObsidianSource(tmp_path).fetch()
    assert chunks[0].text == "본문만"
    assert "tags" not in chunks[0].text


def test_wikilinks_replaced_with_text(tmp_path):
    _note(tmp_path, "a.md", "[[다른 노트]] 참고")
    chunks = ObsidianSource(tmp_path).fetch()
    assert "다른 노트" in chunks[0].text
    assert "[[" not in chunks[0].text


# ── 태그 필터 ──────────────────────────────────────────────────────────

def test_tag_filter_frontmatter(tmp_path):
    _note(tmp_path, "yes.md", "---\ntags: [blog-idea]\n---\n포함됨")
    _note(tmp_path, "no.md", "---\ntags: [other]\n---\n제외됨")
    chunks = ObsidianSource(tmp_path, tags=["blog-idea"]).fetch()
    assert len(chunks) == 1
    assert "포함됨" in chunks[0].text


def test_tag_filter_inline(tmp_path):
    _note(tmp_path, "yes.md", "내용 #worklog 기록")
    _note(tmp_path, "no.md", "내용 #other 기록")
    chunks = ObsidianSource(tmp_path, tags=["worklog"]).fetch()
    assert len(chunks) == 1


def test_tag_filter_case_insensitive(tmp_path):
    _note(tmp_path, "a.md", "---\ntags: [Blog-Idea]\n---\n내용")
    chunks = ObsidianSource(tmp_path, tags=["blog-idea"]).fetch()
    assert len(chunks) == 1


def test_no_tag_filter_reads_all(tmp_path):
    _note(tmp_path, "a.md", "내용A")
    _note(tmp_path, "b.md", "내용B")
    chunks = ObsidianSource(tmp_path).fetch()
    assert len(chunks) == 2


# ── 폴더 필터 ──────────────────────────────────────────────────────────

def test_folder_filter(tmp_path):
    _note(tmp_path, "blog/post.md", "블로그 내용")
    _note(tmp_path, "daily/today.md", "일기 내용")
    chunks = ObsidianSource(tmp_path, folders=["blog"]).fetch()
    assert len(chunks) == 1
    assert "블로그 내용" in chunks[0].text


def test_nonexistent_folder_returns_empty(tmp_path):
    _note(tmp_path, "note.md", "내용")
    chunks = ObsidianSource(tmp_path, folders=["없는폴더"]).fetch()
    assert chunks == []


def test_ref_is_relative_path(tmp_path):
    _note(tmp_path, "sub/note.md", "내용")
    chunks = ObsidianSource(tmp_path).fetch()
    assert chunks[0].ref == str(Path("sub/note.md"))
