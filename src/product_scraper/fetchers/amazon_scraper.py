from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from product_scraper.base import ProductFetcher
from product_scraper.cache import get_cached, set_cache
from product_scraper.config import Settings
from product_scraper.models import Price, Product

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.in"

# Spec table selector candidates tried in order
_SPEC_TABLE_SELECTORS = [
    "#productDetails_techSpec_section_1 tr",
    "#tech-specs-section tr",
    "#technicalSpecifications_section_1 tr",
    "table.a-normal.a-spacing-micro tr",
]


class ScraperError(RuntimeError):
    pass


class CaptchaError(ScraperError):
    pass


class AmazonScraperFetcher(ProductFetcher):
    source = "amazon"

    def __init__(self, settings: Settings, context: BrowserContext) -> None:
        self.settings = settings
        self.context = context

    async def search(self, query: str, limit: int = 3) -> list[Product]:
        cached = get_cached(self.source, query, self.settings)
        if cached is not None:
            logger.info("[amazon] cache hit for %r — returning %d cached products", query, len(cached))
            return [Product(**d) for d in cached]

        logger.info("[amazon] cache miss for %r — fetching live", query)
        url = f"{BASE_URL}/s?k={quote_plus(query)}"
        logger.info("[amazon] fetching search page: %s", url)
        html = await self._fetch(url, wait_selector="[data-component-type='s-search-result']")
        raw_cards = self._parse_search_page(html, limit)
        logger.info("[amazon] parsed %d search cards", len(raw_cards))

        products: list[Product] = []
        for rank, card in enumerate(raw_cards, start=1):
            logger.info("[amazon] fetching product detail page %d/%d: %s", rank, len(raw_cards), card["product_url"])
            product_html = await self._fetch(card["product_url"])
            specs = self._parse_product_page(product_html)
            card.update(specs)
            card["rank"] = rank
            card["source"] = self.source
            try:
                products.append(Product(**card))
            except Exception as exc:
                logger.warning("Failed to build Product from card %d: %s", rank, exc)

        logger.info("[amazon] completed: %d products built for %r", len(products), query)
        set_cache(self.source, query, [p.model_dump(mode="json") for p in products], self.settings)
        return products

    # ------------------------------------------------------------------
    # Search page
    # ------------------------------------------------------------------

    def _parse_search_page(self, html: str, limit: int) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("[data-component-type='s-search-result']")
        results: list[dict] = []
        for card in cards:
            if len(results) >= limit:
                break
            if self._is_sponsored(card):
                continue
            parsed = self._parse_search_card(card)
            if parsed:
                results.append(parsed)
        return results

    def _is_sponsored(self, card: BeautifulSoup) -> bool:
        if card.get("data-component-type") == "sp-sponsored-result":
            return True
        return bool(card.find("span", string=re.compile(r"Sponsored", re.I)))

    def _parse_search_card(self, card: BeautifulSoup) -> Optional[dict]:
        # --- Title and product URL (Amazon's current data-cy layout) ---
        title_div = card.select_one("[data-cy='title-recipe']")
        if title_div:
            link_tag = title_div.select_one("a[href]")
            title = title_div.get_text(strip=True) or None
        else:
            # Fallback: first /dp/ link with non-empty text
            link_tag = next(
                (a for a in card.find_all("a", href=True)
                 if "/dp/" in a.get("href", "") and a.get_text(strip=True)),
                None,
            )
            title = link_tag.get_text(strip=True) if link_tag else None

        if not link_tag or not title:
            return None
        href = link_tag["href"]
        product_url = href if href.startswith("http") else BASE_URL + href

        # Prices — first .a-offscreen is current; .a-text-price .a-offscreen is strike-through MRP
        price_tags = card.select(".a-price .a-offscreen")
        current_price = self._extract_price(price_tags[0].get_text() if price_tags else None)

        original_tag = card.select_one(".a-price.a-text-price .a-offscreen")
        original_price = self._extract_price(original_tag.get_text() if original_tag else None)
        # Only keep original price if it's actually higher than current (avoids per-unit prices)
        if original_price and current_price and original_price["amount"] <= current_price["amount"]:
            original_price = None

        # Rating — data-cy='reviews-ratings-slot' (current layout) or aria-label fallback
        rating: Optional[str] = None
        rating_tag = card.select_one("i[data-cy='reviews-ratings-slot']")
        if rating_tag:
            rating = rating_tag.get_text(strip=True)
        else:
            r_tag = card.select_one("span[aria-label*='out of 5 stars']")
            if r_tag:
                rating = r_tag["aria-label"]

        # Review count — link text like "(2.7L)" or "(1,234)"
        review_count: Optional[str] = None
        review_block = card.select_one("[data-cy='reviews-block']")
        if review_block:
            for a in review_block.find_all("a", href=True):
                t = a.get_text(strip=True)
                if re.search(r"\d", t) and t not in ("", rating or ""):
                    review_count = t
                    break

        # Image
        img_tag = card.select_one("img.s-image")
        image_url = img_tag["src"] if img_tag else None

        return {
            "title": title,
            "product_url": product_url,
            "current_price": current_price,
            "original_price": original_price,
            "rating": rating,
            "review_count": review_count,
            "image_url": image_url,
        }

    # ------------------------------------------------------------------
    # Product page
    # ------------------------------------------------------------------

    def _parse_product_page(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")

        # Specifications
        specs: dict[str, str] = {}
        for selector in _SPEC_TABLE_SELECTORS:
            rows = soup.select(selector)
            if rows:
                for row in rows:
                    th = row.select_one("th")
                    td = row.select_one("td")
                    if th and td:
                        key = _clean_text(th.get_text())
                        val = _clean_text(td.get_text())
                        if key and val:
                            specs[key] = val
                break

        # Availability
        avail_tag = soup.select_one("#availability span")
        availability = _clean_text(avail_tag.get_text()) if avail_tag else None

        # Brand
        brand_tag = soup.select_one("#bylineInfo")
        brand: Optional[str] = None
        if brand_tag:
            raw_brand = brand_tag.get_text(strip=True)
            brand = re.sub(r"^Visit the\s+", "", raw_brand, flags=re.I)
            brand = re.sub(r"\s+Store$", "", brand, flags=re.I)
            brand = re.sub(r"^Brand:\s*", "", brand, flags=re.I).strip()

        return {
            "specifications": specs or None,
            "availability": availability,
            "brand": brand,
        }

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------

    async def _fetch(self, url: str, wait_selector: Optional[str] = None) -> str:
        for attempt in range(self.settings.max_retries):
            page: Optional[Page] = None
            try:
                await asyncio.sleep(self.settings.request_delay_seconds)
                page = await self.context.new_page()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

                # CAPTCHA detection
                title = await page.title()
                current_url = page.url
                if "robot check" in title.lower() or "captcha" in current_url.lower():
                    raise CaptchaError(f"CAPTCHA encountered at {url}")

                if response and response.status in (429, 503):
                    wait_secs = (2 ** attempt) * 5
                    logger.warning("HTTP %d — waiting %ds before retry", response.status, wait_secs)
                    await asyncio.sleep(wait_secs)
                    continue

                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=10_000)
                    except PlaywrightTimeoutError:
                        logger.debug("Selector '%s' not found on %s", wait_selector, url)

                return await page.content()

            except CaptchaError:
                raise
            except PlaywrightTimeoutError:
                if attempt == self.settings.max_retries - 1:
                    raise ScraperError(f"Timeout after {self.settings.max_retries} attempts: {url}")
                wait_secs = (2 ** attempt) * 3
                logger.warning("Timeout on attempt %d — waiting %ds", attempt + 1, wait_secs)
                await asyncio.sleep(wait_secs)
            finally:
                if page:
                    await page.close()

        raise ScraperError(f"Failed after {self.settings.max_retries} attempts: {url}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_price(text: Optional[str]) -> Optional[dict]:
        if not text:
            return None
        # Strip currency symbols and whitespace; keep digits, commas (thousands), and decimal point
        cleaned = re.sub(r"[₹₹RsINR\s]", "", text).replace(",", "")
        try:
            return {"amount": float(cleaned), "currency": "INR"}
        except ValueError:
            return None


def _clean_text(text: str) -> str:
    return text.replace("‎", "").replace("\xa0", " ").strip()
