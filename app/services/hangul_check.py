"""에이전트가 넘긴 한국어 텍스트에서 손상 의심 음절을 찾는다.

모델이 도구 인자를 `\\uXXXX` 이스케이프로 쓰다가 16진수 한 자리를 틀리면 옆 코드포인트의
엉뚱한 음절이 된다(등급 → 뒱급, 예산 → 예삸). 유효한 UTF-8이라 저장 경로에서는 걸리지
않으므로, 기록 시점에 드문 음절을 호출자에게 되돌려 그 세션 안에서 고치게 한다.
"""

from __future__ import annotations

import re

_HANGUL_WORD = re.compile(r"[가-힣]+")


def _is_rare(ch: str) -> bool:
    # ponytail: KS X 1001 상용 2,350자 밖이면 의심 — 상용 음절끼리 바뀐 손상(뺀 → 뻐)은
    # 못 잡고 '왤케' 같은 구어는 오탐한다. 그래서 차단이 아니라 경고로만 쓴다.
    try:
        ch.encode("iso2022_kr")
    except UnicodeEncodeError:
        return True
    return False


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def suspicious_hangul_words(*values) -> list[str]:
    """str·dict·list 값들에서 드문 음절이 든 단어를 등장 순서대로 중복 없이 반환한다."""
    found: dict[str, None] = {}
    for text in _strings(values):
        for match in _HANGUL_WORD.finditer(text):
            word = match.group(0)
            if any(_is_rare(ch) for ch in word):
                found.setdefault(word)
    return list(found)
