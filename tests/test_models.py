from datetime import datetime

import pytest
from pydantic import ValidationError

from product_scraper.models import Price, Product, SearchResult


# ──────────────────────────────────────────────
# Price
# ──────────────────────────────────────────────

def test_price_rejects_negative():
    with pytest.raises(ValidationError):
        Price(amount=-1)


def test_price_zero_is_valid():
    p = Price(amount=0)
    assert p.amount == 0.0


def test_price_defaults_inr():
    p = Price(amount=1000)
    assert p.currency == "INR"


def test_price_float_amount():
    p = Price(amount=40.56)
    assert p.amount == pytest.approx(40.56)


def test_price_custom_currency():
    p = Price(amount=100, currency="USD")
    assert p.currency == "USD"


# ──────────────────────────────────────────────
# Product — current_price / original_price validator
# ──────────────────────────────────────────────

def test_product_current_price_from_rupee_string():
    p = Product(
        source="flipkart", rank=1, title="T", product_url="https://x.com",
        current_price="₹62,990",
    )
    assert p.current_price.amount == pytest.approx(62990.0)
    assert p.current_price.currency == "INR"


def test_product_price_decimal_preserved():
    # ₹40.56 must NOT become ₹4056 — decimal point must survive cleaning
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        current_price="₹40.56",
    )
    assert p.current_price.amount == pytest.approx(40.56)


def test_product_price_large_amount_with_commas():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        current_price="₹1,99,990",
    )
    assert p.current_price.amount == pytest.approx(199990.0)


def test_product_price_from_dict():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        current_price={"amount": 999.0, "currency": "INR"},
    )
    assert p.current_price.amount == pytest.approx(999.0)


def test_product_price_none_stays_none():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.current_price is None
    assert p.original_price is None


def test_product_original_price_from_string():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        original_price="₹79,999",
    )
    assert p.original_price.amount == pytest.approx(79999.0)


# ──────────────────────────────────────────────
# Product — rating validator
# ──────────────────────────────────────────────

def test_product_rating_from_out_of_5_string():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        rating="4.2 out of 5 stars",
    )
    assert p.rating == pytest.approx(4.2)


def test_product_rating_from_plain_float_string():
    p = Product(
        source="flipkart", rank=1, title="T", product_url="https://x.com",
        rating="4.3",
    )
    assert p.rating == pytest.approx(4.3)


def test_product_rating_from_numeric_float():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        rating=4.5,
    )
    assert p.rating == pytest.approx(4.5)


def test_product_rating_boundary_zero():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com", rating=0.0)
    assert p.rating == pytest.approx(0.0)


def test_product_rating_boundary_five():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com", rating=5.0)
    assert p.rating == pytest.approx(5.0)


def test_product_rating_above_five_rejected():
    with pytest.raises(ValidationError):
        Product(source="amazon", rank=1, title="T", product_url="https://x.com", rating=5.1)


def test_product_rating_negative_rejected():
    with pytest.raises(ValidationError):
        Product(source="amazon", rank=1, title="T", product_url="https://x.com", rating=-0.1)


def test_product_rating_none_stays_none():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.rating is None


# ──────────────────────────────────────────────
# Product — review_count validator
# ──────────────────────────────────────────────

def test_product_review_count_plain_digits_with_commas():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count="1,834 ratings",
    )
    assert p.review_count == 1834


def test_product_review_count_lakh_format():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count="2.7L",
    )
    assert p.review_count == 270000


def test_product_review_count_lakh_lowercase():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count="1.5l",
    )
    assert p.review_count == 150000


def test_product_review_count_k_format():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count="45K",
    )
    assert p.review_count == 45000


def test_product_review_count_k_lowercase():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count="12k",
    )
    assert p.review_count == 12000


def test_product_review_count_from_parens():
    p = Product(
        source="flipkart", rank=1, title="T", product_url="https://x.com",
        review_count="(1,234)",
    )
    assert p.review_count == 1234


def test_product_review_count_from_int():
    p = Product(
        source="amazon", rank=1, title="T", product_url="https://x.com",
        review_count=500,
    )
    assert p.review_count == 500


def test_product_review_count_none_stays_none():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.review_count is None


# ──────────────────────────────────────────────
# Product — rank validation
# ──────────────────────────────────────────────

def test_product_rank_1_valid():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.rank == 1


