"""LLM 응답에서 JSON을 안전하게 추출한다.

프롬프트로 순수 JSON을 요구하지만, 모델이 코드펜스나 설명을 덧붙이는 경우가 있어
관대하게 첫 번째 JSON 객체를 잘라낸다.
"""

from __future__ import annotations

import json
from inspect import signature
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.llm.base import LLMProvider


def _complete_json_mode(llm: "LLMProvider", prompt: str, system: str = "") -> str:
    """json_mode를 지원하는 provider면 활성화해 호출, 아니면 일반 호출."""
    if "json_mode" in signature(llm.complete).parameters:
        return llm.complete(prompt, system, json_mode=True)
    return llm.complete(prompt, system)


class JSONParseError(ValueError):
    """LLM 응답에서 JSON을 찾지 못했을 때."""


def extract_json_object(text: str) -> Any:
    """문자열에서 첫 번째 최상위 JSON 객체를 파싱해 반환."""
    text = text.strip()

    # 코드펜스 제거: ```json ... ``` 또는 ``` ... ```
    if text.startswith("```"):
        text = text.strip("`")
        # 첫 줄이 'json' 같은 언어 태그면 제거
        first_newline = text.find("\n")
        if first_newline != -1 and " " not in text[:first_newline]:
            text = text[first_newline + 1 :]

    # 그대로 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 중괄호 균형으로 첫 객체 추출
    start = text.find("{")
    if start == -1:
        raise JSONParseError("응답에서 JSON 객체를 찾지 못했습니다.")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as e:
                    raise JSONParseError(f"JSON 파싱 실패: {e}") from e
    raise JSONParseError("JSON 객체가 닫히지 않았습니다.")


_FIX_HINT = "\n\n주의: 반드시 유효한 JSON 객체 하나만 출력하세요. 코드펜스나 설명을 넣지 마세요."


def complete_json(llm: "LLMProvider", prompt: str, system: str = "") -> Any:
    """LLM 호출 후 JSON을 파싱한다. 파싱 실패 시 보정 지시를 붙여 1회 재시도한다.

    LLM이 가끔 깨진/감싼 JSON을 줄 때 한 번 더 기회를 줘서 명령 실패를 줄인다.
    """
    raw = _complete_json_mode(llm, prompt, system)
    try:
        return extract_json_object(raw)
    except JSONParseError:
        raw2 = _complete_json_mode(llm, prompt + _FIX_HINT, system)
        return extract_json_object(raw2)  # 두 번째도 실패하면 그대로 전파
