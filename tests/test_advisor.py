from __future__ import annotations

import csv
from pathlib import Path
from datetime import datetime, timezone

from invest_agent.advisor import AdvisorService
from invest_agent.advisor_orchestrator import AdvisorOrchestrator
from invest_agent.advisor_scheduler import AdvisorSchedulerRunner
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    AdvisorBriefRequest,
    AdvisorFullBriefType,
    AdvisorProfileConfirmationRequest,
    AdvisorProfileUpdateRequest,
    AdvisorProfileUpdateStatus,
    AdvisorQuestionRequest,
    AdvisorSeverity,
    Quote,
    RunCardActor,
    RunCardType,
    SymbolResolutionStatus,
    ThesisCreate,
    TradeJournalImportRequest,
    TradeJournalSource,
)
from invest_agent.store import Store
from invest_agent.thesis_tracker import ThesisTrackerService
from invest_agent.trade_journal import TradeJournalService


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def write_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["datetime", "symbol", "side", "quantity", "price", "fee", "currency", "market"])
        writer.writerows(
            [
                ["2026-01-01 09:30:00", "AAPL", "buy", "10", "100", "0", "USD", "US"],
                ["2026-01-03 09:30:00", "AAPL", "sell", "10", "110", "0", "USD", "US"],
            ]
        )
    return path


def test_advisor_brief_explains_missing_behavior_report(tmp_path) -> None:
    store = make_store(tmp_path)

    brief = AdvisorService(store).build_brief()

    assert brief.paper_only is True
    assert any(item.category == "behavior" for item in brief.advice)
    assert brief.risk_level in {AdvisorSeverity.WATCH, AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED}


def test_advisor_brief_can_run_light_behavior_analysis_without_creating_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    TradeJournalService(store).import_csv(
        TradeJournalImportRequest(path=str(write_csv(tmp_path / "trades.csv")), source=TradeJournalSource.GENERIC_CSV),
        actor=RunCardActor.CLI,
    )
    proposal_count = len(store.list_proposals(limit=100))

    brief = AdvisorService(store).build_brief(AdvisorBriefRequest(run_light_analysis=True))

    assert brief.automated_actions
    assert brief.data_status["behavior_report_id"]
    assert len(store.list_behavior_reports(limit=10)) == 1
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_mcp_exposes_advisor_brief() -> None:
    import invest_agent.mcp_server as mcp_server

    assert hasattr(mcp_server, "get_advisor_brief")
    assert hasattr(mcp_server, "ask_advisor")
    assert hasattr(mcp_server, "run_hourly_advisor_pulse")
    assert hasattr(mcp_server, "run_pre_market_advisor_brief")
    assert hasattr(mcp_server, "run_post_close_advisor_brief")
    assert hasattr(mcp_server, "get_latest_advisor_brief")
    assert hasattr(mcp_server, "get_advisor_profile")
    assert hasattr(mcp_server, "suggest_advisor_profile_update")
    assert hasattr(mcp_server, "confirm_advisor_profile_update")


