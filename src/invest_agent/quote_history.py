from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    PriceBar,
    QuoteHistoryImport,
    QuoteHistoryRefreshRequest,
    QuoteHistorySource,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
)
from .run_cards import RunCardService, sha256_bytes, sha256_file, stable_hash
from .store import Store


QUOTE_HISTORY_RULE_VERSION = "quote_history_import_v1"


class QuoteHistoryService:
    def __init__(self, store: Store):
        self.store = store

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

