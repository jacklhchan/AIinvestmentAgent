from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from .models import (
    BehaviorReport,
    CatalystEventType,
    CatalystExpectedImpact,
    CatalystStatus,
    CatalystThesisDelta,
    CreatedVia,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ShadowEvent,
    ShadowEventType,
    PriceBarConfidence,
    ShadowReport,
    ShadowReportRunRequest,
    ShadowRule,
    ShadowRuleType,
    ShadowStrategy,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    ShadowStrategyStatus,
    TradeFill,
    TradeFillSide,
    TradeRoundTrip,
)
from .quote_history import QuoteHistoryService
from .run_cards import RunCardService, stable_hash
from .store import Store


SHADOW_STRATEGY_RULE_VERSION = "shadow_strategy_v1"
SHADOW_REPORT_RULE_VERSION = "shadow_report_v1"


class ShadowAccountService:
    def __init__(self, store: Store):
        self.store = store

    def extract_strategy(
        self,
        request: ShadowStrategyExtractRequest,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> ShadowStrategy:
        behavior_report = self._require_behavior_report(request.behavior_report_id)
        fills = _filter_fills(
            self.store.list_trade_fills(limit=100000, ascending=True),
            period_start=behavior_report.period_start,
            period_end=behavior_report.period_end,
            symbols=behavior_report.symbols,
        )
        roundtrips = _filter_roundtrips(
            self.store.list_trade_roundtrips(limit=100000),
            period_start=behavior_report.period_start,
            period_end=behavior_report.period_end,
            symbols=behavior_report.symbols,
        )
        run_card = RunCardService(self.store).start_run(
            RunCardType.SHADOW_STRATEGY_EXTRACT,
            title="Shadow Strategy Extraction",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=SHADOW_STRATEGY_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={
                "behavior_report": behavior_report.model_dump(mode="json"),
                "fills": [_fill_dataset_row(fill) for fill in fills],
                "roundtrips": [_roundtrip_dataset_row(roundtrip) for roundtrip in roundtrips],
            },
            assumptions={
                "strategy_status": "draft_until_human_confirmed",
                "extraction": "deterministic_journal_internal",
                "live_execution": False,
            },
        )
        try:
            rules = _extract_rules(fills, roundtrips)
            strategy = ShadowStrategy(
                name=request.name or f"Shadow rules from {behavior_report.id}",
                description=request.description
                or "Deterministic approximation of observed trading behavior. Research-only; not a trading signal.",
                source_behavior_report_id=behavior_report.id,
                created_via=_actor_to_created_via(actor),
                human_confirmed=False,
                status=ShadowStrategyStatus.DRAFT,
                run_card_id=run_card.id,
                rules=rules,
            )
            strategy.rules = [rule.model_copy(update={"strategy_id": strategy.id}) for rule in strategy.rules]
            strategy = self.store.create_shadow_strategy(strategy)
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics={
                    "rule_count": len(strategy.rules),
                    "roundtrip_count": len(roundtrips),
                    "fill_count": len(fills),
                },
                warnings=[],
                outputs={
                    "strategy_id": strategy.id,
                    "status": strategy.status.value,
                    "rule_types": [rule.rule_type.value for rule in strategy.rules],
                },
                dataset={
                    "rules": [rule.model_dump(mode="json") for rule in strategy.rules],
                    "behavior_report": behavior_report.model_dump(mode="json"),
                },
            )
            return strategy
        except ValueError as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc))
            raise

    def confirm_strategy(
        self,
        strategy_id: str,
        request: ShadowStrategyConfirmRequest | None = None,
    ) -> ShadowStrategy:
        request = request or ShadowStrategyConfirmRequest()
        strategy = self._require_strategy(strategy_id)
        strategy.human_confirmed = request.human_confirmed
        strategy.confirmed_by = request.confirmed_by if request.human_confirmed else None
        strategy.confirmed_at = _utc_now() if request.human_confirmed else None
        strategy.status = ShadowStrategyStatus.ACTIVE if request.human_confirmed else ShadowStrategyStatus.DRAFT
        strategy.updated_at = _utc_now()
        return self.store.update_shadow_strategy(strategy, event_type="shadow_strategy_confirmed")

    def run_report(
        self,
        request: ShadowReportRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> ShadowReport:
        strategy = self._require_strategy(request.strategy_id)
        if strategy.status != ShadowStrategyStatus.ACTIVE or not strategy.human_confirmed:
            raise ValueError("shadow strategy must be human-confirmed and active before running a shadow report")
        behavior_report = self._require_behavior_report(request.behavior_report_id or strategy.source_behavior_report_id)
        period_start = request.period_start or behavior_report.period_start
        period_end = request.period_end or behavior_report.period_end
        symbols = request.symbols or behavior_report.symbols
        fills = _filter_fills(
            self.store.list_trade_fills(limit=100000, ascending=True),
            period_start=period_start,
            period_end=period_end,
            symbols=symbols,
        )
        roundtrips = _filter_roundtrips(
            self.store.list_trade_roundtrips(limit=100000),
            period_start=period_start,
            period_end=period_end,
            symbols=symbols,
        )
        run_card = RunCardService(self.store).start_run(
            RunCardType.SHADOW_REPORT,
            title="Shadow Account Counterfactual Report",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=SHADOW_REPORT_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={
                "strategy": strategy.model_dump(mode="json"),
                "behavior_report": behavior_report.model_dump(mode="json"),
                "roundtrips": [_roundtrip_dataset_row(roundtrip) for roundtrip in roundtrips],
            },
            assumptions={
                "counterfactual_scope": "journal_internal",
                "quote_history_required_for_pnl": True,
                "creates_proposals": False,
            },
        )
        try:
            events, diagnostics, warnings = self._evaluate_strategy(
                strategy,
                fills,
                roundtrips,
                use_quote_history=request.use_quote_history,
            )
            priced_events = [event for event in events if event.delta_pnl is not None]
            unpriced_counterfactual_events = [
                event
                for event in events
                if event.event_type in {ShadowEventType.EARLY_EXIT, ShadowEventType.LATE_EXIT}
                and event.delta_pnl is None
            ]
            total_delta_pnl = round(sum(event.delta_pnl or 0.0 for event in priced_events), 4) if priced_events else None
            report = ShadowReport(
                strategy_id=strategy.id,
                behavior_report_id=behavior_report.id,
                period_start=period_start,
                period_end=period_end,
                total_evaluated_trades=len(roundtrips),
                rule_violation_count=len(events),
                early_exit_count=sum(1 for event in events if event.event_type == ShadowEventType.EARLY_EXIT),
                late_exit_count=sum(1 for event in events if event.event_type == ShadowEventType.LATE_EXIT),
                missed_signal_count=sum(1 for event in events if event.event_type == ShadowEventType.MISSED_ENTRY),
                counterfactual_pnl=round(sum(event.counterfactual_pnl or 0.0 for event in priced_events), 4)
                if priced_events
                else None,
                actual_pnl=sum(roundtrip.realized_pnl for roundtrip in roundtrips),
                delta_pnl=total_delta_pnl,
                counterfactual_coverage_ratio=round(
                    len(priced_events) / max(1, len(priced_events) + len(unpriced_counterfactual_events)),
                    4,
                )
                if request.use_quote_history
                else 0.0,
                events_with_price_count=len(priced_events),
                events_without_price_count=len(unpriced_counterfactual_events),
                total_delta_pnl=total_delta_pnl,
                price_dataset_hash=diagnostics.get("price_dataset_hash", ""),
                diagnostics=diagnostics,
                run_card_id=run_card.id,
            )
            events = [event.model_copy(update={"shadow_report_id": report.id}) for event in events]
            report = self.store.create_shadow_report(report, events)
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics={
                    "total_evaluated_trades": report.total_evaluated_trades,
                    "rule_violation_count": report.rule_violation_count,
                    "early_exit_count": report.early_exit_count,
                    "late_exit_count": report.late_exit_count,
                    "thesis_mismatch_count": diagnostics.get("thesis_mismatch_count", 0),
                    "ignored_catalyst_count": diagnostics.get("ignored_catalyst_count", 0),
                    "actual_pnl": report.actual_pnl,
                    "counterfactual_coverage_ratio": report.counterfactual_coverage_ratio,
                    "events_with_price_count": report.events_with_price_count,
                    "events_without_price_count": report.events_without_price_count,
                },
                warnings=warnings,
                outputs={
                    "shadow_report_id": report.id,
                    "strategy_id": strategy.id,
                    "counterfactual_pnl": report.counterfactual_pnl,
                    "delta_pnl": report.delta_pnl,
                },
                dataset={
                    "events": [event.model_dump(mode="json") for event in events],
                    "roundtrips": [_roundtrip_dataset_row(roundtrip) for roundtrip in roundtrips],
                    "price_dataset_hash": report.price_dataset_hash,
                },
            )
            return report
        except ValueError as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc))
            raise

    def _require_behavior_report(self, report_id: str) -> BehaviorReport:
        report = self.store.get_behavior_report(report_id)
        if not report:
            raise ValueError(f"behavior report not found: {report_id}")
        return report

    def _require_strategy(self, strategy_id: str) -> ShadowStrategy:
        strategy = self.store.get_shadow_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"shadow strategy not found: {strategy_id}")
        return strategy

    def _evaluate_strategy(
        self,
        strategy: ShadowStrategy,
        fills: list[TradeFill],
        roundtrips: list[TradeRoundTrip],
        *,
        use_quote_history: bool = False,
    ) -> tuple[list[ShadowEvent], dict[str, Any], list[str]]:
        rules = {rule.rule_type: rule for rule in strategy.rules}
        events: list[ShadowEvent] = []
        warnings = ["open positions, short sales, splits, dividends, FX conversion, and option assignment are outside shadow_report_v1 scope."]
        if not use_quote_history:
            warnings.insert(
                0,
                "counterfactual_pnl is unavailable because quote history was not requested; only journal-internal violations are counted.",
            )
        holding_days = float(rules.get(ShadowRuleType.EXIT, ShadowRule(rule_type=ShadowRuleType.EXIT)).condition_json.get("median_holding_days", 0) or 0)
        take_profit_pct = float(
            rules.get(ShadowRuleType.TAKE_PROFIT, ShadowRule(rule_type=ShadowRuleType.TAKE_PROFIT)).condition_json.get(
                "median_winner_pnl_pct",
                0,
            )
            or 0
        )
        stop_loss_pct = float(
            rules.get(ShadowRuleType.STOP_LOSS, ShadowRule(rule_type=ShadowRuleType.STOP_LOSS)).condition_json.get(
                "median_loser_pnl_pct",
                0,
            )
            or 0
        )
        sizing_notional = float(
            rules.get(ShadowRuleType.SIZING, ShadowRule(rule_type=ShadowRuleType.SIZING)).condition_json.get(
                "median_entry_notional",
                0,
            )
            or 0
        )

        for roundtrip in sorted(roundtrips, key=lambda item: (item.opened_at, item.id)):
            if holding_days and roundtrip.realized_pnl > 0 and roundtrip.holding_days < holding_days * 0.6:
                event = _shadow_event(
                    roundtrip,
                    ShadowEventType.EARLY_EXIT,
                    expected={"minimum_holding_days": holding_days},
                    actual={"holding_days": roundtrip.holding_days, "realized_pnl_pct": roundtrip.realized_pnl_pct},
                    explanation="Closed a winning roundtrip materially earlier than the extracted holding rule.",
                )
                if use_quote_history:
                    _attach_counterfactual_price(event, roundtrip, holding_days, "early_exit_daily_close", self.store)
                events.append(event)
            if holding_days and roundtrip.realized_pnl < 0 and roundtrip.holding_days > holding_days * 1.5:
                event = _shadow_event(
                    roundtrip,
                    ShadowEventType.LATE_EXIT,
                    expected={"maximum_loser_holding_days": holding_days * 1.5},
                    actual={"holding_days": roundtrip.holding_days, "realized_pnl_pct": roundtrip.realized_pnl_pct},
                    explanation="Held a losing roundtrip materially longer than the extracted holding rule.",
                )
                if use_quote_history:
                    _attach_counterfactual_price(event, roundtrip, holding_days, "late_exit_daily_close", self.store)
                events.append(event)
            if take_profit_pct and roundtrip.realized_pnl_pct > 0 and roundtrip.realized_pnl_pct < take_profit_pct * 0.5:
                events.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.RULE_VIOLATION,
                        expected={"take_profit_reference_pct": take_profit_pct},
                        actual={"realized_pnl_pct": roundtrip.realized_pnl_pct},
                        explanation="Winning exit captured far less than the extracted take-profit reference.",
                    )
                )
            if stop_loss_pct and roundtrip.realized_pnl_pct < stop_loss_pct * 1.5:
                events.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.RULE_VIOLATION,
                        expected={"stop_loss_reference_pct": stop_loss_pct},
                        actual={"realized_pnl_pct": roundtrip.realized_pnl_pct},
                        explanation="Loss exceeded the extracted stop-loss reference.",
                    )
                )
            if sizing_notional and roundtrip.qty * roundtrip.buy_price > sizing_notional * 1.5:
                events.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.OVERSIZED_TRADE,
                        expected={"median_entry_notional": sizing_notional},
                        actual={"entry_notional": roundtrip.qty * roundtrip.buy_price},
                        explanation="Entry notional was materially larger than the extracted sizing rule.",
                    )
                )
            if not self.store.get_active_thesis_for_symbol(roundtrip.symbol):
                events.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.THESIS_MISMATCH,
                        expected={"required": "active_human_confirmed_thesis"},
                        actual={"symbol": roundtrip.symbol},
                        explanation="Roundtrip symbol did not have an active human-confirmed thesis at report time.",
                    )
                )
            events.extend(self._catalyst_events(roundtrip))
            events.extend(self._earnings_events(roundtrip))

        diagnostics = {
            "event_count_by_type": dict(Counter(event.event_type.value for event in events)),
            "symbol_count": dict(Counter(event.symbol for event in events)),
            "thesis_mismatch_count": sum(1 for event in events if event.event_type == ShadowEventType.THESIS_MISMATCH),
            "ignored_catalyst_count": sum(1 for event in events if event.event_type == ShadowEventType.IGNORED_CATALYST),
            "missing_quote_history": use_quote_history and not any(event.price_bar_id for event in events),
            "counterfactual_pnl_available": any(event.delta_pnl is not None for event in events),
            "price_dataset_hash": stable_hash(
                [
                    item.model_dump(mode="json")
                    for symbol in sorted({roundtrip.symbol for roundtrip in roundtrips})
                    for item in self.store.list_quote_history_imports(symbol=symbol, limit=10)
                ]
            )
            if use_quote_history
            else "",
        }
        return events, diagnostics, warnings

    def _catalyst_events(self, roundtrip: TradeRoundTrip) -> list[ShadowEvent]:
        result: list[ShadowEvent] = []
        catalysts = [
            *self.store.list_catalysts(symbol=roundtrip.symbol, limit=100),
            *[
                catalyst
                for catalyst in self.store.list_catalysts(limit=100)
                if catalyst.symbol is None and catalyst.event_type == CatalystEventType.MACRO
            ],
        ]
        for catalyst in catalysts:
            if catalyst.expected_impact != CatalystExpectedImpact.HIGH:
                continue
            opened_at = _ensure_tz(roundtrip.opened_at)
            event_date = _ensure_tz(catalyst.event_date)
            if catalyst.status == CatalystStatus.UPCOMING and timedelta(0) <= event_date - opened_at <= timedelta(hours=48):
                result.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.IGNORED_CATALYST,
                        expected={"avoid_new_entry_before_high_impact_catalyst": catalyst.id},
                        actual={"opened_at": opened_at.isoformat(), "event_date": event_date.isoformat()},
                        explanation=f"Opened exposure within 48 hours before high-impact catalyst {catalyst.title}.",
                    )
                )
            if catalyst.status == CatalystStatus.COMPLETED and opened_at >= event_date:
                if not self.store.list_catalyst_reviews(catalyst.id):
                    result.append(
                        _shadow_event(
                            roundtrip,
                            ShadowEventType.POST_EVENT_REVIEW_MISSING,
                            expected={"post_event_review_required": catalyst.id},
                            actual={"opened_at": opened_at.isoformat(), "event_date": event_date.isoformat()},
                            explanation=f"Opened exposure after completed catalyst {catalyst.title} before a review was recorded.",
                        )
                    )
        return result

    def _earnings_events(self, roundtrip: TradeRoundTrip) -> list[ShadowEvent]:
        result: list[ShadowEvent] = []
        for review in self.store.list_earnings_reviews(symbol=roundtrip.symbol, limit=5):
            if _ensure_tz(review.created_at) > _ensure_tz(roundtrip.opened_at):
                continue
            if review.thesis_delta in {CatalystThesisDelta.WEAKENS, CatalystThesisDelta.INVALIDATES}:
                result.append(
                    _shadow_event(
                        roundtrip,
                        ShadowEventType.CONTRADICTED_EARNINGS_REVIEW,
                        expected={"avoid_adding_after_weakening_earnings_review": review.id},
                        actual={"thesis_delta": review.thesis_delta.value, "opened_at": roundtrip.opened_at.isoformat()},
                        explanation="Roundtrip opened after an earnings review weakened or invalidated the thesis.",
                    )
                )
        return result


