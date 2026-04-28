from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from product_scraper.fetchers.amazon_scraper import AmazonScraperFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    path = FIXTURES / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def fetcher(mock_settings):
    return AmazonScraperFetcher(mock_settings, MagicMock())


# ──────────────────────────────────────────────
# _extract_price
# ──────────────────────────────────────────────

def test_extract_price_rupee_symbol(fetcher):
    result = fetcher._extract_price("₹62,990")
    assert result["amount"] == pytest.approx(62990.0)
    assert result["currency"] == "INR"


def test_extract_price_decimal_preserved(fetcher):
    # ₹40.56 must NOT become ₹4056
    result = fetcher._extract_price("₹40.56")
    assert result["amount"] == pytest.approx(40.56)


def test_extract_price_large_indian_format(fetcher):
    result = fetcher._extract_price("₹1,99,990")
    assert result["amount"] == pytest.approx(199990.0)


def test_extract_price_none_returns_none(fetcher):
    assert fetcher._extract_price(None) is None


def test_extract_price_empty_string_returns_none(fetcher):
    assert fetcher._extract_price("") is None


def test_extract_price_non_numeric_returns_none(fetcher):
    assert fetcher._extract_price("N/A") is None


def test_extract_price_whitespace_only_returns_none(fetcher):
    assert fetcher._extract_price("   ") is None


# ──────────────────────────────────────────────
# _is_sponsored
# ──────────────────────────────────────────────

def test_is_sponsored_by_span_text(fetcher):
    html = '<div><span class="a-color-secondary">Sponsored</span></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._is_sponsored(card) is True


def test_is_sponsored_case_insensitive(fetcher):
    html = '<div><span>SPONSORED</span></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._is_sponsored(card) is True


def test_is_sponsored_by_data_attribute(fetcher):
    html = '<div data-component-type="sp-sponsored-result"></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._is_sponsored(card) is True


def test_is_not_sponsored_organic_result(fetcher):
    html = '<div data-component-type="s-search-result"><h2>Product</h2></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._is_sponsored(card) is False


def test_is_not_sponsored_empty_card(fetcher):
    html = '<div></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._is_sponsored(card) is False


# ──────────────────────────────────────────────
# _parse_search_card
# ──────────────────────────────────────────────

def test_parse_search_card_data_cy_layout(fetcher):
    html = """
    <div>
      <div data-cy="title-recipe">
        <a href="/dp/ABCD1234/">HP Pavilion Laptop 16GB RAM</a>
      </div>
      <div class="a-price"><span class="a-offscreen">₹62,990</span></div>
      <div class="a-price a-text-price"><span class="a-offscreen">₹79,999</span></div>
      <i data-cy="reviews-ratings-slot">4.2 out of 5 stars</i>
      <div data-cy="reviews-block"><a href="#reviews">1,834</a></div>
      <img class="s-image" src="https://img.example.com/product.jpg" />
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result is not None
    assert "HP Pavilion" in result["title"]
    assert result["product_url"] == "https://www.amazon.in/dp/ABCD1234/"
    assert result["current_price"]["amount"] == pytest.approx(62990.0)
    assert result["original_price"]["amount"] == pytest.approx(79999.0)
    assert "4.2" in result["rating"]
    assert result["image_url"] == "https://img.example.com/product.jpg"


def test_parse_search_card_fallback_dp_link(fetcher):
    html = """
    <div>
      <a href="/dp/XYZ999/">Fallback Product Name</a>
      <img class="s-image" src="https://img.example.com/x.jpg" />
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result is not None
    assert result["product_url"] == "https://www.amazon.in/dp/XYZ999/"


def test_parse_search_card_relative_url_prepended(fetcher):
    html = '<div><div data-cy="title-recipe"><a href="/dp/REL/">Product</a></div></div>'
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["product_url"].startswith("https://www.amazon.in")


def test_parse_search_card_absolute_url_unchanged(fetcher):
    html = '<div><div data-cy="title-recipe"><a href="https://www.amazon.in/dp/ABS/">Product</a></div></div>'
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["product_url"] == "https://www.amazon.in/dp/ABS/"


def test_parse_search_card_no_price(fetcher):
    html = '<div><div data-cy="title-recipe"><a href="/dp/X/">Product</a></div></div>'
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["current_price"] is None


def test_parse_search_card_original_price_discarded_when_not_higher(fetcher):
    # original <= current → should be None
    html = """
    <div>
      <div data-cy="title-recipe"><a href="/dp/X/">Product</a></div>
      <div class="a-price"><span class="a-offscreen">₹5,000</span></div>
      <div class="a-price a-text-price"><span class="a-offscreen">₹4,000</span></div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["original_price"] is None


def test_parse_search_card_original_price_kept_when_higher(fetcher):
    html = """
    <div>
      <div data-cy="title-recipe"><a href="/dp/X/">Product</a></div>
      <div class="a-price"><span class="a-offscreen">₹5,000</span></div>
      <div class="a-price a-text-price"><span class="a-offscreen">₹8,000</span></div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["original_price"]["amount"] == pytest.approx(8000.0)


def test_parse_search_card_returns_none_without_any_link(fetcher):
    html = "<div><span>No link here</span></div>"
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._parse_search_card(card) is None


def test_parse_search_card_no_image(fetcher):
    html = '<div><div data-cy="title-recipe"><a href="/dp/X/">Product</a></div></div>'
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["image_url"] is None


