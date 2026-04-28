# Product Scraper

Search for products on Amazon.in and Flipkart.com and return the top 3 results from each as structured JSON or CSV.

## Setup

```bash
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
```

## Usage

```bash
# Single query → stdout JSON
python -m product_scraper "HP laptop with 16GB RAM"

# Save to file
python -m product_scraper "Sony WH-1000XM5" --output results.json

# CSV output
python -m product_scraper "iPhone 15" --format csv --output results.csv

# Batch from file (one query per line)
python -m product_scraper --queries-file queries.txt --output batch.json

# Skip cache for this run
python -m product_scraper "Dell XPS 13" --no-cache
```

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|---|---|---|
| `HEADLESS` | `true` | Run browser headlessly |
| `REQUEST_DELAY_SECONDS` | `2.5` | Seconds between page navigations |
| `MAX_RETRIES` | `3` | Retry attempts on transient failures |
| `CACHE_ENABLED` | `true` | Cache results by query+date |
| `CACHE_DIR` | `.cache` | Directory for cache files |
| `HTTP_PROXY` | _(empty)_ | Optional HTTP proxy URL |

## Output Format

Six rows per query — 3 from Amazon, 3 from Flipkart — with fields:
`source`, `rank`, `title`, `brand`, `model`, `current_price`, `original_price`,
`discount`, `rating`, `review_count`, `specifications`, `product_url`, `image_url`, `availability`.

## Notes

- Scraping is for personal/educational use only. Commercial use may violate Amazon and Flipkart Terms of Service.
- If a CAPTCHA is encountered the scraper fails loudly; it never attempts to bypass anti-bot measures.
- Results are cached per query per day to avoid redundant requests during development.