def test_ask_advisor_returns_concise_card_without_proposal_side_effect(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="Hermes，我而家應唔應該買 AAPL？", symbol="AAPL")
    )

    assert answer.paper_only is True
    assert answer.recommendation_type in {
        AdvisorSeverity.ACTION,
        AdvisorSeverity.WATCH,
        AdvisorSeverity.BLOCKED,
        AdvisorSeverity.INFO,
    }
    assert len(answer.reasons) <= 3
    assert len(answer.risks) <= 3
    assert answer.details_available is True
    assert answer.provenance_json["audit_level"] == "advisor_question_run_card"
    assert answer.provenance_json["full_advisor_brief_run"] is False
    assert "advisor_question_run_card" in answer.provenance_json["executed_layers"]
    assert "research_goal_created" in answer.provenance_json["not_run"]
    assert "evidence_gate_run" in answer.provenance_json["not_run"]
    assert answer.provenance_json["side_effects"]["proposal_created"] is False
    assert len(store.list_advisor_questions(limit=10)) == 1
    assert store.list_advisor_recommendations(limit=10)
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_advisor_answer_provenance_marks_lightweight_not_full_stack(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="Should I buy AAPL now?", symbol="AAPL")
    )

    provenance = answer.provenance_json
    assert provenance["answer_scope"] == "advisor_question"
    assert provenance["audit_level"] == "advisor_question_run_card"
    assert provenance["full_advisor_brief_run"] is False
    assert provenance["external_shell_or_web_used_by_control_plane"] is False
    assert "lightweight_advisor_brief" in provenance["executed_layers"]
    assert "market_context_snapshot" in provenance["executed_layers"]
    assert "market_regime_snapshot" in provenance["executed_layers"]
    assert "cached_thesis_lookup" in provenance["executed_layers"]
    assert "new_earnings_review" in provenance["not_run"]
    assert "committee_review" in provenance["not_run"]
    assert "proposal_created" in provenance["not_run"]
    assert provenance["side_effects"] == {
        "research_goal_created": False,
        "proposal_created": False,
        "proposal_approved": False,
        "trade_executed": False,
    }
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_profile_update_requires_confirmation_before_applying(tmp_path) -> None:
    store = make_store(tmp_path)
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))

    update = orchestrator.suggest_profile_update(
        AdvisorProfileUpdateRequest(
            risk_profile="moderate_conservative",
            max_single_stock_weight=0.2,
            prefer_core_etf=True,
            avoid_chasing_after_big_move=True,
            rationale="User repeatedly said they prefer ETF-first and do not want to chase.",
            source_question_id="advq_test",
        )
    )

    assert update.status == AdvisorProfileUpdateStatus.PENDING
    assert store.get_advisor_profile() is None
    assert store.list_advisor_profile_updates(status=AdvisorProfileUpdateStatus.PENDING, limit=10)

    confirmed = orchestrator.confirm_profile_update(
        update.id,
        AdvisorProfileConfirmationRequest(confirmed=True, confirmed_by="test-user"),
    )
    profile = store.get_advisor_profile()

    assert confirmed.status == AdvisorProfileUpdateStatus.CONFIRMED
    assert confirmed.applied_profile_version == 1
    assert profile is not None
    assert profile.version == 1
    assert profile.risk_profile.value == "moderate_conservative"
    assert profile.max_single_stock_weight == 0.2
    assert profile.prefer_core_etf is True
    assert profile.avoid_chasing_after_big_move is True


def test_rejected_profile_update_does_not_apply(tmp_path) -> None:
    store = make_store(tmp_path)
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))
    update = orchestrator.suggest_profile_update(
        AdvisorProfileUpdateRequest(
            allow_options=True,
            rationale="User mentioned maybe using options, but did not confirm.",
        )
    )

    rejected = orchestrator.confirm_profile_update(
        update.id,
        AdvisorProfileConfirmationRequest(confirmed=False, confirmed_by="test-user", rejection_reason="Not now"),
    )

    assert rejected.status == AdvisorProfileUpdateStatus.REJECTED
    assert rejected.rejection_reason == "Not now"
    assert store.get_advisor_profile() is None


