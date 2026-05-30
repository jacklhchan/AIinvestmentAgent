from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from .config import Settings
from .models import PriceBar, Signal, SignalSide, utc_now
from .store import Store


DEFAULT_OUTCOME_WINDOWS = (1, 5, 20)
DEFAULT_BENCHMARK_SYMBOLS = ("SPY", "QQQ")


class SignalOutcomeEvaluator:
    """Evaluates saved paper signals against imported quote-history bars."""

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
        details: list[dict[str, Any]] = []

        for signal in signals:
            outcomes = dict(signal.outcome_windows or {})
            changed = False
            signal_details: dict[str, Any] = {"signal_id": signal.id, "symbol": signal.symbol, "side": signal.side.value, "windows": {}}
            for days in windows:
                key = f"{days}d"
                window_result = self._evaluate_window(signal, days, checked_at, benchmark_symbols)
                merged = {**(outcomes.get(key) or {}), **window_result}
                signal_details["windows"][key] = merged
                if merged != outcomes.get(key):
                    outcomes[key] = merged
                    changed = True
                if merged.get("status") == "ok":
                    evaluated_windows += 1
            if changed:
                self.store.update_signal(signal.model_copy(update={"outcome_windows": outcomes}), "signal_outcomes_evaluated")
                updated_signals += 1
            details.append(signal_details)

        summary = self.summary(limit=limit, signals=self.store.list_signals(limit=limit))
        result = {
            "ok": True,
            "checked_at": checked_at.isoformat(),
            "signal_count": len(signals),
            "signals_updated": updated_signals,
            "evaluated_window_count": evaluated_windows,
            "windows": list(windows),
            "benchmark_symbols": list(benchmark_symbols),
            "summary": summary,
            "details": details[:50],
        }
        self.store.audit(
            "signal_outcomes_evaluated",
            "signal_outcomes",
            "latest",
            {
                "signal_count": len(signals),
                "signals_updated": updated_signals,
                "evaluated_window_count": evaluated_windows,
                "windows": list(windows),
                "benchmark_symbols": list(benchmark_symbols),
                "status_counts": summary.get("status_counts", {}),
            },
        )
        return result

    def summary(self, *, limit: int = 200, signals: list[Signal] | None = None) -> dict[str, Any]:
        signals = signals if signals is not None else self.store.list_signals(limit=limit)
        rows: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        for signal in signals:
            for key, window in (signal.outcome_windows or {}).items():
                if not isinstance(window, dict):
                    continue
                status = str(window.get("status") or ("pending" if window.get("return_pct") is None else "ok"))
                status_counts[status] += 1
                if status != "ok":
                    continue
                rows.append(
                    {
                        "signal_id": signal.id,
                        "symbol": signal.symbol,
                        "side": signal.side.value,
                        "window": key,
                        "return_pct": float(window.get("return_pct") or 0.0),
                        "excess_return_pct": _maybe_float(window.get("excess_return_pct")),
                        "max_drawdown_pct": _maybe_float(window.get("max_drawdown_pct")),
                        "hit_direction": bool(window.get("hit_direction")),
                    }
                )
        return {
            "signal_count": len(signals),
            "evaluated_window_count": len(rows),
            "status_counts": dict(status_counts),
            "by_window": _aggregate(rows, "window"),
            "by_side": _aggregate(rows, "side"),
        }

    def _evaluate_window(
        self,
        signal: Signal,
        days: int,
        now: datetime,
        benchmark_symbols: tuple[str, ...],
    ) -> dict[str, Any]:
        created_at = _aware(signal.created_at)
        due_at = created_at + timedelta(days=days)
        base = {"status": "pending", "due_at": due_at.isoformat(), "return_pct": None}
        if _aware(now) < due_at:
            return base
        entry_price = signal.signal_price or signal.suggested_limit_price
        if not entry_price or entry_price <= 0:
            return {**base, "status": "missing_entry_price", "message": "Signal has no entry price snapshot."}
        bars = self._bars_for_signal(signal, created_at, due_at)
        if not bars:
            return {**base, "status": "insufficient_data", "message": "No price bars found for signal symbol."}
        target_bar = _first_bar_on_or_after(bars, due_at)
        if not target_bar:
            return {**base, "status": "insufficient_data", "message": "No price bar available at or after due date."}
        interval_bars = _bars_between_dates(bars, created_at, target_bar.ts)
        return_pct = _return_pct(entry_price, target_bar.close)
        benchmark = self._benchmark_return(created_at, due_at, benchmark_symbols)
        hit_direction = _hit_direction(signal, return_pct)
        result = {
            **base,
            "status": "ok",
            "entry_price": round(entry_price, 4),
            "entry_at": created_at.isoformat(),
            "target_close": round(target_bar.close, 4),
            "target_at": _aware(target_bar.ts).isoformat(),
            "return_pct": return_pct,
            "benchmark_symbol": benchmark.get("symbol"),
            "benchmark_return_pct": benchmark.get("return_pct"),
            "excess_return_pct": _excess_return(return_pct, benchmark.get("return_pct")),
            "max_drawdown_pct": _max_drawdown_pct(entry_price, interval_bars),
            "hit_direction": hit_direction,
            "evaluated_at": _aware(now).isoformat(),
        }
        return result

    def _bars_for_signal(self, signal: Signal, created_at: datetime, due_at: datetime) -> list[PriceBar]:
        start = (created_at - timedelta(days=2)).isoformat()
        end = (due_at + timedelta(days=10)).isoformat()
        by_id: dict[str, PriceBar] = {}
        for symbol in _symbol_candidates(signal.symbol):
            for bar in self.store.list_price_bars(symbol=symbol, start=start, end=end, limit=2000, ascending=True):
                by_id[bar.id] = bar
        return sorted(by_id.values(), key=lambda item: _aware(item.ts))

    def _benchmark_return(self, created_at: datetime, due_at: datetime, symbols: tuple[str, ...]) -> dict[str, Any]:
        for symbol in symbols:
            bars = self.store.list_price_bars(
                symbol=symbol,
                start=(created_at - timedelta(days=2)).isoformat(),
                end=(due_at + timedelta(days=10)).isoformat(),
                limit=2000,
                ascending=True,
            )
            entry_bar = _first_bar_on_or_after(bars, created_at)
            target_bar = _first_bar_on_or_after(bars, due_at)
            if entry_bar and target_bar and entry_bar.close > 0:
                return {"symbol": symbol, "return_pct": _return_pct(entry_bar.close, target_bar.close)}
        return {"symbol": None, "return_pct": None}


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    result: dict[str, Any] = {}
    for group, items in grouped.items():
        excess = [item["excess_return_pct"] for item in items if item["excess_return_pct"] is not None]
        drawdowns = [item["max_drawdown_pct"] for item in items if item["max_drawdown_pct"] is not None]
        result[group] = {
            "evaluated_count": len(items),
            "hit_count": sum(1 for item in items if item["hit_direction"]),
            "hit_rate": round(sum(1 for item in items if item["hit_direction"]) / len(items), 4) if items else 0.0,
            "avg_return_pct": round(mean(item["return_pct"] for item in items), 4),
            "avg_excess_return_pct": round(mean(excess), 4) if excess else None,
            "worst_drawdown_pct": round(min(drawdowns), 4) if drawdowns else None,
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


def _first_bar_on_or_after(bars: list[PriceBar], target: datetime) -> PriceBar | None:
    target_date = _aware(target).date()
    for bar in sorted(bars, key=lambda item: _aware(item.ts)):
        if _aware(bar.ts).date() >= target_date:
            return bar
    return None


def _bars_between_dates(bars: list[PriceBar], start: datetime, end: datetime) -> list[PriceBar]:
    start_date = _aware(start).date()
    end_date = _aware(end).date()
    return [bar for bar in bars if start_date <= _aware(bar.ts).date() <= end_date]


def _return_pct(entry: float, exit_price: float) -> float:
    return round((exit_price - entry) / entry * 100, 4)


def _excess_return(signal_return: float, benchmark_return: Any) -> float | None:
    benchmark = _maybe_float(benchmark_return)
    return round(signal_return - benchmark, 4) if benchmark is not None else None


def _max_drawdown_pct(entry_price: float, bars: list[PriceBar]) -> float | None:
    if not bars or entry_price <= 0:
        return None
    return round(min((bar.low - entry_price) / entry_price * 100 for bar in bars), 4)


def _hit_direction(signal: Signal, return_pct: float) -> bool | None:
    side = signal.side
    blocked_action = str(signal.gates.get("blocked_action") or "")
    if side == SignalSide.BLOCKED and blocked_action:
        side = SignalSide(blocked_action) if blocked_action in SignalSide._value2member_map_ else side
    if side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL}:
        return return_pct > 0
    if side in {SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL, SignalSide.AVOID}:
        return return_pct < 0
    return None


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
