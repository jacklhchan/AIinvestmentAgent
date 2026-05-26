from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from invest_agent.backtest_imports import BacktestImportService
from invest_agent.catalysts import CatalystCalendarService
from invest_agent.committee_reviews import CommitteeReviewService
from invest_agent.config import Settings
from invest_agent.daily_briefs import DailyBriefService
from invest_agent.data_bridge import DataBridgeService
from invest_agent.data_quality import DataQualityService
from invest_agent.demo_data import seed_demo_data
from invest_agent.dividend_lens import DividendLensService
from invest_agent.earnings_preview import EarningsPreviewService
from invest_agent.earnings_review import EarningsReviewService
from invest_agent.hypotheses import HypothesisRegistryService
from invest_agent.idea_inbox import IdeaInboxService
from invest_agent.models import (
    BacktestImportRequest,
    BehaviorReportRunRequest,
    CatalystCreate,
    CatalystEventType,
    CommitteeConclusion,
    CommitteeReviewRunRequest,
    CorrelationRunRequest,
    DailyBriefRunRequest,
    DataImportRequest,
    DataQualityRunRequest,
    DividendReviewRunRequest,
    EarningsPreviewRunRequest,
    EarningsReviewRunRequest,
    FundamentalMetric,
    FundamentalSnapshot,
    HypothesisCreate,
    HypothesisInvalidateRequest,
    HypothesisLinkCreate,
    HypothesisLinkType,
    IdeaCandidateCreate,
    IdeaDirection,
    IdeaScreenRunRequest,
    OptionsSnapshotCreate,
    PeerGroupCreate,
    PortfolioTarget,
    PriceBarConfidence,
    Quote,
    QuoteHistoryRefreshRequest,
    RebalanceCandidateStatus,
    RunCardActor,
    RunCardType,
    ShadowEventType,
    ShadowReportRunRequest,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    Thesis,
    ThesisSide,
    ThesisStatus,
    TradeJournalImportRequest,
    TradeJournalSource,
    utc_now,
)
from invest_agent.options_lens import OptionsLensService
from invest_agent.portfolio_studio import PortfolioStudioService
from invest_agent.quote_history import QuoteHistoryService
from invest_agent.sector_lens import SectorLensService
from invest_agent.services import InvestmentService
from invest_agent.shadow_account import ShadowAccountService
from invest_agent.skill_validator import SkillValidatorService
from invest_agent.store import Store
from invest_agent.trade_journal import TradeJournalService


def make_stack(tmp_path: Path):
    settings = Settings(db_path=tmp_path / "test.db", market_context_symbols="SPY,QQQ,VIXY,TLT,GLD,USO")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return settings, store


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def make_fundamentals(symbol: str = "AAPL") -> FundamentalSnapshot:
    filed_at = utc_now() - timedelta(days=2)

    def metric(name: str, yoy: float) -> FundamentalMetric:
        return FundamentalMetric(
            name=name,
            label=name,
            concept=name,
            value=100.0,
            unit="USD",
            fiscal_year=2026,
            fiscal_period="Q1",
            filed_at=filed_at,
            yoy_change_pct=yoy,
        )

    return FundamentalSnapshot(
        symbol=symbol,
        cik="0000320193",
        entity_name="Apple Inc.",
        metrics={
            "revenue": metric("revenue", 8.0),
            "net_income": metric("net_income", 7.0),
            "operating_cash_flow": metric("operating_cash_flow", 9.0),
            "eps_diluted": metric("eps_diluted", 6.0),
        },
    )


def test_hypothesis_registry_is_research_only(tmp_path) -> None:
    settings, store = make_stack(tmp_path)
    service = HypothesisRegistryService(store)
    before = len(store.list_proposals(limit=100))

    hypothesis = service.create(
        HypothesisCreate(title="AI capex cycle", statement="AI capex beneficiaries may outperform when revenue revisions rise.", symbols=["AAPL"]),
        actor=RunCardActor.MCP,
    )
    link = service.link(hypothesis.id, HypothesisLinkCreate(linked_type=HypothesisLinkType.RUN_CARD, linked_id="run_test"))
    invalidated = service.invalidate(hypothesis.id, HypothesisInvalidateRequest(invalidation_note="Evidence weakened."))

    assert hypothesis.human_confirmed is False
    assert link.hypothesis_id == hypothesis.id
    assert invalidated.invalidation_note == "Evidence weakened."
    assert len(store.list_proposals(limit=100)) == before


