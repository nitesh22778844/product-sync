# CLAUDE.md

## Project Overview

A Python-based product information aggregator that searches Amazon.in and Flipkart.com, returning the top 3 results from each (6 total rows) as structured JSON/CSV.

**Primary use case:** Given a query like "HP laptop with 16GB RAM", return 6 rows of comparable product data side-by-side.

## API Status (as of April 2026)

- **Amazon PA-API 5.0** — shutting down May 15 2026; no new signups. `fetchers/amazon_api.py` is a stub that raises `APIUnavailableError`.
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

## Project Structure

```
.
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   └── product_scraper/
│       ├── __init__.py
│       ├── __main__.py            # python -m product_scraper entry point
│       ├── models.py              # Price, Product, SearchResult
│       ├── config.py              # Settings (pydantic-settings)
│       ├── base.py                # Abstract ProductFetcher
│       ├── cache.py               # SHA256-keyed JSON file cache
│       ├── orchestrator.py        # asyncio.gather, shared BrowserContext
│       ├── exporters.py           # export_json, export_csv, export_jsonl
│       ├── cli.py                 # typer CLI
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
    └── test_flipkart_scraper.py
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
Both fetchers share one `BrowserContext`:
- Realistic Chrome 124 user-agent
- 1920×1080 viewport, `en-IN` locale, `Asia/Kolkata` timezone
- `navigator.webdriver` set to `undefined` via init script
- 2.5s delay between requests; exponential backoff on failures (3 retries max)
- CAPTCHA detection: if page title contains "Robot Check" or URL contains "captcha", raise `CaptchaError` immediately — never attempt to bypass

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
Key: `sha256(f"{source}:{query}:{date.today()}")[:16]`. Files written to `CACHE_DIR` (default `.cache/`). Invalidates daily.

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