def _extract_rules(fills: list[TradeFill], roundtrips: list[TradeRoundTrip]) -> list[ShadowRule]:
    rules: list[ShadowRule] = []
    holding_days = [roundtrip.holding_days for roundtrip in roundtrips]
    if holding_days:
        rules.append(
            ShadowRule(
                rule_type=ShadowRuleType.EXIT,
                condition_json={"median_holding_days": round(float(median(holding_days)), 4)},
                action_json={"action": "hold_until_reference_window_unless_thesis_breaks"},
                confidence=_confidence(len(holding_days)),
                support_count=len(holding_days),
            )
        )
    winners = [roundtrip.realized_pnl_pct for roundtrip in roundtrips if roundtrip.realized_pnl_pct > 0]
    if winners:
        rules.append(
            ShadowRule(
                rule_type=ShadowRuleType.TAKE_PROFIT,
                condition_json={"median_winner_pnl_pct": round(float(median(winners)), 4)},
                action_json={"action": "take_profit_reference"},
                confidence=_confidence(len(winners)),
                support_count=len(winners),
            )
        )
    losers = [roundtrip.realized_pnl_pct for roundtrip in roundtrips if roundtrip.realized_pnl_pct < 0]
    if losers:
        rules.append(
            ShadowRule(
                rule_type=ShadowRuleType.STOP_LOSS,
                condition_json={"median_loser_pnl_pct": round(float(median(losers)), 4)},
                action_json={"action": "stop_loss_reference"},
                confidence=_confidence(len(losers)),
                support_count=len(losers),
            )
        )
    buy_fills = [fill for fill in fills if fill.side == TradeFillSide.BUY]
    notionals = [fill.qty * fill.price for fill in buy_fills]
    if notionals:
        rules.append(
            ShadowRule(
                rule_type=ShadowRuleType.SIZING,
                condition_json={"median_entry_notional": round(float(median(notionals)), 4)},
                action_json={"action": "size_near_observed_median"},
                confidence=_confidence(len(notionals)),
                support_count=len(notionals),
            )
        )
    gaps = _same_symbol_entry_gaps(buy_fills)
    if gaps:
        rules.append(
            ShadowRule(
                rule_type=ShadowRuleType.COOLDOWN,
                condition_json={"median_same_symbol_reentry_gap_days": round(float(median(gaps)), 4)},
                action_json={"action": "wait_before_same_symbol_reentry"},
                confidence=_confidence(len(gaps)),
                support_count=len(gaps),
            )
        )
    rules.append(
        ShadowRule(
            rule_type=ShadowRuleType.THESIS,
            condition_json={"requires_active_human_confirmed_thesis": True},
            action_json={"action": "flag_thesis_mismatch"},
            confidence=1.0,
            support_count=len(roundtrips),
        )
    )
    rules.append(
        ShadowRule(
            rule_type=ShadowRuleType.CATALYST,
            condition_json={"avoid_new_entry_before_high_impact_catalyst_hours": 48},
            action_json={"action": "flag_ignored_catalyst"},
            confidence=1.0,
            support_count=len(roundtrips),
        )
    )
    return rules


