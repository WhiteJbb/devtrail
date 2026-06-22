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
    # LLM HTTP 호출 시도 횟수(1=재시도 없음). 일시적 오류/5xx에 지수 백오프 재시도.
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_timeout: float = Field(default=300.0, alias="LLM_TIMEOUT")

    # --- Obsidian ---
    obsidian_vault_dir: str = Field(default="", alias="OBSIDIAN_VAULT_DIR")
    obsidian_tags: str = Field(default="", alias="OBSIDIAN_TAGS")
    obsidian_folders: str = Field(default="", alias="OBSIDIAN_FOLDERS")
    wiki_folder: str = Field(default="60_Wiki", alias="WIKI_FOLDER")

    # --- Notion ---
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")
    notion_blog_database_id: str = Field(default="", alias="NOTION_BLOG_DATABASE_ID")
    notion_idea_database_id: str = Field(default="", alias="NOTION_IDEA_DATABASE_ID")
    notion_worklog_database_id: str = Field(default="", alias="NOTION_WORKLOG_DATABASE_ID")
    # 초안 소스로 본문을 읽어올 Notion 페이지 id들(쉼표 구분). "정리 문서"를 직접 가리킬 때.
    notion_source_page_ids: str = Field(default="", alias="NOTION_SOURCE_PAGE_IDS")

    # --- Paths ---
    workspace_dir: str = Field(default="workspace", alias="WORKSPACE_DIR")
    # 개별 경로 재정의 (비우면 workspace_dir 하위 기본 경로 사용)
    drafts_dir: str = Field(default="", alias="DRAFTS_DIR")
    blogs_dir: str = Field(default="", alias="BLOGS_DIR")
    worklogs_dir: str = Field(default="", alias="WORKLOGS_DIR")
    todos_dir: str = Field(default="", alias="TODOS_DIR")
    portfolio_dir: str = Field(default="", alias="PORTFOLIO_DIR")
    resume_dir: str = Field(default="", alias="RESUME_DIR")

    # --- Git ---
    git_log_limit: int = Field(default=20, alias="GIT_LOG_LIMIT")
    git_include_diff: bool = Field(default=True, alias="GIT_INCLUDE_DIFF")
    git_diff_max_chars: int = Field(default=800, alias="GIT_DIFF_MAX_CHARS")

    # --- Messenger ---
    messenger_provider: str = Field(default="", alias="MESSENGER_PROVIDER")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    # 봇에 명령할 수 있는 chat id(허용 목록, 쉼표 구분). 비우면 아무나 명령 가능(권장하지 않음).
    telegram_allowed_chat_ids: str = Field(default="", alias="TELEGRAM_ALLOWED_CHAT_IDS")
    # 알림(outbound)을 보낼 기본 chat id.
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ----- 파생 경로 -----
    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()

    @property
    def docs_path(self) -> Path:
        return self.workspace_path / "docs"

    @property
    def drafts_path(self) -> Path:
        return Path(self.drafts_dir).resolve() if self.drafts_dir else self.workspace_path / "drafts"

    @property
    def blogs_path(self) -> Path:
        return Path(self.blogs_dir).resolve() if self.blogs_dir else self.workspace_path / "blogs"

    @property
    def worklogs_path(self) -> Path:
        return Path(self.worklogs_dir).resolve() if self.worklogs_dir else self.workspace_path / "worklogs"

    @property
    def todos_path(self) -> Path:
        return Path(self.todos_dir).resolve() if self.todos_dir else self.workspace_path / "todos"

    @property
    def portfolio_path(self) -> Path:
        return Path(self.portfolio_dir).resolve() if self.portfolio_dir else self.workspace_path / "portfolio"

    @property
    def resume_path(self) -> Path:
        return Path(self.resume_dir).resolve() if self.resume_dir else self.workspace_path / "resume"

    @property
    def notion_mock_path(self) -> Path:
        return self.workspace_path / ".notion_mock.json"

    @property
    def source_page_ids(self) -> list[str]:
        return [p.strip() for p in self.notion_source_page_ids.split(",") if p.strip()]

    @property
    def allowed_chat_ids(self) -> list[str]:
        return [c.strip() for c in self.telegram_allowed_chat_ids.split(",") if c.strip()]

    # ----- 편의 판별 -----
    @property
    def notion_enabled(self) -> bool:
        """실제 Notion API를 쓸 수 있는지. 아니면 mock으로 동작."""
        return bool(self.notion_api_key and self.notion_blog_database_id)

    @property
    def wiki_path(self) -> Path | None:
        if not self.obsidian_vault_dir:
            return None
        return Path(self.obsidian_vault_dir) / self.wiki_folder

    @property
    def wiki_enabled(self) -> bool:
        return bool(self.obsidian_vault_dir)

    @property
    def obsidian_enabled(self) -> bool:
        return bool(self.obsidian_vault_dir)

    @property
    def obsidian_tag_list(self) -> list[str]:
        return [t.strip() for t in self.obsidian_tags.split(",") if t.strip()]

    @property
    def obsidian_folder_list(self) -> list[str]:
        return [f.strip() for f in self.obsidian_folders.split(",") if f.strip()]


@lru_cache
def get_settings() -> Settings:
    """프로세스 단위 싱글턴 설정."""
    return Settings()
