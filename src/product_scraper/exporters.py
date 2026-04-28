from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from product_scraper.models import SearchResult


def export_json(result: SearchResult, path: Optional[Path] = None) -> str:
    data = result.model_dump(mode="json")
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    if path:
        path.write_text(json_str, encoding="utf-8")
    return json_str


def export_csv(result: SearchResult, path: Optional[Path] = None) -> str:
    rows = []
    for product in result.results:
        row = product.model_dump(mode="json")
        # Flatten Price dicts
        cp = row.pop("current_price", None)
        row["current_price"] = cp["amount"] if cp else None
        row["current_price_currency"] = cp["currency"] if cp else "INR"

        op = row.pop("original_price", None)
        row["original_price"] = op["amount"] if op else None

        # Flatten specs dict to "k: v; k: v" string
        specs = row.pop("specifications", None)
        row["specifications"] = (
            "; ".join(f"{k}: {v}" for k, v in specs.items()) if specs else None
        )
        rows.append(row)

    df = pd.DataFrame(rows)
    csv_str = df.to_csv(index=False)
    if path:
        path.write_text(csv_str, encoding="utf-8")
    return csv_str


def export_jsonl(results: list[SearchResult], path: Path) -> None:
    """Write multiple SearchResult objects as newline-delimited JSON."""
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in results]
    path.write_text("\n".join(lines), encoding="utf-8")
