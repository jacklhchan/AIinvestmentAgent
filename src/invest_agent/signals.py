from __future__ import annotations

from datetime import timedelta
from typing import Any

from .catalysts import CatalystCalendarService
from .config import Settings
from .market_news import economic_exposure_ticker, resolve_watchlist_symbols
from .market_regime import MarketRegimeService
from .models import (
    BehaviorSeverity,
    FundamentalSnapshot,
    MarketRegimeSnapshot,
    NewsItem,
    Position,
    ProposalCreate,
    Quote,
    ResearchEvidenceCreate,
    RiskAppetite,
    ProposalBias,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    Side,
    Signal,
    SignalHorizon,
    SignalPromoteRequest,
    SignalRejectRequest,
    SignalRun,
    SignalRunRequest,
    SignalRunResult,
    SignalSide,
    SignalSource,
    SignalStatus,
    SignalStrength,
    ThesisPillarStatus,
    ThesisRiskStatus,
    ThesisSide,
    ThesisStatus,
    utc_now,
)
from .proposal_drafts import _fundamental_reference, _is_primary_source, _news_reference, _score_news
from .research_goals import evidence_from_news, research_goal_from_draft
from .run_cards import RunCardService, stable_hash
from .services import InvestmentService
from .store import Store


SIGNAL_RULE_VERSION = "signal_engine_v1"
FRESH_QUOTE_SECONDS = 24 * 3600
SECTOR_PROXIES = {
    "technology": ["XLK", "QQQ"],
    "semiconductor": ["SMH", "SOXX", "QQQ"],
    "financials": ["XLF", "KRE"],
    "energy": ["XLE", "USO"],
    "healthcare": ["XLV"],
    "consumer_discretionary": ["XLY"],
    "consumer_staples": ["XLP"],
    "industrials": ["XLI"],
    "utilities": ["XLU"],
    "materials": ["XLB"],
    "real_estate": ["XLRE"],
}


