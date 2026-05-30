from __future__ import annotations

import plistlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from invest_agent.advice_readiness import AdviceReadinessService
from invest_agent.config import Settings
from invest_agent.daily_pipeline import DailySignalPipeline
from invest_agent.evidence_repair import EvidenceRepairService
from invest_agent.models import (
    FundamentalMetric,
    FundamentalSnapshot,
    NewsItem,
    PaperAdviceRequest,
    PortfolioSnapshot,
    Position,
    PriceBar,
    Quote,
    QuoteHistoryBatchRefreshRequest,
    QuoteHistoryImport,
    QuoteHistorySource,
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

    monkeypatch.setattr("invest_agent.market_data_router.fetch_futu_history_kline", fake_history)

    result = QuoteHistoryService(store, settings).refresh_batch(
        QuoteHistoryBatchRefreshRequest(symbols="watchlist,positions,benchmarks", source="futu", days=30)
    )

    assert result["import_count"] >= 4
    assert {"AAPL", "MSFT", "SPY", "QQQ"}.issubset(set(result["symbols"]))
    assert store.list_price_bars(symbol="AAPL")
    assert store.list_audit_events(event_type="quote_history_batch_refreshed")
    assert store.list_provider_usage(provider="futu")


def test_quote_history_batch_throttles_futu_history_requests(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path, watchlist="AAPL,MSFT,NVDA")
    sleeps: list[float] = []

    monkeypatch.setattr("invest_agent.quote_history.FUTU_HISTORY_BATCH_PAUSE_EVERY", 2)
    monkeypatch.setattr("invest_agent.quote_history.FUTU_HISTORY_BATCH_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr("invest_agent.quote_history.time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        "invest_agent.market_data_router.fetch_futu_history_kline",
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


def test_quote_history_auto_falls_back_to_stooq_when_futu_unavailable(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path, watchlist="AAPL")
    settings = settings.model_copy(update={"futu_read_enabled": False})
    monkeypatch.setattr(
        "invest_agent.market_data_router._get_text",
        lambda url, timeout: "Date,Open,High,Low,Close,Volume\n2026-05-29,100,101,99,100.5,123\n",
    )

    result = QuoteHistoryService(store, settings).refresh_batch(
        QuoteHistoryBatchRefreshRequest(symbols="AAPL", source="auto", days=5)
    )

    assert result["ok"] is True
    assert result["import_count"] == 1
    bar = store.list_price_bars(symbol="AAPL")[0]
    assert bar.source_provider == "stooq"
    assert "paper-only" in bar.license_note


def test_daily_post_close_calls_quote_history_batch(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path)
    calls: list[QuoteHistoryBatchRefreshRequest] = []

    monkeypatch.setattr(
        "invest_agent.daily_pipeline.refresh_futu_readonly",
        lambda _settings, _store: SimpleNamespace(as_dict=lambda: {"ok": True}),
    )
    monkeypatch.setattr("invest_agent.daily_pipeline.MarketNewsIngestor.refresh_news", lambda self: {"ok": True})
    monkeypatch.setattr("invest_agent.daily_pipeline.MarketContextService.refresh_news", lambda self: {"ok": True})
    monkeypatch.setattr("invest_agent.daily_pipeline.SecCompanyFactsIngestor.refresh_fundamentals", lambda self: {"ok": True})
    monkeypatch.setattr(
        "invest_agent.daily_pipeline.QuoteHistoryService.refresh_batch",
        lambda self, request, actor=None: calls.append(request) or {"ok": True, "import_count": 0},
    )
    monkeypatch.setattr(
        "invest_agent.daily_pipeline.SignalEngine.run",
        lambda self, request, actor=None, trigger_source=None: SimpleNamespace(signals=[], metrics={"signal_count": 0}),
    )
    monkeypatch.setattr("invest_agent.daily_pipeline.SignalOutcomeEvaluator.evaluate", lambda self, limit=200: {"ok": True})
    monkeypatch.setattr("invest_agent.daily_pipeline.AdviceReadinessService.run", lambda self: {"score": 80})
    monkeypatch.setattr("invest_agent.daily_pipeline.DailyBriefService.run", lambda self, request, actor=None: {"brief": "ok"})

    result = DailySignalPipeline(settings, store).post_close()

    assert result["pipeline"] == "daily-post-close"
    assert calls
    assert calls[0].source == "auto"
    assert "benchmarks" in calls[0].symbols
    assert "recent_signals" in calls[0].symbols


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


def test_runtime_doctor_warns_when_daily_post_close_never_ran(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path)
    settings = settings.model_copy(update={"futu_read_enabled": False})
    monkeypatch.setattr("invest_agent.runtime_doctor.get_futu_status", lambda _settings: {"connected": False, "message": "disabled"})
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.discover_futu_accounts",
        lambda _settings: type("Discovery", (), {"as_dict": lambda self: {"account_count": 0, "selection_status": "disabled"}})(),
    )

    result = RuntimeDoctorService(settings, store).run()

    assert result["checks"]["daily_post_close_last_run"]["status"] == "warn"
    assert result["checks"]["daily_post_close_stale"]["status"] == "warn"


def test_runtime_doctor_warns_when_benchmark_price_bars_missing(tmp_path, monkeypatch) -> None:
    settings, store, _service = _store(tmp_path)
    settings = settings.model_copy(update={"futu_read_enabled": False})
    monkeypatch.setattr("invest_agent.runtime_doctor.get_futu_status", lambda _settings: {"connected": False, "message": "disabled"})
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.discover_futu_accounts",
        lambda _settings: type("Discovery", (), {"as_dict": lambda self: {"account_count": 0, "selection_status": "disabled"}})(),
    )

    result = RuntimeDoctorService(settings, store).run()

    benchmark = result["checks"]["benchmark_price_bars_present"]
    assert benchmark["status"] == "warn"
    assert set(benchmark["metrics"]["missing_symbols"]) == {"SPY", "QQQ"}


def test_launchd_daily_post_close_plist_runs_daily_post_close() -> None:
    plist_path = Path("deploy/launchd/com.local.invest-agent-daily-post-close.plist")
    payload = plistlib.loads(plist_path.read_bytes())
    command = " ".join(payload["ProgramArguments"])

    assert "daily-post-close" in command
    assert "autonomy-loop" not in command
    assert payload["StartCalendarInterval"] == {"Hour": 6, "Minute": 15}


def test_advice_readiness_reports_price_bar_source_metadata(tmp_path) -> None:
    settings, store, _service = _store(tmp_path)
    item = QuoteHistoryImport(source=QuoteHistorySource.STOOQ_HISTORICAL_CSV, symbol="AAPL", input_hash="x", dataset_hash="y")
    bar = PriceBar(
        import_id=item.id,
        symbol="AAPL",
        ts=utc_now(),
        open=100,
        high=101,
        low=99,
        close=100,
        source=QuoteHistorySource.STOOQ_HISTORICAL_CSV,
        source_provider="stooq",
        source_feed="historical_csv",
        quality_score=0.72,
        license_note="paper-only fallback",
        row_hash="aapl-test-bar",
    )
    store.create_quote_history_import(item, [bar])

    readiness = AdviceReadinessService(settings, store).run_for_symbol("AAPL")

    price_bar = readiness["checks"]["price_bar_coverage"]
    assert price_bar["metrics"]["source_provider"] == "stooq"
    assert price_bar["metrics"]["verified_primary_evidence"] is False


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
