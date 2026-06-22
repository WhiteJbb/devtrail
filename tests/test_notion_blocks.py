from app.notion import mapping
from app.notion.mock_client import MockNotionClient


def test_block_to_text_variants():
    para = {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "문단"}]}}
    h2 = {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "제목"}]}}
    bullet = {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "항목"}]}}
    code = {"type": "code", "code": {"language": "python", "rich_text": [{"plain_text": "print(1)"}]}}
    image = {"type": "image", "image": {}}

    assert mapping.block_to_text(para) == "문단"
    assert mapping.block_to_text(h2) == "## 제목"
    assert mapping.block_to_text(bullet) == "- 항목"
    assert mapping.block_to_text(code) == "```python\nprint(1)\n```"
    assert mapping.block_to_text(image) == ""  # URL 없는 이미지 블록은 무시


def test_block_to_text_image_variants():
    external = {
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": "https://img.test/a.png"},
            "caption": [{"plain_text": "구성도"}],
        },
    }
    file_img = {
        "type": "image",
        "image": {"type": "file", "file": {"url": "https://notion.test/signed.png"}, "caption": []},
    }
    assert mapping.block_to_text(external) == "![구성도](https://img.test/a.png)"
    assert mapping.block_to_text(file_img) == "![](https://notion.test/signed.png)"


def test_mock_get_page_text(tmp_path):
    import json

    store = tmp_path / "notion.json"
    store.write_text(
        json.dumps(
            {
                "blog_rows": {},
                "records": {"db": [{"id": "r1", "title": "t", "body": "본문 내용"}]},
                "pages": {"pg": "명시 페이지 본문"},
            }
        ),
        encoding="utf-8",
    )
    client = MockNotionClient(store)
    assert client.get_page_text("pg") == "명시 페이지 본문"
    assert client.get_page_text("r1") == "본문 내용"
    assert client.get_page_text("missing") == ""
