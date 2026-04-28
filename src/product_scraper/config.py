from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    headless: bool = True
    request_delay_seconds: float = 2.5
    max_retries: int = 3
    cache_enabled: bool = True
    cache_dir: Path = Path(".cache")
    playwright_browser: str = "chromium"
    http_proxy: Optional[str] = None


settings = Settings()
