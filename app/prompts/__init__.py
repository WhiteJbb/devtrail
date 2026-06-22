"""프롬프트 로딩/렌더링.

프롬프트는 코드에 하드코딩하지 않고 이 디렉토리의 `.md` 파일로 관리한다.
`{{KEY}}` 토큰을 단순 치환해 렌더한다(.format은 본문의 중괄호와 충돌하므로 쓰지 않음).
"""

from __future__ import annotations

from importlib import resources


def load_prompt(name: str) -> str:
    """`app/prompts/<name>.md` 원문을 읽는다."""
    return resources.files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def render_prompt(name: str, **variables: str) -> str:
    """프롬프트를 읽어 `{{KEY}}` 토큰을 치환한다."""
    text = load_prompt(name)
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


__all__ = ["load_prompt", "render_prompt"]
