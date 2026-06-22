from app.prompts import load_prompt, render_prompt


def test_load_known_prompts():
    for name in ("recommend_topics", "write_draft", "revise_draft"):
        assert load_prompt(name).strip()


def test_render_replaces_tokens():
    rendered = render_prompt("write_draft", TOPIC="환경 분리", CONTEXT="작업 내용")
    assert "{{TOPIC}}" not in rendered
    assert "{{CONTEXT}}" not in rendered
    assert "환경 분리" in rendered
    assert "작업 내용" in rendered
