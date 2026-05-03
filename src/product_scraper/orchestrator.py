from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright

from product_scraper.config import Settings, settings as default_settings
from product_scraper.fetchers.amazon_scraper import AmazonScraperFetcher
from product_scraper.fetchers.flipkart_scraper import FlipkartScraperFetcher
from product_scraper.models import SearchResult

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Chromium flags tuned for low-memory hosts (Render starter ~512MB).
_CHROMIUM_LOW_MEMORY_ARGS = [
    "--disable-dev-shm-usage",  # /dev/shm is ~64MB on Render — force disk-backed shared mem
    "--disable-gpu",
    "--no-sandbox",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-features=TranslateUI,AcceptCHFrame,MediaRouter,OptimizationHints",
    "--disable-ipc-flooding-protection",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
]

# Resource types we don't need for HTML parsing — blocking them at the network
# layer slashes per-page memory and bandwidth. JS/CSS/XHR/fetch stay enabled
# because both sites SPA-render their product cards.
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}


async def _block_heavy_resources(route, request) -> None:
    if request.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


class Orchestrator:
    def __init__(self, settings: Settings = default_settings) -> None:
        self.settings = settings

    async def run(self, query: str) -> SearchResult:
        import time
        t0 = time.perf_counter()
        logger.info("[%s] starting scrape", query)
        async with async_playwright() as pw:
            launch_kwargs: dict = {
                "headless": self.settings.headless,
                "args": _CHROMIUM_LOW_MEMORY_ARGS,
            }
            if self.settings.http_proxy:
                launch_kwargs["proxy"] = {"server": self.settings.http_proxy}

            logger.info("[%s] launching browser (headless=%s)", query, self.settings.headless)
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                context_kwargs: dict = dict(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1280, "height": 720},
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
                )
                # Flipkart Minutes (HYPERLOCAL) gates products behind a "Use my current location"
                # CTA — granting geolocation up front lets the click resolve immediately.
                if self.settings.grocery_mode:
                    context_kwargs["geolocation"] = {"latitude": 13.0358, "longitude": 77.5970}
                    context_kwargs["permissions"] = ["geolocation"]
                context = await browser.new_context(**context_kwargs)
                await context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )
                # Block heavy resources we never use (image bytes, fonts, media). The DOM
                # `src` attributes are still populated by JS, so parsing is unaffected.
                await context.route("**/*", _block_heavy_resources)

                fetchers = [
                    AmazonScraperFetcher(self.settings, context),
                    FlipkartScraperFetcher(self.settings, context),
                ]
                logger.info("[%s] dispatching amazon + flipkart fetchers", query)
                try:
                    tasks = [f.search(query) for f in fetchers]
                    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

                    products = []
                    errors: dict[str, str] = {}
                    counts: dict[str, int] = {}
                    for fetcher, result in zip(fetchers, outcomes):
                        if isinstance(result, Exception):
                            errors[fetcher.source] = str(result)
                            logger.warning("[%s] %s fetcher failed: %s", query, fetcher.source, result)
                            counts[fetcher.source] = 0
                        else:
                            products.extend(result)
                            counts[fetcher.source] = len(result)

                    elapsed = time.perf_counter() - t0
                    logger.info(
                        "[%s] done in %.1fs — amazon: %d, flipkart: %d, total: %d",
                        query, elapsed, counts.get("amazon", 0), counts.get("flipkart", 0), len(products),
                    )
                    return SearchResult(query=query, results=products, errors=errors)
                finally:
                    for f in fetchers:
                        await f.close()
            finally:
                await browser.close()

    async def run_batch(self, queries: list[str]) -> list[SearchResult]:
        results = []
        for query in queries:
            logger.info("Processing query: %s", query)
            result = await self.run(query)
            results.append(result)
        return results
