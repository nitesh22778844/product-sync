from abc import ABC, abstractmethod

from product_scraper.models import Product


class ProductFetcher(ABC):
    source: str

    @abstractmethod
    async def search(self, query: str, limit: int = 3) -> list[Product]:
        ...

    async def close(self) -> None:
        pass
