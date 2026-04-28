from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from product_scraper.api import app
from product_scraper.models import Product, SearchResult


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _product(source: str, rank: int, **kwargs) -> Product:
    return Product(
        source=source,
        rank=rank,
        title=kwargs.get("title", f"{source.title()} Product {rank}"),
        product_url=kwargs.get("product_url", f"https://{source}.com/p/{rank}"),
        **{k: v for k, v in kwargs.items() if k not in ("title", "product_url")},
    )


def _six_products() -> list[Product]:
    return (
        [_product("amazon", i) for i in range(1, 4)]
        + [_product("flipkart", i) for i in range(1, 4)]
    )


def _mock_orchestrator(result: SearchResult):
    """Patch Orchestrator so its run() coroutine returns *result*."""
    mock_instance = AsyncMock()
    mock_instance.run = AsyncMock(return_value=result)
    return patch("product_scraper.api.Orchestrator", return_value=mock_instance)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ──────────────────────────────────────────────
# /health
# ──────────────────────────────────────────────

async def test_health_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_health_returns_ok_status(client):
    resp = await client.get("/health")
    assert resp.json() == {"status": "ok"}


# ──────────────────────────────────────────────
# /search — input validation
# ──────────────────────────────────────────────

async def test_search_missing_q_returns_422(client):
    resp = await client.get("/search")
    assert resp.status_code == 422


async def test_search_empty_q_returns_422(client):
    resp = await client.get("/search", params={"q": ""})
    assert resp.status_code == 422


