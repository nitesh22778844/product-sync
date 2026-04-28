from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Query

from product_scraper.config import Settings, settings as _default_settings
from product_scraper.models import SearchResult
from product_scraper.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Product Scraper API",
    version="0.1.0",
    description="Search Amazon.in and Flipkart.com — returns top 3 results from each site.",
)


@app.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/search",
    response_model=SearchResult,
    summary="Search products",
    response_description="Top 3 results from Amazon.in and Flipkart.com",
)
async def search(
    q: str = Query(..., min_length=1, description="Product search query"),
    no_cache: bool = Query(False, description="Bypass cache for this request"),
) -> SearchResult:
    req_settings: Settings = (
        _default_settings.model_copy(update={"cache_enabled": False})
        if no_cache
        else _default_settings
    )
    orchestrator = Orchestrator(req_settings)
    try:
        return await orchestrator.run(q)
    except Exception as exc:
        logger.exception("Orchestrator failed for query %r", q)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def start() -> None:
    uvicorn.run("product_scraper.api:app", host="0.0.0.0", port=8000, reload=False)
