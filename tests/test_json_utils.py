import pytest

from app.services.json_utils import JSONParseError, extract_json_object


def test_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = '```json\n{"a": [1, 2], "b": "x"}\n```'
    assert extract_json_object(text) == {"a": [1, 2], "b": "x"}


def test_json_with_surrounding_text():
    text = '여기 결과입니다:\n{"topics": []}\n끝.'
    assert extract_json_object(text) == {"topics": []}


def test_braces_inside_strings():
    text = '{"body": "여기 {중괄호} 포함"}'
    assert extract_json_object(text) == {"body": "여기 {중괄호} 포함"}


def test_no_json_raises():
    with pytest.raises(JSONParseError):
        extract_json_object("JSON이 없습니다")
