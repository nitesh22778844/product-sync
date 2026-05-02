from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Optional

from product_scraper.config import Settings, settings

logger = logging.getLogger(__name__)


def _key(source: str, query: str) -> str:
    raw = f"{source}:{query}:{date.today().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cached(
    source: str, query: str, cache_settings: Optional[Settings] = None
) -> Optional[list[dict]]:
    s = cache_settings if cache_settings is not None else settings
    if not s.cache_enabled:
        return None
    path = s.cache_dir / f"{_key(source, query)}.json"
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("cached_at") != date.today().isoformat():
            return None
        logger.info("Cache hit: %s / %s", source, query)
        return entry["data"]
    except Exception:
        return None


def set_cache(
    source: str, query: str, data: list[dict], cache_settings: Optional[Settings] = None
) -> None:
    s = cache_settings if cache_settings is not None else settings
    if not s.cache_enabled:
        return
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    path = s.cache_dir / f"{_key(source, query)}.json"
    entry = {
        "key": _key(source, query),
        "source": source,
        "query": query,
        "cached_at": date.today().isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    logger.debug("Cache written: %s / %s", source, query)
