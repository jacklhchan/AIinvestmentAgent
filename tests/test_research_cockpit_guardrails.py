from __future__ import annotations

import ast
import csv
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Callable

import pytest

from invest_agent.backtest_imports import BacktestImportService
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
from invest_agent.market_regime import MarketRegimeService
from invest_agent.models import (
    BacktestImportRequest,
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
    IdeaCandidateCreate,
    IdeaDirection,
    IdeaScreenRunRequest,
    OptionsSnapshotCreate,
    PortfolioTarget,
    ProposalCreate,
    QuoteHistoryRefreshRequest,
    RunCardActor,
    RunCardType,
    Side,
    ThesisConviction,
    ThesisCreate,
    ThesisSide,
    ThesisStatus,
    utc_now,
)
from invest_agent.options_lens import OptionsLensService
from invest_agent.permissions import (
    APPROVAL_WRITE_TOOLS,
    FORBIDDEN_LIVE_EXECUTION_TOOL_NAMES,
    MCP_TOOL_PERMISSIONS,
    NEXT_PHASE_MCP_TOOLS,
    PROPOSAL_WRITE_TOOLS,
    READ_ONLY_TOOLS,
)
from invest_agent.portfolio_studio import PortfolioStudioService
from invest_agent.quote_history import QuoteHistoryService
from invest_agent.schema_checks import run_schema_check
from invest_agent.sector_lens import SectorLensService
from invest_agent.services import InvestmentService
from invest_agent.skill_validator import SkillValidatorService
from invest_agent.store import Store
from invest_agent.thesis_tracker import ThesisTrackerService


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER_PATH = REPO_ROOT / "src" / "invest_agent" / "mcp_server.py"
PERMISSIONS_DOC = REPO_ROOT / "docs" / "permissions.md"
HERMES_CONFIG = REPO_ROOT / "deploy" / "hermes" / "config.snippet.yaml"
HERMES_DAILY_ADVISOR_TOOLS = {
    "ask_advisor",
    "get_advisor_profile",
    "suggest_advisor_profile_update",
    "confirm_advisor_profile_update",
    "run_hourly_advisor_pulse",
    "run_pre_market_advisor_brief",
    "run_post_close_advisor_brief",
    "get_latest_advisor_brief",
}


def make_stack(tmp_path: Path) -> tuple[Settings, Store]:
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


def make_fundamentals(symbol: str = "AAPL", yoy: float = 8.0) -> FundamentalSnapshot:
    filed_at = utc_now() - timedelta(days=2)

    def metric(name: str) -> FundamentalMetric:
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
            "revenue": metric("revenue"),
            "net_income": metric("net_income"),
            "operating_cash_flow": metric("operating_cash_flow"),
            "eps_diluted": metric("eps_diluted"),
        },
    )


def control_plane_counts(store: Store) -> tuple[int, int]:
    return len(store.list_proposals(limit=1000)), len(store.list_executions())


def decorated_mcp_tool_names() -> set[str]:
    module = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in module.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            names.add(node.name)
    return names


def docs_permission_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    pattern = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| `execution_forbidden` \|$")
    for line in PERMISSIONS_DOC.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def hermes_included_tools() -> set[str]:
    pattern = re.compile(r"^\s*-\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*$")
    return {
        match.group(1)
        for line in HERMES_CONFIG.read_text(encoding="utf-8").splitlines()
        if (match := pattern.match(line))
    }


def test_mcp_permission_matrix_covers_code_docs_and_hermes_config() -> None:
    decorated_tools = decorated_mcp_tool_names()
    hermes_tools = hermes_included_tools()

    assert set(MCP_TOOL_PERMISSIONS) == decorated_tools
    assert docs_permission_rows() == MCP_TOOL_PERMISSIONS
    assert hermes_tools <= decorated_tools
    assert hermes_tools == HERMES_DAILY_ADVISOR_TOOLS
    assert "approve_trade_proposal" not in hermes_tools
    assert "create_trade_proposal" not in hermes_tools
    assert not (decorated_tools & FORBIDDEN_LIVE_EXECUTION_TOOL_NAMES)
    assert not (hermes_tools & FORBIDDEN_LIVE_EXECUTION_TOOL_NAMES)
    assert all(MCP_TOOL_PERMISSIONS[tool] in {"read_only", "research_write"} for tool in NEXT_PHASE_MCP_TOOLS)


def test_read_only_mcp_tools_do_not_call_write_paths() -> None:
    module = ast.parse(MCP_SERVER_PATH.read_text(encoding="utf-8"))
    functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    write_prefixes = (
        "add",
        "apply",
        "approve",
        "complete",
        "create",
        "draft",
        "export",
        "import",
        "insert",
        "refresh",
        "reject",
        "replay",
        "run",
        "update",
        "upsert",
    )

    for tool in READ_ONLY_TOOLS:
        calls = set()
        for node in ast.walk(functions[tool]):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        write_calls = sorted(name for name in calls if name.startswith(write_prefixes))
        assert write_calls == [], f"{tool} has write-like calls: {write_calls}"