def _same_symbol_entry_gaps(fills: list[TradeFill]) -> list[float]:
    by_symbol: dict[str, list[TradeFill]] = defaultdict(list)
    for fill in sorted(fills, key=lambda item: (item.traded_at, item.id)):
        by_symbol[fill.symbol].append(fill)
    gaps: list[float] = []
    for entries in by_symbol.values():
        for previous, current in zip(entries, entries[1:]):
            gaps.append(max(0.0, (_ensure_tz(current.traded_at) - _ensure_tz(previous.traded_at)).total_seconds() / 86400))
    return gaps


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
        if period_start and _ensure_tz(fill.traded_at) < _ensure_tz(period_start):
            continue
        if period_end and _ensure_tz(fill.traded_at) > _ensure_tz(period_end):
            continue
        if wanted and fill.symbol not in wanted:
            continue
        result.append(fill)
    return result


def _filter_roundtrips(
    roundtrips: list[TradeRoundTrip],
    *,
    period_start: datetime | None,
    period_end: datetime | None,
    symbols: list[str] | None,
) -> list[TradeRoundTrip]:
    wanted = {symbol.upper() for symbol in symbols or []}
    result: list[TradeRoundTrip] = []
    for roundtrip in roundtrips:
        if period_start and _ensure_tz(roundtrip.closed_at) < _ensure_tz(period_start):
            continue
        if period_end and _ensure_tz(roundtrip.closed_at) > _ensure_tz(period_end):
            continue
        if wanted and roundtrip.symbol not in wanted:
            continue
        result.append(roundtrip)
    return sorted(result, key=lambda item: (item.closed_at, item.id))


