# CLAUDE.md

## Project Overview

A Python-based product information aggregator that searches Amazon.in and Flipkart.com, returning the top 3 results from each (6 total rows) as structured JSON/CSV.

**Primary use case:** Given a query like "HP laptop with 16GB RAM", return 6 rows of comparable product data side-by-side.

## API Status (as of May 2026)

- **Amazon PA-API 5.0** — shut down May 15 2026; no new signups. `fetchers/amazon_api.py` is a stub that raises `APIUnavailableError`.
- **Flipkart Affiliate API** — closed to new signups. No public product search API exists.

Both fetchers use Playwright scraping. The `ProductFetcher` abstract base class keeps the interface extensible if APIs become available later.

## Tech Stack

- **Python 3.10+**, asyncio
- **Playwright** — headless Chromium with stealth setup
- **BeautifulSoup4 + lxml** — HTML parsing
- **Pydantic v2** — structured models with field validators
- **pydantic-settings** — env-based config
- **pandas** — CSV export
- **typer** — CLI
- **python-dotenv** — `.env` loading
- **FastAPI + uvicorn** — REST API server
- **httpx** — async HTTP client (Salesforce REST calls)

## Project Structure

```
.
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── requirements.txt               # Flat pin list for Docker — kept in sync with pyproject.toml
├── Dockerfile                     # python:3.12-slim + Playwright Chromium
├── .env.example
├── .env                           # Local secrets — never commit
├── .gitignore
├── src/
│   └── product_scraper/
│       ├── __init__.py
│       ├── __main__.py            # python -m product_scraper entry point
│       ├── models.py              # Price, Product, SearchResult
│       ├── config.py              # Settings (pydantic-settings) incl. Salesforce vars
│       ├── base.py                # Abstract ProductFetcher
│       ├── cache.py               # SHA256-keyed JSON file cache (per-request settings aware)
│       ├── orchestrator.py        # asyncio.gather, shared BrowserContext
│       ├── exporters.py           # export_json, export_csv, export_jsonl
│       ├── cli.py                 # typer CLI
│       ├── api.py                 # FastAPI app — GET /search, GET /health
│       ├── salesforce.py          # SalesforceClient — OAuth + Product__c upsert sync
│       └── fetchers/
│           ├── __init__.py
│           ├── amazon_api.py      # Stub — raises APIUnavailableError
│           ├── amazon_scraper.py  # Playwright scraper for Amazon.in
│           └── flipkart_scraper.py # Playwright scraper for Flipkart.com
└── tests/
    ├── conftest.py
    ├── fixtures/                  # Saved HTML pages for offline tests
    ├── test_models.py
    ├── test_amazon_scraper.py
    ├── test_flipkart_scraper.py
    ├── test_api.py
    ├── test_cache.py
    ├── test_exporters.py
    └── test_orchestrator.py
```

## Output Schema

| Field | Type | Notes |
|---|---|---|
| source | `"amazon"` \| `"flipkart"` | |
| rank | int 1–3 | Position in search results |
| title | str | Full product title |
| brand | str \| null | Extracted from product page |
| model | str \| null | |
| current_price | `{amount, currency}` \| null | |
| original_price | `{amount, currency}` \| null | MRP before discount |
| discount | str \| null | e.g. `"21% off"` |
| rating | float 0–5 \| null | |
| review_count | int \| null | Handles Indian lakh/K format |
| specifications | `dict[str, str]` \| null | From product detail page |
| product_url | str | |
| image_url | str \| null | |
| availability | str \| null | |
| scraped_at | datetime | Auto-stamped |

## Key Implementation Details

### Stealth Browser Context
Both fetchers share one `BrowserContext` created by `Orchestrator`:
- Realistic Chrome 124 user-agent
- 1920×1080 viewport, `en-IN` locale, `Asia/Kolkata` timezone
- `navigator.webdriver` set to `undefined` via init script
- 2.5s delay between requests; exponential backoff on failures (3 retries max)
- CAPTCHA detection: if page title contains "Robot Check" or URL contains "captcha", raise `CaptchaError` immediately — never attempt to bypass
- On Windows, `WindowsProactorEventLoopPolicy` is set at import time in `api.py` so Playwright subprocess works under uvicorn

### Amazon Selectors (current "puis" layout)
- Cards: `[data-component-type='s-search-result']`, skip sponsored
- Title + URL: `[data-cy='title-recipe'] a[href]`
- Price: `.a-price .a-offscreen` (first = current, `.a-text-price .a-offscreen` = original)
- Rating: `i[data-cy='reviews-ratings-slot']`
- Review count: `[data-cy='reviews-block'] a` (handles `2.7L` → 270000, `45K` → 45000)
- Spec table (product page): tries `#productDetails_techSpec_section_1 tr`, `#tech-specs-section tr`, `#technicalSpecifications_section_1 tr`, `table.a-normal.a-spacing-micro tr`
- Availability: `#availability span`
- Brand: `#bylineInfo` (strips "Visit the … Store" and "Brand: " prefix)

