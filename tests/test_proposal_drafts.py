from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import NewsItem, ProposalStatus, Side, utc_now
from invest_agent.proposal_drafts import ProposalDraftEngine
from invest_agent.services import InvestmentService
from invest_agent.store import Store


def make_engine(tmp_path):
    settings = Settings(db_path=tmp_path / "test.db", watchlist_symbols="GOOGL", draft_notional_usd=1000)
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    service = InvestmentService(settings, store)
    return ProposalDraftEngine(settings, store, service), store


def test_drafts_buy_candidate_from_positive_news(tmp_path) -> None:
    engine, store = make_engine(tmp_path)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet shares rise as AI demand growth beats expectations",
            source="gdelt",
            published_at=utc_now(),
            summary="Analysts raise guidance after strong demand.",
        )
    )

    result = engine.draft_from_watchlist(symbols=["GOOGL"])

    assert result.watchlist == ["GOOGL"]
    assert len(result.drafts) == 1
    assert result.drafts[0].symbol == "GOOGL"
    assert result.drafts[0].side == Side.BUY
    assert result.drafts[0].qty == 5
    assert result.drafts[0].confidence >= 0.6


def test_macro_news_does_not_create_symbol_directional_draft(tmp_path) -> None:
    engine, _store = make_engine(tmp_path)

    result = engine.draft_from_watchlist(symbols=["GOOGL"])

    assert result.drafts == []
    assert "GOOGL: no recent market news" in result.skipped


def test_draft_can_create_policy_checked_proposal(tmp_path) -> None:
    engine, store = make_engine(tmp_path)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet raises guidance after record cloud growth",
            source="finnhub",
            published_at=utc_now(),
            summary="Growth and demand remain strong.",
        )
    )

    result = engine.draft_from_watchlist(symbols=["GOOGL"], create_proposals=True)

    assert len(result.created) == 1
    assert result.created[0].status == ProposalStatus.PENDING
    assert result.created[0].evidence