def _shadow_event(
    roundtrip: TradeRoundTrip,
    event_type: ShadowEventType,
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
    explanation: str,
) -> ShadowEvent:
    return ShadowEvent(
        shadow_report_id="pending",
        symbol=roundtrip.symbol,
        event_type=event_type,
        actual_fill_ids=[],
        roundtrip_id=roundtrip.id,
        expected_action=expected,
        actual_action=actual,
        pnl_impact=None,
        explanation=explanation,
    )


def _attach_counterfactual_price(
    event: ShadowEvent,
    roundtrip: TradeRoundTrip,
    holding_days: float,
    method: str,
    store: Store,
) -> None:
    expected_exit_at = _ensure_tz(roundtrip.opened_at) + timedelta(days=max(1.0, holding_days))
    bar, confidence = QuoteHistoryService(store).find_daily_close(roundtrip.symbol, expected_exit_at)
    event.expected_exit_at = expected_exit_at
    event.actual_exit_price = roundtrip.sell_price
    event.actual_pnl = round(roundtrip.realized_pnl, 4)
    event.counterfactual_method = method
    if not bar or not confidence:
        event.expected_exit_price_confidence = PriceBarConfidence.UNAVAILABLE
        return
    event.expected_exit_price = bar.close
    event.expected_exit_price_source = "daily_close"
    event.expected_exit_price_confidence = PriceBarConfidence(confidence)
    event.price_bar_id = bar.id
    event.counterfactual_pnl = round((bar.close - roundtrip.buy_price) * roundtrip.qty - roundtrip.buy_fees - roundtrip.sell_fees, 4)
    event.delta_pnl = round(event.counterfactual_pnl - roundtrip.realized_pnl, 4)
    event.pnl_impact = event.delta_pnl


