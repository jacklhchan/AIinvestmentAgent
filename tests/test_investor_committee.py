from __future__ import annotations

from datetime import timedelta

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.investor_committee import InvestorFrameworkCommitteeService
from invest_agent.models import (
    FundamentalMetric,
    FundamentalSnapshot,
    InvestorCommitteeRun,
    InvestorCommitteeStance,
    InvestorCommitteeVote,
    MarketRegimeSnapshot,
    ProposalBias,
    RiskAppetite,
    Signal,
    SignalOutcomeRow,
    SignalRun,
    SignalSide,
    SignalSource,
    SignalStatus,
    SignalStrength,
    SignalHorizon,
    utc_now,
)
from invest_agent.signal_outcomes import OUTCOME_RULE_VERSION
from invest_agent.store import Store


def _make_store(tmp_path) -> tuple[Settings, Store]:
    settings = Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols="GOOGL",
        market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO",
        draft_notional_usd=1000,
        signal_buy_threshold=70,
        signal_sell_threshold=65,
        signal_watch_threshold=45,
    )
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return settings, store


def _insert_signal(store: Store, *, symbol: str = "GOOGL", score: int = 82, side: SignalSide = SignalSide.BUY_SIGNAL) -> Signal:
    run = SignalRun(source=SignalSource.CLI, horizon=SignalHorizon.SWING, universe=[symbol], summary="test")
    signal = Signal(
        run_id=run.id,
        symbol=symbol,
        side=side,
        score=score,
        confidence=0.8,
        strength=SignalStrength.STRONG,
        source=SignalSource.CLI,
        status=SignalStatus.ACTIVE,
        signal_price=100.0,
        suggested_qty=10,
        suggested_limit_price=100.0,
        suggested_notional_usd=1000.0,
        signal_engine_version="test",
        feature_weight_version="test",
        threshold_profile={"buy_threshold": 70},
        readiness_version="test",
        committee_profile_version="test",
        expires_at=utc_now() + timedelta(days=1),
        created_at=utc_now(),
        gates={"research_gate": {"passed": False, "verified_count": 0}, "blocking_reasons": []},
        feature_breakdown={"price_momentum": 30, "news_catalyst": 20, "portfolio_fit": 5, "risk_penalty": -1},
        evidence=["news item"],
        counter_evidence=[],
    )
    store.create_signal_run(run.model_copy(update={"signals": [signal]}))
    return store.get_signal(signal.id)


def test_quality_value_supports_fundamentals_but_does_not_override_evidence_gate(tmp_path) -> None:
    settings, store = _make_store(tmp_path)
    signal = _insert_signal(store)
    store.upsert_fundamentals(
        FundamentalSnapshot(
            symbol="GOOGL",
            cik="0001652044",
            entity_name="Alphabet Inc.",
            metrics={
                "revenue": FundamentalMetric(name="revenue", label="Revenue", value=1, unit="USD", yoy_change_pct=12),
                "net_income": FundamentalMetric(name="net_income", label="Net income", value=1, unit="USD", yoy_change_pct=10),
                "operating_cash_flow": FundamentalMetric(name="operating_cash_flow", label="OCF", value=1, unit="USD", yoy_change_pct=11),
                "eps_diluted": FundamentalMetric(name="eps_diluted", label="EPS", value=1, unit="USD", yoy_change_pct=9),
            },
        )
    )

    run = InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    quality = next(v for v in run.votes if v.framework_key == "quality_value")

    assert quality.stance == InvestorCommitteeStance.SUPPORT_WITH_CAUTION
    assert run.committee_blocked is True
    assert "evidence_auditor" in run.vetoes


def test_canslim_momentum_is_downgraded_in_defensive_market(tmp_path) -> None:
    settings, store = _make_store(tmp_path)
    signal = _insert_signal(store)
    store.create_market_regime_snapshot(
        MarketRegimeSnapshot(
            risk_appetite=RiskAppetite.RISK_OFF,
            proposal_bias=ProposalBias.CAUTION,
            summary="defensive",
        )
    )

    run = InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    momentum = next(v for v in run.votes if v.framework_key == "canslim_momentum")

    assert momentum.stance == InvestorCommitteeStance.NEUTRAL
    assert momentum.score_delta < 0


def test_index_skeptic_opposes_negative_edge_vs_benchmark(tmp_path) -> None:
    settings, store = _make_store(tmp_path)
    signal = _insert_signal(store, score=76)
    store.upsert_signal_outcome_rows(
        [
            SignalOutcomeRow(
                signal_id=signal.id,
                side=SignalSide.BUY_SIGNAL,
                blocked_action=None,
                window="1d",
                window_type="trading_days",
                entry_bar_ts=utc_now(),
                target_bar_ts=utc_now(),
                raw_return_pct=-2.0,
                directional_return_pct=-2.0,
                raw_excess_return_pct=-1.5,
                directional_excess_return_pct=-1.5,
                hit_direction=False,
                evaluated_at=utc_now(),
                max_drawdown_pct=-3.0,
                max_favorable_excursion_pct=1.0,
                max_adverse_upside_pct=None,
                max_favorable_downside_pct=None,
                score=signal.score,
                readiness_score=82.0,
                blocking_reasons=[],
            )
        ]
    )

    run = InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    index_skeptic = next(v for v in run.votes if v.framework_key == "index_skeptic")

    assert index_skeptic.stance == InvestorCommitteeStance.OPPOSE


def test_execution_skeptic_blocks_high_price_signal_over_notional_budget(tmp_path) -> None:
    settings, store = _make_store(tmp_path)
    signal = _insert_signal(store, score=88)
    signal = signal.model_copy(
        update={
            "suggested_qty": 0,
            "suggested_limit_price": None,
            "gates": {"blocking_reasons": ["price exceeds paper notional budget"], "blocked_action": "BUY_SIGNAL"},
            "side": SignalSide.BLOCKED,
        }
    )
    store.update_signal(signal)

    run = InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    execution = next(v for v in run.votes if v.framework_key == "execution_skeptic")

    assert execution.veto is True
    assert run.committee_blocked is True
