from __future__ import annotations

from datetime import datetime, timedelta, timezone

from invest_agent.catalysts import CatalystCalendarService
from invest_agent.config import Settings
from invest_agent.models import (
    CatalystCreate,
    CatalystEventType,
    CatalystExpectedImpact,
    FundamentalMetric,
    FundamentalSnapshot,
    NewsItem,
    PortfolioSnapshot,
    Position,
    ProposalStatus,
    Quote,
    SignalRunRequest,
    SignalSide,
    SignalSource,
    utc_now,
)
from invest_agent.services import InvestmentService
from invest_agent.signals import SignalEngine
from invest_agent.store import Store
from invest_agent.quote_freshness import quote_is_fresh
from fastapi.testclient import TestClient


def make_signal_engine(tmp_path, *, watchlist: str = "GOOGL") -> tuple[SignalEngine, Store, Settings]:
    settings = Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols=watchlist,
        market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO,XLK,SMH,SOXX",
        draft_notional_usd=1000,
        signal_buy_threshold=70,
        signal_sell_threshold=65,
        signal_watch_threshold=45,
        signal_duplicate_cooldown_minutes=240,
    )
    store = Store(settings.db_path)
    store.upsert_portfolio(
        PortfolioSnapshot(
            cash_usd=50_000,
            total_value_usd=100_000,
            positions=[],
            source="test",
        )
    )
    seed_market_regime_quotes(store)
    service = InvestmentService(settings, store)
    return SignalEngine(settings, store, service), store, settings


def seed_market_regime_quotes(store: Store) -> None:
    for symbol, move in {
        "SPY": 1.0,
        "QQQ": 1.2,
        "VIXY": -2.0,
        "TLT": 0.1,
        "GLD": -0.2,
        "USO": -0.3,
        "XLK": 1.1,
        "SMH": 1.4,
        "SOXX": 1.2,
    }.items():
        store.upsert_quote(Quote(symbol=symbol, last_price=100.0, previous_close=99.0, change_pct=move, source="test"))


def add_positive_context(store: Store, symbol: str = "GOOGL", *, verified: bool = True, move: float = 3.0) -> None:
    store.upsert_quote(Quote(symbol=symbol, last_price=200.0, previous_close=194.0, change_pct=move, source="test"))
    store.upsert_news(
        NewsItem(
            symbol=symbol,
            title=f"{symbol} raises guidance after record AI demand growth beats expectations",
            source="finnhub",
            published_at=utc_now(),
            summary="Strong demand and upside guidance.",
        )
    )
    if verified:
        store.upsert_news(
            NewsItem(
                symbol=symbol,
                title=f"SEC 10-Q filed for {symbol} with strong revenue growth",
                source="sec-edgar",
                tags=["primary-source", "sec-edgar", "10-q"],
                published_at=utc_now(),
                summary="Primary-source filing.",
            )
        )
        store.upsert_fundamentals(
            FundamentalSnapshot(
                symbol=symbol,
                cik="0001652044",
                entity_name=f"{symbol} Inc.",
                metrics={
                    "revenue": FundamentalMetric(name="revenue", label="Revenue", value=80_000_000_000, unit="USD", yoy_change_pct=12),
                    "net_income": FundamentalMetric(
                        name="net_income",
                        label="Net income",
                        value=20_000_000_000,
                        unit="USD",
                        yoy_change_pct=9,
                    ),
                    "operating_cash_flow": FundamentalMetric(
                        name="operating_cash_flow",
                        label="Operating cash flow",
                        value=25_000_000_000,
                        unit="USD",
                        yoy_change_pct=10,
                    ),
                },
            )
        )


def add_negative_context(store: Store, symbol: str = "TSLA") -> None:
    store.upsert_quote(Quote(symbol=symbol, last_price=100.0, previous_close=106.0, change_pct=-5.5, source="test"))
    store.upsert_news(
        NewsItem(
            symbol=symbol,
            title=f"{symbol} downgrade warning after weak demand and lawsuit risk cuts outlook",
            source="finnhub",
            published_at=utc_now(),
            summary="Analysts cut estimates after weak demand.",
        )
    )
    store.upsert_news(
        NewsItem(
            symbol=symbol,
            title=f"SEC 10-Q filed for {symbol} shows revenue decline",
            source="sec-edgar",
            tags=["primary-source", "sec-edgar", "10-q"],
            published_at=utc_now(),
            summary="Primary-source filing.",
        )
    )
    store.upsert_fundamentals(
        FundamentalSnapshot(
            symbol=symbol,
            cik="0001318605",
            entity_name=f"{symbol} Inc.",
            metrics={
                "revenue": FundamentalMetric(name="revenue", label="Revenue", value=20_000_000_000, unit="USD", yoy_change_pct=-12),
                "net_income": FundamentalMetric(name="net_income", label="Net income", value=500_000_000, unit="USD", yoy_change_pct=-25),
            },
        )
    )


