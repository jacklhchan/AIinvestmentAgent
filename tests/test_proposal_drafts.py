from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import FundamentalMetric, FundamentalSnapshot, NewsItem, ProposalStatus, Side, utc_now
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


def test_primary_source_context_is_attached_to_news_draft(tmp_path) -> None:
    engine, store = make_engine(tmp_path)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet cloud demand beats expectations",
            source="google-news",
            published_at=utc_now(),
            summary="Demand remains strong.",
        )
    )
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="SEC 10-Q filed for GOOGL",
            source="sec-edgar",
            published_at=utc_now(),
            tags=["primary-source", "sec-edgar", "10-q"],
            summary="Primary-source SEC EDGAR filing.",
        )
    )

    result = engine.draft_from_watchlist(symbols=["GOOGL"])

    assert len(result.drafts) == 1
    assert any("sec-edgar" in item for item in result.drafts[0].evidence)
    assert "SEC/IR primary-source context is attached" in result.drafts[0].counter_evidence[0]


def test_primary_source_lookback_is_longer_than_news_window(tmp_path) -> None:
    from datetime import timedelta

    engine, store = make_engine(tmp_path)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet cloud demand beats expectations",
            source="google-news",
            published_at=utc_now(),
            summary="Demand remains strong.",
        )
    )
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="SEC 10-Q filed for GOOGL",
            source="sec-edgar",
            published_at=utc_now() - timedelta(days=30),
            tags=["primary-source", "sec-edgar", "10-q"],
            summary="Primary-source SEC EDGAR filing.",
        )
    )

    result = engine.draft_from_watchlist(symbols=["GOOGL"], lookback_hours=24)

    assert any("SEC 10-Q" in item for item in result.drafts[0].evidence)


def test_companyfacts_counter_signal_is_attached_to_positive_draft(tmp_path) -> None:
    engine, store = make_engine(tmp_path)
    store.upsert_news(
        NewsItem(
            symbol="GOOGL",
            title="Alphabet cloud demand beats expectations",
            source="google-news",
            published_at=utc_now(),
            summary="Demand remains strong.",
        )
    )
    store.upsert_fundamentals(
        FundamentalSnapshot(
            symbol="GOOGL",
            cik="0001652044",
            entity_name="Alphabet Inc.",
            metrics={
                "revenue": FundamentalMetric(
                    name="revenue",
                    label="Revenue",
                    concept="RevenueFromContractWithCustomerExcludingAssessedTax",
                    value=80_000_000_000,
                    unit="USD",
                    fiscal_year=2026,
                    fiscal_period="Q1",
                    form="10-Q",
                    yoy_change_pct=-8.5,
                )
            },
        )
    )

    result = engine.draft_from_watchlist(symbols=["GOOGL"])

    assert any("sec-companyfacts" in item for item in result.drafts[0].evidence)
    assert any("declined YoY" in item for item in result.drafts[0].counter_evidence)
