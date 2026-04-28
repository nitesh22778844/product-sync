import json
from pathlib import Path

import pytest

from product_scraper.exporters import export_csv, export_json, export_jsonl
from product_scraper.models import Product, SearchResult


def _product(**kwargs) -> Product:
    defaults = dict(source="amazon", rank=1, title="HP Laptop", product_url="https://amazon.in/dp/X")
    defaults.update(kwargs)
    return Product(**defaults)


def _result(**kwargs) -> SearchResult:
    kwargs.setdefault("query", "test query")
    return SearchResult(**kwargs)


# ──────────────────────────────────────────────
# export_json
# ──────────────────────────────────────────────

def test_export_json_returns_valid_json():
    text = export_json(_result())
    parsed = json.loads(text)
    assert parsed["query"] == "test query"


def test_export_json_is_pretty_printed():
    text = export_json(_result())
    assert "\n" in text  # indent=2 produces newlines


def test_export_json_includes_results():
    r = _result(results=[_product(title="SanDisk 64GB")])
    parsed = json.loads(export_json(r))
    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["title"] == "SanDisk 64GB"


def test_export_json_empty_results():
    parsed = json.loads(export_json(_result(results=[])))
    assert parsed["results"] == []


def test_export_json_includes_errors():
    r = _result(errors={"amazon": "timeout", "flipkart": "captcha"})
    parsed = json.loads(export_json(r))
    assert parsed["errors"]["amazon"] == "timeout"


def test_export_json_unicode_preserved():
    r = _result(results=[_product(title="HP लैपटॉप")])
    text = export_json(r)
    assert "HP लैपटॉप" in text  # ensure_ascii=False


def test_export_json_writes_to_file(tmp_path):
    out = tmp_path / "result.json"
    export_json(_result(), out)
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["query"] == "test query"


def test_export_json_returns_string_even_without_path():
    text = export_json(_result())
    assert isinstance(text, str)


def test_export_json_price_fields_serialized():
    r = _result(results=[_product(
        current_price={"amount": 62990.0, "currency": "INR"},
        original_price={"amount": 79999.0, "currency": "INR"},
    )])
    parsed = json.loads(export_json(r))
    cp = parsed["results"][0]["current_price"]
    assert cp["amount"] == pytest.approx(62990.0)
    assert cp["currency"] == "INR"


def test_export_json_six_products():
    amazon = [_product(source="amazon", rank=i, title=f"A{i}", product_url=f"https://a.com/{i}") for i in range(1, 4)]
    flipkart = [_product(source="flipkart", rank=i, title=f"F{i}", product_url=f"https://f.com/{i}") for i in range(1, 4)]
    r = _result(results=amazon + flipkart)
    parsed = json.loads(export_json(r))
    assert len(parsed["results"]) == 6


# ──────────────────────────────────────────────
# export_csv
# ──────────────────────────────────────────────

def test_export_csv_returns_string():
    assert isinstance(export_csv(_result()), str)


def test_export_csv_has_header_row():
    r = _result(results=[_product()])
    lines = export_csv(r).strip().splitlines()
    assert "title" in lines[0]
    assert "source" in lines[0]


def test_export_csv_one_data_row_per_product():
    products = [_product(rank=i, title=f"Product {i}") for i in range(1, 4)]
    r = _result(results=products)
    lines = [l for l in export_csv(r).strip().splitlines() if l]
    assert len(lines) == 4  # header + 3 data rows


def test_export_csv_flattens_current_price_to_amount():
    r = _result(results=[_product(current_price={"amount": 62990.0, "currency": "INR"})])
    csv_str = export_csv(r)
    assert "62990" in csv_str


def test_export_csv_null_price_does_not_crash():
    r = _result(results=[_product()])  # no prices set
    csv_str = export_csv(r)
    assert csv_str is not None


def test_export_csv_flattens_specifications_to_semicolon_string():
    r = _result(results=[_product(specifications={"RAM": "16 GB", "Storage": "512 GB SSD"})])
    csv_str = export_csv(r)
    assert "RAM: 16 GB" in csv_str


def test_export_csv_null_specifications_does_not_crash():
    r = _result(results=[_product(specifications=None)])
    csv_str = export_csv(r)
    assert csv_str is not None


def test_export_csv_empty_results_does_not_crash():
    csv_str = export_csv(_result(results=[]))
    assert isinstance(csv_str, str)


def test_export_csv_writes_to_file(tmp_path):
    out = tmp_path / "result.csv"
    r = _result(results=[_product()])
    export_csv(r, out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "title" in content


def test_export_csv_both_price_columns_present():
    r = _result(results=[_product(
        current_price={"amount": 5000.0, "currency": "INR"},
        original_price={"amount": 8000.0, "currency": "INR"},
    )])
    csv_str = export_csv(r)
    assert "5000" in csv_str
    assert "8000" in csv_str


def test_export_csv_currency_column_present():
    r = _result(results=[_product(current_price={"amount": 5000.0, "currency": "INR"})])
    csv_str = export_csv(r)
    assert "INR" in csv_str


def test_export_csv_source_and_rank_present():
    r = _result(results=[_product(source="flipkart", rank=2)])
    csv_str = export_csv(r)
    assert "flipkart" in csv_str
    assert "2" in csv_str


# ──────────────────────────────────────────────
# export_jsonl
# ──────────────────────────────────────────────

def test_export_jsonl_one_line_per_result(tmp_path):
    results = [_result(query=f"query {i}") for i in range(3)]
    out = tmp_path / "batch.jsonl"
    export_jsonl(results, out)
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 3


def test_export_jsonl_each_line_is_valid_json(tmp_path):
    results = [_result(query="laptop"), _result(query="phone")]
    out = tmp_path / "out.jsonl"
    export_jsonl(results, out)
    for line in out.read_text(encoding="utf-8").splitlines():
        parsed = json.loads(line)
        assert "query" in parsed


def test_export_jsonl_preserves_queries(tmp_path):
    results = [_result(query="pen drive"), _result(query="ssd")]
    out = tmp_path / "out.jsonl"
    export_jsonl(results, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    queries = [json.loads(l)["query"] for l in lines if l]
    assert queries == ["pen drive", "ssd"]


def test_export_jsonl_single_result(tmp_path):
    out = tmp_path / "single.jsonl"
    export_jsonl([_result()], out)
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 1