def test_buy_signal_with_verified_evidence_can_promote_to_pending_proposal(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    add_positive_context(store)

    result = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    signal = result.signals[0]
    assert signal.side == SignalSide.BUY_SIGNAL
    assert signal.score >= 70
    assert signal.gates["proposal_allowed"] is True
    assert signal.research_goal_id
    assert signal.signal_price == 200.0
    assert set(signal.outcome_windows) == {"1d", "5d", "20d"}

    promoted = engine.promote_to_proposal(signal.id)

    assert promoted["proposal"].status == ProposalStatus.PENDING
    assert promoted["signal"].proposal_id == promoted["proposal"].id
    assert promoted["signal"].status == "promoted"


def test_reduce_signal_for_overweight_negative_position(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path, watchlist="TSLA")
    store.upsert_portfolio(
        PortfolioSnapshot(
            cash_usd=5_000,
            total_value_usd=100_000,
            positions=[Position(symbol="TSLA", qty=500, market_value=60_000, avg_cost=120, last_price=100)],
            source="test",
        )
    )
    add_negative_context(store)

    result = engine.run(SignalRunRequest(symbols=["TSLA"], source=SignalSource.CLI))

    assert result.signals[0].side == SignalSide.REDUCE_SIGNAL
    assert result.signals[0].suggested_qty == 100
    assert result.signals[0].score >= 65


def test_low_score_signal_stays_watch(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    store.upsert_quote(Quote(symbol="GOOGL", last_price=200, previous_close=198, change_pct=1.0, source="test"))
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet shares rise after AI demand update",
            source="gdelt",
            published_at=utc_now(),
            summary="Demand remains stable.",
        )
    )

    result = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    assert result.signals[0].side == SignalSide.WATCH
    assert 45 <= result.signals[0].score < 70


def test_strong_unverified_signal_is_blocked_not_promotable(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    add_positive_context(store, verified=False)

    result = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    signal = result.signals[0]
    assert signal.side == SignalSide.BLOCKED
    assert signal.gates["blocked_action"] == SignalSide.BUY_SIGNAL.value
    assert any("verified" in reason for reason in signal.gates["blocking_reasons"])


def test_high_price_buy_signal_blocks_when_notional_budget_is_too_small(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    add_positive_context(store, symbol="GOOGL", verified=True)
    store.upsert_quote(Quote(symbol="GOOGL", last_price=2_000.0, previous_close=1_900.0, change_pct=5.0, source="test"))

    result = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    signal = result.signals[0]
    assert signal.suggested_qty == 0
    assert signal.side == SignalSide.BLOCKED
    assert "price exceeds paper notional budget" in signal.gates["blocking_reasons"]
    try:
        engine.promote_to_proposal(signal.id)
    except ValueError as exc:
        assert "price exceeds paper notional budget" in str(exc)
    else:
        raise AssertionError("expected promotion to be blocked")


def test_weekend_latest_completed_session_quote_is_not_stale() -> None:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    friday_quote = Quote(
        symbol="US.SPY",
        last_price=500.0,
        updated_at=datetime(2026, 5, 29, 19, 30, tzinfo=timezone.utc),
        source="test",
    )

    assert quote_is_fresh(friday_quote, now)


def test_high_impact_catalyst_blocks_directional_signal(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    add_positive_context(store)
    CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="GOOGL",
            event_type=CatalystEventType.EARNINGS,
            title="GOOGL earnings",
            event_date=utc_now() + timedelta(hours=12),
            expected_impact=CatalystExpectedImpact.HIGH,
        ),
        human_verified=True,
    )

    result = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    assert result.signals[0].side == SignalSide.BLOCKED
    assert any("high-impact catalyst" in reason for reason in result.signals[0].gates["blocking_reasons"])


def test_duplicate_signal_cooldown_blocks_repeat_signal(tmp_path) -> None:
    engine, store, _settings = make_signal_engine(tmp_path)
    add_positive_context(store)
    first = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    second = engine.run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI))

    assert first.signals[0].side == SignalSide.BUY_SIGNAL
    assert second.signals[0].side == SignalSide.BLOCKED
    assert "duplicate active signal cooldown" in second.signals[0].gates["blocking_reasons"]


def test_signal_api_routes_share_store_layer(tmp_path, monkeypatch) -> None:
    from invest_agent import api, deps

    _engine, store, settings = make_signal_engine(tmp_path)
    add_positive_context(store)
    api.get_settings.cache_clear()
    deps.get_settings.cache_clear()
    deps.get_store.cache_clear()
    deps.get_service.cache_clear()
    monkeypatch.setattr("invest_agent.api.get_settings", lambda: settings)
    monkeypatch.setattr("invest_agent.deps.get_settings", lambda: settings)

    response = TestClient(api.app).post("/api/signals/run", json={"symbols": ["GOOGL"], "source": "api"})
    latest = TestClient(api.app).get("/api/signals/latest")

    assert response.status_code == 200
    assert response.json()["signals"][0]["side"] == SignalSide.BUY_SIGNAL.value
    assert latest.status_code == 200
    assert latest.json()["signals"][0]["symbol"] == "GOOGL"
