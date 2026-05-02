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


class Orchestrator:
    def __init__(self, settings: Settings = default_settings) -> None:
        self.settings = settings

    async def run(self, query: str) -> SearchResult:
        import time
        t0 = time.perf_counter()
        logger.info("[%s] starting scrape", query)
        async with async_playwright() as pw:
            launch_kwargs: dict = {"headless": self.settings.headless}
            if self.settings.http_proxy:
                launch_kwargs["proxy"] = {"server": self.settings.http_proxy}

            logger.info("[%s] launching browser (headless=%s)", query, self.settings.headless)
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )

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
