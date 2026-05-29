from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.demo_data import seed_demo_data
from invest_agent.models import ProposalCreate, ProposalStatus, Side
from invest_agent.runtime_doctor import RuntimeDoctorService
from invest_agent.services import InvestmentService
from invest_agent.store import Store


def test_runtime_doctor_reports_core_checks_without_api(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db", futu_read_enabled=True, draft_min_score=9)
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    store.audit(
        "proposal_drafts_generated",
        "proposal",
        "watchlist",
        {
            "draft_count": 0,
            "created_count": 0,
            "skipped": ["GOOGL: directional score 2 below threshold 9"],
            "draft_min_score": 9,
            "skipped_below_min_score": 1,
            "max_score_seen": 2,
        },
    )
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.get_futu_status",
        lambda _settings: {
            "provider": "futu-opend",
            "read_enabled": True,
            "connected": True,
            "available": True,
            "message": "mock connected",
        },
    )

    result = RuntimeDoctorService(settings, store).run()

    assert result["settings"]["draft_min_score"] == 9
    assert result["checks"]["database"]["status"] == "ok"
    assert result["checks"]["futu_connection"]["status"] == "ok"
    assert result["checks"]["draft_min_score"]["metrics"]["skipped_below_min_score"] == 1
    assert result["checks"]["draft_min_score"]["metrics"]["max_score_seen"] == 2
    assert result["checks"]["skipped_reasons"]["metrics"]["top_reasons"]


def test_runtime_doctor_reports_proposal_status_mismatches(tmp_path, monkeypatch) -> None:
    settings = Settings(db_path=tmp_path / "test.db", research_gate_required=False, futu_read_enabled=True)
    store = Store(settings.db_path)
    seed_demo_data(store, force=True)
    service = InvestmentService(settings, store)
    proposal = service.create_proposal(
        ProposalCreate(
            symbol="GOOGL",
            side=Side.BUY,
            qty=1,
            limit_price=175.70,
            thesis="Create a proposal to verify doctor mismatch reporting.",
            trigger="pytest",
            confidence=0.65,
        )
    )
    with store.connect() as conn:
        conn.execute("UPDATE proposals SET status = ? WHERE id = ?", (ProposalStatus.REJECTED.value, proposal.id))
    monkeypatch.setattr(
        "invest_agent.runtime_doctor.get_futu_status",
        lambda _settings: {"read_enabled": True, "connected": True, "available": True, "message": "mock connected"},
    )

    result = RuntimeDoctorService(settings, store).run()

    mismatch = result["checks"]["proposal_status_mismatches"]
    assert mismatch["status"] == "warn"
    assert mismatch["metrics"]["count"] == 1
    assert mismatch["metrics"]["examples"][0]["table_status"] == ProposalStatus.REJECTED.value
    assert store.get_proposal(proposal.id).status == ProposalStatus.REJECTED
