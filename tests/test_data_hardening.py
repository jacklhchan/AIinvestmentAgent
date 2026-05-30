from __future__ import annotations

from datetime import timedelta

import pytest

from invest_agent.advice_readiness import AdviceReadinessService
from invest_agent.config import Settings
from invest_agent.evidence_repair import EvidenceRepairService
from invest_agent.models import (
    FundamentalMetric,
    FundamentalSnapshot,
    NewsItem,
    PaperAdviceRequest,
    PortfolioSnapshot,
    Position,
    Quote,
    QuoteHistoryBatchRefreshRequest,
    SignalRunRequest,
    SignalSource,
    utc_now,
)
from invest_agent.paper_advice import PaperAdviceFlowService
from invest_agent.pilot_report import PilotReportService
from invest_agent.promotion_gate import PromotionGateService
from invest_agent.quote_history import QuoteHistoryService
from invest_agent.runtime_doctor import RuntimeDoctorService
from invest_agent.services import InvestmentService
from invest_agent.signals import SignalEngine
from invest_agent.store import Store
from tests.test_signals import add_positive_context, seed_market_regime_quotes


def _settings(tmp_path, *, watchlist: str = "AAPL") -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        watchlist_symbols=watchlist,
        market_context_symbols="SPY,QQQ,XLK",
        futu_read_enabled=True,
        signal_buy_threshold=70,
        signal_watch_threshold=45,
        draft_notional_usd=1000,
    )


def _store(tmp_path, *, watchlist: str = "AAPL") -> tuple[Settings, Store, InvestmentService]:
    settings = _settings(tmp_path, watchlist=watchlist)
    store = Store(settings.db_path)
    store.upsert_portfolio(
        PortfolioSnapshot(
            cash_usd=20_000,
            total_value_usd=30_000,
            positions=[Position(symbol="MSFT", qty=5, market_value=2000, last_price=400)],
            source="test",
        )
    )
    seed_market_regime_quotes(store)
    return settings, store, InvestmentService(settings, store)


def test_quote_history_batch_resolves_groups_and_uses_futu_kline(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path)
    store.upsert_quote(Quote(symbol="AAPL", last_price=190, previous_close=188, change_pct=1.0))

    def fake_history(_settings, symbol, **_kwargs):
        return f"US.{symbol}", [
            {"ts": utc_now() - timedelta(days=1), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"ts": utc_now(), "open": 101, "high": 102, "low": 100, "close": 101, "volume": 2},
        ]

    monkeypatch.setattr("invest_agent.quote_history.fetch_futu_history_kline", fake_history)

    result = QuoteHistoryService(store, settings).refresh_batch(
        QuoteHistoryBatchRefreshRequest(symbols="watchlist,positions,benchmarks", source="futu", days=30)
    )

    assert result["import_count"] >= 4
    assert {"AAPL", "MSFT", "SPY", "QQQ"}.issubset(set(result["symbols"]))
    assert store.list_price_bars(symbol="AAPL")
    assert store.list_audit_events(event_type="quote_history_batch_refreshed")


def test_quote_history_batch_throttles_futu_history_requests(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path, watchlist="AAPL,MSFT,NVDA")
    sleeps: list[float] = []

    monkeypatch.setattr("invest_agent.quote_history.FUTU_HISTORY_BATCH_PAUSE_EVERY", 2)
    monkeypatch.setattr("invest_agent.quote_history.FUTU_HISTORY_BATCH_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr("invest_agent.quote_history.time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "invest_agent.quote_history.fetch_futu_history_kline",
        lambda _settings, symbol, **_kwargs: (
            f"US.{symbol}",
            [{"ts": utc_now(), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}],
        ),
    )

    result = QuoteHistoryService(store, settings).refresh_batch(
        QuoteHistoryBatchRefreshRequest(symbols="AAPL,MSFT,NVDA", source="futu", days=5)
    )

    assert result["ok"] is True
    assert result["import_count"] == 3
    assert sleeps == [0.01]


