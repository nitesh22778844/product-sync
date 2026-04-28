from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Price(BaseModel):
    amount: Annotated[float, Field(ge=0)]
    currency: str = "INR"


def _parse_price(v: object) -> object:
    if isinstance(v, str):
        cleaned = re.sub(r"[₹₹RsINR\s]", "", v).replace(",", "")
        try:
            return {"amount": float(cleaned), "currency": "INR"}
        except ValueError:
            return v
    return v


class Product(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source: Literal["amazon", "flipkart"]
    rank: Annotated[int, Field(ge=1, le=3)]
    title: str
    product_url: str

    brand: Optional[str] = None
    model: Optional[str] = None
    current_price: Optional[Price] = None
    original_price: Optional[Price] = None
    discount: Optional[str] = None
    rating: Optional[Annotated[float, Field(ge=0.0, le=5.0)]] = None
    review_count: Optional[int] = None
    specifications: Optional[dict[str, str]] = None
    image_url: Optional[str] = None
    availability: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.now)

    @field_validator("rating", mode="before")
    @classmethod
    def parse_rating(cls, v: object) -> object:
        if isinstance(v, str):
            m = re.search(r"(\d+\.?\d*)", v)
            if m:
                return float(m.group(1))
        return v

    @field_validator("review_count", mode="before")
    @classmethod
    def parse_review_count(cls, v: object) -> object:
        if isinstance(v, str):
            # Handle Indian number formats: "2.7L" (lakh) or "45K" (thousand)
            lakh = re.search(r"([\d.]+)\s*[Ll]", v)
            if lakh:
                return int(float(lakh.group(1)) * 100_000)
            kilo = re.search(r"([\d.]+)\s*[Kk]", v)
            if kilo:
                return int(float(kilo.group(1)) * 1_000)
            digits = re.sub(r"[^\d]", "", v)
            return int(digits) if digits else None
        return v

    @field_validator("current_price", "original_price", mode="before")
    @classmethod
    def parse_price(cls, v: object) -> object:
        return _parse_price(v)


class SearchResult(BaseModel):
    query: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=ZoneInfo("Asia/Kolkata"))
    )
    results: list[Product] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
