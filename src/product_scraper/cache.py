from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from product_scraper.config import settings

logger = logging.getLogger(__name__)


def _key(source: str, query: str) -> str:
    raw = f"{source}:{query}:{date.today().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_path(source: str, query: str) -> Path:
    return settings.cache_dir / f"{_key(source, query)}.json"


def get_cached(source: str, query: str) -> Optional[list[dict]]:
    if not settings.cache_enabled:
        return None
    path = _cache_path(source, query)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("cached_at") != date.today().isoformat():
            return None
        logger.debug("Cache hit: %s / %s", source, query)
        return entry["data"]
    except Exception:
        return None


def set_cache(source: str, query: str, data: list[dict]) -> None:
    if not settings.cache_enabled:
        return
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(source, query)
    entry = {
        "key": _key(source, query),
        "source": source,
        "query": query,
        "cached_at": date.today().isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    logger.debug("Cache written: %s / %s", source, query)
