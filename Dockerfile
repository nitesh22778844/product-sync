FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e . --no-deps \
    && playwright install --with-deps chromium

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "uvicorn product_scraper.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
