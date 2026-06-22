from app.content_sources.local_doc_source import LocalDocSource


def test_reads_known_docs(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "worklog.md").write_text("# 작업\n환경 분리함", encoding="utf-8")
    (docs / "blog-ideas.md").write_text("- RAG 분리", encoding="utf-8")
    (docs / "random.md").write_text("무시되어야 함", encoding="utf-8")

    chunks = LocalDocSource(docs).fetch()

    types = {c.source_type for c in chunks}
    assert types == {"worklog", "blog-ideas"}  # random.md는 제외
    assert any("환경 분리" in c.text for c in chunks)


def test_missing_dir_returns_empty(tmp_path):
    assert LocalDocSource(tmp_path / "nope").fetch() == []


def test_empty_file_skipped(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "todo.md").write_text("   \n", encoding="utf-8")
    assert LocalDocSource(docs).fetch() == []
