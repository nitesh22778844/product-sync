from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from product_scraper.base import ProductFetcher
from product_scraper.cache import get_cached, set_cache
from product_scraper.config import Settings
from product_scraper.models import Product

logger = logging.getLogger(__name__)

BASE_URL = "https://www.flipkart.com"
DELIVERY_PINCODE = "560094"

# Tried in order to dismiss the login modal
_MODAL_CLOSE_SELECTORS = [
    "button._2KpZ6l._2doB4z",
    "button[class*='_2KpZ6l']",
    "button[class*='close']",
    "[role='dialog'] button:last-child",
]


class ScraperError(RuntimeError):
    pass


class FlipkartScraperFetcher(ProductFetcher):
    source = "flipkart"

    def __init__(self, settings: Settings, context: BrowserContext) -> None:
        self.settings = settings
        self.context = context
        self._modal_dismissed = False

    async def search(self, query: str, limit: int = 3) -> list[Product]:
        cached = get_cached(self.source, query, self.settings)
        if cached is not None:
            logger.info("[flipkart] cache hit for %r — returning %d cached products", query, len(cached))
            return [Product(**d) for d in cached]

        logger.info("[flipkart] cache miss for %r — fetching live", query)
        url = f"{BASE_URL}/search?q={quote_plus(query)}"
        logger.info("[flipkart] fetching search page: %s", url)
        page = await self.context.new_page()
        try:
            html = await self._load_search_page(page, url)
        finally:
            await page.close()

        raw_cards = self._parse_search_page(html, limit)
        logger.info("[flipkart] parsed %d search cards", len(raw_cards))

        products: list[Product] = []
        for rank, card in enumerate(raw_cards, start=1):
            try:
                logger.info("[flipkart] fetching product detail page %d/%d: %s", rank, len(raw_cards), card["product_url"])
                detail_html = await self._fetch(card["product_url"])
                specs = self._parse_product_page(detail_html)
                card.update(specs)
                card["rank"] = rank
                card["source"] = self.source
                products.append(Product(**card))
            except Exception as exc:
                logger.warning("Failed to build Flipkart product %d: %s", rank, exc)

        logger.info("[flipkart] completed: %d products built for %r", len(products), query)
        set_cache(self.source, query, [p.model_dump(mode="json") for p in products], self.settings)
        return products

    # ------------------------------------------------------------------
    # Search page
    # ------------------------------------------------------------------

    async def _load_search_page(self, page: Page, url: str) -> str:
        await asyncio.sleep(self.settings.request_delay_seconds)
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        if not self._modal_dismissed:
            await self._dismiss_modal(page)
            self._modal_dismissed = True

        await self._fill_pincode_if_needed(page)

        # Wait for product cards to appear
        try:
            await page.wait_for_selector("a[href*='/p/']", timeout=10_000)
        except PlaywrightTimeoutError:
            logger.debug("No /p/ links found on Flipkart search page")

        # Scroll to trigger lazy-loaded images
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(1.5)

        return await page.content()

    async def _dismiss_modal(self, page: Page) -> None:
        for sel in _MODAL_CLOSE_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=3_000)
                await page.click(sel)
                logger.info("[flipkart] dismissed login modal with selector: %s", sel)
                return
            except PlaywrightTimeoutError:
                continue

    async def _fill_pincode_if_needed(self, page: Page) -> None:
        try:
            pin_input = await page.wait_for_selector(
                "input[placeholder*='Pincode'], input[placeholder*='pincode']",
                timeout=2_000,
            )
            if pin_input:
                logger.info("[flipkart] filling pincode: %s", DELIVERY_PINCODE)
                await pin_input.fill(DELIVERY_PINCODE)
                await page.keyboard.press("Enter")
                await asyncio.sleep(1.5)
        except PlaywrightTimeoutError:
            pass

    def _parse_search_page(self, html: str, limit: int) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        # Each product card is a div[data-id] — stable Flipkart attribute
        cards = soup.select("div[data-id]")
        seen_urls: set[str] = set()
        results: list[dict] = []

        for card in cards:
            if len(results) >= limit:
                break
            parsed = self._parse_card(card)
            if parsed and parsed.get("title") and parsed.get("product_url"):
                url = parsed["product_url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(parsed)

        return results

    def _parse_card(self, card: Tag) -> dict:
        # Product URL — any /p/ link in the card
        link_tag = card.select_one("a[href*='/p/']")
        if not link_tag:
            return {}
        href = link_tag.get("href", "")
        product_url = href if href.startswith("http") else BASE_URL + href

        # Title — prefer the `title` attribute of a link (full text, not CSS-clipped)
        title: Optional[str] = None
        for a in card.find_all("a", href=True):
            t = a.get("title", "").strip()
            if len(t) > 10:
                title = t
                break
        if not title:
            # Fallback: img alt attribute
            img = card.select_one("img")
            if img:
                title = img.get("alt", "").strip() or None

        # Image — src on the image inside the first /p/ link (real CDN URL, not lazy placeholder)
        image_url: Optional[str] = None
        img_tag = link_tag.select_one("img")
        if img_tag:
            src = img_tag.get("src", "")
            image_url = src if src and not src.startswith("data:") else None

        # All text nodes in the card for extracting price/rating/etc.
        all_text = [
            t.get_text(strip=True)
            for t in card.find_all(string=True)
            if t.strip() and len(t.strip()) > 1
        ]

        # Current price: first text containing ₹ followed by digits
        current_price: Optional[dict] = None
        for t in all_text:
            m = re.search(r"₹([\d,]+)", t)
            if m:
                current_price = {"amount": float(m.group(1).replace(",", "")), "currency": "INR"}
                break

        # Original price: second distinct price > current
        original_price: Optional[dict] = None
        price_nodes = [t for t in all_text if re.search(r"₹[\d,]{3,}", t)]
        if len(price_nodes) >= 2:
            m2 = re.search(r"₹([\d,]+)", price_nodes[1])
            if m2:
                amt = float(m2.group(1).replace(",", ""))
                if current_price and amt > current_price["amount"]:
                    original_price = {"amount": amt, "currency": "INR"}

        # Discount
        discount_match = next(
            (t for t in all_text if re.search(r"\d+%\s*off", t, re.I)), None
        )
        discount = discount_match.strip() if discount_match else None

        # Rating: standalone decimal like "4.3"
        rating_match = next(
            (t for t in all_text if re.fullmatch(r"\d\.\d", t)), None
        )

        # Review count: "(99)" or "1,234 Ratings"
        review_match = next(
            (t for t in all_text
             if re.search(r"\([\d,]+\)", t) or re.search(r"[\d,]+\s+Ratings?", t, re.I)),
            None,
        )

        return {
            "title": title,
            "product_url": product_url,
            "current_price": current_price,
            "original_price": original_price,
            "discount": discount,
            "rating": rating_match,
            "review_count": review_match,
            "image_url": image_url,
        }

    # ------------------------------------------------------------------
    # Product page
    # ------------------------------------------------------------------

    def _parse_product_page(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        specs: dict[str, str] = {}

        # Try the stable two-column spec table
        for row in soup.select("div._3k-BhJ table tr, table._14cfVK tr, ._2TIQom table tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True)
                val = cells[1].get_text(strip=True)
                if key and val:
                    specs[key] = val

        # Availability: check for out-of-stock indicators
        availability = "In Stock"
        oos_tag = soup.find(string=re.compile(r"out of stock|sold out", re.I))
        if oos_tag:
            availability = "Out of Stock"

        return {
            "specifications": specs or None,
            "availability": availability,
        }

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------

    async def _fetch(self, url: str) -> str:
        for attempt in range(self.settings.max_retries):
            page: Optional[Page] = None
            try:
                await asyncio.sleep(self.settings.request_delay_seconds)
                page = await self.context.new_page()

                if not self._modal_dismissed:
                    # First page load may show modal
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await self._dismiss_modal(page)
                    self._modal_dismissed = True
                else:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

                await self._fill_pincode_if_needed(page)
                return await page.content()

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
