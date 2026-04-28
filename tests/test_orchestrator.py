from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from product_scraper.models import Product, SearchResult
from product_scraper.orchestrator import Orchestrator


def _product(source: str, rank: int) -> Product:
    return Product(
        source=source,
        rank=rank,
        title=f"{source.title()} Product {rank}",
        product_url=f"https://{source}.com/p/{rank}",
    )


def _make_playwright_mock():
    """Return a mock that satisfies: async with async_playwright() as pw: ..."""
    mock_context = MagicMock()
    mock_context.add_init_script = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    # async context manager: async with async_playwright() as pw
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_pw)
    cm.__aexit__ = AsyncMock(return_value=False)

    return cm, mock_browser


@pytest.fixture
def orchestrator(mock_settings):
    return Orchestrator(mock_settings)


# ──────────────────────────────────────────────
# run — happy path
# ──────────────────────────────────────────────

async def test_run_returns_search_result(orchestrator):
    amazon_products = [_product("amazon", i) for i in range(1, 4)]
    flipkart_products = [_product("flipkart", i) for i in range(1, 4)]
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        amazon_f = AsyncMock()
        amazon_f.source = "amazon"
        amazon_f.search = AsyncMock(return_value=amazon_products)
        amazon_f.close = AsyncMock()
        MockAmazon.return_value = amazon_f

        flipkart_f = AsyncMock()
        flipkart_f.source = "flipkart"
        flipkart_f.search = AsyncMock(return_value=flipkart_products)
        flipkart_f.close = AsyncMock()
        MockFlipkart.return_value = flipkart_f

        result = await orchestrator.run("HP laptop")

    assert isinstance(result, SearchResult)
    assert result.query == "HP laptop"
    assert len(result.results) == 6
    assert result.errors == {}


async def test_run_query_preserved_in_result(orchestrator):
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        for Mock, src in [(MockAmazon, "amazon"), (MockFlipkart, "flipkart")]:
            f = AsyncMock()
            f.source = src
            f.search = AsyncMock(return_value=[])
            f.close = AsyncMock()
            Mock.return_value = f

        result = await orchestrator.run("Sony WH-1000XM5")

    assert result.query == "Sony WH-1000XM5"


# ──────────────────────────────────────────────
# run — error isolation
# ──────────────────────────────────────────────

async def test_run_amazon_failure_captured_flipkart_results_returned(orchestrator):
    flipkart_products = [_product("flipkart", i) for i in range(1, 4)]
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        amazon_f = AsyncMock()
        amazon_f.source = "amazon"
        amazon_f.search = AsyncMock(side_effect=RuntimeError("Amazon timeout"))
        amazon_f.close = AsyncMock()
        MockAmazon.return_value = amazon_f

        flipkart_f = AsyncMock()
        flipkart_f.source = "flipkart"
        flipkart_f.search = AsyncMock(return_value=flipkart_products)
        flipkart_f.close = AsyncMock()
        MockFlipkart.return_value = flipkart_f

        result = await orchestrator.run("HP laptop")

    assert "amazon" in result.errors
    assert "flipkart" not in result.errors
    assert len(result.results) == 3
    assert all(p.source == "flipkart" for p in result.results)


async def test_run_flipkart_failure_amazon_results_returned(orchestrator):
    amazon_products = [_product("amazon", i) for i in range(1, 4)]
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        amazon_f = AsyncMock()
        amazon_f.source = "amazon"
        amazon_f.search = AsyncMock(return_value=amazon_products)
        amazon_f.close = AsyncMock()
        MockAmazon.return_value = amazon_f

        flipkart_f = AsyncMock()
        flipkart_f.source = "flipkart"
        flipkart_f.search = AsyncMock(side_effect=ConnectionError("Flipkart blocked"))
        flipkart_f.close = AsyncMock()
        MockFlipkart.return_value = flipkart_f

        result = await orchestrator.run("HP laptop")

    assert "flipkart" in result.errors
    assert "amazon" not in result.errors
    assert len(result.results) == 3
    assert all(p.source == "amazon" for p in result.results)


async def test_run_both_fail_returns_empty_with_both_errors(orchestrator):
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        for Mock, src in [(MockAmazon, "amazon"), (MockFlipkart, "flipkart")]:
            f = AsyncMock()
            f.source = src
            f.search = AsyncMock(side_effect=RuntimeError(f"{src} failed"))
            f.close = AsyncMock()
            Mock.return_value = f

        result = await orchestrator.run("HP laptop")

    assert len(result.results) == 0
    assert "amazon" in result.errors
    assert "flipkart" in result.errors


async def test_run_error_message_captured(orchestrator):
    cm, _ = _make_playwright_mock()

    with patch("product_scraper.orchestrator.async_playwright", return_value=cm), \
         patch("product_scraper.orchestrator.AmazonScraperFetcher") as MockAmazon, \
         patch("product_scraper.orchestrator.FlipkartScraperFetcher") as MockFlipkart:

        amazon_f = AsyncMock()
        amazon_f.source = "amazon"
        amazon_f.search = AsyncMock(side_effect=RuntimeError("specific error message"))
        amazon_f.close = AsyncMock()
        MockAmazon.return_value = amazon_f

        flipkart_f = AsyncMock()
        flipkart_f.source = "flipkart"
        flipkart_f.search = AsyncMock(return_value=[])
        flipkart_f.close = AsyncMock()
        MockFlipkart.return_value = flipkart_f

        result = await orchestrator.run("test")

    assert "specific error message" in result.errors["amazon"]


# ──────────────────────────────────────────────
# run_batch
# ──────────────────────────────────────────────

async def test_run_batch_processes_all_queries(orchestrator):
    queries = ["laptop", "phone", "ssd"]

    with patch.object(orchestrator, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = SearchResult(query="test")
        results = await orchestrator.run_batch(queries)

    assert mock_run.call_count == 3
    assert len(results) == 3


async def test_run_batch_empty_queries(orchestrator):
    with patch.object(orchestrator, "run", new_callable=AsyncMock) as mock_run:
        results = await orchestrator.run_batch([])

    assert mock_run.call_count == 0
    assert results == []


async def test_run_batch_returns_results_in_order(orchestrator):
    queries = ["query_A", "query_B", "query_C"]

    async def fake_run(q):
        return SearchResult(query=q)

    with patch.object(orchestrator, "run", side_effect=fake_run):
        results = await orchestrator.run_batch(queries)

    assert [r.query for r in results] == queries
