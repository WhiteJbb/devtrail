import pytest

from app.services.json_utils import JSONParseError, complete_json, extract_json_object


class SeqLLM:
    """호출마다 미리 정해둔 응답을 순서대로 돌려주는 LLM 대역."""

    name = "seq"
    model = "seq"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, prompt, system=""):
        self.calls += 1
        return self._responses.pop(0)


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


def test_complete_json_first_try():
    llm = SeqLLM(['{"a": 1}'])
    assert complete_json(llm, "p") == {"a": 1}
    assert llm.calls == 1


def test_complete_json_retries_on_bad_json():
    llm = SeqLLM(["깨진 응답", '{"a": 2}'])
    assert complete_json(llm, "p") == {"a": 2}
    assert llm.calls == 2  # 보정 지시로 1회 재시도


def test_complete_json_propagates_second_failure():
    llm = SeqLLM(["nope", "still nope"])
    with pytest.raises(JSONParseError):
        complete_json(llm, "p")
    assert llm.calls == 2
