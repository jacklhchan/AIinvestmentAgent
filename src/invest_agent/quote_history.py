from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .futu_adapter import FutuIntegrationError, fetch_futu_history_kline
from .market_news import external_ticker, resolve_market_context_symbols, resolve_watchlist_symbols
from .market_data_router import MarketDataProviderError, MarketDataRouter, latest_completed_bar
from .models import (
    PriceBar,
    QuoteHistoryBatchRefreshRequest,
    QuoteHistoryImport,
    QuoteHistoryRefreshRequest,
    QuoteHistorySource,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    utc_now,
)
from .run_cards import RunCardService, sha256_bytes, sha256_file, stable_hash
from .store import Store


QUOTE_HISTORY_RULE_VERSION = "quote_history_import_v1"
FUTU_HISTORY_BATCH_PAUSE_EVERY = 55
FUTU_HISTORY_BATCH_PAUSE_SECONDS = 31.0


class QuoteHistoryService:
    def __init__(self, store: Store, settings: Settings | None = None):
        self.store = store
        self.settings = settings or get_settings()

    def refresh(
        self,
        request: QuoteHistoryRefreshRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> QuoteHistoryImport:
        if request.path:
            return self.import_csv(
                request.path,
                symbol=request.symbol,
                ktype=request.ktype,
                autype=request.autype,
                actor=actor,
            )
        source = (request.source or "auto").strip().lower()
        if source not in {"auto", "futu"}:
            return self.refresh_provider_history(
                request.symbol,
                source=source,
                days=request.days,
                ktype=request.ktype,
                autype=request.autype,
                actor=actor,
            )
        try:
            if source == "futu" or self.settings.futu_read_enabled:
                return self.refresh_provider_history(
                    request.symbol,
                    source="futu",
                    days=request.days,
                    ktype=request.ktype,
                    autype=request.autype,
                    actor=actor,
                )
        except (FutuIntegrationError, MarketDataProviderError, ValueError):
            if request.path:
                raise
        quote = self.store.get_quote(request.symbol)
        if not quote:
            raise ValueError("quote history refresh without path requires a cached quote")
        today = quote.updated_at.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = []
        for day in range(min(request.days, 5)):
            ts = today - timedelta(days=day)
            rows.append(
                {
                    "ts": ts,
                    "open": quote.previous_close or quote.last_price,
                    "high": max(quote.last_price, quote.previous_close or quote.last_price),
                    "low": min(quote.last_price, quote.previous_close or quote.last_price),
                    "close": quote.last_price,
                    "volume": 0.0,
                    "raw": {"source": "cached_quote_fallback"},
                }
            )
        return self._store_rows(
            request.symbol,
            rows,
            source=QuoteHistorySource.FUTURE_IMPORT,
            input_hash=stable_hash({"symbol": request.symbol, "quote": quote.model_dump(mode="json")}),
            ktype=request.ktype,
            autype=request.autype,
            actor=actor,
        )

    def refresh_futu_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        ktype: str = "K_DAY",
        autype: str = "qfq",
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> QuoteHistoryImport:
        broker_symbol, rows = fetch_futu_history_kline(
            self.settings,
            symbol,
            days=days,
            ktype=ktype,
            autype=autype,
        )
        return self._store_rows(
            external_ticker(symbol),
            rows,
            source=QuoteHistorySource.FUTU_HISTORY_KLINE,
            input_hash=stable_hash(
                {
                    "source": "futu_history_kline",
                    "symbol": symbol,
                    "broker_symbol": broker_symbol,
                    "days": days,
                    "ktype": ktype,
                    "autype": autype,
                }
            ),
            ktype=ktype,
            autype=autype,
            actor=actor,
            broker_symbol=broker_symbol,
            source_provider="futu",
            source_feed="request_history_kline",
            adjusted=autype.lower() != "none",
            quality_score=0.95,
            license_note="Futu OpenD read-only historical K-line; paper-only local use.",
        )

    def refresh_provider_history(
        self,
        symbol: str,
        *,
        source: str = "auto",
        days: int = 365,
        ktype: str = "K_DAY",
        autype: str = "qfq",
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> QuoteHistoryImport:
        result = MarketDataRouter(self.settings, self.store).fetch_history(
            symbol,
            source=source,
            days=days,
            ktype=ktype,
            autype=autype,
        )
        return self._store_rows(
            external_ticker(symbol),
            result.rows,
            source=result.source,
            input_hash=stable_hash(
                {
                    "source": result.source.value,
                    "symbol": symbol,
                    "broker_symbol": result.broker_symbol,
                    "days": days,
                    "ktype": ktype,
                    "autype": autype,
                    "provider": result.provider,
                    "source_feed": result.source_feed,
                }
            ),
            ktype=ktype,
            autype=autype,
            actor=actor,
            broker_symbol=result.broker_symbol,
            source_provider=result.provider,
            source_feed=result.source_feed,
            adjusted=result.adjusted,
            retrieved_at=result.retrieved_at,
            quality_score=result.quality_score,
            license_note=result.license_note,
        )

    def refresh_batch(
        self,
        request: QuoteHistoryBatchRefreshRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> dict[str, Any]:
        symbols = self.resolve_batch_symbols(request.symbols)
        imports: list[QuoteHistoryImport] = []
        errors: list[dict[str, str]] = []
        skips: list[dict[str, str]] = []
        futu_attempts = 0
        for symbol in symbols:
            try:
                existing = latest_completed_bar(self.store, symbol)
                if existing:
                    skips.append(
                        {
                            "symbol": symbol,
                            "reason": "latest completed trading-day bar already present",
                            "latest_ts": existing.ts.isoformat(),
                            "source_provider": existing.source_provider,
                        }
                    )
                    continue
                source = request.source.lower()
                if source == "futu":
                    if (
                        futu_attempts
                        and FUTU_HISTORY_BATCH_PAUSE_EVERY > 0
                        and futu_attempts % FUTU_HISTORY_BATCH_PAUSE_EVERY == 0
                        and FUTU_HISTORY_BATCH_PAUSE_SECONDS > 0
                    ):
                        time.sleep(FUTU_HISTORY_BATCH_PAUSE_SECONDS)
                    futu_attempts += 1
                if source in {"auto", "futu", "alpaca", "stooq", "fmp", "twelvedata", "alphavantage", "yfinance_dev"}:
                    imports.append(
                        self.refresh_provider_history(
                            symbol,
                            source=source,
                            days=request.days,
                            ktype=request.ktype,
                            autype=request.autype,
                            actor=actor,
                        )
                    )
                else:
                    imports.append(
                        self.refresh(
                            QuoteHistoryRefreshRequest(
                                symbol=symbol,
                                days=request.days,
                                ktype=request.ktype,
                                autype=request.autype,
                            ),
                            actor=actor,
                        )
                    )
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
        result = {
            "ok": not errors,
            "source": request.source,
            "requested_symbols": request.symbols,
            "symbols": symbols,
            "import_count": len(imports),
            "error_count": len(errors),
            "skip_count": len(skips),
            "imports": [item.model_dump(mode="json") for item in imports],
            "errors": errors,
            "skips": skips,
        }
        self.store.audit(
            "quote_history_batch_refreshed",
            "quote_history_import",
            "batch",
            {
                "source": request.source,
                "symbol_count": len(symbols),
                "import_count": len(imports),
                "error_count": len(errors),
                "skip_count": len(skips),
                "symbols": symbols[:50],
                "errors": errors[:12],
                "skips": skips[:12],
            },
        )
        return result

    def resolve_batch_symbols(self, value: list[str] | str) -> list[str]:
        tokens = _split_symbol_tokens(value)
        symbols: list[str] = []
        if not tokens:
            tokens = ["watchlist", "positions", "benchmarks"]
        latest_run = self.store.get_latest_signal_run()
        recent_signal_symbols = [signal.symbol for signal in latest_run.signals] if latest_run else []
        for token in tokens:
            normalized = token.lower()
            if normalized in {"watchlist", "watchlists"}:
                symbols.extend(resolve_watchlist_symbols(self.settings, self.store, None))
            elif normalized in {"position", "positions", "holdings"}:
                symbols.extend(position.symbol for position in self.store.get_portfolio().positions)
            elif normalized in {"recent", "recent_signals", "signals", "signal_symbols"}:
                symbols.extend(recent_signal_symbols)
            elif normalized in {"benchmark", "benchmarks"}:
                symbols.extend(["SPY", "QQQ", *resolve_market_context_symbols(self.settings, self.store)])
            elif normalized in {"market_context", "market-context", "etfs"}:
                symbols.extend(resolve_market_context_symbols(self.settings, self.store))
            elif normalized == "all":
                symbols.extend(resolve_watchlist_symbols(self.settings, self.store, None))
                symbols.extend(position.symbol for position in self.store.get_portfolio().positions)
                symbols.extend(recent_signal_symbols)
                symbols.extend(["SPY", "QQQ", *resolve_market_context_symbols(self.settings, self.store)])
            else:
                symbols.append(token)
        return _dedupe_symbols(external_ticker(symbol) for symbol in symbols)

    def import_csv(
        self,
        path: str | Path,
        *,
        symbol: str,
        ktype: str = "K_DAY",
        autype: str = "qfq",
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> QuoteHistoryImport:
        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"quote history file not found: {file_path}")
        rows = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                rows.append(_parse_bar_row(raw))
        return self._store_rows(
            symbol,
            rows,
            source=QuoteHistorySource.MANUAL_CSV,
            input_hash=sha256_file(file_path),
            ktype=ktype,
            autype=autype,
            actor=actor,
        )

    def summary(self, symbol: str | None = None) -> dict[str, Any]:
        imports = self.store.list_quote_history_imports(symbol=symbol, limit=20)
        bars = self.store.list_price_bars(symbol=symbol, limit=100000)
        return {
            "symbol": symbol.upper() if symbol else None,
            "import_count": len(imports),
            "bar_count": len(bars),
            "symbols": sorted({bar.symbol for bar in bars}),
            "latest_bar": bars[-1].model_dump(mode="json") if bars else None,
        }

    def find_daily_close(self, symbol: str, target: datetime):
        bars = self.store.list_price_bars(symbol=symbol, limit=100000, ascending=True)
        if not bars:
            return None, None
        target_date = target.date()
        exact = [bar for bar in bars if bar.ts.date() == target_date]
        if exact:
            return exact[0], "exact_bar"
        after = [bar for bar in bars if bar.ts.date() > target_date]
        if after:
            return after[0], "next_available_bar"
        before = [bar for bar in bars if bar.ts.date() < target_date]
        if before:
            return before[-1], "previous_available_bar"
        return None, None

    def _store_rows(
        self,
        symbol: str,
        rows: list[dict[str, Any]],
        *,
        source: QuoteHistorySource,
        input_hash: str,
        ktype: str,
        autype: str,
        actor: RunCardActor | str,
        broker_symbol: str | None = None,
        source_provider: str | None = None,
        source_feed: str = "",
        adjusted: bool | None = None,
        retrieved_at: datetime | None = None,
        quality_score: float | None = None,
        license_note: str = "",
    ) -> QuoteHistoryImport:
        symbol = symbol.upper()
        if not rows:
            raise ValueError("quote history import has no rows")
        dataset_hash = stable_hash({"symbol": symbol, "rows": rows, "ktype": ktype, "autype": autype})
        run_card = RunCardService(self.store).start_run(
            RunCardType.QUOTE_HISTORY_IMPORT,
            title=f"Quote History Import: {symbol}",
            symbol=symbol,
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=QUOTE_HISTORY_RULE_VERSION,
            inputs={"symbol": symbol, "source": source.value, "ktype": ktype, "autype": autype},
            dataset={"dataset_hash": dataset_hash, "row_count": len(rows)},
            assumptions={
                "daily_close_is_diagnostic_not_executable": True,
                "no_dividends_splits_fx_tax_or_liquidity_model": True,
                "creates_proposals": False,
            },
        )
        import_item = QuoteHistoryImport(
            source=source,
            symbol=symbol,
            broker_symbol=broker_symbol,
            start_date=min(row["ts"] for row in rows),
            end_date=max(row["ts"] for row in rows),
            ktype=ktype,
            autype=autype,
            row_count=len(rows),
            input_hash=input_hash,
            dataset_hash=dataset_hash,
            run_card_id=run_card.id,
        )
        bars = [
            PriceBar(
                import_id=import_item.id,
                symbol=symbol,
                broker_symbol=broker_symbol,
                ts=row["ts"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                turnover=row.get("turnover"),
                ktype=ktype,
                autype=autype,
                source=source,
                source_provider=source_provider or source.value,
                source_feed=source_feed,
                adjusted=bool(adjusted),
                retrieved_at=retrieved_at or utc_now(),
                quality_score=quality_score if quality_score is not None else 0.5,
                license_note=license_note,
                raw=row.get("raw", {}),
                row_hash=_row_hash(symbol, row, ktype, autype),
            )
            for row in sorted(rows, key=lambda item: item["ts"])
        ]
        stored = self.store.create_quote_history_import(import_item, bars)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"row_count": len(bars)},
            warnings=[],
            outputs={"quote_history_import_id": stored.id, "symbol": symbol, "dataset_hash": dataset_hash},
            dataset={"bars": [bar.model_dump(mode="json") for bar in bars]},
        )
        return stored


def _parse_bar_row(row: dict[str, str]) -> dict[str, Any]:
    ts_value = row.get("ts") or row.get("date") or row.get("datetime") or row.get("time")
    if not ts_value:
        raise ValueError("quote history row missing ts/date/datetime")
    ts = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
    if not ts.tzinfo:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "ts": ts,
        "open": float(row.get("open") or row.get("Open") or row.get("close") or 0),
        "high": float(row.get("high") or row.get("High") or row.get("close") or 0),
        "low": float(row.get("low") or row.get("Low") or row.get("close") or 0),
        "close": float(row.get("close") or row.get("Close") or row.get("last") or 0),
        "volume": float(row.get("volume") or row.get("Volume") or 0),
        "turnover": float(row["turnover"]) if row.get("turnover") else None,
        "raw": dict(row),
    }


def _row_hash(symbol: str, row: dict[str, Any], ktype: str, autype: str) -> str:
    return sha256_bytes(
        stable_hash(
            {
                "symbol": symbol,
                "ts": row["ts"].isoformat(),
                "close": row["close"],
                "ktype": ktype,
                "autype": autype,
            }
        ).encode("utf-8")
    )


def _split_symbol_tokens(value: list[str] | str) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    result: list[str] = []
    for item in value:
        result.extend(part.strip() for part in str(item).split(",") if part.strip())
    return result


def _dedupe_symbols(symbols) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        normalized = str(symbol or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
