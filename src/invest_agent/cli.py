from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .backtest_imports import BacktestImportService
from .autonomy import SafeAutonomyRunner, autonomy_status
from .catalysts import CatalystCalendarService
from .committee_reviews import CommitteeReviewService
from .config import get_settings
from .daily_briefs import DailyBriefService
from .data_bridge import DataBridgeService
from .data_quality import DataQualityService
from .demo_data import seed_demo_data
from .deps import get_service, get_store
from .dividend_lens import DividendLensService
from .earnings_preview import EarningsPreviewService
from .earnings_review import EarningsReviewService
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file
from .futu_adapter import refresh_futu_readonly
from .hypotheses import HypothesisRegistryService
from .idea_inbox import IdeaInboxService
from .ir_feeds import IrFeedIngestor
from .market_regime import MarketRegimeService
from .market_news import MarketNewsIngestor
from .models import (
    BacktestImportRequest,
    EarningsReviewRunRequest,
    BehaviorReportRunRequest,
    CommitteeReviewRunRequest,
    CorrelationRunRequest,
    DailyBriefRunRequest,
    DataImportRequest,
    DataQualityRunRequest,
    DataQualityTargetType,
    DividendReviewRunRequest,
    EarningsPreviewRunRequest,
    ExternalBacktestSource,
    HypothesisCreate,
    HypothesisInvalidateRequest,
    HypothesisLinkCreate,
    HypothesisLinkType,
    HypothesisScope,
    IdeaScreenRunRequest,
    OptionsSnapshotCreate,
    PeerGroupCreate,
    ProposalCreate,
    QuoteHistoryRefreshRequest,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    SectorSnapshotRunRequest,
    ShadowReportRunRequest,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    Side,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .portfolio_studio import PortfolioStudioService
from .quote_history import QuoteHistoryService
from .run_cards import RunCardService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .sector_lens import SectorLensService
from .shadow_account import ShadowAccountService
from .skill_validator import SkillValidatorService
from .trade_journal import TradeJournalService


def seed_main() -> None:
    store = get_store()
    seed_demo_data(store, force=True)
    print(f"Seeded demo data at {get_settings().db_path}")


def smoke_main() -> None:
    service = get_service()
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=5,
            limit_price=175.70,
            thesis="Small paper allocation to validate proposal, approval and execution audit flow.",
            trigger="Smoke test from local CLI",
            confidence=0.61,
            evidence=["local smoke test"],
            manual_override_reason="CLI smoke test for paper-only proposal flow.",
        )
    )
    result = service.approve_proposal(proposal.id, approved_by="smoke-test")
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def futu_refresh_main() -> None:
    result = refresh_futu_readonly(get_settings(), get_store())
    print(
        json.dumps(
            {
                "source": result.source,
                "position_count": result.position_count,
                "quote_count": result.quote_count,
                "portfolio_source": result.portfolio.source,
                "updated_at": result.portfolio.updated_at.isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def news_refresh_main() -> None:
    result = MarketNewsIngestor(get_settings(), get_store()).refresh_news()
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def draft_proposals_main() -> None:
    result = ProposalDraftEngine(get_settings(), get_store(), get_service()).draft_from_watchlist()
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def draft_and_create_main() -> None:
    result = ProposalDraftEngine(get_settings(), get_store(), get_service()).draft_from_watchlist(create_proposals=True)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def primary_refresh_main() -> None:
    settings = get_settings()
    store = get_store()
    result = refresh_primary_sources(SecEdgarIngestor(settings, store), IrFeedIngestor(settings, store))
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def fundamentals_refresh_main() -> None:
    result = SecCompanyFactsIngestor(get_settings(), get_store()).refresh_fundamentals()
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def event_export_main(path: str | None = None) -> None:
    result = export_event_replay(
        get_store(),
        path or DEFAULT_REPLAY_PATH,
        actor=RunCardActor.CLI,
        trigger_source=RunCardTriggerSource.REPLAY,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def event_replay_main(path: str | None = None) -> None:
    result = replay_event_file(get_settings(), get_store(), path or DEFAULT_REPLAY_PATH)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def autonomy_once_main() -> None:
    result = SafeAutonomyRunner(get_settings(), get_store(), get_service()).run_cycle(mode="cli-once")
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def autonomy_loop_main() -> None:
    SafeAutonomyRunner(get_settings(), get_store(), get_service()).run_forever()


def autonomy_status_main() -> None:
    print(json.dumps(autonomy_status(get_settings(), get_store()), indent=2, ensure_ascii=False))


def list_theses_main() -> None:
    print(json.dumps(_json(get_store().list_theses()), indent=2, ensure_ascii=False))


def list_catalysts_main(days: int | None = None) -> None:
    service = CatalystCalendarService(get_store())
    if days is not None:
        result = service.list_upcoming(days=days)
    else:
        result = get_store().list_catalysts()
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def market_regime_main(refresh: bool = False) -> None:
    service = MarketRegimeService(get_settings(), get_store())
    result = service.refresh(actor=RunCardActor.CLI) if refresh else service.build_snapshot()
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_hypotheses_main() -> None:
    print(json.dumps(_json(get_store().list_hypotheses()), indent=2, ensure_ascii=False))


def show_hypothesis_main(hypothesis_id: str) -> None:
    item = get_store().get_hypothesis(hypothesis_id)
    if not item:
        raise SystemExit(f"hypothesis not found: {hypothesis_id}")
    print(json.dumps(_json(item), indent=2, ensure_ascii=False))


def create_hypothesis_main(title: str, statement: str, symbols: str | None = None) -> None:
    result = HypothesisRegistryService(get_store()).create(
        HypothesisCreate(
            title=title,
            statement=statement,
            scope=HypothesisScope.SYMBOL,
            symbols=_parse_symbols(symbols) or [],
        ),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def link_hypothesis_main(hypothesis_id: str, linked_id: str, linked_type: str = "run_card") -> None:
    result = HypothesisRegistryService(get_store()).link(
        hypothesis_id,
        HypothesisLinkCreate(linked_type=HypothesisLinkType(linked_type), linked_id=linked_id),
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def invalidate_hypothesis_main(hypothesis_id: str, note: str) -> None:
    result = HypothesisRegistryService(get_store()).invalidate(hypothesis_id, HypothesisInvalidateRequest(invalidation_note=note))
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def portfolio_risk_main() -> None:
    result = PortfolioStudioService(get_settings(), get_store()).refresh_risk_snapshot(actor=RunCardActor.CLI)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def rebalance_review_main() -> None:
    result = PortfolioStudioService(get_settings(), get_store()).run_rebalance_review(actor=RunCardActor.CLI)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def earnings_review_main(
    symbol: str,
    catalyst_id: str | None = None,
    research_goal_id: str | None = None,
    thesis_id: str | None = None,
) -> None:
    result = EarningsReviewService(get_store()).run_review(
        EarningsReviewRunRequest(
            symbol=symbol,
            catalyst_id=catalyst_id,
            research_goal_id=research_goal_id,
            thesis_id=thesis_id,
        ),
        actor=RunCardActor.CLI,
        trigger_source=RunCardTriggerSource.MANUAL,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_earnings_reviews_main(symbol: str | None = None) -> None:
    print(json.dumps(_json(get_store().list_earnings_reviews(symbol=symbol)), indent=2, ensure_ascii=False))


def earnings_preview_main(symbol: str, catalyst_id: str | None = None, thesis_id: str | None = None) -> None:
    result = EarningsPreviewService(get_store()).run_preview(
        EarningsPreviewRunRequest(symbol=symbol, catalyst_id=catalyst_id, thesis_id=thesis_id),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_earnings_previews_main(symbol: str | None = None) -> None:
    print(json.dumps(_json(get_store().list_earnings_previews(symbol=symbol)), indent=2, ensure_ascii=False))


def quote_history_refresh_main(symbol: str, path: str | None = None, days: int = 365) -> None:
    result = QuoteHistoryService(get_store()).refresh(
        QuoteHistoryRefreshRequest(symbol=symbol, path=path, days=days),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_price_bars_main(symbol: str | None = None, limit: int = 20) -> None:
    print(json.dumps(_json(get_store().list_price_bars(symbol=symbol, limit=limit)), indent=2, ensure_ascii=False))


def import_backtest_main(path: str, source: str = "manual") -> None:
    result = BacktestImportService(get_store()).import_run_card(
        BacktestImportRequest(path=path, source=ExternalBacktestSource(source)),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_backtest_imports_main() -> None:
    print(json.dumps(_json(get_store().list_external_backtest_imports()), indent=2, ensure_ascii=False))


def show_backtest_import_main(import_id: str) -> None:
    item = get_store().get_external_backtest_import(import_id)
    if not item:
        raise SystemExit(f"backtest import not found: {import_id}")
    print(json.dumps(_json(item), indent=2, ensure_ascii=False))


def data_import_main(schema_name: str, path: str, source_name: str = "local") -> None:
    result = DataBridgeService(get_store()).import_file(
        DataImportRequest(schema_name=schema_name, path=path, source_name=source_name),
        actor=RunCardActor.CLI,
        allow_absolute=True,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_data_imports_main() -> None:
    print(json.dumps(_json(get_store().list_data_imports()), indent=2, ensure_ascii=False))


def daily_brief_main(brief_type: str = "morning") -> None:
    from .models import DailyBriefType

    result = DailyBriefService(get_settings(), get_store()).run(
        DailyBriefRunRequest(brief_type=DailyBriefType(brief_type)),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def correlation_run_main(symbols: str | None = None) -> None:
    result = SectorLensService(get_store()).run_correlation(
        CorrelationRunRequest(symbols=_parse_symbols(symbols) or []),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def sector_snapshot_main(sector: str, symbols: str | None = None) -> None:
    result = SectorLensService(get_store()).run_sector_snapshot(
        SectorSnapshotRunRequest(sector=sector, symbols=_parse_symbols(symbols) or []),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def import_options_snapshot_main(symbol: str, expiry: str, implied_move_pct: float | None = None, atm_iv: float | None = None) -> None:
    from .options_lens import OptionsLensService

    result = OptionsLensService(get_store()).create_snapshot(
        OptionsSnapshotCreate(symbol=symbol, expiry=expiry, implied_move_pct=implied_move_pct, atm_iv=atm_iv),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def dividend_review_main(symbol: str, dividend_yield: float | None = None, payout_ratio: float | None = None) -> None:
    result = DividendLensService(get_store()).run_review(
        DividendReviewRunRequest(symbol=symbol, dividend_yield=dividend_yield, payout_ratio=payout_ratio),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def idea_screen_main() -> None:
    result = IdeaInboxService(get_settings(), get_store()).run_screen(IdeaScreenRunRequest(), actor=RunCardActor.CLI)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_ideas_main() -> None:
    print(json.dumps(_json(get_store().list_idea_candidates()), indent=2, ensure_ascii=False))


def committee_review_main(topic: str) -> None:
    result = CommitteeReviewService(get_store()).run_review(CommitteeReviewRunRequest(topic=topic), actor=RunCardActor.CLI)
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def validate_skills_main() -> None:
    print(json.dumps(_json(SkillValidatorService(get_store()).validate(actor=RunCardActor.CLI)), indent=2, ensure_ascii=False))


def data_quality_main(target_type: str = "all") -> None:
    result = DataQualityService(get_store()).run_report(
        DataQualityRunRequest(target_type=DataQualityTargetType(target_type)),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_data_quality_reports_main() -> None:
    print(json.dumps(_json(get_store().list_data_quality_reports()), indent=2, ensure_ascii=False))


def list_run_cards_main(run_type: str | None = None, symbol: str | None = None, limit: int = 20) -> None:
    parsed_type = RunCardType(run_type) if run_type else None
    print(
        json.dumps(
            _json(get_store().list_run_cards(run_type=parsed_type, symbol=symbol, limit=limit)),
            indent=2,
            ensure_ascii=False,
        )
    )


def show_run_card_main(run_card_id: str, kind: str | None = None) -> None:
    if kind:
        print(RunCardService(get_store()).get_artifact_text(run_card_id, kind=kind))
        return
    print(json.dumps(_json(RunCardService(get_store()).require_run_card(run_card_id)), indent=2, ensure_ascii=False))


def import_trade_journal_main(path: str, source: str) -> None:
    result = TradeJournalService(get_store()).import_csv(
        TradeJournalImportRequest(path=path, source=TradeJournalSource(source)),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def behavior_report_main(
    period_start: str | None = None,
    period_end: str | None = None,
    symbols: str | None = None,
) -> None:
    result = TradeJournalService(get_store()).run_behavior_report(
        BehaviorReportRunRequest(
            period_start=_parse_cli_datetime(period_start),
            period_end=_parse_cli_datetime(period_end),
            symbols=_parse_symbols(symbols),
        ),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_behavior_reports_main(symbol: str | None = None, limit: int = 20) -> None:
    print(json.dumps(_json(get_store().list_behavior_reports(symbol=symbol, limit=limit)), indent=2, ensure_ascii=False))


def show_behavior_report_main(report_id: str) -> None:
    item = get_store().get_behavior_report(report_id)
    if not item:
        raise SystemExit(f"behavior report not found: {report_id}")
    print(json.dumps(_json(item), indent=2, ensure_ascii=False))


def list_trade_roundtrips_main(symbol: str | None = None, limit: int = 20) -> None:
    print(json.dumps(_json(get_store().list_trade_roundtrips(symbol=symbol, limit=limit)), indent=2, ensure_ascii=False))


def extract_shadow_strategy_main(report_id: str, name: str | None = None) -> None:
    result = ShadowAccountService(get_store()).extract_strategy(
        ShadowStrategyExtractRequest(behavior_report_id=report_id, name=name),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def confirm_shadow_strategy_main(strategy_id: str, confirmed_by: str | None = None) -> None:
    result = ShadowAccountService(get_store()).confirm_strategy(
        strategy_id,
        ShadowStrategyConfirmRequest(human_confirmed=True, confirmed_by=confirmed_by or "local-user"),
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def run_shadow_report_main(
    strategy_id: str,
    behavior_report_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    symbols: str | None = None,
    use_quote_history: bool = False,
) -> None:
    result = ShadowAccountService(get_store()).run_report(
        ShadowReportRunRequest(
            strategy_id=strategy_id,
            behavior_report_id=behavior_report_id,
            period_start=_parse_cli_datetime(period_start),
            period_end=_parse_cli_datetime(period_end),
            symbols=_parse_symbols(symbols),
            use_quote_history=use_quote_history,
        ),
        actor=RunCardActor.CLI,
    )
    print(json.dumps(_json(result), indent=2, ensure_ascii=False))


def list_shadow_strategies_main(limit: int = 20) -> None:
    print(json.dumps(_json(get_store().list_shadow_strategies(limit=limit)), indent=2, ensure_ascii=False))


def list_shadow_reports_main(strategy_id: str | None = None, limit: int = 20) -> None:
    print(json.dumps(_json(get_store().list_shadow_reports(strategy_id=strategy_id, limit=limit)), indent=2, ensure_ascii=False))


def show_shadow_report_main(report_id: str) -> None:
    report = get_store().get_shadow_report(report_id)
    if not report:
        raise SystemExit(f"shadow report not found: {report_id}")
    print(json.dumps(_json(report), indent=2, ensure_ascii=False))


def _parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_symbols(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Investment Agent helper commands")
    parser.add_argument(
        "command",
        choices=[
            "seed",
            "smoke",
            "futu-refresh",
            "news-refresh",
            "draft-proposals",
            "draft-and-create",
            "primary-refresh",
            "fundamentals-refresh",
            "event-export",
            "event-replay",
            "autonomy-once",
            "autonomy-loop",
            "autonomy-status",
            "market-regime",
            "list-theses",
            "list-catalysts",
            "catalyst-preview",
            "list-hypotheses",
            "show-hypothesis",
            "create-hypothesis",
            "link-hypothesis",
            "invalidate-hypothesis",
            "portfolio-risk",
            "rebalance-review",
            "earnings-preview",
            "list-earnings-previews",
            "earnings-review",
            "list-earnings-reviews",
            "quote-history-refresh",
            "list-price-bars",
            "import-backtest-run-card",
            "list-backtest-imports",
            "show-backtest-import",
            "data-import",
            "list-data-imports",
            "morning-brief",
            "close-brief",
            "weekly-brief",
            "correlation-run",
            "sector-snapshot",
            "import-options-snapshot",
            "list-options-snapshots",
            "dividend-review",
            "idea-screen",
            "list-ideas",
            "committee-review",
            "validate-skills",
            "data-quality-run",
            "list-data-quality-reports",
            "list-run-cards",
            "show-run-card",
            "import-trade-journal",
            "behavior-report",
            "list-behavior-reports",
            "show-behavior-report",
            "list-trade-roundtrips",
            "extract-shadow-strategy",
            "confirm-shadow-strategy",
            "run-shadow-report",
            "list-shadow-strategies",
            "list-shadow-reports",
            "show-shadow-report",
        ],
    )
    parser.add_argument("--path", default=None)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--catalyst-id", default=None)
    parser.add_argument("--research-goal-id", default=None)
    parser.add_argument("--thesis-id", default=None)
    parser.add_argument("--run-type", default=None)
    parser.add_argument("--run-card-id", default=None)
    parser.add_argument("--source", default="futu_csv")
    parser.add_argument("--period-start", default=None)
    parser.add_argument("--period-end", default=None)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--report-id", default=None)
    parser.add_argument("--strategy-id", default=None)
    parser.add_argument("--behavior-report-id", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--confirmed-by", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--kind", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--statement", default=None)
    parser.add_argument("--hypothesis-id", default=None)
    parser.add_argument("--linked-id", default=None)
    parser.add_argument("--linked-type", default="run_card")
    parser.add_argument("--note", default=None)
    parser.add_argument("--schema", default=None)
    parser.add_argument("--source-name", default="local")
    parser.add_argument("--import-id", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--expiry", default=None)
    parser.add_argument("--implied-move-pct", type=float, default=None)
    parser.add_argument("--atm-iv", type=float, default=None)
    parser.add_argument("--dividend-yield", type=float, default=None)
    parser.add_argument("--payout-ratio", type=float, default=None)
    parser.add_argument("--target-type", default="all")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--use-quote-history", action="store_true")
    args = parser.parse_args()
    if args.command == "seed":
        seed_main()
    if args.command == "smoke":
        smoke_main()
    if args.command == "futu-refresh":
        futu_refresh_main()
    if args.command == "news-refresh":
        news_refresh_main()
    if args.command == "draft-proposals":
        draft_proposals_main()
    if args.command == "draft-and-create":
        draft_and_create_main()
    if args.command == "primary-refresh":
        primary_refresh_main()
    if args.command == "fundamentals-refresh":
        fundamentals_refresh_main()
    if args.command == "event-export":
        event_export_main(args.path)
    if args.command == "event-replay":
        event_replay_main(args.path)
    if args.command == "autonomy-once":
        autonomy_once_main()
    if args.command == "autonomy-loop":
        autonomy_loop_main()
    if args.command == "autonomy-status":
        autonomy_status_main()
    if args.command == "market-regime":
        market_regime_main(args.refresh)
    if args.command == "list-theses":
        list_theses_main()
    if args.command == "list-catalysts":
        list_catalysts_main(args.days)
    if args.command == "catalyst-preview":
        list_catalysts_main(args.days or 14)
    if args.command == "list-hypotheses":
        list_hypotheses_main()
    if args.command == "show-hypothesis":
        if not args.hypothesis_id:
            parser.error("--hypothesis-id is required for show-hypothesis")
        show_hypothesis_main(args.hypothesis_id)
    if args.command == "create-hypothesis":
        if not args.title or not args.statement:
            parser.error("--title and --statement are required for create-hypothesis")
        create_hypothesis_main(args.title, args.statement, args.symbols)
    if args.command == "link-hypothesis":
        if not args.hypothesis_id or not args.linked_id:
            parser.error("--hypothesis-id and --linked-id are required for link-hypothesis")
        link_hypothesis_main(args.hypothesis_id, args.linked_id, args.linked_type)
    if args.command == "invalidate-hypothesis":
        if not args.hypothesis_id or not args.note:
            parser.error("--hypothesis-id and --note are required for invalidate-hypothesis")
        invalidate_hypothesis_main(args.hypothesis_id, args.note)
    if args.command == "portfolio-risk":
        portfolio_risk_main()
    if args.command == "rebalance-review":
        rebalance_review_main()
    if args.command == "earnings-preview":
        if not args.symbol:
            parser.error("--symbol is required for earnings-preview")
        earnings_preview_main(args.symbol, args.catalyst_id, args.thesis_id)
    if args.command == "list-earnings-previews":
        list_earnings_previews_main(args.symbol)
    if args.command == "earnings-review":
        if not args.symbol:
            parser.error("--symbol is required for earnings-review")
        earnings_review_main(args.symbol, args.catalyst_id, args.research_goal_id, args.thesis_id)
    if args.command == "list-earnings-reviews":
        list_earnings_reviews_main(args.symbol)
    if args.command == "quote-history-refresh":
        if not args.symbol:
            parser.error("--symbol is required for quote-history-refresh")
        quote_history_refresh_main(args.symbol, args.path, args.days or 365)
    if args.command == "list-price-bars":
        list_price_bars_main(args.symbol, args.limit)
    if args.command == "import-backtest-run-card":
        if not args.path:
            parser.error("--path is required for import-backtest-run-card")
        import_backtest_main(args.path, args.source)
    if args.command == "list-backtest-imports":
        list_backtest_imports_main()
    if args.command == "show-backtest-import":
        if not args.import_id:
            parser.error("--import-id is required for show-backtest-import")
        show_backtest_import_main(args.import_id)
    if args.command == "data-import":
        if not args.schema or not args.path:
            parser.error("--schema and --path are required for data-import")
        data_import_main(args.schema, args.path, args.source_name)
    if args.command == "list-data-imports":
        list_data_imports_main()
    if args.command == "morning-brief":
        daily_brief_main("morning")
    if args.command == "close-brief":
        daily_brief_main("close")
    if args.command == "weekly-brief":
        daily_brief_main("weekly")
    if args.command == "correlation-run":
        correlation_run_main(args.symbols)
    if args.command == "sector-snapshot":
        if not args.sector:
            parser.error("--sector is required for sector-snapshot")
        sector_snapshot_main(args.sector, args.symbols)
    if args.command == "import-options-snapshot":
        if not args.symbol or not args.expiry:
            parser.error("--symbol and --expiry are required for import-options-snapshot")
        import_options_snapshot_main(args.symbol, args.expiry, args.implied_move_pct, args.atm_iv)
    if args.command == "list-options-snapshots":
        print(json.dumps(_json(get_store().list_options_snapshots(symbol=args.symbol)), indent=2, ensure_ascii=False))
    if args.command == "dividend-review":
        if not args.symbol:
            parser.error("--symbol is required for dividend-review")
        dividend_review_main(args.symbol, args.dividend_yield, args.payout_ratio)
    if args.command == "idea-screen":
        idea_screen_main()
    if args.command == "list-ideas":
        list_ideas_main()
    if args.command == "committee-review":
        if not args.topic:
            parser.error("--topic is required for committee-review")
        committee_review_main(args.topic)
    if args.command == "validate-skills":
        validate_skills_main()
    if args.command == "data-quality-run":
        data_quality_main(args.target_type)
    if args.command == "list-data-quality-reports":
        list_data_quality_reports_main()
    if args.command == "list-run-cards":
        list_run_cards_main(args.run_type, args.symbol, args.limit)
    if args.command == "show-run-card":
        if not args.run_card_id:
            parser.error("--run-card-id is required for show-run-card")
        show_run_card_main(args.run_card_id, args.kind)
    if args.command == "import-trade-journal":
        if not args.path:
            parser.error("--path is required for import-trade-journal")
        import_trade_journal_main(args.path, args.source)
    if args.command == "behavior-report":
        behavior_report_main(args.period_start, args.period_end, args.symbols)
    if args.command == "list-behavior-reports":
        list_behavior_reports_main(args.symbol, args.limit)
    if args.command == "show-behavior-report":
        if not args.report_id:
            parser.error("--report-id is required for show-behavior-report")
        show_behavior_report_main(args.report_id)
    if args.command == "list-trade-roundtrips":
        list_trade_roundtrips_main(args.symbol, args.limit)
    if args.command == "extract-shadow-strategy":
        report_id = args.behavior_report_id or args.report_id
        if not report_id:
            parser.error("--behavior-report-id is required for extract-shadow-strategy")
        extract_shadow_strategy_main(report_id, args.name)
    if args.command == "confirm-shadow-strategy":
        if not args.strategy_id:
            parser.error("--strategy-id is required for confirm-shadow-strategy")
        confirm_shadow_strategy_main(args.strategy_id, args.confirmed_by)
    if args.command == "run-shadow-report":
        if not args.strategy_id:
            parser.error("--strategy-id is required for run-shadow-report")
        run_shadow_report_main(
            args.strategy_id,
            args.behavior_report_id,
            args.period_start,
            args.period_end,
            args.symbols,
            args.use_quote_history,
        )
    if args.command == "list-shadow-strategies":
        list_shadow_strategies_main(args.limit)
    if args.command == "list-shadow-reports":
        list_shadow_reports_main(args.strategy_id, args.limit)
    if args.command == "show-shadow-report":
        if not args.report_id:
            parser.error("--report-id is required for show-shadow-report")
        show_shadow_report_main(args.report_id)


if __name__ == "__main__":
    main()
