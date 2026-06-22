from app.content_sources.collector import SourceCollector
from app.models import SourceChunk


class _FakeSource:
    name = "fake"

    def __init__(self, chunks):
        self._chunks = chunks

    def fetch(self):
        return self._chunks


class _BrokenSource:
    name = "broken"

    def fetch(self):
        raise RuntimeError("boom")


def test_budget_truncates_total():
    big = SourceChunk(source_type="worklog", ref="w", text="x" * 5000)
    collector = SourceCollector([_FakeSource([big])], char_budget=1000, per_chunk_limit=4000)
    ctx = collector.collect()
    assert sum(len(c.text) for c in ctx.chunks) <= 1000 + 20  # 생략 표시 여유


def test_broken_source_does_not_stop_pipeline():
    ok = SourceChunk(source_type="git", ref="g", text="commit")
    collector = SourceCollector([_BrokenSource(), _FakeSource([ok])], char_budget=1000)
    ctx = collector.collect()
    assert any(c.source_type == "git" for c in ctx.chunks)


def test_refs_deduped_and_ordered():
    a = SourceChunk(source_type="worklog", ref="w", title="worklog", text="a")
    b = SourceChunk(source_type="worklog", ref="w", title="worklog", text="b")
    ctx = SourceCollector([_FakeSource([a, b])]).collect()
    assert ctx.refs == ["worklog:worklog"]