def test_ask_advisor_uses_confirmed_profile_without_proposal_side_effect(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))
    update = orchestrator.suggest_profile_update(
        AdvisorProfileUpdateRequest(
            risk_profile="moderate_conservative",
            avoid_chasing_after_big_move=True,
            rationale="User confirmed they do not want to chase after large moves.",
        )
    )
    orchestrator.confirm_profile_update(update.id, AdvisorProfileConfirmationRequest(confirmed_by="test-user"))
    store.upsert_quote(
        Quote(
            symbol="AAPL",
            last_price=220,
            previous_close=205,
            change_pct=7.32,
            updated_at=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
            source="test",
        )
    )

    answer = orchestrator.answer_user_question(AdvisorQuestionRequest(question="Should I buy AAPL now?", symbol="AAPL"))

    assert answer.recommendation_type == AdvisorSeverity.BLOCKED
    assert any("profile" in reason.lower() or "不追高" in reason for reason in answer.reasons)
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_ask_advisor_ignores_bad_symbol_for_portfolio_strategy(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(
            question="What is the recommended strategy for tonight for my current portfolio?",
            symbol="WHAT",
        )
    )
    question = store.list_advisor_questions(limit=1)[0]

    assert question.symbol is None
    assert question.original_symbol == "WHAT"
    assert question.resolved_symbol is None
    assert question.symbol_resolution_status == SymbolResolutionStatus.PORTFOLIO_SCOPE
    assert answer.symbol_resolution_status == SymbolResolutionStatus.PORTFOLIO_SCOPE
    assert answer.recommendation_type in {AdvisorSeverity.WATCH, AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED}
    assert "WHAT" not in answer.conclusion
    assert "Portfolio" in answer.conclusion
    assert len(answer.reasons) <= 3
    assert len(answer.risks) <= 3
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_ask_advisor_blocks_private_ipo_instead_of_treating_ipo_as_symbol(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(
            question="what about the spacex ipo, should i invest? and for how much?",
            symbol="IPO",
        )
    )
    question = store.list_advisor_questions(limit=1)[0]

    assert question.symbol is None
    assert question.original_symbol == "IPO"
    assert question.resolved_symbol is None
    assert question.symbol_resolution_status == SymbolResolutionStatus.PRIVATE_COMPANY
    assert answer.symbol_resolution_status == SymbolResolutionStatus.PRIVATE_COMPANY
    assert answer.recommendation_type == AdvisorSeverity.BLOCKED
    assert "SpaceX IPO" in answer.conclusion
    assert "proposal" in answer.summary.lower()
    assert len(answer.reasons) <= 3
    assert len(answer.risks) <= 3
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_ask_advisor_common_uppercase_words_are_not_symbols(tmp_path) -> None:
    store = make_store(tmp_path)
    orchestrator = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db"))

    for token in ["ACTION", "AI", "AVOID", "BLOCKED", "RECOMMENDATION", "US"]:
        answer = orchestrator.answer_user_question(
            AdvisorQuestionRequest(question=f"Should I use {token} as part of my strategy?", symbol=token)
        )

        assert answer.resolved_symbol is None
        assert answer.symbol_resolution_status in {
            SymbolResolutionStatus.NO_SYMBOL,
            SymbolResolutionStatus.PORTFOLIO_SCOPE,
        }
        assert all(item.get("id") != token for item in answer.linked_artifacts_json)


def test_ask_advisor_unknown_symbol_blocks_without_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="Should I buy ZZZZZ now?", symbol="ZZZZZ")
    )
    question = store.list_advisor_questions(limit=1)[0]

    assert question.original_symbol == "ZZZZZ"
    assert question.resolved_symbol is None
    assert question.symbol_resolution_status == SymbolResolutionStatus.UNKNOWN
    assert question.symbol is None
    assert answer.recommendation_type == AdvisorSeverity.BLOCKED
    assert "ZZZZZ" in answer.conclusion
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_advisor_answer_default_text_hides_internal_artifact_ids(tmp_path) -> None:
    store = make_store(tmp_path)

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="Hermes，我而家應唔應該買 AAPL？", symbol="AAPL")
    )
    visible_text = "\n".join(
        [
            answer.conclusion,
            answer.summary,
            answer.suggested_user_action,
            *answer.reasons,
            *answer.risks,
        ]
    )

    assert not any(prefix in visible_text for prefix in ["run_", "goal_", "thesis_", "evidence_", "committee_"])
    assert answer.details_available is True
    assert answer.linked_artifacts_json


