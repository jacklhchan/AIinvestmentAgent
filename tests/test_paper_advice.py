from __future__ import annotations

from datetime import timedelta

import pytest

from invest_agent.config import Settings
from invest_agent.investor_committee import InvestorFrameworkCommitteeService
from invest_agent.models import (
    PaperAdviceRequest,
    PaperAdviceStatus,
    PortfolioSnapshot,
    Quote,
    Signal,
    SignalHorizon,
    SignalRun,
    SignalRunRequest,
    SignalSide,
    SignalSource,
    SignalStatus,
    SignalStrength,
    utc_now,
)
from invest_agent.paper_advice import PaperAdviceFlowService
from invest_agent.services import InvestmentService
from invest_agent.signals import SignalEngine
from invest_agent.store import Store
from tests.test_signals import add_positive_context, seed_market_regime_quotes


def _settings(tmp_path, *, watchlist: str = "GOOGL") -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols=watchlist,
        market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO,XLK,SMH,SOXX",
        draft_notional_usd=1000,
        signal_buy_threshold=70,
        signal_sell_threshold=65,
        signal_watch_threshold=45,
        signal_duplicate_cooldown_minutes=240,
        paper_advice_committee_freshness_minutes=240,
    )


def _store(tmp_path, *, watchlist: str = "GOOGL") -> tuple[Settings, Store, InvestmentService]:
    settings = _settings(tmp_path, watchlist=watchlist)
    store = Store(settings.db_path)
    store.upsert_portfolio(PortfolioSnapshot(cash_usd=50_000, total_value_usd=100_000, positions=[], source="test"))
    seed_market_regime_quotes(store)
    return settings, store, InvestmentService(settings, store)


def _high_readiness() -> dict:
    return {
        "score": 92.0,
        "severity": "ok",
        "checks": {"test": {"status": "ok", "message": "ready"}},
        "summary": {"attention": []},
    }


def _manual_signal(store: Store, *, side: SignalSide = SignalSide.BUY_SIGNAL, gates: dict | None = None, qty: int = 10) -> Signal:
    run = SignalRun(source=SignalSource.CLI, horizon=SignalHorizon.SWING, universe=["GOOGL"], summary="manual")
    signal = Signal(
        run_id=run.id,
        symbol="GOOGL",
        side=side,
        score=82,
        confidence=0.8,
        strength=SignalStrength.STRONG,
        source=SignalSource.CLI,
        status=SignalStatus.ACTIVE,
        signal_price=100.0,
        suggested_qty=qty,
        suggested_limit_price=100.0 if qty else None,
        suggested_notional_usd=1000.0,
        signal_engine_version="test",
        feature_weight_version="test",
        threshold_profile={"buy_threshold": 70},
        readiness_version="test",
        committee_profile_version="test",
        expires_at=utc_now() + timedelta(days=1),
        created_at=utc_now(),
        gates=gates or {"research_gate": {"passed": True, "verified_count": 1}, "proposal_allowed": True, "blocking_reasons": []},
        feature_breakdown={"price_momentum": 30, "news_catalyst": 20, "portfolio_fit": 5, "risk_penalty": -1},
        evidence=["verified test evidence"],
    )
    store.create_signal_run(run.model_copy(update={"signals": [signal]}))
    return store.get_signal(signal.id)


def test_mcp_english_and_chinese_buy_sell_route_to_paper_advice(monkeypatch) -> None:
    import invest_agent.mcp_server as mcp_server

    calls = []

    def fake_advice(**kwargs):
        calls.append(kwargs)
        return {"summary": "paper advice", "items": []}

    monkeypatch.setattr(mcp_server, "get_paper_buy_sell_advice", fake_advice)

    english = mcp_server.ask_advisor("Should I buy or sell anything today?")
    chinese = mcp_server.ask_advisor("今日我應該買入還是賣出？")

    assert english["summary"] == "paper advice"
    assert chinese["summary"] == "paper advice"
    assert len(calls) == 2


def test_readiness_below_75_blocks_actionable_paper_advice(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store)
    monkeypatch.setattr(
        "invest_agent.paper_advice.AdviceReadinessService.run",
        lambda self: {"score": 40.0, "severity": "warn", "checks": {"quotes": {"status": "warn", "message": "stale"}}},
    )

    result = PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))

    assert result.readiness_ok is False
    assert result.items[0].final_status == PaperAdviceStatus.BLOCKED
    assert result.items[0].promotable is False
    assert result.items[0].vetoes == ["advice_readiness_below_75"]


def test_committee_evidence_auditor_veto_blocks_advice_and_promotion(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store, verified=False)
    monkeypatch.setattr("invest_agent.paper_advice.AdviceReadinessService.run", lambda self: _high_readiness())

    result = PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))
    item = result.items[0]

    assert item.final_status == PaperAdviceStatus.BLOCKED
    assert "evidence_auditor" in item.vetoes
    signal = _manual_signal(
        store,
        gates={"research_gate": {"passed": False, "verified_count": 0}, "proposal_allowed": True, "blocking_reasons": []},
    )
    InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    with pytest.raises(ValueError, match="committee blocked promotion"):
        SignalEngine(settings, store, service).promote_to_proposal(signal.id)


def test_execution_skeptic_veto_blocks_high_price_over_budget_promotion(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store)
    store.upsert_quote(Quote(symbol="GOOGL", last_price=2_000.0, previous_close=1_900.0, change_pct=5.0, source="test"))
    monkeypatch.setattr("invest_agent.paper_advice.AdviceReadinessService.run", lambda self: _high_readiness())

    result = PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))

    assert result.items[0].final_status == PaperAdviceStatus.BLOCKED
    assert "execution_skeptic" in result.items[0].vetoes


def test_support_with_caution_allows_paper_advice_but_requires_human_approval(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store)
    monkeypatch.setattr("invest_agent.paper_advice.AdviceReadinessService.run", lambda self: _high_readiness())

    result = PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))
    item = result.items[0]

    assert item.final_status == PaperAdviceStatus.SUPPORT_WITH_CAUTION
    assert item.promotable is True
    promoted = SignalEngine(settings, store, service).promote_to_proposal(item.signal_id)
    assert promoted["proposal"].status.value == "PENDING"


def test_stale_committee_run_blocks_promotion(tmp_path) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store)
    signal = SignalEngine(settings, store, service).run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI)).signals[0]
    committee = InvestorFrameworkCommitteeService(settings, store).run_for_signal(signal.id)
    stale_at = utc_now() - timedelta(minutes=settings.paper_advice_committee_freshness_minutes + 5)
    stale = committee.model_copy(update={"created_at": stale_at})
    with store.connect() as conn:
        conn.execute(
            "UPDATE investor_committee_runs SET created_at = ?, payload = ? WHERE id = ?",
            (stale_at.isoformat(), store._dump(stale), committee.id),
        )

    with pytest.raises(ValueError, match="stale"):
        SignalEngine(settings, store, service).promote_to_proposal(signal.id)


def test_direct_promote_signal_cannot_bypass_committee(tmp_path) -> None:
    settings, store, service = _store(tmp_path)
    add_positive_context(store)
    signal = SignalEngine(settings, store, service).run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI)).signals[0]

    with pytest.raises(ValueError, match="fresh investor committee run required"):
        SignalEngine(settings, store, service).promote_to_proposal(signal.id)
