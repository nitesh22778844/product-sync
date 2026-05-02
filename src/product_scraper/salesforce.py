from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from product_scraper.config import Settings
from product_scraper.models import Product

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_BUFFER = 60  # refresh token this many seconds before it expires


def _clean_url(url: str) -> str:
    """Strip query string and fragment so the URL fits in a 255-char SF Text field."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _parse_discount_pct(discount: Optional[str]) -> Optional[float]:
    """Extract numeric percentage from strings like '21% off' for SF Percent fields."""
    if not discount:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", discount)
    return float(m.group(1)) if m else None


def _build_payload(product: Product) -> dict[str, Any]:
    return {
        "Title__c": product.title[:100],  # SF Text(100) field
        "Source__c": product.source,
        "Rank__c": product.rank,
        "Product_URL__c": _clean_url(product.product_url),
        "Brand__c": product.brand,
        "Model__c": product.model,
        "Current_Price__c": product.current_price.amount if product.current_price else None,
        "Original_Price__c": product.original_price.amount if product.original_price else None,
        "Discount__c": _parse_discount_pct(product.discount),
        "Rating__c": product.rating,
        "Review_Count__c": product.review_count,
        "Specifications__c": json.dumps(product.specifications) if product.specifications else None,
        "Image_URL__c": product.image_url,
        "Availability__c": product.availability,
        "Scraped_At__c": product.scraped_at.isoformat(),
    }


class SalesforceClient:
    def __init__(self, settings: Settings) -> None:
        self._token_url: str = settings.sf_token_url  # type: ignore[assignment]
        self._client_id: str = settings.sf_client_id  # type: ignore[assignment]
        self._client_secret: str = settings.sf_client_secret  # type: ignore[assignment]
        self._api_endpoint: str = settings.sf_api_endpoint  # type: ignore[assignment]

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        self._access_token = payload["access_token"]
        expires_in: int = payload.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_EXPIRY_BUFFER
        logger.debug("Salesforce token obtained (expires_in=%ds)", expires_in)
        return self._access_token

    async def sync_products(self, products: list[Product]) -> None:
        if not products:
            return
        try:
            token = await self._get_token()
        except Exception as exc:
            logger.warning("Salesforce token fetch failed — skipping sync: %s", exc)
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        succeeded = 0
        failed = 0
        async with httpx.AsyncClient(timeout=20) as client:
            for product in products:
                try:
                    body = _build_payload(product)
                    resp = await client.post(self._api_endpoint, json=body, headers=headers)
                    if resp.is_success:
                        succeeded += 1
                    else:
                        failed += 1
                        logger.warning(
                            "Salesforce rejected product %r (rank=%d source=%s): HTTP %d — %s",
                            product.title[:60],
                            product.rank,
                            product.source,
                            resp.status_code,
                            resp.text[:500],
                        )
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "Salesforce sync error for product %r: %s",
                        product.title[:60],
                        exc,
                    )

        logger.info(
            "Salesforce sync complete — succeeded=%d failed=%d total=%d",
            succeeded,
            failed,
            len(products),
        )
