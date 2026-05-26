from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .models import (
    BehaviorDiagnostic,
    BehaviorReport,
    BehaviorReportRunRequest,
    BehaviorSeverity,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    TradeFill,
    TradeFillSide,
    TradeImport,
    TradeJournalImportRequest,
    TradeJournalSource,
    TradeRoundTrip,
)
from .run_cards import RunCardService, sha256_file, stable_hash
from .store import Store


TRADE_JOURNAL_IMPORT_RULE_VERSION = "trade_journal_import_v1"
BEHAVIOR_REPORT_RULE_VERSION = "behavior_report_v1"
MAX_IMPORT_BYTES = 10 * 1024 * 1024

GENERIC_ALIASES = {
    "traded_at": ["datetime", "date time", "traded_at", "traded time", "time", "date", "成交時間", "交易時間"],
    "symbol": ["symbol", "code", "ticker", "代碼", "股票代號", "證券代碼", "证券代码"],
    "side": ["side", "direction", "action", "買賣方向", "方向", "买卖方向", "交易方向"],
    "qty": ["quantity", "qty", "shares", "成交數量", "數量", "数量", "股數"],
    "price": ["price", "成交價格", "成交价", "價格", "价格"],
    "fees": ["fee", "fees", "commission", "費用", "手续费", "手續費", "佣金"],
    "currency": ["currency", "ccy", "幣種", "币种"],
    "market": ["market", "市場", "市场"],
    "broker_order_id": ["order id", "order_id", "訂單號", "订单号", "委託編號"],
    "broker_trade_id": ["trade id", "trade_id", "成交號", "成交编号"],
}

FUTU_EXTRA_ALIASES = {
    "traded_at": ["成交日期", "交易日期", "dealt time", "filled time"],
    "symbol": ["股票代码", "证券代码", "code"],
    "side": ["買賣", "买卖", "transaction direction"],
    "qty": ["成交股數", "filled qty", "dealt qty"],
    "price": ["成交均價", "filled price", "dealt price"],
    "fees": ["交易費", "平台費", "佣金及費用"],
}


class TradeJournalService:
    def __init__(self, store: Store):
        self.store = store

    def import_csv(
        self,
        request: TradeJournalImportRequest,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> TradeImport:
        path = _validate_csv_path(request.path)
        file_hash = sha256_file(path)
        existing = self.store.get_trade_import_by_hash(file_hash)
        if existing:
            return existing

        run_card = RunCardService(self.store).start_run(
            RunCardType.TRADE_JOURNAL_IMPORT,
            title=f"Trade Journal Import: {path.name}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=TRADE_JOURNAL_IMPORT_RULE_VERSION,
            inputs={
                "path": str(path),
                "filename": path.name,
                "file_hash": file_hash,
                "source": request.source.value,
                "size_bytes": path.stat().st_size,
            },
            assumptions={
                "accepted_file_types": ["csv"],
                "max_import_bytes": MAX_IMPORT_BYTES,
                "duplicate_policy": "file_hash_idempotent",
            },
        )
        try:
            parsed_fills, warnings = _parse_csv(path, request.source)
            trade_import = TradeImport(
                source=request.source,
                filename=path.name,
                file_hash=file_hash,
                imported_by=RunCardActor(actor),
                row_count=len(parsed_fills),
                parse_warnings=warnings,
                run_card_id=run_card.id,
            )
            fills = [
                fill.model_copy(update={"import_id": trade_import.id})
                for fill in parsed_fills
            ]
            self.store.create_trade_import(trade_import)
            inserted = self.store.add_trade_fills(fills)
            completed = RunCardService(self.store).complete_run(
                run_card.id,
                metrics={
                    "parsed_rows": len(parsed_fills),
                    "inserted_fills": len(inserted),
                    "warning_count": len(warnings),
                },
                warnings=warnings,
                outputs={
                    "trade_import_id": trade_import.id,
                    "row_count": trade_import.row_count,
                    "inserted_fill_count": len(inserted),
                },
                dataset={"normalized_fills": [_fill_dataset_row(fill) for fill in fills]},
            )
            trade_import.run_card_id = completed.id
            return trade_import
        except ValueError as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc))
            raise

    def run_behavior_report(
        self,
        request: BehaviorReportRunRequest | None = None,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> BehaviorReport:
        request = request or BehaviorReportRunRequest()
        fills = _filter_fills(
            self.store.list_trade_fills(limit=100000, ascending=True),
            period_start=request.period_start,
            period_end=request.period_end,
            symbols=request.symbols,
        )
        run_card = RunCardService(self.store).start_run(
            RunCardType.BEHAVIOR_REPORT,
            title="Trade Behavior Report",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=BEHAVIOR_REPORT_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"fills": [_fill_dataset_row(fill) for fill in fills]},
            assumptions={
                "roundtrip_pairing": "fifo",
                "closed_roundtrips_only": True,
                "diagnostics": ["disposition_effect", "overtrading", "chasing_momentum", "anchoring"],
            },
        )
        try:
            roundtrips, warnings = _pair_fifo_roundtrips(fills)
            self.store.replace_trade_roundtrips(roundtrips)
            report = _build_behavior_report(fills, roundtrips, request, run_card.id)
            report = self.store.create_behavior_report(report)
            metrics = {
                "total_trades": report.total_trades,
                "total_roundtrips": report.total_roundtrips,
                "win_rate": report.win_rate,
                "profit_loss_ratio": report.profit_loss_ratio,
                "avg_holding_days": report.avg_holding_days,
                "max_drawdown": report.max_drawdown,
                "total_realized_pnl": report.total_realized_pnl,
            }
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics=metrics,
                warnings=warnings,
                outputs={
                    "behavior_report_id": report.id,
                    "diagnostics": {
                        key: diagnostic.model_dump(mode="json")
                        for key, diagnostic in report.diagnostics.items()
                    },
                },
                dataset={
                    "fills": [_fill_dataset_row(fill) for fill in fills],
                    "roundtrips": [roundtrip.model_dump(mode="json") for roundtrip in roundtrips],
                },
            )
            return report
        except ValueError as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc))
            raise


