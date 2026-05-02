from __future__ import annotations

import logging
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response

from product_scraper.config import Settings, settings as _default_settings
from product_scraper.models import SearchResult
from product_scraper.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Product Scraper API",
    version="0.1.0",
    description="Search Amazon.in and Flipkart.com — returns top 3 results from each site.",
)


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    start = time.perf_counter()
    client = request.client.host if request.client else "unknown"
    logger.info("→ %s %s  client=%s  params=%s", request.method, request.url.path, client, dict(request.query_params))
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    logger.info("← %s %s  status=%d  %.2fs", request.method, request.url.path, response.status_code, elapsed)
    return response


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
    logger.info("Search request: q=%r  no_cache=%s", q, no_cache)
    req_settings: Settings = (
        _default_settings.model_copy(update={"cache_enabled": False})
        if no_cache
        else _default_settings
    )
    orchestrator = Orchestrator(req_settings)
    try:
        result = await orchestrator.run(q)
        logger.info("Search complete: q=%r  results=%d  errors=%s", q, len(result.results), list(result.errors.keys()) or "none")
        return result
    except Exception as exc:
        logger.exception("Orchestrator failed for query %r", q)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def start() -> None:
    uvicorn.run("product_scraper.api:app", host="0.0.0.0", port=8000, reload=False)
