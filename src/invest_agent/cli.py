from __future__ import annotations

import argparse
import json

from .config import get_settings
from .demo_data import seed_demo_data
from .deps import get_service, get_store
from .models import ProposalCreate, Side


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
    parser.add_argument("command", choices=["seed", "smoke"])
    args = parser.parse_args()
    if args.command == "seed":
        seed_main()
    if args.command == "smoke":
        smoke_main()


if __name__ == "__main__":
    main()
