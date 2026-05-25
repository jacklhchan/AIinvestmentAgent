from __future__ import annotations

from .ir_feeds import IrFeedIngestor
from .models import NewsIngestResult
from .sec_edgar import SecEdgarIngestor


def combine_news_results(*results: NewsIngestResult) -> NewsIngestResult:
    symbols: list[str] = []
    sources: dict[str, int] = {}
    errors: list[str] = []
    items = []
    total_count = 0
    stored_count = 0

    for result in results:
        for symbol in result.symbols:
            if symbol not in symbols:
                symbols.append(symbol)
        total_count += result.total_count
        stored_count += result.stored_count
        errors.extend(result.errors)
        items.extend(result.items)
        for source, count in result.sources.items():
            sources[source] = sources.get(source, 0) + count

    return NewsIngestResult(
        symbols=symbols,
        total_count=total_count,
        stored_count=stored_count,
        sources=sources,
        errors=errors,
        items=items,
    )


def refresh_primary_sources(
    sec_ingestor: SecEdgarIngestor,
    ir_ingestor: IrFeedIngestor,
    *,
    symbols: list[str] | None = None,
    include_sec: bool = True,
    include_ir: bool = True,
    forms: list[str] | None = None,
    max_filings: int | None = None,
    max_symbols: int | None = None,
) -> NewsIngestResult:
    results: list[NewsIngestResult] = []
    if include_sec:
        results.append(
            sec_ingestor.refresh_filings(
                symbols=symbols,
                forms=forms,
                max_filings=max_filings,
                max_symbols=max_symbols,
            )
        )
    if include_ir:
        results.append(ir_ingestor.refresh_ir_feeds())
    return combine_news_results(*results)