def _actor_to_created_via(actor: RunCardActor | str) -> CreatedVia:
    value = RunCardActor(actor)
    if value == RunCardActor.CLI:
        return CreatedVia.CLI
    if value == RunCardActor.DASHBOARD:
        return CreatedVia.DASHBOARD
    if value == RunCardActor.MCP:
        return CreatedVia.MCP
    if value == RunCardActor.API:
        return CreatedVia.REST
    return CreatedVia.SYSTEM


def _confidence(count: int) -> float:
    return round(min(0.95, 0.35 + count / 20), 4)


def _fill_dataset_row(fill: TradeFill) -> dict[str, Any]:
    return {
        "id": fill.id,
        "symbol": fill.symbol,
        "side": fill.side.value,
        "qty": fill.qty,
        "price": fill.price,
        "traded_at": fill.traded_at.isoformat(),
        "raw_row_hash": fill.raw_row_hash,
    }


def _roundtrip_dataset_row(roundtrip: TradeRoundTrip) -> dict[str, Any]:
    return {
        "id": roundtrip.id,
        "symbol": roundtrip.symbol,
        "opened_at": roundtrip.opened_at.isoformat(),
        "closed_at": roundtrip.closed_at.isoformat(),
        "qty": roundtrip.qty,
        "buy_price": roundtrip.buy_price,
        "sell_price": roundtrip.sell_price,
        "holding_days": roundtrip.holding_days,
        "realized_pnl": roundtrip.realized_pnl,
        "realized_pnl_pct": roundtrip.realized_pnl_pct,
    }


def _ensure_tz(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
