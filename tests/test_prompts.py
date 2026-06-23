from app.prompts import load_prompt, render_prompt


def test_load_known_prompts():
    for name in ("distill_candidates", "worklog_summary", "todo_suggest", "write_wiki_blog"):
        assert load_prompt(name).strip()


def test_render_replaces_tokens():
    rendered = render_prompt("distill_candidates", KIND="knowledge", DATE="2026-06-23", CONTEXT="작업 내용", RELATED_KNOWLEDGE="")
    assert "{{KIND}}" not in rendered
    assert "{{CONTEXT}}" not in rendered
    assert "2026-06-23" in rendered
    assert "작업 내용" in rendered
