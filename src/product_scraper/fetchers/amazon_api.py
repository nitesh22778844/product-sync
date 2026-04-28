from product_scraper.base import ProductFetcher
from product_scraper.models import Product


class APIUnavailableError(RuntimeError):
    pass


class AmazonAPIFetcher(ProductFetcher):
    """Placeholder for Amazon PA-API / Creators API.

    Amazon PA-API 5.0 shut down May 15 2026 and accepts no new signups.
    Raise immediately so the orchestrator falls back to the scraper.
    """

    source = "amazon"

    async def search(self, query: str, limit: int = 3) -> list[Product]:
        raise APIUnavailableError(
            "Amazon Product Advertising API is unavailable (shut down May 2026). "
            "Use AmazonScraperFetcher instead."
        )