def test_parse_search_card_rating_from_aria_label(fetcher):
    html = """
    <div>
      <div data-cy="title-recipe"><a href="/dp/X/">Product</a></div>
      <span aria-label="4.5 out of 5 stars">4.5</span>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_search_card(card)
    assert result["rating"] is not None
    assert "4.5" in result["rating"]


# ──────────────────────────────────────────────
# _parse_product_page
# ──────────────────────────────────────────────

def test_parse_product_page_spec_table_section_1(fetcher):
    html = """
    <html><body>
      <table id="productDetails_techSpec_section_1">
        <tr><th>RAM</th><td>16 GB DDR4</td></tr>
        <tr><th>Storage</th><td>512 GB SSD</td></tr>
      </table>
      <div id="availability"><span>In Stock</span></div>
      <a id="bylineInfo">Visit the HP Store</a>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    assert result["specifications"]["RAM"] == "16 GB DDR4"
    assert result["specifications"]["Storage"] == "512 GB SSD"
    assert result["availability"] == "In Stock"
    assert result["brand"] == "HP"


def test_parse_product_page_tech_specs_section(fetcher):
    html = """
    <html><body>
      <table id="tech-specs-section">
        <tr><th>Processor</th><td>Intel Core i5</td></tr>
      </table>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    assert result["specifications"]["Processor"] == "Intel Core i5"


def test_parse_product_page_brand_from_visit_store(fetcher):
    html = '<html><body><a id="bylineInfo">Visit the Samsung Store</a></body></html>'
    result = fetcher._parse_product_page(html)
    assert result["brand"] == "Samsung"


def test_parse_product_page_brand_from_brand_prefix(fetcher):
    html = '<html><body><a id="bylineInfo">Brand: HIKVISION</a></body></html>'
    result = fetcher._parse_product_page(html)
    assert result["brand"] == "HIKVISION"


def test_parse_product_page_no_brand_returns_none(fetcher):
    html = "<html><body></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["brand"] is None


def test_parse_product_page_availability_out_of_stock(fetcher):
    html = '<html><body><div id="availability"><span>Out of Stock</span></div></body></html>'
    result = fetcher._parse_product_page(html)
    assert result["availability"] == "Out of Stock"


def test_parse_product_page_no_specs_returns_none(fetcher):
    html = "<html><body><p>No spec table here</p></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["specifications"] is None


def test_parse_product_page_strips_special_chars(fetcher):
    # ‎ is LEFT-TO-RIGHT MARK; \xa0 is non-breaking space
    html = (
        "<html><body>"
        '<table id="productDetails_techSpec_section_1">'
        "<tr><th>Processor‎</th><td>Intel\xa0Core i5</td></tr>"
        "</table></body></html>"
    )
    result = fetcher._parse_product_page(html)
    specs = result["specifications"]
    assert specs is not None
    assert "Processor" in specs
    assert specs["Processor"] == "Intel Core i5"


def test_parse_product_page_skips_empty_cells(fetcher):
    html = """
    <html><body>
      <table id="productDetails_techSpec_section_1">
        <tr><th></th><td>Orphan value</td></tr>
        <tr><th>RAM</th><td>8 GB</td></tr>
      </table>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    specs = result["specifications"]
    assert "" not in specs
    assert specs.get("RAM") == "8 GB"


# ──────────────────────────────────────────────
# _parse_search_page
# ──────────────────────────────────────────────

def test_parse_search_page_skips_sponsored(fetcher):
    html = """
    <html><body>
      <div data-component-type="sp-sponsored-result">
        <div data-cy="title-recipe"><a href="/dp/S1/">Sponsored Product</a></div>
      </div>
      <div data-component-type="s-search-result">
        <div data-cy="title-recipe"><a href="/dp/P1/">Real Product 1</a></div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=3)
    titles = [r["title"] for r in results]
    assert not any("Sponsored" in t for t in titles)
    assert "Real Product 1" in titles


def test_parse_search_page_respects_limit(fetcher):
    items = "\n".join(
        f'<div data-component-type="s-search-result">'
        f'<div data-cy="title-recipe"><a href="/dp/P{i}/">Product {i}</a></div></div>'
        for i in range(1, 8)
    )
    html = f"<html><body>{items}</body></html>"
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) <= 3


def test_parse_search_page_limit_1(fetcher):
    html = """
    <html><body>
      <div data-component-type="s-search-result">
        <div data-cy="title-recipe"><a href="/dp/P1/">Product A</a></div>
      </div>
      <div data-component-type="s-search-result">
        <div data-cy="title-recipe"><a href="/dp/P2/">Product B</a></div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=1)
    assert len(results) == 1


def test_parse_search_page_empty_html(fetcher):
    results = fetcher._parse_search_page("<html><body></body></html>", limit=3)
    assert results == []


def test_parse_search_page_all_sponsored_returns_empty(fetcher):
    html = """
    <html><body>
      <div data-component-type="sp-sponsored-result">
        <div data-cy="title-recipe"><a href="/dp/S1/">Sponsored 1</a></div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=3)
    assert results == []


# ──────────────────────────────────────────────
# Fixture-based tests (skipped when fixtures absent)
# ──────────────────────────────────────────────

@pytest.mark.skipif(
    not (FIXTURES / "amazon_search.html").exists(),
    reason="Fixture amazon_search.html not present",
)
def test_parse_real_search_fixture(fetcher):
    html = _load_fixture("amazon_search.html")
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) <= 3
    for r in results:
        assert r["title"]
        assert r["product_url"].startswith("https://www.amazon.in")


@pytest.mark.skipif(
    not (FIXTURES / "amazon_product.html").exists(),
    reason="Fixture amazon_product.html not present",
)
def test_parse_real_product_fixture(fetcher):
    html = _load_fixture("amazon_product.html")
    result = fetcher._parse_product_page(html)
    assert isinstance(result.get("specifications"), (dict, type(None)))
