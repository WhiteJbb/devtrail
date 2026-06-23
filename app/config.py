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

    local_llm_provider: str = Field(default="", alias="LOCAL_LLM_PROVIDER")
    writer_provider: str = Field(default="", alias="WRITER_PROVIDER")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_lite_model: str = Field(default="gemini-2.5-flash-lite", alias="GEMINI_LITE_MODEL")
    gemini_flash_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_FLASH_MODEL")

    context_char_budget: int = Field(default=12000, alias="CONTEXT_CHAR_BUDGET")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_timeout: float = Field(default=300.0, alias="LLM_TIMEOUT")

    # --- Obsidian ---
    obsidian_vault_path: str = Field(default="", alias="OBSIDIAN_VAULT_PATH")
    obsidian_vault_dir: str = Field(default="", alias="OBSIDIAN_VAULT_DIR")  # legacy alias
    wiki_folder: str = Field(default="60_Wiki", alias="WIKI_FOLDER")

    # --- Git ---
    git_log_limit: int = Field(default=20, alias="GIT_LOG_LIMIT")
    git_include_diff: bool = Field(default=True, alias="GIT_INCLUDE_DIFF")
    git_diff_max_chars: int = Field(default=800, alias="GIT_DIFF_MAX_CHARS")

    # --- Messenger ---
    messenger_provider: str = Field(default="", alias="MESSENGER_PROVIDER")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_chat_ids: str = Field(default="", alias="TELEGRAM_ALLOWED_CHAT_IDS")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ----- 파생 프로퍼티 -----
    @property
    def allowed_chat_ids(self) -> list[str]:
        return [c.strip() for c in self.telegram_allowed_chat_ids.split(",") if c.strip()]

    @property
    def obsidian_vault_root(self) -> str:
        return self.obsidian_vault_path or self.obsidian_vault_dir

    @property
    def wiki_path(self) -> Path | None:
        if not self.obsidian_vault_root:
            return None
        return Path(self.obsidian_vault_root) / self.wiki_folder

    @property
    def wiki_enabled(self) -> bool:
        return bool(self.obsidian_vault_root)

    @property
    def obsidian_enabled(self) -> bool:
        return bool(self.obsidian_vault_root)


@lru_cache
def get_settings() -> Settings:
    """프로세스 단위 싱글턴 설정."""
    return Settings()
