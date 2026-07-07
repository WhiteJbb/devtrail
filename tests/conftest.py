"""테스트 공용 fixture/헬퍼."""

from app.models import SourceChunk


class FakeLLM:
    """고정 응답을 돌려주는 LLM provider 대역."""

    name = "fake"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.last_prompt = ""
        self.last_system = ""
        self.prompts: list[str] = []  # 호출 순서대로 누적 (critic 등 다단계 검증용)

    def complete(self, prompt: str, system: str = "") -> str:
        self.last_prompt = prompt
        self.last_system = system
        self.prompts.append(prompt)
        return self.response


class FakeSource:
    name = "fake"

    def __init__(self, chunks):
        self._chunks = chunks

    def fetch(self):
        return self._chunks


def sample_chunks():
    return [
        SourceChunk(source_type="worklog", ref="w", title="worklog", text="환경 분리 작업"),
        SourceChunk(source_type="git", ref="abc123", title="commit", text="분리 커밋"),
    ]
