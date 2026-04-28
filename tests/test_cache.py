import json
from datetime import date

import pytest

from product_scraper.cache import _key, get_cached, set_cache


# ──────────────────────────────────────────────
# _key helper
# ──────────────────────────────────────────────

def test_key_is_deterministic():
    assert _key("amazon", "laptop") == _key("amazon", "laptop")


def test_key_differs_by_source():
    assert _key("amazon", "laptop") != _key("flipkart", "laptop")


def test_key_differs_by_query():
    assert _key("amazon", "laptop") != _key("amazon", "phone")


def test_key_length_is_16():
    assert len(_key("amazon", "test")) == 16


def test_key_is_hex():
    k = _key("amazon", "test")
    int(k, 16)  # should not raise


# ──────────────────────────────────────────────
# get_cached — disabled
# ──────────────────────────────────────────────

def test_get_cached_returns_none_when_disabled(mock_settings):
    # mock_settings has cache_enabled=False
    assert get_cached("amazon", "laptop") is None


# ──────────────────────────────────────────────
# get_cached — file missing or stale
# ──────────────────────────────────────────────

def test_get_cached_returns_none_when_file_missing(cache_settings):
    assert get_cached("amazon", "nonexistent query xyz") is None


def test_get_cached_returns_none_for_stale_date(cache_settings, tmp_path):
    data = [{"title": "Old Product"}]
    entry = {
        "key": "x",
        "source": "amazon",
        "query": "laptop",
        "cached_at": "2000-01-01",
        "data": data,
    }
    key = _key("amazon", "laptop")
    (tmp_path / f"{key}.json").write_text(json.dumps(entry), encoding="utf-8")
    assert get_cached("amazon", "laptop") is None


def test_get_cached_returns_none_for_corrupted_json(cache_settings, tmp_path):
    key = _key("amazon", "laptop")
    (tmp_path / f"{key}.json").write_text("NOT VALID JSON }{", encoding="utf-8")
    assert get_cached("amazon", "laptop") is None


def test_get_cached_returns_none_when_missing_data_key(cache_settings, tmp_path):
    entry = {"key": "x", "source": "amazon", "query": "laptop", "cached_at": date.today().isoformat()}
    key = _key("amazon", "laptop")
    (tmp_path / f"{key}.json").write_text(json.dumps(entry), encoding="utf-8")
    # "data" key is absent — should return None gracefully via KeyError → exception handler
    result = get_cached("amazon", "laptop")
    # Either None (exception swallowed) or missing key causes KeyError which returns None
    # Based on implementation: entry["data"] would raise KeyError → except → return None
    assert result is None


# ──────────────────────────────────────────────
# set_cache + get_cached round-trip
# ──────────────────────────────────────────────

def test_set_and_get_cache_roundtrip(cache_settings):
    data = [{"title": "SanDisk Pen Drive", "rank": 1}]
    set_cache("amazon", "pen drive 16gb", data)
    result = get_cached("amazon", "pen drive 16gb")
    assert result == data


def test_set_cache_is_query_specific(cache_settings):
    set_cache("amazon", "laptop", [{"title": "Laptop"}])
    set_cache("amazon", "phone", [{"title": "Phone"}])
    assert get_cached("amazon", "laptop")[0]["title"] == "Laptop"
    assert get_cached("amazon", "phone")[0]["title"] == "Phone"


def test_set_cache_is_source_specific(cache_settings):
    set_cache("amazon", "laptop", [{"title": "Amazon Laptop"}])
    set_cache("flipkart", "laptop", [{"title": "Flipkart Laptop"}])
    assert get_cached("amazon", "laptop")[0]["title"] == "Amazon Laptop"
    assert get_cached("flipkart", "laptop")[0]["title"] == "Flipkart Laptop"


def test_set_cache_overwrites_existing(cache_settings):
    set_cache("amazon", "laptop", [{"title": "Old"}])
    set_cache("amazon", "laptop", [{"title": "New"}])
    result = get_cached("amazon", "laptop")
    assert result[0]["title"] == "New"


def test_set_cache_empty_list(cache_settings):
    set_cache("amazon", "empty query", [])
    result = get_cached("amazon", "empty query")
    assert result == []


# ──────────────────────────────────────────────
# set_cache — disabled / directory creation
# ──────────────────────────────────────────────

def test_set_cache_noop_when_disabled(mock_settings, tmp_path):
    # mock_settings: cache_enabled=False — no files should be written
    set_cache("amazon", "laptop", [{"title": "X"}])
    assert list(tmp_path.iterdir()) == []


def test_set_cache_creates_cache_directory(tmp_path, monkeypatch):
    from product_scraper import cache as cache_mod
    from product_scraper.config import Settings

    nested = tmp_path / "deep" / "nested" / "cache"
    s = Settings(cache_enabled=True, cache_dir=nested, headless=True, request_delay_seconds=0, max_retries=1)
    monkeypatch.setattr(cache_mod, "settings", s)

    set_cache("amazon", "test", [])
    assert nested.exists()


def test_set_cache_writes_json_file(cache_settings, tmp_path):
    set_cache("flipkart", "ssd", [{"title": "Samsung SSD"}])
    key = _key("flipkart", "ssd")
    cache_file = tmp_path / f"{key}.json"
    assert cache_file.exists()
    entry = json.loads(cache_file.read_text(encoding="utf-8"))
    assert entry["source"] == "flipkart"
    assert entry["query"] == "ssd"
    assert entry["cached_at"] == date.today().isoformat()
    assert entry["data"][0]["title"] == "Samsung SSD"
