from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional

# Playwright spawns a subprocess for the browser — requires ProactorEventLoop on Windows.
# SelectorEventLoop (uvicorn's default in reload mode on Windows) raises NotImplementedError.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response

from product_scraper.config import Settings, settings as _default_settings
from product_scraper.models import SearchResult
from product_scraper.orchestrator import Orchestrator
from product_scraper.salesforce import SalesforceClient

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

_sf_client: Optional[SalesforceClient] = (
    SalesforceClient(_default_settings) if _default_settings.salesforce_enabled else None
)
if _sf_client:
    logger.info("Salesforce sync enabled (endpoint=%s)", _default_settings.sf_api_endpoint)
else:
    logger.info("Salesforce sync disabled — set SF_TOKEN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET, SF_API_ENDPOINT to enable")


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
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=1, description="Product search query"),
    no_cache: bool = Query(False, description="Bypass cache for this request"),
    grocery: bool = Query(False, description="Search grocery stores (Amazon nowstore + Flipkart HYPERLOCAL)"),
) -> SearchResult:
    logger.info("Search request: q=%r  no_cache=%s  grocery=%s", q, no_cache, grocery)
    overrides: dict = {}
    if no_cache:
        overrides["cache_enabled"] = False
    if grocery:
        overrides["grocery_mode"] = True
    req_settings: Settings = _default_settings.model_copy(update=overrides) if overrides else _default_settings
    orchestrator = Orchestrator(req_settings)
    try:
        result = await orchestrator.run(q)
        logger.info("Search complete: q=%r  results=%d  errors=%s", q, len(result.results), list(result.errors.keys()) or "none")
        if _sf_client and result.results:
            background_tasks.add_task(_sf_client.sync_products, result.results)
            logger.info("Salesforce sync queued for %d products (q=%r)", len(result.results), q)
        return result
    except Exception as exc:
        logger.exception("Orchestrator failed for query %r", q)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def start() -> None:
    uvicorn.run("product_scraper.api:app", host="0.0.0.0", port=8000, reload=False)
