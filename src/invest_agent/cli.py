from __future__ import annotations

import argparse
import json

from .autonomy import SafeAutonomyRunner, autonomy_status
from .config import get_settings
from .demo_data import seed_demo_data
from .deps import get_service, get_store
from .event_replay import DEFAULT_REPLAY_PATH, export_event_replay, replay_event_file
from .futu_adapter import refresh_futu_readonly
from .ir_feeds import IrFeedIngestor
from .market_news import MarketNewsIngestor
from .models import ProposalCreate, Side
from .primary_sources import refresh_primary_sources
from .proposal_drafts import ProposalDraftEngine
from .sec_companyfacts import SecCompanyFactsIngestor
from .sec_edgar import SecEdgarIngestor


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
    result = export_event_replay(get_store(), path or DEFAULT_REPLAY_PATH)
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
        ],
    )
    parser.add_argument("--path", default=str(DEFAULT_REPLAY_PATH))
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


if __name__ == "__main__":
    main()
