"""정기 푸시용 다이제스트 구성(순수 포맷팅, 네트워크 무관).

주제 추천 + (선택) 작업 회고를 메신저로 보낼 한 덩이 텍스트로 만든다.
"""

from __future__ import annotations

from app.models import TopicSuggestion


def build_digest(suggestions: list[TopicSuggestion], worklog_text: str = "") -> str:
    blocks: list[str] = []

    if suggestions:
        lines = ["[블로그 주제 추천]"]
        for i, s in enumerate(suggestions, 1):
            title = s.title_candidates[0] if s.title_candidates else "(제목 후보 없음)"
            lines.append(f"{i}. {title}")
            if s.reason:
                lines.append(f"   - {s.reason}")
        blocks.append("\n".join(lines))
    else:
        blocks.append("[블로그 주제 추천]\n추천할 주제를 찾지 못했습니다.")

    if worklog_text.strip():
        blocks.append("[작업 회고]\n" + worklog_text.strip())

    return "\n\n".join(blocks)