### Flipkart Selectors
- Cards: `div[data-id]` (stable attribute, works for both grid and list layouts)
- Title: `a[title]` attribute (DOM text is CSS-truncated; `title` attr has full name)
- Product URL: `a[href*='/p/']`
- Image: `link_tag.select_one("img")["src"]` — skips base64 SVG placeholders
- Price: first text node matching `₹[\d,]+`
- Rating: text node matching `\d\.\d`
- Spec table (product page): `div._3k-BhJ table tr`, `table._14cfVK tr`, `._2TIQom table tr`
- Login modal: dismissed once per fetcher instance using multiple selector fallbacks
- Pin code: fills `560094` if `input[placeholder*='Pincode']` appears

### Price Parsing
Strip `₹`, `Rs`, `INR`, whitespace; replace `,` (thousands separator); **keep `.`** (decimal point):
```python
re.sub(r"[₹₹RsINR\s]", "", text).replace(",", "")
```

### Cache
- Key: `sha256(f"{source}:{query}:{date.today()}")[:16]` — invalidates daily at midnight
- Files written to `CACHE_DIR` (default `.cache/`), one JSON file per `(source, query, date)`
- Both `get_cached` and `set_cache` accept an optional `cache_settings: Settings` parameter
- Fetchers pass `self.settings` explicitly so per-request overrides (e.g. `no_cache=true`) propagate correctly
- The module-level `settings` singleton is only used as a fallback when no explicit settings are passed

### no_cache Flag
When `GET /search?no_cache=true` is received, `api.py` creates a copy of the default settings with `cache_enabled=False` and passes it to `Orchestrator`. This flows through to each fetcher's `get_cached` / `set_cache` calls, ensuring the cache is bypassed for the entire request — both reading and writing.

## REST API

Start the server:
```bash
python -m uvicorn product_scraper.api:app --host 0.0.0.0 --port 8080
```

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check — returns `{"status": "ok"}` |
| `/search?q=<query>` | GET | Search products; optional `&no_cache=true` |
| `/docs` | GET | Swagger UI |

On each `/search` response the API also fires a **background task** that pushes all returned products to the Salesforce `Product__c` object. The HTTP response is returned immediately — Salesforce sync runs independently and never delays or fails the response.

## Salesforce Integration

### Configuration (`.env`)
```
SF_TOKEN_URL=https://<instance>.my.salesforce.com/services/oauth2/token
SF_CLIENT_ID=<connected-app-client-id>
SF_CLIENT_SECRET=<connected-app-client-secret>
SF_API_ENDPOINT=https://<instance>.my.salesforce.com/services/data/v57.0/sobjects/Product__c/
```
Leave all four blank to disable sync entirely. The `salesforce_enabled` property on `Settings` controls whether `SalesforceClient` is instantiated at startup.

### Auth flow
Client credentials grant (`grant_type=client_credentials`). Token is cached in memory and refreshed 60 s before expiry.

### Upsert logic
Each product is synced using Salesforce's **upsert-by-external-ID** endpoint:
```
PATCH …/sobjects/Product__c/Title__c/<url-encoded-title>
```
- `Title__c` must be marked **External ID** in the Salesforce org (`Setup → Object Manager → Product__c → Fields & Relationships → Title__c → Edit → check "External ID"`)
- 201 = record created; 200 or 204 = record updated (no duplicate created)
- Title is trimmed to 200 chars before being used as the external ID key
- `Title__c` is placed in the URL (not the request body); the body contains all other fields

### Field mapping — `Product__c`
| Product field | Salesforce field | Notes |
|---|---|---|
| `title[:200]` | `Title__c` | External ID — used in upsert URL; trimmed to 200 chars |
| `source` | `Source__c` | `"amazon"` or `"flipkart"` |
| `rank` | `Rank__c` | 1–3 |
| `product_url` | `Product_URL__c` | Query string stripped to fit 255-char Text field |
| `brand` | `Brand__c` | |
| `model` | `Model__c` | |
| `current_price.amount` | `Current_Price__c` | Numeric INR amount |
| `original_price.amount` | `Original_Price__c` | |
| `discount` | `Discount__c` | Numeric % extracted from `"21% off"` → `21.0` |
| `rating` | `Rating__c` | |
| `review_count` | `Review_Count__c` | |
| `specifications` | `Specifications__c` | JSON-serialised dict |
| `image_url` | `Image_URL__c` | |
| `availability` | `Availability__c` | |
| `scraped_at` | `Scraped_At__c` | ISO 8601 datetime string |

All custom fields must exist on `Product__c` before triggering a search, or Salesforce will reject the record. Per-product errors are logged as warnings and never surface to the API caller.

## CLI Usage

```bash
# Single query
python -m product_scraper "HP laptop with 16GB RAM"

# Save to file
python -m product_scraper "Sony WH-1000XM5" --output results.json

# CSV output
python -m product_scraper "iPhone 15" --format csv --output results.csv

# Multiple queries from file
python -m product_scraper --queries-file queries.txt --output batch.json

# Bypass cache
python -m product_scraper "Dell XPS 13" --no-cache
```

## Scraping Rules

1. Respect `robots.txt` — never scrape disallowed paths.
2. Never bypass CAPTCHAs, login walls, or anti-bot measures.
3. Rate-limit: ~1 request per 2–3 seconds per site.
4. Do not commit `.env` files or scraped HTML/JSON data.
5. Personal/educational use only — commercial use may violate Terms of Service.