def test_portfolio_studio_creates_candidates_not_proposals(tmp_path) -> None:
    settings, store = make_stack(tmp_path)
    store.upsert_portfolio_target(PortfolioTarget(asset_class="equity", target_weight=0.4, min_weight=0.2, max_weight=0.5))
    before = len(store.list_proposals(limit=100))

    snapshot = PortfolioStudioService(settings, store).refresh_risk_snapshot(actor=RunCardActor.CLI)
    review = PortfolioStudioService(settings, store).run_rebalance_review(actor=RunCardActor.CLI)
    candidate = review.candidates[0]
    promoted = PortfolioStudioService(settings, store).promote_candidate_to_research_goal(candidate.id)

    assert snapshot.run_card_id
    assert review.run_card_id
    assert promoted.status == RebalanceCandidateStatus.PROMOTED_TO_RESEARCH_GOAL
    assert promoted.linked_research_goal_id
    assert len(store.list_proposals(limit=100)) == before


def test_earnings_preview_links_to_post_event_review(tmp_path) -> None:
    _settings, store = make_stack(tmp_path)
    store.upsert_fundamentals(make_fundamentals("AAPL"))
    catalyst = CatalystCalendarService(store).create_catalyst(
        CatalystCreate(
            symbol="AAPL",
            event_type=CatalystEventType.EARNINGS,
            title="AAPL earnings",
            event_date=utc_now() + timedelta(days=2),
        )
    )
    preview = EarningsPreviewService(store).run_preview(EarningsPreviewRunRequest(symbol="AAPL", catalyst_id=catalyst.id))
    catalyst.status = __import__("invest_agent.models", fromlist=["CatalystStatus"]).CatalystStatus.COMPLETED
    catalyst.event_date = utc_now() - timedelta(hours=1)
    store.update_catalyst(catalyst)
    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="AAPL", catalyst_id=catalyst.id))

    assert preview.run_card_id
    assert review.earnings_preview_id == preview.id


def test_quote_history_shadow_report_estimates_diagnostic_pnl_when_available(tmp_path) -> None:
    _settings, store = make_stack(tmp_path)
    trade_path = write_csv(
        tmp_path / "trades.csv",
        ["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"],
        [
            ["2026-01-01 09:30:00", "FAST", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-02 09:30:00", "FAST", "sell", "10", "108", "0", "USD", "US"],
            ["2026-01-01 09:30:00", "SLOW", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-11 09:30:00", "SLOW", "sell", "10", "112", "0", "USD", "US"],
            ["2026-01-01 09:30:00", "LOSS", "buy", "10", "100", "0", "USD", "US"],
            ["2026-01-11 09:30:00", "LOSS", "sell", "10", "95", "0", "USD", "US"],
        ],
    )
    TradeJournalService(store).import_csv(TradeJournalImportRequest(path=str(trade_path), source=TradeJournalSource.GENERIC_CSV))
    behavior = TradeJournalService(store).run_behavior_report(BehaviorReportRunRequest())
    strategy = ShadowAccountService(store).extract_strategy(ShadowStrategyExtractRequest(behavior_report_id=behavior.id))
    strategy = ShadowAccountService(store).confirm_strategy(strategy.id, ShadowStrategyConfirmRequest(confirmed_by="test"))
    quote_path = write_csv(
        tmp_path / "fast_bars.csv",
        ["date", "open", "high", "low", "close", "volume"],
        [[f"2026-01-{day:02d}", "100", "120", "90", str(100 + day), "1000"] for day in range(1, 13)],
    )
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="FAST", path=str(quote_path)), actor=RunCardActor.CLI)

    report = ShadowAccountService(store).run_report(ShadowReportRunRequest(strategy_id=strategy.id, use_quote_history=True))
    events = store.list_shadow_events(shadow_report_id=report.id)

    assert report.events_with_price_count >= 1
    assert report.counterfactual_coverage_ratio > 0
    assert any(event.expected_exit_price_confidence in {PriceBarConfidence.EXACT_BAR, PriceBarConfidence.NEXT_AVAILABLE_BAR} for event in events)
    assert any(event.event_type == ShadowEventType.EARLY_EXIT and event.delta_pnl is not None for event in events)


