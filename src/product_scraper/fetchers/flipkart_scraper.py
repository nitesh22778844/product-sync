from __future__ import annotations

import asyncio
import logging
import re
import uuid
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
        if self.settings.grocery_mode:
            q = quote_plus(query)
            request_id = str(uuid.uuid4())
            url = (
                f"{BASE_URL}/search?q={q}"
                f"&as=on&as-show=on&marketplace=HYPERLOCAL"
                f"&otracker=AS_Query_OrganicAutoSuggest_1_11_na_na_na"
                f"&otracker1=AS_Query_OrganicAutoSuggest_1_11_na_na_na"
                f"&as-pos=1&as-type=RECENT"
                f"&suggestionId={q}&requestId={request_id}&as-searchtext={q}"
            )
        else:
            url = f"{BASE_URL}/search?q={quote_plus(query)}"
        logger.info("[flipkart] fetching search page: %s", url)
        page = await self.context.new_page()
        try:
            html = await self._load_search_page(page, url)
        finally:
            await page.close()

        raw_cards = self._parse_search_page(html, limit)
        logger.info("[flipkart] parsed %d search cards", len(raw_cards))

        if self.settings.grocery_mode:
            for card in raw_cards:
                purl = card.get("product_url", "")
                if purl and "marketplace=HYPERLOCAL" not in purl:
                    sep = "&" if "?" in purl else "?"
                    card["product_url"] = purl + sep + "marketplace=HYPERLOCAL"

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
        wait_strategy = "networkidle" if self.settings.grocery_mode else "domcontentloaded"
        await page.goto(url, wait_until=wait_strategy, timeout=45_000)

        if self.settings.grocery_mode:
            # Flipkart Minutes is gated by a "Use my current location" CTA. Geolocation
            # was granted at the BrowserContext level, so clicking resolves immediately.
            await self._click_use_current_location(page)
        else:
            if not self._modal_dismissed:
                await self._dismiss_modal(page)
                self._modal_dismissed = True
            await self._fill_pincode_if_needed(page)

        # Wait for product cards to appear
        try:
            await page.wait_for_selector("a[href*='/p/']", timeout=15_000)
        except PlaywrightTimeoutError:
            logger.debug("No /p/ links found on Flipkart search page")

        # Scroll to trigger lazy-loaded images
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(1.5)

        return await page.content()

    async def _click_use_current_location(self, page: Page) -> None:
        """Flipkart Minutes (HYPERLOCAL) shows a 'Use my current location' CTA before
        any products render. The element is a div in a CSS-in-JS tree (no stable
        selector), so we find it by exact text match in the DOM."""
        try:
            clicked = await page.evaluate(
                """() => {
                    const all = document.querySelectorAll('div, button, span, a');
                    for (const el of all) {
                        if (el.children.length === 0 &&
                            el.textContent.trim() === 'Use my current location') {
                            let target = el;
                            for (let i = 0; i < 5 && target; i++) {
                                if (target.tagName === 'BUTTON' ||
                                    target.onclick ||
                                    target.getAttribute('role') === 'button') break;
                                target = target.parentElement;
                            }
                            (target || el).click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if clicked:
                logger.info("[flipkart] clicked 'Use my current location' (Minutes gate)")
                await asyncio.sleep(4)
            else:
                logger.debug("[flipkart] no 'Use my current location' CTA found")
        except Exception as exc:
            logger.warning("[flipkart] failed to click location CTA: %s", exc)

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
        if self.settings.grocery_mode:
            return self._parse_minutes_search_page(soup, limit)

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

    def _parse_minutes_search_page(self, soup: BeautifulSoup, limit: int) -> list[dict]:
        """Flipkart Minutes (HYPERLOCAL) renders each product as an `<a href*='/p/'>`
        with no wrapping data-id. Title/image are inside the link; price/discount
        are sibling text nodes in the parent <div>.
        """
        results: list[dict] = []
        seen_urls: set[str] = set()

        for link_tag in soup.select("a[href*='/p/']"):
            if len(results) >= limit:
                break
            parsed = self._parse_minutes_card(link_tag)
            if not parsed or not parsed.get("title") or not parsed.get("product_url"):
                continue
            url = parsed["product_url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(parsed)

        return results

    def _parse_minutes_card(self, link_tag: Tag) -> dict:
        href = link_tag.get("href", "")
        product_url = href if href.startswith("http") else BASE_URL + href

        # Image: <img> inside the link
        image_url: Optional[str] = None
        img_tag = link_tag.find("img")
        if img_tag:
            src = img_tag.get("src", "")
            image_url = src if src and not src.startswith("data:") else None

        # Title: first non-trivial text node in the link (NOT "9 mins" delivery time)
        title: Optional[str] = None
        for t in link_tag.find_all(string=True):
            txt = t.strip()
            if txt and not re.fullmatch(r"\d+\s*mins?", txt, re.I) and len(txt) > 2:
                title = txt
                break

        # Prices/discount/quantity: in the parent container's text nodes (in DOM order:
        # discount %, "Off", quantity, title, "N mins", MRP ₹, current ₹, "Add")
        parent = link_tag.parent
        current_price: Optional[dict] = None
        original_price: Optional[dict] = None
        discount: Optional[str] = None
        if parent:
            text_nodes = [t.strip() for t in parent.find_all(string=True) if t.strip()]
            prices = [
                float(m.group(1).replace(",", ""))
                for t in text_nodes
                for m in [re.search(r"₹\s*([\d,]+(?:\.\d+)?)", t)]
                if m
            ]
            # In Minutes layout: MRP appears before discounted price in DOM order
            if len(prices) >= 2:
                original_price = {"amount": prices[0], "currency": "INR"}
                current_price = {"amount": prices[1], "currency": "INR"}
            elif prices:
                current_price = {"amount": prices[0], "currency": "INR"}

            # Discount: "42%" + "Off" → "42% off"
            for i, t in enumerate(text_nodes):
                pct = re.match(r"(\d+)%$", t)
                if pct:
                    next_t = text_nodes[i + 1] if i + 1 < len(text_nodes) else ""
                    if next_t.lower() == "off":
                        discount = f"{pct.group(1)}% off"
                    break

        return {
            "title": title,
            "product_url": product_url,
            "current_price": current_price,
            "original_price": original_price,
            "discount": discount,
            "rating": None,
            "review_count": None,
            "image_url": image_url,
        }

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
                wait_strategy = "networkidle" if self.settings.grocery_mode else "domcontentloaded"
                await page.goto(url, wait_until=wait_strategy, timeout=45_000)

                if self.settings.grocery_mode:
                    await self._click_use_current_location(page)
                else:
                    if not self._modal_dismissed:
                        await self._dismiss_modal(page)
                        self._modal_dismissed = True
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
