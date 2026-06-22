"""애플리케이션 설정 로드.

`.env` + 환경변수에서 설정을 읽는다. 비밀값/엔드포인트를 코드에 하드코딩하지 않고
이 한 곳으로 모은다. 다른 계층은 `get_settings()`로 주입받아 사용한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 기반 설정. 필드명은 대소문자 구분 없이 환경변수와 매핑된다."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---
    llm_provider: str = Field(default="", alias="LLM_PROVIDER")

    openai_base_url: str = Field(default="http://localhost:8000/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:14b-instruct-q4_K_M", alias="OLLAMA_MODEL")

    context_char_budget: int = Field(default=12000, alias="CONTEXT_CHAR_BUDGET")

    # --- Notion ---
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")
    notion_blog_database_id: str = Field(default="", alias="NOTION_BLOG_DATABASE_ID")
    notion_idea_database_id: str = Field(default="", alias="NOTION_IDEA_DATABASE_ID")
    notion_worklog_database_id: str = Field(default="", alias="NOTION_WORKLOG_DATABASE_ID")

    # --- Paths ---
    workspace_dir: str = Field(default="workspace", alias="WORKSPACE_DIR")

    # --- Git ---
    git_log_limit: int = Field(default=20, alias="GIT_LOG_LIMIT")

    # ----- 파생 경로 -----
    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()

    @property
    def docs_path(self) -> Path:
        return self.workspace_path / "docs"

    @property
    def drafts_path(self) -> Path:
        return self.workspace_path / "drafts"

    @property
    def blogs_path(self) -> Path:
        return self.workspace_path / "blogs"

    @property
    def notion_mock_path(self) -> Path:
        return self.workspace_path / ".notion_mock.json"

    # ----- 편의 판별 -----
    @property
    def notion_enabled(self) -> bool:
        """실제 Notion API를 쓸 수 있는지. 아니면 mock으로 동작."""
        return bool(self.notion_api_key and self.notion_blog_database_id)


@lru_cache
def get_settings() -> Settings:
    """프로세스 단위 싱글턴 설정."""
    return Settings()
