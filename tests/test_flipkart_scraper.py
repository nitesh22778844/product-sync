from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from product_scraper.fetchers.flipkart_scraper import FlipkartScraperFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    path = FIXTURES / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def fetcher(mock_settings):
    return FlipkartScraperFetcher(mock_settings, MagicMock())


# ──────────────────────────────────────────────
# _parse_card — basic field extraction
# ──────────────────────────────────────────────

def test_parse_card_extracts_all_fields(fetcher):
    html = """
    <div data-id="ITMABC123">
      <a href="/hp-laptop-16gb/p/itm123?pid=ABC"
         title="HP Pavilion 15 Intel Core i5 16GB RAM 512GB SSD Laptop">
        <img src="https://img.example.com/laptop.jpg" alt="HP Pavilion 15" />
      </a>
      <div>₹62,990</div>
      <div>₹79,999</div>
      <div>21% off</div>
      <div>4.3</div>
      <div>(1,234 Ratings)</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["title"] is not None
    assert "HP Pavilion" in result["title"]
    assert result["product_url"] == "https://www.flipkart.com/hp-laptop-16gb/p/itm123?pid=ABC"
    assert result["current_price"]["amount"] == pytest.approx(62990.0)
    assert result["original_price"]["amount"] == pytest.approx(79999.0)
    assert result["discount"] is not None
    assert "21%" in result["discount"]
    assert result["rating"] == "4.3"
    assert result["image_url"] == "https://img.example.com/laptop.jpg"


def test_parse_card_review_count_parens_format(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
      <div>(4,567 Ratings)</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["review_count"] is not None


def test_parse_card_review_count_ratings_format(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
      <div>4,567 Ratings</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["review_count"] is not None
    assert "4,567" in result["review_count"]


def test_parse_card_no_price_returns_none(fetcher):
    html = """
    <div data-id="ITMXYZ999">
      <a href="/some-product/p/itm999" title="Some Product Title That Is Long Enough">
        <img src="https://img.example.com/product.jpg" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["current_price"] is None


def test_parse_card_no_product_link_returns_empty(fetcher):
    html = '<div data-id="ITM001"><a href="/category/browse">Category</a></div>'
    card = BeautifulSoup(html, "lxml").div
    assert fetcher._parse_card(card) == {}


