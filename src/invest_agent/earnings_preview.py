from __future__ import annotations

from .models import (
    CatalystEventType,
    CatalystStatus,
    EarningsPreview,
    EarningsPreviewRunRequest,
    OptionsSnapshot,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


EARNINGS_PREVIEW_RULE_VERSION = "earnings_preview_v1"


class EarningsPreviewService:
    def __init__(self, store: Store):
        self.store = store

    def run_preview(
        self,
        request: EarningsPreviewRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> EarningsPreview:
        catalyst = self._resolve_catalyst(request.symbol, request.catalyst_id)
        fundamentals = self.store.get_fundamentals(request.symbol)
        options = self._latest_options(request.symbol)
        implied_move_pct = request.implied_move_pct
        if implied_move_pct is None and options:
            implied_move_pct = options.implied_move_pct
        dataset = {
            "request": request.model_dump(mode="json"),
            "catalyst": catalyst.model_dump(mode="json") if catalyst else None,
            "fundamentals": fundamentals.model_dump(mode="json") if fundamentals else None,
            "options": options.model_dump(mode="json") if options else None,
        }
        run_card = RunCardService(self.store).start_run(
            RunCardType.EARNINGS_PREVIEW,
            title=f"Earnings Preview: {request.symbol}",
            symbol=request.symbol,
            actor=actor,
            trigger_source=trigger_source,
            rule_version=EARNINGS_PREVIEW_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset=dataset,
            assumptions={"preview_cannot_create_proposal": True, "uses_local_sources_only": True},
            links={"thesis_id": request.thesis_id, "catalyst_id": catalyst.id if catalyst else None},
        )
        key_metrics = _key_metrics(fundamentals)
        source_summary = _source_summary(request.symbol, fundamentals, catalyst, options)
        preview = EarningsPreview(
            symbol=request.symbol,
            catalyst_id=catalyst.id if catalyst else None,
            thesis_id=request.thesis_id or (catalyst.linked_thesis_id if catalyst else None),
            period=request.period or _period(fundamentals),
            earnings_date=catalyst.event_date if catalyst else None,
            source_summary=source_summary,
            key_metrics=key_metrics,
            bull_case={"watch": "growth acceleration, margin resilience, and constructive guidance"},
            base_case={"watch": "results broadly match recent trend and no thesis-breaking surprise"},
            bear_case={"watch": "revenue deceleration, cash-flow deterioration, or guidance reset"},
            implied_move_pct=implied_move_pct,
            what_to_watch=_watch_list(key_metrics, implied_move_pct),
            evidence_hash=stable_hash(dataset),
            run_card_id=run_card.id,
        )
        stored = self.store.create_earnings_preview(preview)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"key_metric_count": len(key_metrics), "has_catalyst": bool(catalyst), "has_implied_move": implied_move_pct is not None},
            warnings=[] if catalyst else ["No upcoming earnings catalyst found; preview is symbol-level context only."],
            outputs={"earnings_preview_id": stored.id, "symbol": stored.symbol, "what_to_watch": stored.what_to_watch},
            dataset=dataset,
            evidence_hash=stored.evidence_hash,
            links={"thesis_id": stored.thesis_id, "catalyst_id": stored.catalyst_id},
        )
        return stored

    def _resolve_catalyst(self, symbol: str, catalyst_id: str | None):
        if catalyst_id:
            catalyst = self.store.get_catalyst(catalyst_id)
            if not catalyst:
                raise ValueError(f"catalyst not found: {catalyst_id}")
            if catalyst.symbol and catalyst.symbol != symbol:
                raise ValueError(f"catalyst symbol {catalyst.symbol} does not match preview symbol {symbol}")
            return catalyst
        for catalyst in self.store.list_catalysts(status=CatalystStatus.UPCOMING, symbol=symbol, limit=20):
            if catalyst.event_type == CatalystEventType.EARNINGS:
                return catalyst
        return None

    def _latest_options(self, symbol: str) -> OptionsSnapshot | None:
        snapshots = self.store.list_options_snapshots(symbol=symbol, limit=1)
        return snapshots[0] if snapshots else None


def _key_metrics(fundamentals) -> dict[str, dict[str, object]]:
    if not fundamentals:
        return {}
    result: dict[str, dict[str, object]] = {}
    for name in ["revenue", "net_income", "operating_income", "operating_cash_flow", "eps_diluted"]:
        metric = fundamentals.metrics.get(name)
        if metric:
            result[name] = {
                "value": metric.value,
                "unit": metric.unit,
                "fiscal_year": metric.fiscal_year,
                "fiscal_period": metric.fiscal_period,
                "yoy_change_pct": metric.yoy_change_pct,
                "filed_at": metric.filed_at.isoformat() if metric.filed_at else None,
            }
    return result


def _period(fundamentals) -> str:
    if not fundamentals:
        return "unknown"
    metric = next(iter(fundamentals.metrics.values()), None)
    if not metric:
        return "unknown"
    return f"{metric.fiscal_year or 'FY'} {metric.fiscal_period or ''}".strip()


def _source_summary(symbol: str, fundamentals, catalyst, options) -> str:
    pieces = [f"{symbol} earnings preview from local research artifacts."]
    if catalyst:
        pieces.append(f"Catalyst: {catalyst.title} at {catalyst.event_date.isoformat()}.")
    if fundamentals:
        pieces.append(f"SEC companyfacts snapshot CIK {fundamentals.cik}.")
    if options and options.implied_move_pct is not None:
        pieces.append(f"Options implied move {options.implied_move_pct:.2f}%.")
    return " ".join(pieces)


def _watch_list(key_metrics: dict[str, dict[str, object]], implied_move_pct: float | None) -> list[str]:
    items = [
        "Revenue growth versus recent companyfacts trend.",
        "Operating cash flow quality versus net income.",
        "Management guidance tone and thesis delta after the print.",
    ]
    if implied_move_pct is not None:
        items.append(f"Compare realized move with options-implied move of {implied_move_pct:.2f}%.")
    if not key_metrics:
        items.append("Refresh SEC companyfacts before relying on preview metrics.")
    return items

