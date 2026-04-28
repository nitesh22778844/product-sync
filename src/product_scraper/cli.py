from __future__ import annotations

import asyncio
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

app = typer.Typer(name="product-scraper", help="Search Amazon.in and Flipkart.com for products.")


class OutputFormat(str, Enum):
    json = "json"
    csv = "csv"


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s  %(name)s  %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


@app.command()
def search(
    query: Annotated[Optional[str], typer.Argument(help="Product search query")] = None,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Write output to this file")
    ] = None,
    format: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format")
    ] = OutputFormat.json,
    queries_file: Annotated[
        Optional[Path],
        typer.Option("--queries-file", help="File with one query per line (batch mode)"),
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache for this run")] = False,
) -> None:
    if query is None and queries_file is None:
        raise typer.BadParameter("Provide a QUERY argument or --queries-file.")
    if query is not None and queries_file is not None:
        raise typer.BadParameter("Provide either a QUERY or --queries-file, not both.")

    _setup_logging()

    from product_scraper.config import settings
    from product_scraper.exporters import export_csv, export_json, export_jsonl
    from product_scraper.orchestrator import Orchestrator

    if no_cache:
        settings.cache_enabled = False

    orchestrator = Orchestrator(settings)

    if query:
        result = asyncio.run(orchestrator.run(query))
        if format == OutputFormat.json:
            text = export_json(result, output)
        else:
            text = export_csv(result, output)
        if not output:
            print(text)
    else:
        assert queries_file is not None
        queries = [
            line.strip()
            for line in queries_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        results = asyncio.run(orchestrator.run_batch(queries))
        if output:
            if format == OutputFormat.json:
                export_jsonl(results, output)
            else:
                import pandas as pd
                from product_scraper.exporters import export_csv as _csv
                # Concatenate all CSV rows into one file
                all_rows = "\n".join(
                    _csv(r).split("\n", 1)[1] for r in results  # strip header from 2nd+
                )
                header = _csv(results[0]).split("\n", 1)[0] if results else ""
                output.write_text(header + "\n" + all_rows, encoding="utf-8")
        else:
            for r in results:
                if format == OutputFormat.json:
                    print(export_json(r))
                else:
                    print(export_csv(r))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
