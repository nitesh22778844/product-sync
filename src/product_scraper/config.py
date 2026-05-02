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

    # Salesforce — client credentials OAuth flow
    sf_token_url: Optional[str] = None      # e.g. https://login.salesforce.com/services/oauth2/token
    sf_client_id: Optional[str] = None
    sf_client_secret: Optional[str] = None
    sf_api_endpoint: Optional[str] = None   # e.g. https://myorg.my.salesforce.com/services/data/v57.0/sobjects/ProductSync__c/

    @property
    def salesforce_enabled(self) -> bool:
        return all([self.sf_token_url, self.sf_client_id, self.sf_client_secret, self.sf_api_endpoint])


settings = Settings()
