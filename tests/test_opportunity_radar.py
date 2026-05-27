from __future__ import annotations

from pathlib import Path

from invest_agent.advisor_orchestrator import AdvisorOrchestrator
from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import (
    AdvisorQuestionRequest,
    AdvisorSeverity,
    OpportunityRadarRequest,
    OpportunityRecommendationType,
    NewsItem,
    PortfolioSnapshot,
    Position,
    Quote,
    RunCardType,
    utc_now,
)
from invest_agent.opportunity_radar import OpportunityRadarService
from invest_agent.store import Store


def make_store(tmp_path: Path) -> Store:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    return store


def add_market_quotes(store: Store) -> None:
    now = utc_now()
    for quote in [
        Quote(symbol="SPY", last_price=700, previous_close=693, change_pct=1.0, updated_at=now),
        Quote(symbol="QQQ", last_price=600, previous_close=590, change_pct=1.7, updated_at=now),
        Quote(symbol="IWM", last_price=240, previous_close=237, change_pct=1.3, updated_at=now),
        Quote(symbol="VIXY", last_price=12, previous_close=12.5, change_pct=-4.0, updated_at=now),
        Quote(symbol="TLT", last_price=96, previous_close=95.4, change_pct=0.6, updated_at=now),
        Quote(symbol="VOO", last_price=690, previous_close=685, change_pct=0.7, updated_at=now),
        Quote(symbol="XLV", last_price=150, previous_close=149.7, change_pct=0.2, updated_at=now),
        Quote(symbol="SMH", last_price=330, previous_close=320, change_pct=3.1, updated_at=now),
        Quote(symbol="NVDA", last_price=145, previous_close=138, change_pct=5.1, updated_at=now),
        Quote(symbol="AMD", last_price=490, previous_close=470, change_pct=4.3, updated_at=now),
    ]:
        store.upsert_quote(quote)


def test_opportunity_radar_creates_watch_and_blocked_cards_without_proposal(tmp_path) -> None:
    store = make_store(tmp_path)
    add_market_quotes(store)
    proposal_count = len(store.list_proposals(limit=100))

    radar = OpportunityRadarService(store, settings=Settings(db_path=tmp_path / "test.db")).run(
        OpportunityRadarRequest(question="今晚市場有無值得留意的新機會？")
    )

    assert radar.run_card_id
    assert store.get_run_card(radar.run_card_id).run_type == RunCardType.OPPORTUNITY_RADAR
    assert any(
        card.recommendation_type in {OpportunityRecommendationType.WATCH, OpportunityRecommendationType.RESEARCH}
        for card in radar.cards
    )
    assert any(
        card.recommendation_type in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID}
        for card in radar.cards
    )
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_broad_opportunity_question_uses_radar_inside_ask_advisor(tmp_path) -> None:
    store = make_store(tmp_path)
    add_market_quotes(store)
    proposal_count = len(store.list_proposals(limit=100))

    answer = AdvisorOrchestrator(store, settings=Settings(db_path=tmp_path / "test.db")).answer_user_question(
        AdvisorQuestionRequest(question="今晚市場有無值得留意的新機會？")
    )
    question = store.list_advisor_questions(limit=1)[0]

    assert answer.recommendation_type == AdvisorSeverity.WATCH
    assert answer.opportunity_radar_run_id
    assert answer.opportunity_cards_json
    assert "Opportunity Radar" in answer.conclusion
    assert question.symbol is None
    assert question.symbol_resolution_status.value == "portfolio_scope"
    assert len(store.list_proposals(limit=100)) == proposal_count


def test_high_tech_concentration_blocks_ai_chasing_ideas(tmp_path) -> None:
    store = make_store(tmp_path)
    now = utc_now()
    store.upsert_portfolio(
        PortfolioSnapshot(
            cash_usd=5000,
            total_value_usd=100000,
            positions=[
                Position(symbol="NVDA", qty=100, market_value=45000, last_price=450),
                Position(symbol="AMD", qty=100, market_value=20000, last_price=200),
                Position(symbol="QQQM", qty=100, market_value=15000, last_price=150),
            ],
            updated_at=now,
            source="test",
        )
    )
    add_market_quotes(store)

    radar = OpportunityRadarService(store, settings=Settings(db_path=tmp_path / "test.db")).run()
    semis = [card for card in radar.cards if "NVDA" in card.symbols or "AMD" in card.symbols]

    assert semis
    assert all(card.recommendation_type in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID} for card in semis)
    assert any("科技" in " ".join(card.risks + card.reasons) or "tech" in " ".join(card.risks + card.reasons).lower() for card in semis)


def test_risk_off_downgrades_high_beta_ideas(tmp_path) -> None:
    store = make_store(tmp_path)
    now = utc_now()
    for quote in [
        Quote(symbol="SPY", last_price=680, previous_close=700, change_pct=-2.8, updated_at=now),
        Quote(symbol="QQQ", last_price=570, previous_close=600, change_pct=-5.0, updated_at=now),
        Quote(symbol="VIXY", last_price=14, previous_close=12, change_pct=16.7, updated_at=now),
        Quote(symbol="SMH", last_price=300, previous_close=330, change_pct=-9.1, updated_at=now),
    ]:
        store.upsert_quote(quote)

    radar = OpportunityRadarService(store, settings=Settings(db_path=tmp_path / "test.db")).run()
    high_beta = [card for card in radar.cards if "SMH" in card.symbols or "SOXX" in card.symbols]

    assert high_beta
    assert all(card.recommendation_type in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID} for card in high_beta)


def test_mixed_etf_single_stock_card_needs_primary_evidence_for_action_candidate(tmp_path) -> None:
    store = make_store(tmp_path)
    now = utc_now()
    for quote in [
        Quote(symbol="SPY", last_price=700, previous_close=696.5, change_pct=0.5, updated_at=now),
        Quote(symbol="QQQ", last_price=600, previous_close=597, change_pct=0.5, updated_at=now),
        Quote(symbol="VIXY", last_price=12, previous_close=12.4, change_pct=-3.2, updated_at=now),
        Quote(symbol="XLF", last_price=50, previous_close=48.5, change_pct=3.1, updated_at=now),
    ]:
        store.upsert_quote(quote)
    store.upsert_news(
        NewsItem(
            id="test_news_xlf_strength",
            symbol="XLF",
            title="Financials rally as risk appetite improves",
            source="test",
            published_at=now,
        )
    )

    radar = OpportunityRadarService(store, settings=Settings(db_path=tmp_path / "test.db")).run(
        OpportunityRadarRequest(max_blocked=6)
    )
    financial = next(card for card in radar.cards if card.title.startswith("Financials / rate-sensitive value"))

    assert financial.recommendation_type == OpportunityRecommendationType.BLOCKED
    assert any("source-backed" in item for item in financial.risks)