def test_schema_check_is_idempotent_and_preserves_control_plane_rows(tmp_path: Path) -> None:
    settings, store = make_stack(tmp_path)
    service = InvestmentService(settings, store)
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=1,
            limit_price=175.70,
            thesis="Schema check seed proposal remains paper-only.",
            trigger="pytest schema check",
            confidence=0.75,
            manual_override_reason="Schema integrity test only.",
        )
    )
    service.approve_proposal(proposal.id, approved_by="pytest")
    ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol="AAPL",
            thesis_statement="Schema check seed thesis.",
            side=ThesisSide.LONG,
            status=ThesisStatus.WATCH,
            conviction=ThesisConviction.MEDIUM,
            human_confirmed=True,
            confirmed_by="pytest",
        )
    )

    result = run_schema_check(store)

    assert result["ok"] is True
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["preserved_counts"]["unchanged"] is True
    assert result["preserved_counts"]["before"]["proposals"] >= 1
    assert result["preserved_counts"]["before"]["executions"] >= 1


LayerRunner = Callable[[Settings, Store, Path], list[RunCardType]]


def run_market_regime(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    MarketRegimeService(settings, store).refresh(actor=RunCardActor.CLI)
    return [RunCardType.MARKET_REGIME]


def run_hypothesis(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    hypothesis = HypothesisRegistryService(store).create(
        HypothesisCreate(title="AI capex", statement="AI capex needs verification.", symbols=["AAPL"]),
        actor=RunCardActor.MCP,
    )
    HypothesisRegistryService(store).invalidate(
        hypothesis.id,
        HypothesisInvalidateRequest(invalidation_note="Evidence weakened."),
    )
    return []


def run_portfolio_studio(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    store.upsert_portfolio_target(PortfolioTarget(asset_class="equity", target_weight=0.4, min_weight=0.2, max_weight=0.5))
    review = PortfolioStudioService(settings, store).run_rebalance_review(actor=RunCardActor.CLI)
    if review.candidates:
        PortfolioStudioService(settings, store).promote_candidate_to_research_goal(review.candidates[0].id)
    return [RunCardType.PORTFOLIO_RISK, RunCardType.REBALANCE_REVIEW]


def run_earnings_preview(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    store.upsert_fundamentals(make_fundamentals("AAPL"))
    EarningsPreviewService(store).run_preview(EarningsPreviewRunRequest(symbol="AAPL"), actor=RunCardActor.CLI)
    return [RunCardType.EARNINGS_PREVIEW]


def run_earnings_review(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    store.upsert_fundamentals(make_fundamentals("AAPL"))
    EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="AAPL"), actor=RunCardActor.CLI)
    return [RunCardType.EARNINGS_REVIEW]


def run_quote_history(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="AAPL"), actor=RunCardActor.CLI)
    return [RunCardType.QUOTE_HISTORY_IMPORT]


def run_backtest_import(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    path = tmp_path / "run_card.json"
    path.write_text(
        json.dumps({"hashes": {"run_card_hash": "abc", "input_hash": "input"}, "strategy_name": "alpha", "metrics": {"ir": 1.2}}),
        encoding="utf-8",
    )
    BacktestImportService(store).import_run_card(BacktestImportRequest(path=str(path)), actor=RunCardActor.CLI)
    return [RunCardType.EXTERNAL_BACKTEST_IMPORT]


def run_data_bridge(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    import_root = tmp_path / "imports"
    import_root.mkdir()
    write_csv(import_root / "classifications.csv", ["symbol", "asset_class", "sector"], [["AAPL", "equity", "technology"]])
    DataBridgeService(store, import_root=import_root).import_file(
        DataImportRequest(schema_name="symbol_classification", path="classifications.csv"),
        actor=RunCardActor.CLI,
    )
    return [RunCardType.DATA_IMPORT]


def run_daily_brief(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    DailyBriefService(settings, store).run(DailyBriefRunRequest(), actor=RunCardActor.CLI)
    return [RunCardType.DAILY_BRIEF]


def run_sector_lens(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="AAPL"), actor=RunCardActor.CLI)
    QuoteHistoryService(store).refresh(QuoteHistoryRefreshRequest(symbol="MSFT"), actor=RunCardActor.CLI)
    SectorLensService(store).run_correlation(CorrelationRunRequest(symbols=["AAPL", "MSFT"], lookback_days=10), actor=RunCardActor.CLI)
    from invest_agent.models import SectorSnapshotRunRequest

    SectorLensService(store).run_sector_snapshot(SectorSnapshotRunRequest(sector="technology"), actor=RunCardActor.CLI)
    return [RunCardType.CORRELATION_SNAPSHOT, RunCardType.SECTOR_SNAPSHOT]


def run_options_lens(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    OptionsLensService(store).create_snapshot(
        OptionsSnapshotCreate(symbol="AAPL", expiry="2026-06-19", implied_move_pct=8.5),
        actor=RunCardActor.CLI,
    )
    return [RunCardType.OPTIONS_SNAPSHOT]


def run_dividend_lens(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    DividendLensService(store).run_review(
        DividendReviewRunRequest(symbol="AAPL", dividend_yield=0.03, payout_ratio=1.2),
        actor=RunCardActor.CLI,
    )
    return [RunCardType.DIVIDEND_REVIEW]


def run_idea_inbox(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    IdeaInboxService(settings, store).run_screen(IdeaScreenRunRequest(symbols=["AAPL"]), actor=RunCardActor.CLI)
    candidate = IdeaInboxService(settings, store).create_candidate(
        IdeaCandidateCreate(symbol="MSFT", direction=IdeaDirection.LONG, one_line_thesis="Cloud growth needs more evidence.")
    )
    IdeaInboxService(settings, store).promote_to_research_goal(candidate.id)
    return [RunCardType.IDEA_SCREEN]


def run_committee_review(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    review = CommitteeReviewService(store).run_review(
        CommitteeReviewRunRequest(
            topic="MSFT research memo",
            missing_evidence=["verified primary source"],
            conclusion=CommitteeConclusion.ELIGIBLE_FOR_PROPOSAL,
        ),
        actor=RunCardActor.CLI,
    )
    assert review.conclusion == CommitteeConclusion.RESEARCH_MORE
    return [RunCardType.COMMITTEE_REVIEW]


def run_skill_validator(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    report = SkillValidatorService(store).validate(actor=RunCardActor.CLI)
    assert report.issue_count == 0
    return [RunCardType.SKILL_VALIDATION]


def run_data_quality(settings: Settings, store: Store, tmp_path: Path) -> list[RunCardType]:
    DataQualityService(store).run_report(DataQualityRunRequest(), actor=RunCardActor.CLI)
    return [RunCardType.DATA_QUALITY_REPORT]


@pytest.mark.parametrize(
    ("name", "runner"),
    [
        ("market_regime", run_market_regime),
        ("hypothesis", run_hypothesis),
        ("portfolio_studio", run_portfolio_studio),
        ("earnings_preview", run_earnings_preview),
        ("earnings_review", run_earnings_review),
        ("quote_history", run_quote_history),
        ("backtest_import", run_backtest_import),
        ("data_bridge", run_data_bridge),
        ("daily_brief", run_daily_brief),
        ("sector_lens", run_sector_lens),
        ("options_lens", run_options_lens),
        ("dividend_lens", run_dividend_lens),
        ("idea_inbox", run_idea_inbox),
        ("committee_review", run_committee_review),
        ("skill_validator", run_skill_validator),
        ("data_quality", run_data_quality),
    ],
)
def test_next_phase_layers_do_not_create_proposals_or_executions(
    tmp_path: Path,
    name: str,
    runner: LayerRunner,
) -> None:
    settings, store = make_stack(tmp_path)
    before = control_plane_counts(store)

    expected_run_types = runner(settings, store, tmp_path)

    assert control_plane_counts(store) == before, name
    for run_type in expected_run_types:
        assert store.list_run_cards(run_type=run_type, limit=5), f"{name} missing {run_type.value} run card"


def test_mcp_severe_and_promotion_actions_remain_research_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _settings, store = make_stack(tmp_path)
    store.upsert_fundamentals(make_fundamentals("AAPL", yoy=-20.0))
    thesis = ThesisTrackerService(store).create_thesis(
        ThesisCreate(
            symbol="AAPL",
            thesis_statement="AAPL needs post-earnings confirmation.",
            side=ThesisSide.LONG,
            status=ThesisStatus.ACTIVE,
            conviction=ThesisConviction.HIGH,
            human_confirmed=True,
            confirmed_by="pytest",
        )
    )
    review = EarningsReviewService(store).run_review(EarningsReviewRunRequest(symbol="AAPL", thesis_id=thesis.id))
    before = control_plane_counts(store)

    import invest_agent.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "get_store", lambda: store)

    result = mcp_server.apply_earnings_review_to_thesis(review.id, thesis_id=thesis.id)

    assert "human confirmation required" in result["error"]
    assert control_plane_counts(store) == before
    assert "confirm_shadow_strategy" not in decorated_mcp_tool_names()
    assert "run_shadow_report" not in decorated_mcp_tool_names()
    assert "promote_idea_candidate_to_thesis" not in decorated_mcp_tool_names()
    assert "promote_rebalance_candidate" not in decorated_mcp_tool_names()
    assert PROPOSAL_WRITE_TOOLS.isdisjoint(NEXT_PHASE_MCP_TOOLS)
    assert APPROVAL_WRITE_TOOLS.isdisjoint(NEXT_PHASE_MCP_TOOLS)
