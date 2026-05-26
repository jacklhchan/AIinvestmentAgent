from __future__ import annotations

from pathlib import Path

from invest_agent.advisor import AdvisorService
from invest_agent.config import Settings
from invest_agent.market_news import resolve_watchlist_symbols
from invest_agent.market_regime import MarketRegimeService
from invest_agent.models import (
    GrowthPressure,
    InflationPressure,
    NewsItem,
    ProposalBias,
    Quote,
    RatesPressure,
    RiskAppetite,
    RunCardType,
    VolatilityRegime,
)
from invest_agent.proposal_drafts import ProposalDraftEngine
from invest_agent.store import Store


def make_store(tmp_path: Path, settings: Settings) -> Store:
    return Store(settings.db_path)


def test_market_regime_risk_on_when_equities_up_and_vol_down(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO")
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="SPY", last_price=101, previous_close=100, change_pct=1.0))
    store.upsert_quote(Quote(symbol="QQQ", last_price=102, previous_close=100, change_pct=2.0))
    store.upsert_quote(Quote(symbol="VIXY", last_price=98, previous_close=100, change_pct=-2.0))
    store.upsert_quote(Quote(symbol="TLT", last_price=100.2, previous_close=100, change_pct=0.2))
    store.upsert_quote(Quote(symbol="GLD", last_price=99.8, previous_close=100, change_pct=-0.2))
    store.upsert_quote(Quote(symbol="USO", last_price=99.0, previous_close=100, change_pct=-1.0))

    snapshot = MarketRegimeService(settings, store).build_snapshot()

    assert snapshot.risk_appetite == RiskAppetite.RISK_ON
    assert snapshot.growth_pressure == GrowthPressure.SUPPORTIVE
    assert snapshot.volatility_regime == VolatilityRegime.CALM
    assert snapshot.proposal_bias == ProposalBias.NORMAL


def test_market_regime_risk_off_when_spy_qqq_down_and_vixy_up(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO")
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="SPY", last_price=99, previous_close=100, change_pct=-1.0))
    store.upsert_quote(Quote(symbol="QQQ", last_price=98, previous_close=100, change_pct=-2.0))
    store.upsert_quote(Quote(symbol="VIXY", last_price=104, previous_close=100, change_pct=4.0))
    store.upsert_quote(Quote(symbol="TLT", last_price=99, previous_close=100, change_pct=-1.0))
    store.upsert_quote(Quote(symbol="GLD", last_price=101, previous_close=100, change_pct=1.0))
    store.upsert_quote(Quote(symbol="USO", last_price=102, previous_close=100, change_pct=2.0))

    snapshot = MarketRegimeService(settings, store).build_snapshot()

    assert snapshot.risk_appetite == RiskAppetite.RISK_OFF
    assert snapshot.growth_pressure == GrowthPressure.PRESSURED
    assert snapshot.rates_pressure == RatesPressure.RISING_YIELDS
    assert snapshot.volatility_regime == VolatilityRegime.STRESSED
    assert snapshot.inflation_pressure == InflationPressure.OIL_GOLD_PRESSURE
    assert snapshot.proposal_bias == ProposalBias.DEFENSIVE_ONLY


def test_market_regime_handles_news_only_context_without_crashing(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,VIXY")
    store = make_store(tmp_path, settings)
    store.upsert_news(NewsItem(symbol="VIXY", title="VIX jumps as markets wobble", source="google-news"))

    snapshot = MarketRegimeService(settings, store).build_snapshot()

    assert snapshot.quote_coverage == 0
    assert snapshot.news_coverage == 1
    assert snapshot.volatility_regime == VolatilityRegime.ELEVATED
    assert snapshot.proposal_bias == ProposalBias.CAUTION
    assert snapshot.warnings


def test_market_regime_refresh_creates_run_card_without_proposals(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ")
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="SPY", last_price=99, previous_close=100, change_pct=-1.0))
    store.upsert_quote(Quote(symbol="QQQ", last_price=98, previous_close=100, change_pct=-2.0))
    proposal_count = len(store.list_proposals(limit=100))

    snapshot = MarketRegimeService(settings, store).refresh()

    assert len(store.list_proposals(limit=100)) == proposal_count
    assert snapshot.run_card_id
    run_card = store.get_run_card(snapshot.run_card_id)
    assert run_card is not None
    assert run_card.run_type == RunCardType.MARKET_REGIME
    assert run_card.outputs["market_regime_snapshot_id"] == snapshot.id


def test_market_context_symbols_do_not_enter_watchlist_proposal_candidates(tmp_path) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols="AAPL",
        market_context_symbols="SPY,QQQ",
    )
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="AAPL", last_price=180))
    store.upsert_quote(Quote(symbol="US.SPY", last_price=500))
    store.upsert_quote(Quote(symbol="US.QQQ", last_price=450))

    assert resolve_watchlist_symbols(settings, store) == ["AAPL"]


def test_market_context_refresh_does_not_create_proposals(tmp_path) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols="AAPL",
        market_context_symbols="SPY",
    )
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="US.SPY", last_price=500))
    store.upsert_news(NewsItem(symbol="US.SPY", title="S&P 500 strong rally", source="gdelt"))

    result = ProposalDraftEngine(settings, store).draft_from_watchlist(create_proposals=True)

    assert all(draft.symbol != "US.SPY" for draft in result.drafts)
    assert not result.created
    assert not store.list_proposals(limit=100)


def test_advisor_brief_includes_market_regime_but_not_trade_signal(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,VIXY")
    store = make_store(tmp_path, settings)
    store.upsert_quote(Quote(symbol="SPY", last_price=99, previous_close=100, change_pct=-1.0))
    store.upsert_quote(Quote(symbol="QQQ", last_price=98, previous_close=100, change_pct=-2.0))
    store.upsert_quote(Quote(symbol="VIXY", last_price=104, previous_close=100, change_pct=4.0))
    proposal_count = len(store.list_proposals(limit=100))

    brief = AdvisorService(store, settings=settings).build_brief()

    assert any(item.category == "market_regime" for item in brief.advice)
    assert brief.data_status["market_regime"]["proposal_bias"] == ProposalBias.DEFENSIVE_ONLY.value
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_mcp_market_regime_tool_is_read_only() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "get_market_regime")
    assert not hasattr(mcp_server, "refresh_market_regime")
