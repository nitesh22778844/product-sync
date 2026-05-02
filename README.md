# Product Sync

A Python service that scrapes Amazon.in and Flipkart.com for a given search query, returns the top 3 results from each site (6 products total) as structured JSON, and optionally syncs them to a Salesforce `Product__c` object.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Project Structure](#project-structure)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Starting and Stopping the Server](#starting-and-stopping-the-server)
7. [API Reference](#api-reference)
8. [Caching](#caching)
9. [Salesforce Integration](#salesforce-integration)
10. [CLI Usage](#cli-usage)
11. [Running Tests](#running-tests)
12. [Docker](#docker)
13. [Output Schema](#output-schema)

---

## How It Works

```
User → GET /search?q=<query>
         │
         ▼
    api.py builds per-request Settings
    (cache_enabled=False if no_cache=true)
         │
         ▼
    Orchestrator.run(query)
         │
         ├── launches headless Chromium (Playwright)
         ├── creates one shared BrowserContext
         │
         ├── AmazonScraperFetcher.search(query)   ─┐
         │   ├── check cache (get_cached)           │  asyncio.gather
         │   ├── scrape amazon.in search page       │  runs both
         │   └── scrape 3 product detail pages      │  concurrently
         │                                           │
         └── FlipkartScraperFetcher.search(query)  ─┘
             ├── check cache (get_cached)
             ├── dismiss login modal (once)
             ├── fill delivery pincode
             ├── scrape flipkart.com search page
             └── scrape 3 product detail pages
         │
         ▼
    SearchResult(query, results=[6 Products], errors={})
         │
         ├── return JSON response immediately
         │
         └── BackgroundTask: SalesforceClient.sync_products(results)
             └── PATCH …/Product__c/Title__c/<title> for each product
                 (upsert: creates on 201, updates on 200/204)
```

Each fetcher checks the local file cache first. On a cache hit the browser is never launched for that source. On a cache miss the fetcher scrapes live, then writes results to cache for the rest of the day.

---

## Project Structure

```
product-sync/
├── src/product_scraper/
│   ├── api.py              # FastAPI app — /search and /health
│   ├── orchestrator.py     # Launches browser, runs both fetchers concurrently
│   ├── cache.py            # File-based JSON cache (SHA256 key, daily TTL)
│   ├── config.py           # Settings loaded from .env via pydantic-settings
│   ├── models.py           # Pydantic models: Price, Product, SearchResult
│   ├── salesforce.py       # OAuth2 + upsert sync to Salesforce Product__c
│   ├── exporters.py        # JSON / CSV / JSONL export helpers
│   ├── cli.py              # typer CLI (python -m product_scraper)
│   ├── base.py             # Abstract ProductFetcher base class
│   └── fetchers/
│       ├── amazon_scraper.py    # Playwright scraper for Amazon.in
│       └── flipkart_scraper.py  # Playwright scraper for Flipkart.com
├── tests/
│   ├── conftest.py         # Shared fixtures (mock_settings, cache_settings, etc.)
│   ├── fixtures/           # Saved HTML snapshots for offline scraper tests
│   ├── test_api.py
│   ├── test_cache.py
│   ├── test_models.py
│   ├── test_amazon_scraper.py
│   ├── test_flipkart_scraper.py
│   ├── test_exporters.py
│   └── test_orchestrator.py
├── Dockerfile
├── pyproject.toml
├── requirements.txt        # Flat pin list for Docker builds
└── .env.example
```

---

## Prerequisites

- Python 3.10 or later
- `pip` / `venv`
- Chromium system dependencies (handled automatically by the Playwright installer)

---

## Installation

```bash
# 1. Clone the repo
git clone <repo-url>
cd product-sync

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install Python dependencies (including dev tools)
pip install -e ".[dev]"

# 4. Install Playwright browser + OS dependencies
playwright install --with-deps chromium

# 5. Copy env template and fill in values
cp .env.example .env
```

---

## Configuration

All settings are read from `.env` (or real environment variables). Copy `.env.example` to `.env` and edit as needed.

| Variable | Default | Description |
|---|---|---|
| `HEADLESS` | `true` | Run browser headlessly (`false` shows the browser window) |
| `REQUEST_DELAY_SECONDS` | `2.5` | Pause between HTTP requests per site |
| `MAX_RETRIES` | `3` | Retry attempts on timeout / 5xx errors |
| `CACHE_ENABLED` | `true` | Enable file-based result cache |
| `CACHE_DIR` | `.cache` | Directory for cache JSON files |
| `PLAYWRIGHT_BROWSER` | `chromium` | Browser engine (`chromium`, `firefox`, `webkit`) |
| `HTTP_PROXY` | _(empty)_ | Optional proxy, e.g. `http://proxy:8080` |
| `SF_TOKEN_URL` | _(empty)_ | Salesforce OAuth2 token endpoint |
| `SF_CLIENT_ID` | _(empty)_ | Salesforce connected app client ID |
| `SF_CLIENT_SECRET` | _(empty)_ | Salesforce connected app client secret |
| `SF_API_ENDPOINT` | _(empty)_ | Salesforce REST endpoint for `Product__c` |

Salesforce sync is **disabled** when any of the four `SF_*` variables is blank.

---

## Starting and Stopping the Server

### Start (development)

```bash
python -m uvicorn product_scraper.api:app --host 0.0.0.0 --port 8080
```

> **Windows note:** Do not use `--reload` with Playwright — the `SelectorEventLoop` that uvicorn uses in reload mode is incompatible with Playwright's subprocess. Use a fixed port without `--reload` instead.

### Start (installed entry-point)

```bash
product-scraper-api
# equivalent to: python -m uvicorn product_scraper.api:app --host 0.0.0.0 --port 8000
```

### Start with Docker

```bash
docker build -t product-sync .
docker run -p 8080:8000 --env-file .env product-sync
# server is now at http://localhost:8080
```

### Stop

**Foreground process** — press `Ctrl+C` in the terminal.

**Background process / different terminal:**

```bash
# Windows — find PID then kill
netstat -ano | findstr :8080
taskkill /PID <pid> /F

# macOS / Linux
lsof -ti :8080 | xargs kill
```

**Docker:**

```bash
docker ps                  # find container ID
docker stop <container-id>
```

### Health check

```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

---

## API Reference

Base URL: `http://localhost:8080`

### `GET /health`

Returns `{"status": "ok"}`. Use this to verify the server is running.

---

### `GET /search`

Search Amazon.in and Flipkart.com and return up to 6 products (3 per site).

**Query parameters**

| Parameter | Required | Description |
|---|---|---|
| `q` | Yes | Search query (minimum 1 character) |
| `no_cache` | No | `true` to skip cache and force a live scrape |

**Examples**

```bash
# Normal search (uses cache if available)
curl "http://localhost:8080/search?q=HP+laptop+16GB+RAM"

# Force live scrape, bypass cache
curl "http://localhost:8080/search?q=pendrive&no_cache=true"
```

**Response**

```json
{
  "query": "HP laptop 16GB RAM",
  "timestamp": "2026-05-02T14:30:00+05:30",
  "results": [
    {
      "source": "amazon",
      "rank": 1,
      "title": "HP Laptop 15s, Intel Core i5...",
      "brand": "HP",
      "model": null,
      "current_price": {"amount": 62990.0, "currency": "INR"},
      "original_price": {"amount": 79999.0, "currency": "INR"},
      "discount": "21% off",
      "rating": 4.3,
      "review_count": 1234,
      "specifications": {"RAM": "16 GB", "Storage": "512 GB SSD"},
      "product_url": "https://www.amazon.in/dp/B0XXXXXX",
      "image_url": "https://m.media-amazon.com/images/...",
      "availability": "In Stock",
      "scraped_at": "2026-05-02T14:30:01.123456"
    }
  ],
  "errors": {}
}
```

If one source fails (e.g. Flipkart hits a CAPTCHA), results from the working source are still returned and the failure is recorded in `errors`:

```json
{
  "results": [...],
  "errors": {"flipkart": "CaptchaError: CAPTCHA encountered at ..."}
}
```

---

### `GET /docs`

Swagger UI — interactive API documentation and request builder.

### `GET /openapi.json`

Raw OpenAPI 3.x schema.

---

## Caching

The cache avoids re-scraping the same query on the same day.

### Key generation

```
key = sha256("{source}:{query}:{today's date}")[:16]
```

- Source-specific: `amazon` and `flipkart` have separate cache entries
- Query-specific: different search terms produce different keys
- Expires daily: the date is baked into the key, so midnight rolls a new key automatically

### Storage

One JSON file per `(source, query, date)` stored in `CACHE_DIR` (default `.cache/`):

```json
{
  "key": "a3f9e2b1c4d56789",
  "source": "amazon",
  "query": "HP laptop",
  "cached_at": "2026-05-02",
  "data": [ ... list of product dicts ... ]
}
```

### Read / write flow

1. Fetcher calls `get_cached(source, query, self.settings)`
2. If `cache_enabled=False` or file missing or `cached_at` ≠ today → returns `None` (cache miss)
3. On miss: fetcher scrapes live, then calls `set_cache(source, query, data, self.settings)`

### Per-request settings

Both `get_cached` and `set_cache` accept an optional `cache_settings: Settings` parameter. Fetchers always pass `self.settings`, which is the per-request `Settings` object built in `api.py`.

This means `no_cache=true` flows all the way down:

```
api.py                 → Settings(cache_enabled=False)
  → Orchestrator       → receives that Settings object
    → AmazonFetcher    → calls get_cached(..., self.settings)  # cache disabled
    → FlipkartFetcher  → calls get_cached(..., self.settings)  # cache disabled
```

No read from cache, no write to cache for the entire request.

### Disabling cache globally

Set `CACHE_ENABLED=false` in `.env` to skip caching for every request.

---

## Salesforce Integration

When all four `SF_*` variables are configured, each successful `/search` response queues a background task that upserts each product into `Product__c`. The HTTP response is never delayed by this sync.

### Prerequisites in Salesforce

1. Create a Connected App with the **Client Credentials** OAuth flow enabled
2. Create a custom object `Product__c` with the custom fields listed in the table below
3. Mark `Title__c` as an **External ID**: `Setup → Object Manager → Product__c → Fields & Relationships → Title__c → Edit → check "External ID"`

### Auth

OAuth 2.0 client credentials flow (`grant_type=client_credentials`). The access token is cached in memory and refreshed automatically 60 seconds before expiry.

### Upsert behaviour

```
PATCH /services/data/v57.0/sobjects/Product__c/Title__c/<url-encoded-title>
```

| HTTP status | Meaning |
|---|---|
| 201 | Record created (new title) |
| 200 / 204 | Record updated (existing title matched) |
| 4xx / 5xx | Error — logged as warning, sync continues for other products |

Titles longer than 200 characters are trimmed before being used as the key or stored.

### Field mapping

| Product field | Salesforce field | Notes |
|---|---|---|
| `title[:200]` | `Title__c` | External ID — in URL, not body |
| `source` | `Source__c` | `"amazon"` or `"flipkart"` |
| `rank` | `Rank__c` | 1–3 |
| `product_url` | `Product_URL__c` | Query string stripped (fits 255-char Text) |
| `brand` | `Brand__c` | |
| `model` | `Model__c` | |
| `current_price.amount` | `Current_Price__c` | INR amount (Number) |
| `original_price.amount` | `Original_Price__c` | |
| `discount` | `Discount__c` | Numeric %, e.g. `21.0` (Percent field) |
| `rating` | `Rating__c` | |
| `review_count` | `Review_Count__c` | |
| `specifications` | `Specifications__c` | JSON-serialised dict (Long Text Area) |
| `image_url` | `Image_URL__c` | |
| `availability` | `Availability__c` | |
| `scraped_at` | `Scraped_At__c` | ISO 8601 string (DateTime field) |

---

## CLI Usage

```bash
# Single query — prints JSON to stdout
python -m product_scraper "HP laptop with 16GB RAM"

# Save JSON to file
python -m product_scraper "Sony WH-1000XM5" --output results.json

# CSV output
python -m product_scraper "iPhone 15" --format csv --output results.csv

# JSONL output (one product per line — useful for streaming / big batches)
python -m product_scraper "Dell XPS 13" --format jsonl --output results.jsonl

# Multiple queries from a text file (one query per line)
python -m product_scraper --queries-file queries.txt --output batch.json

# Bypass cache for this run
python -m product_scraper "Dell XPS 13" --no-cache
```

---

## Running Tests

```bash
# Full test suite
pytest

# Verbose output
pytest -v

# Single file
pytest tests/test_cache.py -v

# Single test
pytest tests/test_api.py::test_no_cache_true_bypasses_fetcher_cache -v
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator needed on async tests.

Scraper tests use saved HTML fixtures from `tests/fixtures/` so they run offline without launching a browser.

---

## Docker

### Build

```bash
docker build -t product-sync .
```

The image is based on `python:3.12-slim`. It installs Python dependencies from `requirements.txt` then runs `playwright install --with-deps chromium` to pull in the browser binary and its OS libraries.

### Run

```bash
docker run -p 8080:8000 --env-file .env product-sync
# server available at http://localhost:8080
```

The container reads `$PORT` at startup (defaults to `8000`).

### Updating requirements.txt

`requirements.txt` is the flat pin list consumed by the Dockerfile. Regenerate it after any dependency change in `pyproject.toml`:

```bash
pip install pip-tools
pip-compile pyproject.toml -o requirements.txt
```

---

## Output Schema

Each product in `results` has these fields:

| Field | Type | Description |
|---|---|---|
| `source` | `"amazon"` \| `"flipkart"` | Which site the result came from |
| `rank` | `int` 1–3 | Position within that site's results |
| `title` | `str` | Full product title |
| `brand` | `str \| null` | Brand name extracted from product page |
| `model` | `str \| null` | Model identifier |
| `current_price` | `{amount: float, currency: str} \| null` | Current selling price |
| `original_price` | `{amount: float, currency: str} \| null` | MRP / crossed-out price |
| `discount` | `str \| null` | e.g. `"21% off"` |
| `rating` | `float` 0–5 \| null | Star rating |
| `review_count` | `int \| null` | Review count (`2.7L` → 270000, `45K` → 45000) |
| `specifications` | `dict[str, str] \| null` | Key-value specs from the product detail page |
| `product_url` | `str` | Direct link to the product listing |
| `image_url` | `str \| null` | Primary product image URL |
| `availability` | `str \| null` | e.g. `"In Stock"`, `"Out of Stock"` |
| `scraped_at` | `datetime` | When the product was fetched |

---

## Scraping Policy

- Respects `robots.txt` — never accesses disallowed paths.
- Never bypasses CAPTCHAs, login walls, or anti-bot measures — fails loudly instead.
- Rate-limited to ~1 request per 2–3 seconds per site.
- For personal / educational use only. Commercial use may violate Amazon and Flipkart Terms of Service.