def test_paper_advice_items_include_per_symbol_readiness(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path, watchlist="GOOGL")
    add_positive_context(store, "GOOGL")
    monkeypatch.setattr(
        "invest_agent.paper_advice.AdviceReadinessService.run",
        lambda self: {"score": 90.0, "severity": "ok", "checks": {"test": {"status": "ok", "message": "ready"}}, "by_symbol": {}},
    )

    result = PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))

    assert result.items[0].symbol == "GOOGL"
    assert result.items[0].symbol_readiness["symbol"] == "GOOGL"
    assert "quote_freshness" in result.items[0].symbol_readiness["checks"]


def test_runtime_doctor_warns_when_running_commit_differs_from_head(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path)
    monkeypatch.setattr("invest_agent.runtime_version.RUNNING_GIT_COMMIT", "old123")
    monkeypatch.setattr("invest_agent.runtime_version._git_rev_parse", lambda *_args, **_kwargs: "new456")
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.get_futu_status",
        lambda _settings: {"read_enabled": True, "connected": True, "available": True, "message": "mock"},
    )
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.discover_futu_accounts",
        lambda _settings: type("Discovery", (), {"as_dict": lambda self: {"account_count": 1, "selection_status": "ok"}})(),
    )

    result = RuntimeDoctorService(settings, store).run()

    version = result["checks"]["runtime_version"]
    assert version["status"] == "warn"
    assert version["metrics"]["commit_mismatch"] is True


def test_evidence_repair_writes_evidence_and_does_not_create_proposals(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path, watchlist="GOOGL")
    add_positive_context(store, "GOOGL", verified=False)
    signal = SignalEngine(settings, store, service).run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI)).signals[0]
    store.upsert_fundamentals(
        FundamentalSnapshot(
            symbol="GOOGL",
            cik="0001652044",
            entity_name="Alphabet",
            metrics={"revenue": FundamentalMetric(name="revenue", label="Revenue", value=1, unit="USD", yoy_change_pct=10)},
        )
    )
    monkeypatch.setattr(EvidenceRepairService, "_hydrate", lambda self, symbol: {"mock": "hydrated"})
    monkeypatch.setattr(
        "invest_agent.evidence_repair.PaperAdviceFlowService.run",
        lambda self, request=None, **_kwargs: {"mock": "paper_advice_rerun"},
    )

    before = len(store.list_proposals())
    result = EvidenceRepairService(settings, store, service).repair_signal(signal.id)

    assert result["evidence_added"]["count"] >= 1
    assert len(store.list_proposals()) == before
    assert result["created_proposals"] == 0


def test_shared_promotion_gate_blocks_otherwise_passing_signal_without_committee(tmp_path) -> None:
    settings, store, service = _store(tmp_path, watchlist="GOOGL")
    add_positive_context(store, "GOOGL")
    signal = SignalEngine(settings, store, service).run(SignalRunRequest(symbols=["GOOGL"], source=SignalSource.CLI)).signals[0]

    gate = PromotionGateService(settings, store).evaluate(signal)

    assert gate["ok"] is False
    assert any("fresh investor committee run required" in reason for reason in gate["reasons"])
    with pytest.raises(ValueError, match="fresh investor committee run required"):
        SignalEngine(settings, store, service).promote_to_proposal(signal.id)


def test_pilot_weekly_report_counts_advice_and_blockers(tmp_path, monkeypatch) -> None:
    settings, store, service = _store(tmp_path, watchlist="GOOGL")
    add_positive_context(store, "GOOGL", verified=False)
    monkeypatch.setattr(
        "invest_agent.paper_advice.AdviceReadinessService.run",
        lambda self: {"score": 90.0, "severity": "ok", "checks": {"test": {"status": "ok", "message": "ready"}}, "by_symbol": {}},
    )
    PaperAdviceFlowService(settings, store, service).run(PaperAdviceRequest(symbols=["GOOGL"]))

    report = PilotReportService(store).weekly_summary()

    assert report["signal_count"] >= 1
    assert report["paper_advice_count"] >= 1
    assert report["blocked_by_reason"]
