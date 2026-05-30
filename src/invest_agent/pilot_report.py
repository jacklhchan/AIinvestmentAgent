from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean
from typing import Any

from .models import utc_now
from .store import Store


class PilotReportService:
    def __init__(self, store: Store):
        self.store = store

    def weekly_summary(self, *, days: int = 7) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, days))
        signals = [signal for signal in self.store.list_signals(limit=5000) if signal.created_at >= since]
        advice_runs = [run for run in self.store.list_paper_advice_runs(limit=1000) if run.created_at >= since]
        advice_items = [item for run in advice_runs for item in run.items]
        outcome_rows = [
            row for row in self.store.list_signal_outcome_rows(limit=10000) if row.evaluated_at >= since
        ]
        blocked_reasons = Counter()
        for item in advice_items:
            for reason in [*item.vetoes, *item.missing_evidence, *(item.gates or {}).get("blocking_reasons", [])]:
                blocked_reasons[_bucket_reason(str(reason))] += 1
        by_side = _outcome_by_side(outcome_rows)
        veto_effectiveness = self._committee_veto_effectiveness(outcome_rows)
        return {
            "ok": True,
            "period_days": days,
            "since": since.isoformat(),
            "generated_at": utc_now().isoformat(),
            "signal_count": len(signals),
            "paper_advice_count": len(advice_items),
            "paper_advice_run_count": len(advice_runs),
            "promotable_count": sum(1 for item in advice_items if item.promotable),
            "blocked_by_reason": [{"reason": reason, "count": count} for reason, count in blocked_reasons.most_common(12)],
            "outcome_row_count": len(outcome_rows),
            "hit_rate_by_side": {
                side: metrics["hit_rate"] for side, metrics in by_side.items()
            },
            "avg_directional_excess_return_by_side": {
                side: metrics["avg_directional_excess_return_pct"] for side, metrics in by_side.items()
            },
            "outcomes_by_side": by_side,
            "committee_veto_effectiveness": veto_effectiveness,
        }

    def _committee_veto_effectiveness(self, outcome_rows) -> dict[str, Any]:
        signal_ids = {row.signal_id for row in outcome_rows}
        vetoed_rows = []
        non_vetoed_rows = []
        for row in outcome_rows:
            runs = self.store.list_investor_committee_runs(signal_id=row.signal_id, limit=1)
            if runs and runs[0].vetoes:
                vetoed_rows.append(row)
            else:
                non_vetoed_rows.append(row)
        return {
            "signals_with_outcomes": len(signal_ids),
            "vetoed_window_count": len(vetoed_rows),
            "non_vetoed_window_count": len(non_vetoed_rows),
            "vetoed_hit_rate": _hit_rate(vetoed_rows),
            "non_vetoed_hit_rate": _hit_rate(non_vetoed_rows),
            "vetoed_avg_directional_return_pct": _avg(row.directional_return_pct for row in vetoed_rows),
            "non_vetoed_avg_directional_return_pct": _avg(row.directional_return_pct for row in non_vetoed_rows),
        }


def _outcome_by_side(rows) -> dict[str, dict[str, Any]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.side.value].append(row)
    return {
        side: {
            "sample_size": len(items),
            "hit_rate": _hit_rate(items),
            "avg_directional_return_pct": _avg(row.directional_return_pct for row in items),
            "avg_directional_excess_return_pct": _avg(
                row.directional_excess_return_pct for row in items if row.directional_excess_return_pct is not None
            ),
            "worst_adverse_excursion_pct": _worst_adverse(items),
        }
        for side, items in sorted(grouped.items())
    }


def _hit_rate(rows) -> float | None:
    rows = list(rows)
    return round(sum(1 for row in rows if row.hit_direction) / len(rows), 4) if rows else None


def _avg(values) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return round(mean(numbers), 4) if numbers else None


def _worst_adverse(rows) -> float | None:
    values = []
    for row in rows:
        if row.max_adverse_upside_pct is not None:
            values.append(row.max_adverse_upside_pct)
        elif row.max_drawdown_pct is not None:
            values.append(abs(row.max_drawdown_pct))
    return round(max(values), 4) if values else None


def _bucket_reason(reason: str) -> str:
    lowered = reason.lower()
    if "evidence" in lowered:
        return "evidence"
    if "committee" in lowered or "veto" in lowered:
        return "committee"
    if "quote" in lowered:
        return "quote"
    if "catalyst" in lowered or "earnings" in lowered:
        return "catalyst"
    if "notional" in lowered or "quantity" in lowered or "sizing" in lowered:
        return "sizing"
    if "readiness" in lowered:
        return "readiness"
    return reason[:80] or "unknown"