async def test_search_valid_q_returns_200(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.status_code == 200


# ──────────────────────────────────────────────
# /search — response shape
# ──────────────────────────────────────────────

async def test_search_response_contains_query(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.json()["query"] == "HP laptop"


async def test_search_response_contains_results_array(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "results" in resp.json()
    assert isinstance(resp.json()["results"], list)


async def test_search_response_contains_errors_dict(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "errors" in resp.json()
    assert isinstance(resp.json()["errors"], dict)


async def test_search_response_contains_timestamp(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "timestamp" in resp.json()


# ──────────────────────────────────────────────
# /search — result count
# ──────────────────────────────────────────────

async def test_search_six_products_returned(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert len(resp.json()["results"]) == 6


async def test_search_three_amazon_three_flipkart(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    sources = [p["source"] for p in resp.json()["results"]]
    assert sources.count("amazon") == 3
    assert sources.count("flipkart") == 3


async def test_search_empty_results_when_no_products(client):
    result = SearchResult(query="xyzzy", results=[])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "xyzzy"})
    assert resp.json()["results"] == []


# ──────────────────────────────────────────────
# /search — product fields
# ──────────────────────────────────────────────

async def test_search_product_has_source(client):
    result = SearchResult(query="HP laptop", results=[_product("amazon", 1)])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "source" in resp.json()["results"][0]


async def test_search_product_has_rank(client):
    result = SearchResult(query="HP laptop", results=[_product("amazon", 1)])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.json()["results"][0]["rank"] == 1


async def test_search_product_has_title(client):
    result = SearchResult(query="HP laptop", results=[_product("amazon", 1, title="HP 15s")])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.json()["results"][0]["title"] == "HP 15s"


async def test_search_product_has_product_url(client):
    result = SearchResult(query="HP laptop", results=[_product("amazon", 1)])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "product_url" in resp.json()["results"][0]


async def test_search_product_price_serialized(client):
    p = _product(
        "amazon", 1,
        current_price={"amount": 62990.0, "currency": "INR"},
        original_price={"amount": 79999.0, "currency": "INR"},
    )
    result = SearchResult(query="HP laptop", results=[p])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    cp = resp.json()["results"][0]["current_price"]
    assert cp["amount"] == pytest.approx(62990.0)
    assert cp["currency"] == "INR"


async def test_search_product_null_price_is_null(client):
    result = SearchResult(query="HP laptop", results=[_product("amazon", 1)])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.json()["results"][0]["current_price"] is None


async def test_search_product_specifications_serialized(client):
    p = _product("flipkart", 1, specifications={"RAM": "16 GB", "Storage": "512 GB SSD"})
    result = SearchResult(query="laptop", results=[p])
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "laptop"})
    specs = resp.json()["results"][0]["specifications"]
    assert specs["RAM"] == "16 GB"


# ──────────────────────────────────────────────
# /search — error isolation
# ──────────────────────────────────────────────

async def test_search_amazon_error_captured_in_errors(client):
    result = SearchResult(
        query="HP laptop",
        results=[_product("flipkart", i) for i in range(1, 4)],
        errors={"amazon": "timeout"},
    )
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    data = resp.json()
    assert "amazon" in data["errors"]
    assert len(data["results"]) == 3


async def test_search_flipkart_error_amazon_results_returned(client):
    result = SearchResult(
        query="HP laptop",
        results=[_product("amazon", i) for i in range(1, 4)],
        errors={"flipkart": "captcha"},
    )
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    data = resp.json()
    assert "flipkart" in data["errors"]
    assert all(p["source"] == "amazon" for p in data["results"])


async def test_search_both_errors_empty_results(client):
    result = SearchResult(
        query="HP laptop",
        results=[],
        errors={"amazon": "blocked", "flipkart": "blocked"},
    )
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop"})
    data = resp.json()
    assert data["results"] == []
    assert "amazon" in data["errors"]
    assert "flipkart" in data["errors"]


# ──────────────────────────────────────────────
# /search — orchestrator exception → 500
# ──────────────────────────────────────────────

async def test_search_orchestrator_exception_returns_500(client):
    mock_instance = AsyncMock()
    mock_instance.run = AsyncMock(side_effect=RuntimeError("playwright crashed"))
    with patch("product_scraper.api.Orchestrator", return_value=mock_instance):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert resp.status_code == 500


async def test_search_500_detail_contains_error_message(client):
    mock_instance = AsyncMock()
    mock_instance.run = AsyncMock(side_effect=RuntimeError("specific crash"))
    with patch("product_scraper.api.Orchestrator", return_value=mock_instance):
        resp = await client.get("/search", params={"q": "HP laptop"})
    assert "specific crash" in resp.json()["detail"]


# ──────────────────────────────────────────────
# /search — no_cache flag
# ──────────────────────────────────────────────

async def test_search_no_cache_flag_accepted(client):
    result = SearchResult(query="HP laptop", results=_six_products())
    with _mock_orchestrator(result):
        resp = await client.get("/search", params={"q": "HP laptop", "no_cache": "true"})
    assert resp.status_code == 200


async def test_search_no_cache_creates_settings_with_cache_disabled(client):
    result = SearchResult(query="HP laptop", results=[])

    captured_settings = []

    def capture(settings):
        captured_settings.append(settings)
        instance = AsyncMock()
        instance.run = AsyncMock(return_value=result)
        return instance

    with patch("product_scraper.api.Orchestrator", side_effect=capture):
        await client.get("/search", params={"q": "HP laptop", "no_cache": "true"})

    assert captured_settings[0].cache_enabled is False


async def test_search_cache_enabled_by_default(client):
    result = SearchResult(query="HP laptop", results=[])

    captured_settings = []

    def capture(settings):
        captured_settings.append(settings)
        instance = AsyncMock()
        instance.run = AsyncMock(return_value=result)
        return instance

    with patch("product_scraper.api.Orchestrator", side_effect=capture):
        await client.get("/search", params={"q": "HP laptop"})

    assert captured_settings[0].cache_enabled is True


# ──────────────────────────────────────────────
# /search — query forwarded to orchestrator
# ──────────────────────────────────────────────

async def test_search_query_forwarded_to_orchestrator(client):
    result = SearchResult(query="Sony WH-1000XM5", results=[])

    received_queries: list[str] = []

    async def fake_run(q: str):
        received_queries.append(q)
        return result

    mock_instance = AsyncMock()
    mock_instance.run = fake_run
    with patch("product_scraper.api.Orchestrator", return_value=mock_instance):
        await client.get("/search", params={"q": "Sony WH-1000XM5"})

    assert received_queries == ["Sony WH-1000XM5"]


async def test_search_query_with_spaces_forwarded_correctly(client):
    result = SearchResult(query="HP laptop 16GB RAM", results=[])

    received_queries: list[str] = []

    async def fake_run(q: str):
        received_queries.append(q)
        return result

    mock_instance = AsyncMock()
    mock_instance.run = fake_run
    with patch("product_scraper.api.Orchestrator", return_value=mock_instance):
        await client.get("/search", params={"q": "HP laptop 16GB RAM"})

    assert received_queries == ["HP laptop 16GB RAM"]


# ──────────────────────────────────────────────
# OpenAPI schema
# ──────────────────────────────────────────────

async def test_openapi_schema_accessible(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200


async def test_docs_accessible(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