def _validate_csv_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"trade journal file not found: {raw_path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("trade journal import currently accepts .csv files only")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError(f"trade journal file exceeds {MAX_IMPORT_BYTES} bytes")
    return path


def _parse_csv(path: Path, source: TradeJournalSource) -> tuple[list[TradeFill], list[str]]:
    warnings: list[str] = []
    fills: list[TradeFill] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("trade journal CSV has no header row")
        aliases = _aliases_for_source(source)
        header_map = _header_map(reader.fieldnames, aliases)
        missing = [field for field in ["traded_at", "symbol", "side", "qty", "price"] if field not in header_map]
        if missing:
            raise ValueError(f"trade journal CSV missing required columns: {', '.join(missing)}")
        if "fees" not in header_map:
            warnings.append("fee column missing; fees defaulted to 0")
        for index, row in enumerate(reader, start=1):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                fill = TradeFill(
                    import_id="pending",
                    broker="futu" if source == TradeJournalSource.FUTU_CSV else "generic",
                    broker_order_id=_cell(row, header_map, "broker_order_id") or None,
                    broker_trade_id=_cell(row, header_map, "broker_trade_id") or None,
                    symbol=_normalize_symbol(_cell(row, header_map, "symbol")),
                    broker_symbol=_cell(row, header_map, "symbol") or None,
                    side=_parse_side(_cell(row, header_map, "side")),
                    qty=_parse_number(_cell(row, header_map, "qty")),
                    price=_parse_number(_cell(row, header_map, "price")),
                    fees=_parse_number(_cell(row, header_map, "fees") or "0"),
                    currency=(_cell(row, header_map, "currency") or "USD").strip().upper(),
                    market=(_cell(row, header_map, "market") or "").strip().upper(),
                    traded_at=_parse_datetime(_cell(row, header_map, "traded_at")),
                    raw_row_hash=stable_hash({"source": source.value, "row_index": index, "raw": row}),
                    raw={str(key): value for key, value in row.items()},
                )
                fills.append(fill)
            except ValueError as exc:
                warnings.append(f"row {index} skipped: {exc}")
    if not fills:
        raise ValueError("trade journal CSV did not contain any valid fills")
    return fills, warnings


def _aliases_for_source(source: TradeJournalSource) -> dict[str, list[str]]:
    aliases = {key: list(values) for key, values in GENERIC_ALIASES.items()}
    if source == TradeJournalSource.FUTU_CSV:
        for key, values in FUTU_EXTRA_ALIASES.items():
            aliases.setdefault(key, []).extend(values)
    return aliases