def test_product_rank_3_valid():
    p = Product(source="amazon", rank=3, title="T", product_url="https://x.com")
    assert p.rank == 3


def test_product_rank_0_rejected():
    with pytest.raises(ValidationError):
        Product(source="amazon", rank=0, title="T", product_url="https://x.com")


def test_product_rank_4_rejected():
    with pytest.raises(ValidationError):
        Product(source="amazon", rank=4, title="T", product_url="https://x.com")


def test_product_rank_negative_rejected():
    with pytest.raises(ValidationError):
        Product(source="amazon", rank=-1, title="T", product_url="https://x.com")


# ──────────────────────────────────────────────
# Product — source validation
# ──────────────────────────────────────────────

def test_product_source_amazon():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.source == "amazon"


def test_product_source_flipkart():
    p = Product(source="flipkart", rank=1, title="T", product_url="https://x.com")
    assert p.source == "flipkart"


def test_product_source_invalid_rejected():
    with pytest.raises(ValidationError):
        Product(source="ebay", rank=1, title="T", product_url="https://x.com")


# ──────────────────────────────────────────────
# Product — whitespace stripping
# ──────────────────────────────────────────────

def test_product_strips_title_whitespace():
    p = Product(source="amazon", rank=1, title="  HP Laptop  ", product_url="https://amazon.in/dp/X")
    assert p.title == "HP Laptop"


def test_product_strips_url_whitespace():
    p = Product(source="amazon", rank=1, title="T", product_url="  https://amazon.in/dp/X  ")
    assert p.product_url == "https://amazon.in/dp/X"


# ──────────────────────────────────────────────
# Product — optional fields
# ──────────────────────────────────────────────

def test_product_optional_fields_default_none():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert p.brand is None
    assert p.model is None
    assert p.discount is None
    assert p.specifications is None
    assert p.image_url is None
    assert p.availability is None


def test_product_scraped_at_is_datetime():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    assert isinstance(p.scraped_at, datetime)


def test_product_with_all_fields():
    p = Product(
        source="amazon",
        rank=2,
        title="Samsung SSD 1TB",
        product_url="https://amazon.in/dp/ABC",
        brand="Samsung",
        model="870 EVO",
        current_price={"amount": 8999.0, "currency": "INR"},
        original_price={"amount": 11999.0, "currency": "INR"},
        discount="25% off",
        rating=4.7,
        review_count=5200,
        specifications={"Interface": "SATA", "Capacity": "1 TB"},
        image_url="https://m.media-amazon.com/images/I/example.jpg",
        availability="In Stock",
    )
    assert p.brand == "Samsung"
    assert p.model == "870 EVO"
    assert p.discount == "25% off"
    assert p.specifications["Capacity"] == "1 TB"
    assert p.availability == "In Stock"


# ──────────────────────────────────────────────
# SearchResult
# ──────────────────────────────────────────────

def test_search_result_timestamp_is_timezone_aware():
    r = SearchResult(query="test")
    assert r.timestamp.tzinfo is not None


def test_search_result_errors_defaults_empty():
    r = SearchResult(query="test")
    assert r.errors == {}


def test_search_result_results_defaults_empty():
    r = SearchResult(query="test")
    assert r.results == []


def test_search_result_preserves_query():
    r = SearchResult(query="HP laptop 16GB")
    assert r.query == "HP laptop 16GB"


def test_search_result_with_products():
    p = Product(source="amazon", rank=1, title="T", product_url="https://x.com")
    r = SearchResult(query="test", results=[p])
    assert len(r.results) == 1
    assert r.results[0].source == "amazon"


def test_search_result_with_errors():
    r = SearchResult(query="test", errors={"amazon": "timeout", "flipkart": "captcha"})
    assert r.errors["amazon"] == "timeout"
    assert r.errors["flipkart"] == "captcha"


def test_search_result_with_six_products():
    amazon = [Product(source="amazon", rank=i, title=f"A{i}", product_url=f"https://a.com/{i}") for i in range(1, 4)]
    flipkart = [Product(source="flipkart", rank=i, title=f"F{i}", product_url=f"https://f.com/{i}") for i in range(1, 4)]
    r = SearchResult(query="pen drive", results=amazon + flipkart)
    assert len(r.results) == 6
    sources = {p.source for p in r.results}
    assert sources == {"amazon", "flipkart"}
