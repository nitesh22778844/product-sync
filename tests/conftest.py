import pytest

from product_scraper.config import Settings


@pytest.fixture
def mock_settings(monkeypatch):
    s = Settings(
        headless=True,
        cache_enabled=False,
        request_delay_seconds=0,
        max_retries=1,
    )
    monkeypatch.setattr("product_scraper.config.settings", s)
    monkeypatch.setattr("product_scraper.cache.settings", s)
    return s


@pytest.fixture
def cache_settings(tmp_path, monkeypatch):
    """Settings with cache enabled, writing to a temp directory."""
    from product_scraper import cache

    s = Settings(
        headless=True,
        cache_enabled=True,
        request_delay_seconds=0,
        max_retries=1,
        cache_dir=tmp_path,
    )
    monkeypatch.setattr("product_scraper.config.settings", s)
    monkeypatch.setattr(cache, "settings", s)
    return s
