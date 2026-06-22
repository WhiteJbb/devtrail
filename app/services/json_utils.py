"""LLM 응답에서 JSON을 안전하게 추출한다.

프롬프트로 순수 JSON을 요구하지만, 모델이 코드펜스나 설명을 덧붙이는 경우가 있어
관대하게 첫 번째 JSON 객체를 잘라낸다.
"""

from __future__ import annotations

import json
from typing import Any


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