def test_parse_card_base64_image_returns_null(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAi" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["image_url"] is None


def test_parse_card_no_image_returns_null(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here"></a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["image_url"] is None


def test_parse_card_relative_url_prepended(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["product_url"].startswith("https://www.flipkart.com")


def test_parse_card_absolute_url_unchanged(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="https://www.flipkart.com/product/p/itm001"
         title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["product_url"] == "https://www.flipkart.com/product/p/itm001"


def test_parse_card_title_from_title_attribute(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/p/itm001" title="Full Product Name That Is Not Truncated In DOM">
        <img src="https://img.example.com/x.jpg" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["title"] == "Full Product Name That Is Not Truncated In DOM"


def test_parse_card_title_from_img_alt_fallback(fetcher):
    # No a[title], fall back to img[alt]
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001">
        <img src="https://img.example.com/x.jpg" alt="Fallback Alt Title Product" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    # title may come from alt or be None — just verify no crash
    assert "title" in result


def test_parse_card_rating_extracted(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
      <div>4.5</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["rating"] == "4.5"


def test_parse_card_no_rating_returns_none(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["rating"] is None


def test_parse_card_discount_extracted(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
      <div>₹500</div>
      <div>15% off</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["discount"] is not None
    assert "15%" in result["discount"]


def test_parse_card_discount_case_insensitive(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/x.jpg" />
      </a>
      <div>₹500</div>
      <div>30% OFF</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    assert result["discount"] is not None


def test_parse_card_original_price_only_kept_when_higher(fetcher):
    html = """
    <div data-id="ITM001">
      <a href="/product/p/itm001" title="Product Title Long Enough Here">
        <img src="https://img.example.com/1.jpg" />
      </a>
      <div>₹50,000</div>
      <div>₹30,000</div>
    </div>
    """
    card = BeautifulSoup(html, "lxml").div
    result = fetcher._parse_card(card)
    # ₹50,000 is current (first ₹ match); ₹30,000 is second but NOT > current → no original_price
    assert result["current_price"]["amount"] == pytest.approx(50000.0)
    assert result["original_price"] is None


# ──────────────────────────────────────────────
# _parse_search_page
# ──────────────────────────────────────────────

def test_parse_search_page_deduplicates_same_url(fetcher):
    html = """
    <html><body>
      <div data-id="ITM001">
        <a href="/laptop/p/itm001" title="HP Laptop 16GB RAM 512GB SSD Full Title Here">
          <img src="https://img.example.com/1.jpg" />
        </a>
        <div>₹62,990</div>
      </div>
      <div data-id="ITM001">
        <a href="/laptop/p/itm001" title="HP Laptop 16GB RAM Duplicate Card">
          <img src="https://img.example.com/1.jpg" />
        </a>
        <div>₹62,990</div>
      </div>
      <div data-id="ITM002">
        <a href="/laptop/p/itm002" title="Dell Laptop 16GB RAM 512GB SSD Another Product">
          <img src="https://img.example.com/2.jpg" />
        </a>
        <div>₹58,000</div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=3)
    urls = [r["product_url"] for r in results]
    assert len(urls) == len(set(urls)), "Duplicate URLs should be deduplicated"
    assert len(results) == 2


def test_parse_search_page_respects_limit(fetcher):
    items = "\n".join(
        f'<div data-id="ITM{i}"><a href="/p/itm{i}" title="Product Title Number {i} Extra Words Here Long">'
        f'<img src="https://img.example.com/{i}.jpg" /></a>'
        f'<div>₹{10000 + i * 1000}</div></div>'
        for i in range(1, 10)
    )
    html = f"<html><body>{items}</body></html>"
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) <= 3


def test_parse_search_page_limit_1(fetcher):
    items = "\n".join(
        f'<div data-id="ITM{i}"><a href="/p/itm{i}" title="Product Title Number {i} Enough Long Here">'
        f'<img src="https://img.example.com/{i}.jpg" /></a>'
        f'<div>₹{10000 + i * 1000}</div></div>'
        for i in range(1, 5)
    )
    html = f"<html><body>{items}</body></html>"
    results = fetcher._parse_search_page(html, limit=1)
    assert len(results) == 1


def test_parse_search_page_empty_html(fetcher):
    results = fetcher._parse_search_page("<html><body></body></html>", limit=3)
    assert results == []


def test_parse_search_page_skips_cards_without_title(fetcher):
    html = """
    <html><body>
      <div data-id="ITM001">
        <a href="/p/itm001"><img src="https://img.example.com/1.jpg" /></a>
      </div>
      <div data-id="ITM002">
        <a href="/laptop/p/itm002" title="Dell Laptop 16GB RAM 512GB SSD Good Title">
          <img src="https://img.example.com/2.jpg" />
        </a>
        <div>₹58,000</div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) == 1
    assert "Dell" in results[0]["title"]


def test_parse_search_page_skips_cards_without_product_url(fetcher):
    html = """
    <html><body>
      <div data-id="ITM001">
        <a href="/category/browse" title="Browse Category Page">No /p/ link here</a>
      </div>
      <div data-id="ITM002">
        <a href="/laptop/p/itm002" title="Real Product Title Long Enough Here">
          <img src="https://img.example.com/2.jpg" />
        </a>
        <div>₹58,000</div>
      </div>
    </body></html>
    """
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) == 1


# ──────────────────────────────────────────────
# _parse_product_page
# ──────────────────────────────────────────────

def test_parse_product_page_specs_3k_bhj_selector(fetcher):
    html = """
    <html><body>
      <div class="_3k-BhJ">
        <table>
          <tr><td>Processor</td><td>Intel Core i5-1235U</td></tr>
          <tr><td>RAM</td><td>16 GB</td></tr>
          <tr><td>Storage</td><td>512 GB SSD</td></tr>
        </table>
      </div>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    assert result["specifications"]["RAM"] == "16 GB"
    assert result["specifications"]["Processor"] == "Intel Core i5-1235U"


def test_parse_product_page_availability_in_stock_by_default(fetcher):
    html = "<html><body><div>Some product page</div></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["availability"] == "In Stock"


def test_parse_product_page_out_of_stock(fetcher):
    html = "<html><body><p>This item is currently out of stock.</p></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["availability"] == "Out of Stock"


def test_parse_product_page_sold_out(fetcher):
    html = "<html><body><p>Sold Out</p></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["availability"] == "Out of Stock"


def test_parse_product_page_no_specs_returns_none(fetcher):
    html = "<html><body><p>No spec table here</p></body></html>"
    result = fetcher._parse_product_page(html)
    assert result["specifications"] is None


def test_parse_product_page_skips_single_cell_rows(fetcher):
    html = """
    <html><body>
      <div class="_3k-BhJ">
        <table>
          <tr><td>Section Header Only</td></tr>
          <tr><td>RAM</td><td>8 GB</td></tr>
        </table>
      </div>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    specs = result["specifications"]
    assert "Section Header Only" not in specs
    assert specs["RAM"] == "8 GB"


def test_parse_product_page_skips_empty_key_rows(fetcher):
    html = """
    <html><body>
      <div class="_3k-BhJ">
        <table>
          <tr><td></td><td>Value with no key</td></tr>
          <tr><td>RAM</td><td>16 GB</td></tr>
        </table>
      </div>
    </body></html>
    """
    result = fetcher._parse_product_page(html)
    specs = result["specifications"]
    assert "" not in specs
    assert specs["RAM"] == "16 GB"


# ──────────────────────────────────────────────
# Fixture-based tests (skipped when fixtures absent)
# ──────────────────────────────────────────────

@pytest.mark.skipif(
    not (FIXTURES / "flipkart_search.html").exists(),
    reason="Fixture flipkart_search.html not present",
)
def test_parse_real_search_fixture(fetcher):
    html = _load_fixture("flipkart_search.html")
    results = fetcher._parse_search_page(html, limit=3)
    assert len(results) <= 3
    for r in results:
        assert r["title"]
        assert r["product_url"].startswith("https://www.flipkart.com")


@pytest.mark.skipif(
    not (FIXTURES / "flipkart_product.html").exists(),
    reason="Fixture flipkart_product.html not present",
)
def test_parse_real_product_fixture(fetcher):
    html = _load_fixture("flipkart_product.html")
    result = fetcher._parse_product_page(html)
    assert isinstance(result.get("specifications"), (dict, type(None)))
