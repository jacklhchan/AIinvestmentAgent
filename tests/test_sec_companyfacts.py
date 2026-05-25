from __future__ import annotations

from invest_agent.config import Settings
from invest_agent.sec_companyfacts import companyfacts_snapshot_from_payload
from invest_agent.store import Store


def sample_companyfacts_payload():
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "val": 100_000_000_000,
                                "fy": 2025,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2025-05-02",
                                "end": "2025-03-29",
                                "frame": "CY2025Q1",
                            },
                            {
                                "val": 112_000_000_000,
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-05-01",
                                "end": "2026-03-28",
                                "frame": "CY2026Q1",
                            },
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "val": 24_000_000_000,
                                "fy": 2025,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2025-05-02",
                                "end": "2025-03-29",
                            },
                            {
                                "val": 28_800_000_000,
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-05-01",
                                "end": "2026-03-28",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "val": 352_000_000_000,
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-05-01",
                                "end": "2026-03-28",
                            }
                        ]
                    }
                },
            }
        },
    }


def test_companyfacts_payload_maps_to_fundamental_snapshot() -> None:
    snapshot = companyfacts_snapshot_from_payload(
        "AAPL",
        "0000320193",
        sample_companyfacts_payload(),
        form_filter={"10-Q"},
    )

    assert snapshot.symbol == "AAPL"
    assert snapshot.cik == "0000320193"
    assert snapshot.entity_name == "Apple Inc."
    assert snapshot.metrics["revenue"].value == 112_000_000_000
    assert snapshot.metrics["revenue"].yoy_change_pct == 12.0
    assert snapshot.metrics["net_income"].concept == "NetIncomeLoss"
    assert snapshot.metrics["assets"].form == "10-Q"


def test_store_persists_fundamental_snapshots(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db")
    store = Store(settings.db_path)
    snapshot = companyfacts_snapshot_from_payload("AAPL", "0000320193", sample_companyfacts_payload())

    store.upsert_fundamentals(snapshot)

    stored = store.get_fundamentals("AAPL")
    assert stored is not None
    assert stored.metrics["revenue"].unit == "USD"
    assert store.list_fundamentals()[0].symbol == "AAPL"
