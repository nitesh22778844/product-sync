from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from product_scraper.config import Settings
from product_scraper.models import Price, Product
from urllib.parse import quote

from product_scraper.salesforce import SalesforceClient, _build_payload, _parse_discount_pct


@pytest.fixture(scope="module")
def sf_settings() -> Settings:
    s = Settings()
    if not s.salesforce_enabled:
        pytest.skip("SF credentials not configured")
    return s


@pytest.fixture(scope="module")
async def sf_client(sf_settings) -> SalesforceClient:
    return SalesforceClient(sf_settings)


@pytest.fixture
def product() -> Product:
    return Product(
        source="amazon",
        rank=1,
        title=f"Test Product {datetime.now().strftime('%H:%M:%S')}",
        product_url="https://www.amazon.in/dp/TEST001",
        brand="TestBrand",
        model="TB-001",
        current_price=Price(amount=1499.0),
        original_price=Price(amount=1999.0),
        discount="25% off",
        rating=4.3,
        review_count=320,
        specifications={"Color": "Black", "Warranty": "1 year"},
        availability="In Stock",
        scraped_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Unit — payload builder (no network)
# ---------------------------------------------------------------------------

def test_payload_maps_all_fields(product):
    p = _build_payload(product, "non-grocery")
    assert p["Title__c"] == product.title  # title is short enough here
    assert len(p["Title__c"]) <= 200
    assert p["Source__c"] == "amazon"
    assert p["Rank__c"] == 1
    assert p["Current_Price__c"] == 1499.0
    assert p["Original_Price__c"] == 1999.0
    assert p["Discount__c"] == 25.0
    assert p["Rating__c"] == 4.3
    assert p["Review_Count__c"] == 320
    assert '"Color"' in p["Specifications__c"]
    assert p["Availability__c"] == "In Stock"
    assert p["Product_URL__c"] == product.product_url
    assert p["Category__c"] == "non-grocery"


def test_payload_category_grocery(product):
    p = _build_payload(product, "grocery")
    assert p["Category__c"] == "grocery"


def test_payload_nulls_for_missing_fields():
    p = _build_payload(Product(source="flipkart", rank=2, title="Bare", product_url="https://flipkart.com/p/x"), "non-grocery")
    assert p["Current_Price__c"] is None
    assert p["Original_Price__c"] is None
    assert p["Discount__c"] is None
    assert p["Specifications__c"] is None


def test_title_truncated_to_200():
    long_title = "A" * 250
    p = _build_payload(Product(source="flipkart", rank=1, title=long_title, product_url="https://flipkart.com/p/x"), "non-grocery")
    assert p["Title__c"] == "A" * 200


def test_parse_discount_pct():
    assert _parse_discount_pct("21% off") == 21.0
    assert _parse_discount_pct("4% off") == 4.0
    assert _parse_discount_pct(None) is None
    assert _parse_discount_pct("no discount") is None


# ---------------------------------------------------------------------------
# Live — token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_token(sf_client):
    token = await sf_client._get_token()
    assert len(token) > 30
    assert token == await sf_client._get_token()  # cached


# ---------------------------------------------------------------------------
# Live — push a record and query it back
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_product(sf_settings, sf_client, product):
    token = await sf_client._get_token()
    payload = _build_payload(product, "non-grocery")
    title = payload.pop("Title__c")  # external ID goes in URL
    upsert_url = f"{sf_settings.sf_api_endpoint.rstrip('/')}/Title__c/{quote(title, safe='')}"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.patch(
            upsert_url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

    assert resp.status_code in (200, 201, 204), f"HTTP {resp.status_code} — {resp.text}"
    action = "created" if resp.status_code == 201 else "updated"
    record_id = resp.json().get("id") if resp.status_code == 201 else "(existing record updated)"
    print(f"\n[OK] Product__c {action}: {record_id}")


@pytest.mark.asyncio
async def test_query_records_exist(sf_settings, sf_client):
    token = await sf_client._get_token()
    instance_url = sf_settings.sf_token_url.split("/services/")[0]

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{instance_url}/services/data/v57.0/query",
            params={"q": "SELECT Id, Name, CreatedDate FROM Product__c ORDER BY CreatedDate DESC LIMIT 5"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.is_success, f"SOQL failed: {resp.status_code} — {resp.text}"
    data = resp.json()
    assert data["totalSize"] > 0, "No Product__c records found in org"
    print(f"\n[OK] {data['totalSize']} record(s) found:")
    for r in data["records"]:
        print(f"  {r['Id']}  {r['Name']}  {r['CreatedDate']}")