def test_ask_advisor_uses_alphabet_thesis_across_share_classes(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", watchlist_symbols="GOOGL")
    store = Store(settings.db_path)
    store.upsert_quote(
        Quote(
            symbol="US.GOOG",
            last_price=175,
            previous_close=174,
            change_pct=0.57,
            updated_at=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
            source="test",
        )
    )
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol="US.GOOG",
            thesis_statement="Alphabet thesis covers both GOOG and GOOGL share classes for issuer-level risk.",
        )
    )

    answer = AdvisorOrchestrator(store, settings=settings).answer_user_question(
        AdvisorQuestionRequest(question="Should I buy GOOGL now?", symbol="GOOGL")
    )

    assert answer.resolved_symbol in {"GOOGL", "US.GOOG"}
    assert any(item.get("type") == "thesis" and item.get("id") == thesis.id for item in answer.linked_artifacts_json)
    assert any(item.get("type") == "quote" and item.get("id") == "US.GOOG" for item in answer.linked_artifacts_json)


def test_hourly_pulse_respects_quiet_hours_except_urgent(tmp_path) -> None:
    store = make_store(tmp_path)
    settings = Settings(db_path=tmp_path / "test.db")
    orchestrator = AdvisorOrchestrator(store, settings=settings)
    proposal_count = len(store.list_proposals(limit=100))

    quiet_watch = orchestrator.run_hourly_pulse(now=datetime(2026, 5, 25, 18, 0, tzinfo=timezone.utc))

    assert quiet_watch.severity.value in {"silent", "info", "watch"}
    if quiet_watch.severity.value == "watch":
        assert quiet_watch.should_notify is False

    store.upsert_quote(
        Quote(
            symbol="AAPL",
            last_price=170,
            previous_close=191,
            change_pct=-10.99,
            updated_at=datetime(2026, 5, 25, 18, 5, tzinfo=timezone.utc),
            source="test",
        )
    )
    urgent = orchestrator.run_hourly_pulse(now=datetime(2026, 5, 25, 18, 10, tzinfo=timezone.utc))

    assert urgent.severity.value == "urgent"
    assert urgent.should_notify is True
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_full_advisor_briefs_create_run_cards_and_grouped_recommendations(tmp_path) -> None:
    store = make_store(tmp_path)
    settings = Settings(db_path=tmp_path / "test.db")
    proposal_count = len(store.list_proposals(limit=100))
    orchestrator = AdvisorOrchestrator(store, settings=settings)

    pre = orchestrator.run_full_advisor_brief(
        AdvisorFullBriefType.PRE_MARKET,
        now=datetime(2026, 5, 26, 12, 45, tzinfo=timezone.utc),
    )
    post = orchestrator.run_full_advisor_brief(
        AdvisorFullBriefType.POST_CLOSE,
        now=datetime(2026, 5, 26, 20, 30, tzinfo=timezone.utc),
    )

    assert pre.run_card_id
    assert post.run_card_id
    assert pre.market_session_date
    assert post.market_session_date
    assert pre.recommendations
    assert any(
        item.recommendation_type
        in {AdvisorSeverity.WATCH, AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED, AdvisorSeverity.INFO}
        for item in pre.recommendations
    )
    assert store.get_latest_advisor_brief() is not None
    assert store.list_run_cards(run_type=RunCardType.ADVISOR_BRIEF, limit=10)
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_advisor_scheduler_runs_due_pulse_without_duplicate_or_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    settings = Settings(db_path=tmp_path / "test.db")
    proposal_count = len(store.list_proposals(limit=100))
    scheduler = AdvisorSchedulerRunner(settings, store)

    first = scheduler.run_once(now=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc))
    second = scheduler.run_once(now=datetime(2026, 5, 26, 10, 10, tzinfo=timezone.utc))

    assert any(item["job"] == "hourly_pulse" for item in first["ran"])
    assert any(item["job"] == "hourly_pulse" and item["reason"] == "not due" for item in second["skipped"])
    assert len(store.list_proposals(limit=100)) == proposal_count