class SignalEngine:
    def __init__(self, settings: Settings, store: Store, service: InvestmentService | None = None):
        self.settings = settings
        self.store = store
        self.service = service or InvestmentService(settings, store)

    def run(
        self,
        request: SignalRunRequest | None = None,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> SignalRunResult:
        request = request or SignalRunRequest()
        universe = resolve_watchlist_symbols(self.settings, self.store, request.symbols)
        max_signals = request.max_signals or self.settings.signal_max_per_run
        created_at = utc_now()
        regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        portfolio = self.store.get_portfolio()
        dataset = {
            "universe": universe,
            "portfolio": portfolio.model_dump(mode="json"),
            "market_regime": regime.model_dump(mode="json"),
            "quotes": [quote.model_dump(mode="json") for quote in self.store.list_quotes()],
            "fundamentals": [item.model_dump(mode="json") for item in self.store.list_fundamentals()],
            "rule_version": SIGNAL_RULE_VERSION,
        }
        run_card = RunCardService(self.store).start_run(
            RunCardType.SIGNAL_RUN,
            title="Paper Signal Run",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=SIGNAL_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset=dataset,
            assumptions={
                "paper_only": self.settings.is_paper,
                "signals_are_not_approvals": True,
                "live_orders_disabled": True,
                "score_is_deterministic": True,
            },
        )
        try:
            run = SignalRun(
                source=request.source,
                horizon=request.horizon,
                universe=universe,
                run_card_id=run_card.id,
                created_at=created_at,
            )
            signals: list[Signal] = []
            skipped: list[str] = []
            for symbol in universe:
                signal = self._build_signal(
                    run=run,
                    symbol=symbol,
                    horizon=request.horizon,
                    source=request.source,
                    created_at=created_at,
                    regime=regime,
                    portfolio=portfolio,
                )
                if signal:
                    signals.append(signal)
                else:
                    skipped.append(f"{symbol}: insufficient quote, news, fundamentals, thesis, or position context")

            signals.sort(key=lambda item: (_signal_rank(item), item.score, item.confidence), reverse=True)
            signals = signals[:max_signals]
            run.signals = signals
            run.skipped = skipped
            run.summary = _signal_summary(signals, skipped)
            run.metrics = _signal_metrics(signals, skipped)
            stored = self.store.create_signal_run(run)
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics=run.metrics,
                warnings=skipped,
                outputs={
                    "signal_run_id": stored.id,
                    "signal_ids": [signal.id for signal in stored.signals],
                    "summary": stored.summary,
                },
                dataset={**dataset, "signals": [signal.model_dump(mode="json") for signal in stored.signals]},
            )
            self.store.audit(
                "signals_generated",
                "signal_run",
                stored.id,
                {"signal_count": len(stored.signals), "skipped": skipped[:12], **run.metrics},
            )
            return SignalRunResult(run=stored, signals=stored.signals, skipped=skipped, metrics=run.metrics)
        except Exception as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc), write_artifacts=True)
            raise

    def promote_to_proposal(
        self,
        signal_id: str,
        request: SignalPromoteRequest | None = None,
    ) -> dict[str, Any]:
        request = request or SignalPromoteRequest()
        signal = self._require_signal(signal_id)
        if signal.status != SignalStatus.ACTIVE:
            raise ValueError(f"signal is {signal.status.value}, not active")
        proposal_side = _proposal_side(signal)
        if proposal_side is None:
            blocked_action = signal.gates.get("blocked_action")
            reason = f"signal is {signal.side.value}"
            if blocked_action:
                reason += f" for {blocked_action}"
            raise ValueError(f"{reason}; it cannot be promoted until gates pass")
        if signal.suggested_qty <= 0 or not signal.suggested_limit_price:
            raise ValueError("signal has no promotable quantity or limit price")
        proposal = self.service.create_proposal(
            ProposalCreate(
                symbol=signal.symbol,
                side=proposal_side,
                qty=signal.suggested_qty,
                limit_price=signal.suggested_limit_price,
                thesis=_proposal_thesis(signal),
                trigger=f"SignalEngine {signal.side.value}: score {signal.score}/100",
                confidence=signal.confidence,
                evidence=signal.evidence,
                counter_evidence=signal.counter_evidence,
                research_goal_id=signal.research_goal_id,
                thesis_id=signal.thesis_id,
            )
        )
        updated = signal.model_copy(update={"status": SignalStatus.PROMOTED, "proposal_id": proposal.id})
        updated = self.store.update_signal(updated, "signal_promoted_to_proposal")
        self.store.audit(
            "signal_promotion_requested",
            "signal",
            signal.id,
            {"proposal_id": proposal.id, "proposal_status": proposal.status.value, "approved_by": request.approved_by},
        )
        return {"signal": updated, "proposal": proposal}

    def reject_signal(self, signal_id: str, request: SignalRejectRequest | None = None) -> Signal:
        request = request or SignalRejectRequest()
        signal = self._require_signal(signal_id)
        if signal.status != SignalStatus.ACTIVE:
            raise ValueError(f"signal is {signal.status.value}, not active")
        updated = signal.model_copy(
            update={"status": SignalStatus.REJECTED, "rejected_at": utc_now(), "rejection_reason": request.reason}
        )
        return self.store.update_signal(updated, "signal_rejected")

    def _require_signal(self, signal_id: str) -> Signal:
        signal = self.store.get_signal(signal_id)
        if not signal:
            raise ValueError(f"signal not found: {signal_id}")
        return signal

    def _build_signal(
        self,
        *,
        run: SignalRun,
        symbol: str,
        horizon: SignalHorizon,
        source: SignalSource,
        created_at,
        regime: MarketRegimeSnapshot,
        portfolio,
    ) -> Signal | None:
        quote = self._find_quote(symbol)
        position = self._find_position(symbol)
        news = self._recent_news(symbol)
        fundamentals = self._find_fundamentals(symbol)
        thesis = self._find_active_thesis(symbol)
        if not any([quote, position, news, fundamentals, thesis]):
            return None

        features = self._feature_breakdown(symbol, quote, position, news, fundamentals, thesis, regime, portfolio, created_at)
        raw_score = int(_clamp(sum(float(value) for value in features.values()), -100, 100))
        proposed_side = self._proposed_side(raw_score, position, thesis, portfolio)
        gates = self._gates(symbol, proposed_side, quote, news, fundamentals, regime, created_at)
        blockers = list(gates.get("blocking_reasons", []))
        side = SignalSide.BLOCKED if _is_promotable_side(proposed_side) and blockers else proposed_side
        if side == SignalSide.BLOCKED:
            gates["blocked_action"] = proposed_side.value

        evidence, counter_evidence = self._evidence(symbol, quote, news, fundamentals, thesis, gates)
        research_goal_id = None
        if _is_promotable_side(proposed_side) and news:
            gate = self._record_research_goal(symbol, proposed_side, raw_score, evidence, news, fundamentals)
            research_goal_id = gate.goal_id
            gates["research_gate"] = {
                "passed": gate.passed,
                "reasons": gate.reasons,
                "evidence_count": gate.evidence_count,
                "verified_count": gate.verified_count,
            }
            if not gate.passed and side != SignalSide.BLOCKED:
                side = SignalSide.BLOCKED
                gates["blocked_action"] = proposed_side.value
                gates.setdefault("blocking_reasons", []).append(f"research evidence gate failed: {'; '.join(gate.reasons)}")
                gates["proposal_allowed"] = False
                counter_evidence.extend(gate.reasons)

        score = int(abs(raw_score))
        confidence = round(_clamp(0.35 + score / 100 * 0.52 - (0.08 if side == SignalSide.BLOCKED else 0.0), 0.0, 0.9), 2)
        qty, limit_price = self._suggested_order(side if side != SignalSide.BLOCKED else proposed_side, quote, position)
        return Signal(
            run_id=run.id,
            symbol=symbol,
            side=side,
            horizon=horizon,
            score=score,
            confidence=confidence,
            strength=_strength(score),
            source=source,
            feature_breakdown={
                **{key: round(value, 2) for key, value in features.items()},
                "raw_score": raw_score,
                "proposed_side": proposed_side.value,
            },
            evidence=evidence,
            counter_evidence=counter_evidence,
            gates=gates,
            research_goal_id=research_goal_id,
            thesis_id=thesis.id if thesis else None,
            signal_price=quote.last_price if quote else (position.last_price if position else None),
            suggested_qty=qty,
            suggested_limit_price=limit_price,
            suggested_notional_usd=round(qty * (limit_price or 0.0), 2),
            outcome_windows=_outcome_windows(created_at),
            expires_at=created_at + timedelta(hours=max(1, self.settings.signal_expiry_hours)),
            created_at=created_at,
        )

    def _feature_breakdown(
        self,
        symbol: str,
        quote: Quote | None,
        position: Position | None,
        news: list[NewsItem],
        fundamentals: FundamentalSnapshot | None,
        thesis,
        regime: MarketRegimeSnapshot,
        portfolio,
        now,
    ) -> dict[str, float]:
        base_direction = _price_momentum_score(self.store, symbol, quote) + _news_catalyst_score(news) + _fundamentals_score(fundamentals)
        return {
            "market_regime": _market_regime_score(regime),
            "sector_theme_strength": self._sector_theme_score(symbol),
            "price_momentum": _price_momentum_score(self.store, symbol, quote),
            "news_catalyst": _news_catalyst_score(news),
            "fundamentals": _fundamentals_score(fundamentals),
            "thesis_alignment": _thesis_alignment_score(thesis, base_direction),
            "portfolio_fit": _portfolio_fit_score(self.settings, portfolio, position),
            "risk_penalty": _risk_penalty(symbol, quote, regime, now, CatalystCalendarService(self.store)),
            "behavior_penalty": _behavior_penalty(self.store, symbol),
        }

    def _gates(
        self,
        symbol: str,
        proposed_side: SignalSide,
        quote: Quote | None,
        news: list[NewsItem],
        fundamentals: FundamentalSnapshot | None,
        regime: MarketRegimeSnapshot,
        now,
    ) -> dict[str, Any]:
        quote_age = _quote_age_seconds(quote, now)
        catalyst_reasons, catalyst_warnings = CatalystCalendarService(self.store).proposal_catalyst_findings(
            symbol,
            has_manual_override=False,
        )
        verified_evidence = bool(fundamentals or any(_is_primary_source(item) for item in news))
        directional_evidence = any(_score_news(item) != 0 for item in news)
        duplicate = self._duplicate_active_signal(symbol, proposed_side, now)
        blocking_reasons: list[str] = []
        if _is_promotable_side(proposed_side):
            if not quote:
                blocking_reasons.append("no local quote found")
            elif quote_age is not None and quote_age > FRESH_QUOTE_SECONDS:
                blocking_reasons.append("quote snapshot is stale")
            if not verified_evidence:
                blocking_reasons.append("no verified primary-source or fundamentals evidence attached")
            if not directional_evidence:
                blocking_reasons.append("no recent directional market evidence attached")
            if proposed_side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL} and regime.proposal_bias == ProposalBias.DEFENSIVE_ONLY:
                blocking_reasons.append("market regime is defensive_only")
            blocking_reasons.extend(catalyst_reasons)
            if duplicate:
                blocking_reasons.append("duplicate active signal cooldown")
        return {
            "quote_fresh": bool(quote and (quote_age is None or quote_age <= FRESH_QUOTE_SECONDS)),
            "quote_age_seconds": quote_age,
            "verified_evidence": verified_evidence,
            "directional_evidence": directional_evidence,
            "market_regime": regime.proposal_bias.value,
            "catalyst_reasons": catalyst_reasons,
            "catalyst_warnings": catalyst_warnings,
            "duplicate_signal": duplicate,
            "blocking_reasons": blocking_reasons,
            "proposal_allowed": _is_promotable_side(proposed_side) and not blocking_reasons,
        }

    def _proposed_side(self, raw_score: int, position: Position | None, thesis, portfolio) -> SignalSide:
        if _thesis_invalidated(thesis) and position and position.qty > 0:
            return SignalSide.SELL_SIGNAL
        if _position_overweight(self.settings, portfolio, position) and raw_score <= -self.settings.signal_watch_threshold:
            return SignalSide.REDUCE_SIGNAL
        if raw_score >= self.settings.signal_buy_threshold:
            return SignalSide.ADD_SIGNAL if position and position.qty > 0 else SignalSide.BUY_SIGNAL
        if raw_score <= -self.settings.signal_sell_threshold:
            if position and position.qty > 0:
                return SignalSide.REDUCE_SIGNAL
            return SignalSide.AVOID
        if abs(raw_score) >= self.settings.signal_watch_threshold:
            return SignalSide.WATCH
        return SignalSide.HOLD if position and position.qty > 0 else SignalSide.WATCH

    def _evidence(
        self,
        symbol: str,
        quote: Quote | None,
        news: list[NewsItem],
        fundamentals: FundamentalSnapshot | None,
        thesis,
        gates: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        evidence: list[str] = []
        counter_evidence: list[str] = []
        if quote:
            evidence.append(f"quote: {quote.symbol} last {quote.last_price:.2f}, change {quote.change_pct if quote.change_pct is not None else 'n/a'}%")
        scored_news = [item for item in news if _score_news(item) != 0]
        for item in scored_news[:3]:
            evidence.append(_news_reference(item))
        primary = [item for item in news if _is_primary_source(item)]
        for item in primary[:2]:
            ref = _news_reference(item)
            if ref not in evidence:
                evidence.append(ref)
        fundamental_ref = _fundamental_reference(fundamentals)
        if fundamental_ref:
            evidence.append(fundamental_ref)
        if thesis:
            evidence.append(f"thesis-tracker: {thesis.id} ({thesis.side.value}, conviction {thesis.conviction.value})")
        if not gates.get("verified_evidence"):
            counter_evidence.append("No verified primary-source or SEC companyfacts evidence is attached.")
        if not gates.get("directional_evidence"):
            counter_evidence.append("No recent directional market/news evidence is attached.")
        counter_evidence.extend(gates.get("blocking_reasons", []))
        return evidence[:10], list(dict.fromkeys(counter_evidence))[:10]

    def _record_research_goal(
        self,
        symbol: str,
        side: SignalSide,
        raw_score: int,
        evidence: list[str],
        news: list[NewsItem],
        fundamentals: FundamentalSnapshot | None,
    ):
        news_evidence = [
            evidence_from_news(
                goal_id="_pending",
                symbol=symbol,
                source_type=item.source or "market-news",
                title=item.title,
                source_uri=item.url,
                published_at=item.published_at,
                verified=_is_primary_source(item),
            )
            for item in news
            if _score_news(item) != 0
        ][:5]
        verified_evidence = [
            evidence_from_news(
                goal_id="_pending",
                symbol=symbol,
                source_type=item.source or "primary-source",
                title=item.title,
                source_uri=item.url,
                published_at=item.published_at,
                verified=True,
            )
            for item in news
            if _is_primary_source(item)
        ][:3]
        fundamental_ref = _fundamental_reference(fundamentals)
        if fundamentals and fundamental_ref:
            verified_evidence.append(
                ResearchEvidenceCreate(
                    goal_id="_pending",
                    symbol=symbol,
                    source_type="sec-companyfacts",
                    source_uri=None,
                    text=fundamental_ref,
                    data_as_of=fundamentals.updated_at,
                    freshness_status="latest-local",
                    verification_status="verified",
                    source_verified=True,
                    added_via="system",
                    confidence=0.7,
                    caveat="SEC companyfacts snapshot parsed locally; still requires human interpretation.",
                )
            )
        return research_goal_from_draft(
            store=self.store,
            symbol=symbol,
            side=side.value,
            score=raw_score,
            thesis="; ".join(evidence[:3]) or f"SignalEngine {side.value} candidate for {symbol}",
            news_evidence=news_evidence,
            verified_evidence=verified_evidence,
        )

    def _suggested_order(self, side: SignalSide, quote: Quote | None, position: Position | None) -> tuple[int, float | None]:
        price = quote.last_price if quote else (position.last_price if position else 0.0)
        if price <= 0:
            return 0, None
        if side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL}:
            budget = min(self.settings.draft_notional_usd, self.settings.max_trade_notional_usd)
            return int(max(1, budget // price)), round(price, 2)
        if side == SignalSide.REDUCE_SIGNAL and position and position.qty > 0:
            return int(max(1, min(position.qty, round(position.qty * 0.2)))), round(price, 2)
        if side == SignalSide.SELL_SIGNAL and position and position.qty > 0:
            return int(max(1, position.qty)), round(price, 2)
        return 0, round(price, 2)

    def _duplicate_active_signal(self, symbol: str, side: SignalSide, now) -> bool:
        if not _is_promotable_side(side):
            return False
        cooldown = now - timedelta(minutes=max(1, self.settings.signal_duplicate_cooldown_minutes))
        ticker = economic_exposure_ticker(symbol)
        for signal in self.store.list_signals(status=SignalStatus.ACTIVE, limit=200):
            existing_side = SignalSide(signal.gates.get("blocked_action") or signal.side.value)
            if signal.created_at < cooldown:
                continue
            if economic_exposure_ticker(signal.symbol) == ticker and existing_side == side:
                return True
        return False

    def _recent_news(self, symbol: str) -> list[NewsItem]:
        cutoff = utc_now() - timedelta(days=max(1, self.settings.news_lookback_days))
        primary_cutoff = utc_now() - timedelta(days=max(1, self.settings.primary_source_lookback_days))
        ticker = economic_exposure_ticker(symbol)
        return [
            item
            for item in self.store.list_news(limit=80, symbol=symbol)
            if item.symbol is not None
            and economic_exposure_ticker(item.symbol) == ticker
            and (item.published_at >= cutoff or (_is_primary_source(item) and item.published_at >= primary_cutoff))
        ]

    def _find_quote(self, symbol: str) -> Quote | None:
        quote = self.store.get_quote(symbol)
        if quote:
            return quote
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.list_quotes() if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_position(self, symbol: str) -> Position | None:
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.get_portfolio().positions if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        snapshot = self.store.get_fundamentals(symbol)
        if snapshot:
            return snapshot
        ticker = economic_exposure_ticker(symbol)
        return next((item for item in self.store.list_fundamentals() if economic_exposure_ticker(item.symbol) == ticker), None)

    def _find_active_thesis(self, symbol: str):
        thesis = self.store.get_active_thesis_for_symbol(symbol)
        if thesis:
            return thesis
        ticker = economic_exposure_ticker(symbol)
        return next(
            (
                item
                for item in self.store.list_theses(limit=200)
                if item.human_confirmed
                and item.status == ThesisStatus.ACTIVE
                and economic_exposure_ticker(item.symbol) == ticker
            ),
            None,
        )

    def _sector_theme_score(self, symbol: str) -> float:
        classification = self.store.get_symbol_classification(symbol)
        sector_key = (classification.sector if classification else "").strip().lower().replace(" ", "_")
        proxies = SECTOR_PROXIES.get(sector_key)
        if not proxies and economic_exposure_ticker(symbol) in {"AAPL", "MSFT", "GOOGL", "NVDA", "AMD", "META"}:
            proxies = ["SMH", "SOXX", "QQQ"] if economic_exposure_ticker(symbol) in {"NVDA", "AMD"} else ["XLK", "QQQ"]
        moves = [
            quote.change_pct
            for proxy in proxies or []
            if (quote := self._find_quote(proxy)) and quote.change_pct is not None
        ]
        if not moves:
            return 0.0
        return _clamp(sum(moves) / len(moves) * 5.0, -15.0, 15.0)


def _market_regime_score(regime: MarketRegimeSnapshot) -> float:
    score = 0.0
    if regime.risk_appetite == RiskAppetite.RISK_ON:
        score += 12
    elif regime.risk_appetite == RiskAppetite.RISK_OFF:
        score -= 18
    if regime.proposal_bias == ProposalBias.NORMAL:
        score += 10
    elif regime.proposal_bias == ProposalBias.CAUTION:
        score -= 5
    elif regime.proposal_bias == ProposalBias.DEFENSIVE_ONLY:
        score -= 20
    return score


def _price_momentum_score(store: Store, symbol: str, quote: Quote | None) -> float:
    if quote and quote.change_pct is not None:
        return _clamp(quote.change_pct * 8.0, -25.0, 25.0)
    bars = store.list_price_bars(symbol=symbol, limit=30, ascending=True)
    if len(bars) >= 6 and bars[-6].close > 0:
        move = (bars[-1].close / bars[-6].close - 1.0) * 100
        return _clamp(move * 2.5, -25.0, 25.0)
    return 0.0


def _news_catalyst_score(news: list[NewsItem]) -> float:
    score = sum(_score_news(item) for item in news) * 12.0
    primary_bonus = sum(1 for item in news if _is_primary_source(item) and _score_news(item) != 0) * 4.0
    return _clamp(score + (primary_bonus if score >= 0 else -primary_bonus), -35.0, 35.0)


def _fundamentals_score(snapshot: FundamentalSnapshot | None) -> float:
    if not snapshot:
        return 0.0
    values = [
        metric.yoy_change_pct
        for name in ("revenue", "net_income", "operating_cash_flow")
        if (metric := snapshot.metrics.get(name)) and metric.yoy_change_pct is not None
    ]
    if not values:
        return 0.0
    score = sum(values) / len(values) * 1.2
    net_income = snapshot.metrics.get("net_income")
    if net_income and net_income.value is not None and net_income.value < 0:
        score -= 10
    return _clamp(score, -20.0, 20.0)


def _thesis_alignment_score(thesis, direction_score: float) -> float:
    if not thesis:
        return 0.0
    score = 0.0
    if thesis.side == ThesisSide.LONG:
        score += 12 if direction_score >= 0 else -16
    elif thesis.side == ThesisSide.SHORT:
        score += 12 if direction_score <= 0 else -16
    else:
        score -= 10
    if thesis.status in {ThesisStatus.INVALIDATED, ThesisStatus.ARCHIVED}:
        score -= 30
    if any(risk.status == ThesisRiskStatus.TRIGGERED for risk in thesis.risks):
        score -= 20
    if any(pillar.status == ThesisPillarStatus.BROKEN for pillar in thesis.pillars):
        score -= 14
    return score


def _portfolio_fit_score(settings: Settings, portfolio, position: Position | None) -> float:
    total = portfolio.total_value_usd or portfolio.cash_usd + sum(item.market_value for item in portfolio.positions)
    if total <= 0:
        return 0.0
    cash_weight = portfolio.cash_usd / total
    score = 6.0 if cash_weight >= 0.05 else -8.0
    if position and total > 0:
        weight = position.market_value / total
        cap = settings.max_position_pct / 100.0
        if weight > cap:
            score -= 26.0
        elif weight < cap * 0.5:
            score += 4.0
    return _clamp(score, -30.0, 12.0)


def _risk_penalty(symbol: str, quote: Quote | None, regime: MarketRegimeSnapshot, now, catalysts: CatalystCalendarService) -> float:
    penalty = 0.0
    if not quote:
        penalty -= 30
    elif (age := _quote_age_seconds(quote, now)) is not None and age > FRESH_QUOTE_SECONDS:
        penalty -= 12
    catalyst_reasons, catalyst_warnings = catalysts.proposal_catalyst_findings(symbol, has_manual_override=False)
    penalty -= min(30, len(catalyst_reasons) * 18 + len(catalyst_warnings) * 6)
    if regime.proposal_bias == ProposalBias.DEFENSIVE_ONLY:
        penalty -= 10
    return penalty


def _behavior_penalty(store: Store, symbol: str) -> float:
    report = next(iter(store.list_behavior_reports(symbol=symbol, limit=1)), None)
    if not report:
        return 0.0
    penalty = 0.0
    for name in ("chasing_momentum", "overtrading", "anchoring"):
        diagnostic = report.diagnostics.get(name)
        if not diagnostic:
            continue
        if diagnostic.severity == BehaviorSeverity.HIGH:
            penalty -= 8
        elif diagnostic.severity == BehaviorSeverity.MEDIUM:
            penalty -= 4
    return penalty


def _proposal_side(signal: Signal) -> Side | None:
    if signal.side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL}:
        return Side.BUY
    if signal.side in {SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL}:
        return Side.SELL
    return None


def _is_promotable_side(side: SignalSide) -> bool:
    return side in {SignalSide.BUY_SIGNAL, SignalSide.ADD_SIGNAL, SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL}


def _strength(score: int) -> SignalStrength:
    if score >= 80:
        return SignalStrength.STRONG
    if score >= 60:
        return SignalStrength.MEDIUM
    return SignalStrength.WEAK


def _signal_rank(signal: Signal) -> int:
    ranks = {
        SignalSide.BUY_SIGNAL: 8,
        SignalSide.ADD_SIGNAL: 7,
        SignalSide.REDUCE_SIGNAL: 7,
        SignalSide.SELL_SIGNAL: 7,
        SignalSide.BLOCKED: 6,
        SignalSide.AVOID: 5,
        SignalSide.WATCH: 4,
        SignalSide.HOLD: 3,
    }
    return ranks.get(signal.side, 0)


def _signal_summary(signals: list[Signal], skipped: list[str]) -> str:
    counts: dict[str, int] = {}
    for signal in signals:
        counts[signal.side.value] = counts.get(signal.side.value, 0) + 1
    parts = [f"{side} {count}" for side, count in sorted(counts.items())]
    if skipped:
        parts.append(f"skipped {len(skipped)}")
    return ", ".join(parts) if parts else "No signals generated."


def _signal_metrics(signals: list[Signal], skipped: list[str]) -> dict[str, Any]:
    return {
        "signal_count": len(signals),
        "skipped_count": len(skipped),
        "buy_count": sum(1 for item in signals if item.side == SignalSide.BUY_SIGNAL),
        "sell_reduce_count": sum(1 for item in signals if item.side in {SignalSide.SELL_SIGNAL, SignalSide.REDUCE_SIGNAL}),
        "blocked_count": sum(1 for item in signals if item.side == SignalSide.BLOCKED),
        "watch_count": sum(1 for item in signals if item.side == SignalSide.WATCH),
        "max_score": max((item.score for item in signals), default=0),
    }


def _position_overweight(settings: Settings, portfolio, position: Position | None) -> bool:
    if not position:
        return False
    total = portfolio.total_value_usd or portfolio.cash_usd + sum(item.market_value for item in portfolio.positions)
    if total <= 0:
        return False
    return position.market_value / total > settings.max_position_pct / 100.0


def _thesis_invalidated(thesis) -> bool:
    if not thesis:
        return False
    return (
        thesis.status == ThesisStatus.INVALIDATED
        or any(risk.status == ThesisRiskStatus.TRIGGERED for risk in thesis.risks)
        or any(pillar.status == ThesisPillarStatus.BROKEN for pillar in thesis.pillars)
    )


def _quote_age_seconds(quote: Quote | None, now) -> float | None:
    if not quote:
        return None
    return max(0.0, (now - quote.updated_at).total_seconds())


def _outcome_windows(created_at) -> dict[str, Any]:
    return {
        "1d": {"due_at": (created_at + timedelta(days=1)).isoformat(), "return_pct": None},
        "5d": {"due_at": (created_at + timedelta(days=5)).isoformat(), "return_pct": None},
        "20d": {"due_at": (created_at + timedelta(days=20)).isoformat(), "return_pct": None},
    }


def _proposal_thesis(signal: Signal) -> str:
    blocked_action = signal.gates.get("blocked_action")
    action = blocked_action or signal.side.value
    return (
        f"Paper-only {action} signal for {signal.symbol} scored {signal.score}/100. "
        "Promotion still goes through research gate, policy checks, and human approval."
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