def test_backtest_import_and_data_bridge_safety(tmp_path) -> None:
    _settings, store = make_stack(tmp_path)
    bad_path = tmp_path / "bad_run_card.json"
    bad_path.write_text(json.dumps({"metrics": {"ir": 1.2}}), encoding="utf-8")
    with pytest.raises(ValueError, match="run_card_hash"):
        BacktestImportService(store).import_run_card(BacktestImportRequest(path=str(bad_path)))

    good_path = tmp_path / "run_card.json"
    good_path.write_text(
        json.dumps({"hashes": {"run_card_hash": "abc", "input_hash": "in"}, "strategy_name": "alpha", "metrics": {"ir": 1.2}}),
        encoding="utf-8",
    )
    imported = BacktestImportService(store).import_run_card(BacktestImportRequest(path=str(good_path)))
    assert imported.run_card_hash == "abc"

    bridge = DataBridgeService(store, import_root=tmp_path / "imports")
    bridge.import_root.mkdir(parents=True)
    csv_path = write_csv(
        bridge.import_root / "classifications.csv",
        ["symbol", "asset_class", "sector"],
        [["AAPL", "equity", "technology"]],
    )
    data_import = bridge.import_file(DataImportRequest(schema_name="symbol_classification", path=csv_path.name))
    assert data_import.row_count == 1
    assert store.get_symbol_classification("AAPL").sector == "technology"
    with pytest.raises(ValueError, match="path traversal"):
        bridge.import_file(DataImportRequest(schema_name="symbol_classification", path="../secret.csv"))


def test_daily_sector_options_dividend_idea_committee_and_data_quality_layers(tmp_path) -> None:
    settings, store = make_stack(tmp_path)
    before = len(store.list_proposals(limit=100))
    store.upsert_quote(Quote(symbol="SPY", last_price=99, previous_close=100, change_pct=-1.0))
    bars_path = write_csv(
        tmp_path / "bars.csv",
        ["date", "open", "high", "low", "close", "volume"],
        [
            ["2026-01-01", "100", "101", "99", "100", "0"],
            ["2026-01-02", "100", "102", "98", "101", "0"],
            ["2026-01-03", "101", "104", "100", "103", "0"],
        ],
    )
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="AAPL", path=str(bars_path)), actor=RunCardActor.CLI)
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="MSFT", path=str(bars_path)), actor=RunCardActor.CLI)

    brief = DailyBriefService(settings, store).run(DailyBriefRunRequest(), actor=RunCardActor.CLI)
    peer = SectorLensService(store).create_peer_group(PeerGroupCreate(name="Mega cap", sector="tech", symbols=["AAPL", "MSFT"]))
    corr = SectorLensService(store).run_correlation(CorrelationRunRequest(symbols=["AAPL", "MSFT"], lookback_days=500), actor=RunCardActor.CLI)
    from invest_agent.models import SectorSnapshotRunRequest

    sector = SectorLensService(store).run_sector_snapshot(SectorSnapshotRunRequest(sector="tech"), actor=RunCardActor.CLI)
    option = OptionsLensService(store).create_snapshot(OptionsSnapshotCreate(symbol="AAPL", expiry="2026-02-20", implied_move_pct=9.0))
    dividend = DividendLensService(store).run_review(DividendReviewRunRequest(symbol="AAPL", dividend_yield=0.03, payout_ratio=1.2))
    screen = IdeaInboxService(settings, store).run_screen(IdeaScreenRunRequest(symbols=["AAPL"]), actor=RunCardActor.CLI)
    idea = IdeaInboxService(settings, store).create_candidate(
        IdeaCandidateCreate(symbol="MSFT", direction=IdeaDirection.LONG, one_line_thesis="Cloud growth needs more evidence.")
    )
    promoted = IdeaInboxService(settings, store).promote_to_research_goal(idea.id)
    committee = CommitteeReviewService(store).run_review(
        CommitteeReviewRunRequest(topic="MSFT idea", missing_evidence=["verified source"], conclusion=CommitteeConclusion.ELIGIBLE_FOR_PROPOSAL)
    )
    quality = DataQualityService(store).run_report(DataQualityRunRequest(), actor=RunCardActor.CLI)
    skills = SkillValidatorService(store).validate(actor=RunCardActor.CLI)

    assert brief.run_card_id
    assert peer.symbols == ["AAPL", "MSFT"]
    assert corr.run_card_id and corr.warnings
    assert sector.run_card_id
    assert option.implied_move_pct == 9.0
    assert dividend.yield_trap_warning
    assert screen.run_card_id
    assert promoted.linked_research_goal_id
    assert committee.conclusion == CommitteeConclusion.RESEARCH_MORE
    assert quality.run_card_id and quality.severity_counts["outliers"] >= 1
    assert skills.issue_count == 0
    assert len(store.list_proposals(limit=100)) == before
