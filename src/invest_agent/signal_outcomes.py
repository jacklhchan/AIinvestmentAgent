from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from .config import Settings
from .models import PriceBar, Signal, SignalOutcomeRow, SignalSide, utc_now
from .store import Store


DEFAULT_OUTCOME_WINDOWS = (1, 5, 20)
DEFAULT_BENCHMARK_SYMBOLS = ("SPY", "QQQ")
OUTCOME_RULE_VERSION = "signal_outcome_v2_trading_days"


class SignalOutcomeEvaluator:
    """Evaluates saved paper signals against imported quote-history trading bars."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def evaluate(
        self,
        *,
        limit: int = 200,
        windows: tuple[int, ...] = DEFAULT_OUTCOME_WINDOWS,
        benchmark_symbols: tuple[str, ...] = DEFAULT_BENCHMARK_SYMBOLS,
    ) -> dict[str, Any]:
        checked_at = utc_now()
        signals = self.store.list_signals(limit=limit)
        updated_signals = 0
        evaluated_windows = 0
        rows_to_store: list[SignalOutcomeRow] = []
        details: list[dict[str, Any]] = []

        for signal in signals:
            outcomes = dict(signal.outcome_windows or {})
            changed = False
            signal_rows: list[SignalOutcomeRow] = []
            signal_details: dict[str, Any] = {"signal_id": signal.id, "symbol": signal.symbol, "side": signal.side.value, "windows": {}}
            for trading_days in windows:
                key = f"{trading_days}d"
                window_result, row = self._evaluate_window(signal, trading_days, checked_at, benchmark_symbols)
                merged = {**(outcomes.get(key) or {}), **window_result}
                signal_details["windows"][key] = merged
                if merged != outcomes.get(key):
                    outcomes[key] = merged
                    changed = True
                if row:
                    signal_rows.append(row)
                    evaluated_windows += 1
            if changed:
                self.store.update_signal(signal.model_copy(update={"outcome_windows": outcomes}), "signal_outcomes_evaluated")
                updated_signals += 1
            rows_to_store.extend(signal_rows)
            details.append(signal_details)

        self.store.upsert_signal_outcome_rows(rows_to_store)
        summary = self.summary(limit=limit)
        result = {
            "ok": True,
            "checked_at": checked_at.isoformat(),
            "rule_version": OUTCOME_RULE_VERSION,
            "signal_count": len(signals),
            "signals_updated": updated_signals,
            "evaluated_window_count": evaluated_windows,
            "rows_upserted": len(rows_to_store),
            "windows": list(windows),
            "window_type": "trading_days",
            "benchmark_symbols": list(benchmark_symbols),
            "summary": summary,
            "details": details[:50],
        }
        self.store.audit(
            "signal_outcomes_evaluated",
            "signal_outcomes",
            "latest",
            {
                "rule_version": OUTCOME_RULE_VERSION,
                "signal_count": len(signals),
                "signals_updated": updated_signals,
                "evaluated_window_count": evaluated_windows,
                "rows_upserted": len(rows_to_store),
                "windows": list(windows),
                "window_type": "trading_days",
                "benchmark_symbols": list(benchmark_symbols),
                "status_counts": summary.get("status_counts", {}),
            },
        )
        return result

    def summary(self, *, limit: int = 200, signals: list[Signal] | None = None) -> dict[str, Any]:
        signals = signals if signals is not None else self.store.list_signals(limit=limit)
        signal_by_id = {signal.id: signal for signal in signals}
        outcome_rows = [
            row for row in self.store.list_signal_outcome_rows(limit=max(limit * 3, 1000)) if row.signal_id in signal_by_id
        ]
        status_counts = self._json_status_counts(signals, outcome_rows)
        rows = [_row_for_summary(row, signal_by_id.get(row.signal_id)) for row in outcome_rows]
        return {
            "rule_version": OUTCOME_RULE_VERSION,
            "signal_count": len(signals),
            "evaluated_window_count": len(rows),
            "status_counts": dict(status_counts),
            "by_window": _aggregate(rows, "window"),
            "by_side": _aggregate(rows, "side"),
            "by_score_bucket": _aggregate(rows, "score_bucket"),
            "by_readiness_bucket": _aggregate(rows, "readiness_bucket"),
            "by_blocking_reason": _aggregate(rows, "blocking_reason"),
        }

    def _json_status_counts(self, signals: list[Signal], outcome_rows: list[SignalOutcomeRow]) -> Counter[str]:
        status_counts: Counter[str] = Counter()
        row_keys = {(row.signal_id, row.window) for row in outcome_rows}
        for signal in signals:
            for key, window in (signal.outcome_windows or {}).items():
                if (signal.id, key) in row_keys:
                    status_counts["ok"] += 1
                elif isinstance(window, dict):
                    status_counts[str(window.get("status") or "pending")] += 1
        return status_counts

    def _evaluate_window(
        self,
        signal: Signal,
        trading_days: int,
        now: datetime,
        benchmark_symbols: tuple[str, ...],
    ) -> tuple[dict[str, Any], SignalOutcomeRow | None]:
        created_at = _aware(signal.created_at)
        calendar_due_at = created_at + timedelta(days=trading_days)
        base = {
            "status": "pending",
            "window": f"{trading_days}d",
            "window_type": "trading_days",
            "calendar_due_at": calendar_due_at.isoformat(),
            "due_at": calendar_due_at.isoformat(),
            "raw_return_pct": None,
            "directional_return_pct": None,
            "return_pct": None,
        }
        bars = self._bars_for_signal(signal, created_at, trading_days)
        if not bars:
            return {**base, "status": "insufficient_data", "message": "No price bars found for signal symbol."}, None
        entry_index = _first_bar_index_on_or_after(bars, created_at)
        if entry_index is None:
            return {**base, "status": "insufficient_data", "message": "No entry bar available on or after signal time."}, None
        target_index = entry_index + trading_days
        if target_index >= len(bars):
            return {
                **base,
                "status": "insufficient_data",
                "message": f"Need {trading_days} trading bars after entry; only {len(bars) - entry_index - 1} available.",
                "entry_bar_ts": _aware(bars[entry_index].ts).isoformat(),
            }, None

        entry_bar = bars[entry_index]
        target_bar = bars[target_index]
        interval_bars = bars[entry_index : target_index + 1]
        raw_return = _return_pct(entry_bar.close, target_bar.close)
        direction = _direction_multiplier(signal)
        directional_return = round(raw_return * direction, 4)
        benchmark = self._benchmark_return(created_at, trading_days, benchmark_symbols)
        raw_excess = _excess_return(raw_return, benchmark.get("raw_return_pct"))
        directional_excess = round(raw_excess * direction, 4) if raw_excess is not None else None
        hit_direction = directional_return > 0
        excursions = _excursions(entry_bar.close, interval_bars, direction)
        row = SignalOutcomeRow(
            signal_id=signal.id,
            side=signal.side,
            blocked_action=_blocked_action(signal),
            window=f"{trading_days}d",
            window_type="trading_days",
            entry_bar_ts=_aware(entry_bar.ts),
            target_bar_ts=_aware(target_bar.ts),
            raw_return_pct=raw_return,
            directional_return_pct=directional_return,
            raw_excess_return_pct=raw_excess,
            directional_excess_return_pct=directional_excess,
            hit_direction=hit_direction,
            evaluated_at=_aware(now),
            score=signal.score,
            readiness_score=_maybe_float(signal.feature_breakdown.get("advice_readiness_score")),
            blocking_reasons=[str(item) for item in (signal.gates.get("blocking_reasons") or [])],
            **excursions,
        )
        result = {
            **base,
            "status": "ok",
            "rule_version": OUTCOME_RULE_VERSION,
            "entry_price": round(entry_bar.close, 4),
            "entry_bar_ts": row.entry_bar_ts.isoformat(),
            "entry_at": row.entry_bar_ts.isoformat(),
            "target_close": round(target_bar.close, 4),
            "target_bar_ts": row.target_bar_ts.isoformat(),
            "target_at": row.target_bar_ts.isoformat(),
            "raw_return_pct": raw_return,
            "directional_return_pct": directional_return,
            "return_pct": directional_return,
            "benchmark_symbol": benchmark.get("symbol"),
            "benchmark_raw_return_pct": benchmark.get("raw_return_pct"),
            "benchmark_return_pct": benchmark.get("raw_return_pct"),
            "raw_excess_return_pct": raw_excess,
            "directional_excess_return_pct": directional_excess,
            "excess_return_pct": directional_excess,
            "hit_direction": hit_direction,
            "evaluated_at": _aware(now).isoformat(),
            **excursions,
        }
        return result, row

    def _bars_for_signal(self, signal: Signal, created_at: datetime, trading_days: int) -> list[PriceBar]:
        start = (created_at - timedelta(days=5)).isoformat()
        end = (created_at + timedelta(days=trading_days * 4 + 21)).isoformat()
        by_id: dict[str, PriceBar] = {}
        for symbol in _symbol_candidates(signal.symbol):
            for bar in self.store.list_price_bars(symbol=symbol, start=start, end=end, limit=5000, ascending=True):
                by_id[bar.id] = bar
        return sorted(by_id.values(), key=lambda item: _aware(item.ts))

    def _benchmark_return(self, created_at: datetime, trading_days: int, symbols: tuple[str, ...]) -> dict[str, Any]:
        for symbol in symbols:
            bars = self.store.list_price_bars(
                symbol=symbol,
                start=(created_at - timedelta(days=5)).isoformat(),
                end=(created_at + timedelta(days=trading_days * 4 + 21)).isoformat(),
                limit=5000,
                ascending=True,
            )
            entry_index = _first_bar_index_on_or_after(bars, created_at)
            if entry_index is None or entry_index + trading_days >= len(bars):
                continue
            entry_bar = bars[entry_index]
            target_bar = bars[entry_index + trading_days]
            if entry_bar.close > 0:
                return {
                    "symbol": symbol,
                    "entry_bar_ts": _aware(entry_bar.ts).isoformat(),
                    "target_bar_ts": _aware(target_bar.ts).isoformat(),
                    "raw_return_pct": _return_pct(entry_bar.close, target_bar.close),
                }
        return {"symbol": None, "raw_return_pct": None}


def _row_for_summary(row: SignalOutcomeRow, signal: Signal | None) -> dict[str, Any]:
    blocking_reasons = row.blocking_reasons or []
    return {
        "signal_id": row.signal_id,
        "side": row.side.value,
        "window": row.window,
        "directional_return_pct": row.directional_return_pct,
        "directional_excess_return_pct": row.directional_excess_return_pct,
        "hit_direction": row.hit_direction,
        "adverse_excursion_pct": _adverse_excursion(row),
        "score_bucket": _score_bucket(row.score),
        "readiness_bucket": _readiness_bucket(row.readiness_score),
        "blocking_reason": _blocking_bucket(blocking_reasons),
        "signal_status": signal.status.value if signal else None,
    }


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    result: dict[str, Any] = {}
    for group, items in sorted(grouped.items()):
        directional_excess = [item["directional_excess_return_pct"] for item in items if item["directional_excess_return_pct"] is not None]
        adverse = [item["adverse_excursion_pct"] for item in items if item["adverse_excursion_pct"] is not None]
        result[group] = {
            "sample_size": len(items),
            "evaluated_count": len(items),
            "hit_count": sum(1 for item in items if item["hit_direction"]),
            "hit_rate": round(sum(1 for item in items if item["hit_direction"]) / len(items), 4) if items else 0.0,
            "avg_directional_return_pct": round(mean(item["directional_return_pct"] for item in items), 4),
            "avg_directional_excess_return_pct": round(mean(directional_excess), 4) if directional_excess else None,
            "worst_adverse_excursion_pct": round(max(adverse), 4) if adverse else None,
        }
    return result


def _symbol_candidates(symbol: str) -> list[str]:
    normalized = symbol.strip().upper()
    candidates = [normalized]
    if normalized.startswith("US."):
        candidates.append(normalized.split(".", 1)[1])
    elif normalized.startswith("HK."):
        candidates.append(normalized.split(".", 1)[1])
    elif normalized.endswith(".HK"):
        root = normalized.rsplit(".", 1)[0]
        candidates.extend([f"HK.{root}", root])
    elif "." not in normalized:
        candidates.append(f"US.{normalized}")
    return list(dict.fromkeys(item for item in candidates if item))


def _first_bar_index_on_or_after(bars: list[PriceBar], target: datetime) -> int | None:
    target_dt = _aware(target)
    for index, bar in enumerate(sorted(bars, key=lambda item: _aware(item.ts))):
        if _aware(bar.ts) >= target_dt:
            return index
    return None


def _return_pct(entry: float, exit_price: float) -> float:
    return round((exit_price - entry) / entry * 100, 4)


def _excess_return(signal_return: float, benchmark_return: Any) -> float | None:
    benchmark = _maybe_float(benchmark_return)
    return round(signal_return - benchmark, 4) if benchmark is not None else None


def _excursions(entry_price: float, bars: list[PriceBar], direction: int) -> dict[str, float | None]:
    if not bars or entry_price <= 0:
        return {}
    high = max(bar.high for bar in bars)
    low = min(bar.low for bar in bars)
    if direction >= 0:
        return {
            "max_drawdown_pct": round(min(0.0, (low - entry_price) / entry_price * 100), 4),
            "max_favorable_excursion_pct": round(max(0.0, (high - entry_price) / entry_price * 100), 4),
            "max_adverse_upside_pct": None,
            "max_favorable_downside_pct": None,
        }
    return {
        "max_drawdown_pct": None,
        "max_favorable_excursion_pct": None,
        "max_adverse_upside_pct": round(max(0.0, (high - entry_price) / entry_price * 100), 4),
        "max_favorable_downside_pct": round(max(0.0, (entry_price - low) / entry_price * 100), 4),
    }


def _adverse_excursion(row: SignalOutcomeRow) -> float | None:
    if _direction_multiplier_from_side(row.side, row.blocked_action) >= 0:
        drawdown = _maybe_float(row.max_drawdown_pct)
        return abs(drawdown) if drawdown is not None else None
    return _maybe_float(row.max_adverse_upside_pct)


def _direction_multiplier(signal: Signal) -> int:
    return _direction_multiplier_from_side(signal.side, _blocked_action(signal))


def _direction_multiplier_from_side(side: SignalSide, blocked_action: str | None = None) -> int:
    if side == SignalSide.BLOCKED and blocked_action:
        side = SignalSide(blocked_action) if blocked_action in SignalSide._value2member_map_ else side
    if side in {SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL, SignalSide.AVOID}:
        return -1
    return 1


def _blocked_action(signal: Signal) -> str | None:
    return str(signal.gates.get("blocked_action") or "") or None


def _score_bucket(score: int | None) -> str:
    if score is None:
        return "unknown"
    lower = int(score // 10 * 10)
    upper = min(100, lower + 9)
    return f"{lower}-{upper}"


def _readiness_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 50:
        return "0-49"
    if score < 75:
        return "50-74"
    if score < 90:
        return "75-89"
    return "90-100"


def _blocking_bucket(reasons: list[str]) -> str:
    if not reasons:
        return "none"
    reason = reasons[0]
    if ": " in reason:
        return reason.split(": ", 1)[0]
    return reason[:80]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
