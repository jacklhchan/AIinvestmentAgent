from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .autonomy import SafeAutonomyRunner, autonomy_status
from .catalysts import CatalystCalendarService
from .config import get_settings
from .demo_data import seed_demo_data
from .deps import get_service, get_store
from .earnings_review import EarningsReviewService
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file
from .futu_adapter import refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor
from .models import (
    EarningsReviewRunRequest,
    BehaviorReportRunRequest,
    ProposalCreate,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ShadowReportRunRequest,
    ShadowStrategyConfirmRequest,
    ShadowStrategyExtractRequest,
    Side,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .run_cards import RunCardService
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor
from .shadow_account import ShadowAccountService
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
) -> None:
    result = ShadowAccountService(get_store()).run_report(
        ShadowReportRunRequest(
            strategy_id=strategy_id,
            behavior_report_id=behavior_report_id,
            period_start=_parse_cli_datetime(period_start),
            period_end=_parse_cli_datetime(period_end),
            symbols=_parse_symbols(symbols),
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
            "list-theses",
            "list-catalysts",
            "catalyst-preview",
            "earnings-review",
            "list-earnings-reviews",
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
    if args.command == "list-theses":
        list_theses_main()
    if args.command == "list-catalysts":
        list_catalysts_main(args.days)
    if args.command == "catalyst-preview":
        list_catalysts_main(args.days or 14)
    if args.command == "earnings-review":
        if not args.symbol:
            parser.error("--symbol is required for earnings-review")
        earnings_review_main(args.symbol, args.catalyst_id, args.research_goal_id, args.thesis_id)
    if args.command == "list-earnings-reviews":
        list_earnings_reviews_main(args.symbol)
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
        run_shadow_report_main(args.strategy_id, args.behavior_report_id, args.period_start, args.period_end, args.symbols)
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