def _header_map(fieldnames: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    normalized = {_normalize_header(name): name for name in fieldnames}
    result: dict[str, str] = {}
    for canonical, names in aliases.items():
        for name in names:
            match = normalized.get(_normalize_header(name))
            if match:
                result[canonical] = match
                break
    return result


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _cell(row: dict[str, str], header_map: dict[str, str], key: str) -> str:
    column = header_map.get(key)
    return str(row.get(column, "")).strip() if column else ""


def _normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if symbol.endswith(".US"):
        return f"US.{symbol[:-3]}"
    return symbol


def _parse_side(value: str) -> TradeFillSide:
    text = value.strip().lower()
    if text in {"buy", "b"} or "買" in value or "买" in value:
        return TradeFillSide.BUY
    if text in {"sell", "s"} or "賣" in value or "卖" in value:
        return TradeFillSide.SELL
    raise ValueError(f"unknown side: {value}")


def _parse_number(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    text = text.replace(",", "").replace("$", "").replace("HK$", "").replace("US$", "")
    text = text.replace("(", "-").replace(")", "")
    try:
        return abs(float(text))
    except ValueError as exc:
        raise ValueError(f"invalid number: {value}") from exc


def _parse_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing traded time")
    normalized = text.replace("/", "-").replace("T", " ")
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%m-%d-%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid traded time: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _filter_fills(
    fills: list[TradeFill],
    *,
    period_start: datetime | None,
    period_end: datetime | None,
    symbols: list[str] | None,
) -> list[TradeFill]:
    wanted = {symbol.upper() for symbol in symbols or []}
    result: list[TradeFill] = []
    for fill in fills:
        if period_start and fill.traded_at < _ensure_tz(period_start):
            continue
        if period_end and fill.traded_at > _ensure_tz(period_end):
            continue
        if wanted and fill.symbol not in wanted:
            continue
        result.append(fill)
    return result


def _ensure_tz(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _pair_fifo_roundtrips(fills: list[TradeFill]) -> tuple[list[TradeRoundTrip], list[str]]:
    lots: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
    roundtrips: list[TradeRoundTrip] = []
    warnings: list[str] = []
    for fill in sorted(fills, key=lambda item: (item.traded_at, item.id)):
        key = (fill.symbol, fill.currency)
        if fill.side == TradeFillSide.BUY:
            lots[key].append(
                {
                    "qty": fill.qty,
                    "original_qty": fill.qty,
                    "price": fill.price,
                    "fees": fill.fees,
                    "traded_at": fill.traded_at,
                    "import_id": fill.import_id,
                }
            )
            continue
        remaining = fill.qty
        sell_original_qty = fill.qty
        while remaining > 1e-9 and lots[key]:
            lot = lots[key][0]
            matched_qty = min(remaining, float(lot["qty"]))
            buy_fee = _allocated_fee(float(lot["fees"]), matched_qty, float(lot["original_qty"]))
            sell_fee = _allocated_fee(fill.fees, matched_qty, sell_original_qty)
            gross_cost = matched_qty * float(lot["price"])
            gross_proceeds = matched_qty * fill.price
            realized = gross_proceeds - sell_fee - gross_cost - buy_fee
            basis = gross_cost + buy_fee
            opened_at = lot["traded_at"]
            holding_days = max(0.0, (fill.traded_at - opened_at).total_seconds() / 86400)
            roundtrips.append(
                TradeRoundTrip(
                    import_id=fill.import_id or lot.get("import_id"),
                    symbol=fill.symbol,
                    opened_at=opened_at,
                    closed_at=fill.traded_at,
                    qty=matched_qty,
                    buy_price=float(lot["price"]),
                    sell_price=fill.price,
                    buy_fees=buy_fee,
                    sell_fees=sell_fee,
                    holding_days=holding_days,
                    realized_pnl=realized,
                    realized_pnl_pct=(realized / basis * 100) if basis else 0.0,
                    currency=fill.currency,
                )
            )
            lot["qty"] = float(lot["qty"]) - matched_qty
            remaining -= matched_qty
            if float(lot["qty"]) <= 1e-9:
                lots[key].popleft()
        if remaining > 1e-9:
            warnings.append(f"unmatched sell skipped for {fill.symbol}: {remaining:g} shares")
    return roundtrips, warnings


def _allocated_fee(total_fee: float, qty: float, original_qty: float) -> float:
    if not total_fee or original_qty <= 0:
        return 0.0
    return total_fee * qty / original_qty


def _build_behavior_report(
    fills: list[TradeFill],
    roundtrips: list[TradeRoundTrip],
    request: BehaviorReportRunRequest,
    run_card_id: str,
) -> BehaviorReport:
    pnl_values = [item.realized_pnl for item in roundtrips]
    winners = [item for item in roundtrips if item.realized_pnl > 0]
    losers = [item for item in roundtrips if item.realized_pnl < 0]
    total_trades = len(fills)
    total_roundtrips = len(roundtrips)
    avg_win = mean([item.realized_pnl for item in winners]) if winners else 0.0
    avg_loss = abs(mean([item.realized_pnl for item in losers])) if losers else 0.0
    span_days = _span_days(fills)
    diagnostics = {
        "disposition_effect": _diagnose_disposition(roundtrips),
        "overtrading": _diagnose_overtrading(fills, roundtrips),
        "chasing_momentum": _diagnose_chasing(fills),
        "anchoring": _diagnose_anchoring(fills),
    }
    return BehaviorReport(
        period_start=request.period_start,
        period_end=request.period_end,
        symbols=sorted({fill.symbol for fill in fills}) if not request.symbols else sorted(request.symbols),
        total_trades=total_trades,
        total_roundtrips=total_roundtrips,
        win_rate=(len(winners) / total_roundtrips) if total_roundtrips else 0.0,
        profit_loss_ratio=_ratio(avg_win, avg_loss),
        avg_holding_days=mean([item.holding_days for item in roundtrips]) if roundtrips else 0.0,
        trade_frequency_per_week=total_trades / max(span_days / 7, 1 / 7) if total_trades else 0.0,
        total_realized_pnl=sum(pnl_values),
        max_drawdown=_max_drawdown(roundtrips),
        top_symbols=dict(Counter(fill.symbol for fill in fills).most_common(8)),
        hourly_distribution=dict(sorted(Counter(f"{fill.traded_at.hour:02d}" for fill in fills).items())),
        market_distribution=dict(Counter(fill.market or "UNKNOWN" for fill in fills)),
        diagnostics=diagnostics,
        run_card_id=run_card_id,
    )


def _span_days(fills: list[TradeFill]) -> float:
    if not fills:
        return 0.0
    times = [fill.traded_at for fill in fills]
    return max(1.0, (max(times) - min(times)).total_seconds() / 86400)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return round(numerator, 4) if numerator else 0.0
    return round(numerator / denominator, 4)


def _max_drawdown(roundtrips: list[TradeRoundTrip]) -> float:
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for item in sorted(roundtrips, key=lambda rt: (rt.closed_at, rt.id)):
        cumulative += item.realized_pnl
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return drawdown


def _diagnose_disposition(roundtrips: list[TradeRoundTrip]) -> BehaviorDiagnostic:
    winners = [item.holding_days for item in roundtrips if item.realized_pnl > 0]
    losers = [item.holding_days for item in roundtrips if item.realized_pnl < 0]
    if not winners or not losers:
        return BehaviorDiagnostic(
            severity=BehaviorSeverity.UNKNOWN,
            summary="Need both winning and losing roundtrips before checking loser holding bias.",
            metrics={"winner_count": len(winners), "loser_count": len(losers)},
        )
    winner_avg = mean(winners)
    loser_avg = mean(losers)
    ratio = loser_avg / max(winner_avg, 0.01)
    severity = BehaviorSeverity.HIGH if ratio > 1.5 else BehaviorSeverity.MEDIUM if ratio >= 1.2 else BehaviorSeverity.LOW
    return BehaviorDiagnostic(
        severity=severity,
        score=round(ratio, 4),
        summary="Compares average loser holding days with winner holding days.",
        metrics={"avg_winner_holding_days": winner_avg, "avg_loser_holding_days": loser_avg, "ratio": ratio},
    )


def _diagnose_overtrading(fills: list[TradeFill], roundtrips: list[TradeRoundTrip]) -> BehaviorDiagnostic:
    trade_counts = Counter(fill.traded_at.date().isoformat() for fill in fills)
    if len(trade_counts) < 3:
        return BehaviorDiagnostic(
            severity=BehaviorSeverity.UNKNOWN,
            summary="Need at least three trading days to compare busy and quiet days.",
            metrics={"trading_days": len(trade_counts)},
        )
    pnl_by_day: dict[str, float] = defaultdict(float)
    for roundtrip in roundtrips:
        pnl_by_day[roundtrip.closed_at.date().isoformat()] += roundtrip.realized_pnl
    sorted_days = sorted(trade_counts, key=lambda day: trade_counts[day])
    bucket_size = max(1, math.ceil(len(sorted_days) * 0.25))
    quiet_days = sorted_days[:bucket_size]
    busy_days = sorted_days[-bucket_size:]
    busy_pnl = mean([pnl_by_day.get(day, 0.0) for day in busy_days])
    quiet_pnl = mean([pnl_by_day.get(day, 0.0) for day in quiet_days])
    if busy_pnl < quiet_pnl and busy_pnl < 0:
        severity = BehaviorSeverity.HIGH
    elif busy_pnl < quiet_pnl:
        severity = BehaviorSeverity.MEDIUM
    else:
        severity = BehaviorSeverity.LOW
    return BehaviorDiagnostic(
        severity=severity,
        score=round(quiet_pnl - busy_pnl, 4),
        summary="Compares realized PnL on highest-trade-count days with quiet days.",
        metrics={
            "busy_days": busy_days,
            "quiet_days": quiet_days,
            "busy_day_avg_pnl": busy_pnl,
            "quiet_day_avg_pnl": quiet_pnl,
        },
    )


def _diagnose_chasing(fills: list[TradeFill]) -> BehaviorDiagnostic:
    by_symbol: dict[str, list[TradeFill]] = defaultdict(list)
    evaluated = 0
    chasing = 0
    for fill in sorted(fills, key=lambda item: (item.traded_at, item.id)):
        history = by_symbol[fill.symbol]
        if fill.side == TradeFillSide.BUY and len(history) >= 3:
            reference = history[-3].price
            if reference > 0:
                evaluated += 1
                if (fill.price - reference) / reference > 0.03:
                    chasing += 1
        history.append(fill)
    ratio = chasing / evaluated if evaluated else 0.0
    severity = BehaviorSeverity.HIGH if ratio >= 0.5 else BehaviorSeverity.MEDIUM if ratio >= 0.25 else BehaviorSeverity.LOW
    if not evaluated:
        severity = BehaviorSeverity.UNKNOWN
    return BehaviorDiagnostic(
        severity=severity,
        score=round(ratio, 4),
        summary="Flags buys after the trader's own recent same-symbol trade prices have already run up.",
        metrics={"evaluated_buys": evaluated, "chase_buys": chasing, "chase_ratio": ratio},
    )


def _diagnose_anchoring(fills: list[TradeFill]) -> BehaviorDiagnostic:
    anchored_symbols: dict[str, float] = {}
    for symbol, prices in _prices_by_symbol(fills).items():
        if len(prices) < 5:
            continue
        avg_price = mean(prices)
        cv = pstdev(prices) / avg_price if avg_price else 0.0
        if cv < 0.05:
            anchored_symbols[symbol] = cv
    severity = BehaviorSeverity.HIGH if anchored_symbols else BehaviorSeverity.LOW
    return BehaviorDiagnostic(
        severity=severity,
        score=len(anchored_symbols),
        summary="Flags repeated trades clustered in a narrow same-symbol price band.",
        metrics={"anchored_symbols": anchored_symbols},
    )


def _prices_by_symbol(fills: list[TradeFill]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = defaultdict(list)
    for fill in fills:
        result[fill.symbol].append(fill.price)
    return result


def _fill_dataset_row(fill: TradeFill) -> dict[str, Any]:
    return {
        "raw_row_hash": fill.raw_row_hash,
        "symbol": fill.symbol,
        "side": fill.side.value,
        "qty": fill.qty,
        "price": fill.price,
        "fees": fill.fees,
        "currency": fill.currency,
        "market": fill.market,
        "traded_at": fill.traded_at.isoformat(),
    }
