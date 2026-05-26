from __future__ import annotations

from .models import OptionsSnapshot, OptionsSnapshotCreate, RunCardActor, RunCardTriggerSource, RunCardType
from .run_cards import RunCardService
from .store import Store


OPTIONS_LENS_RULE_VERSION = "options_lens_v1"
HIGH_IMPLIED_MOVE_PCT = 8.0


class OptionsLensService:
    def __init__(self, store: Store):
        self.store = store

    def create_snapshot(
        self,
        request: OptionsSnapshotCreate,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> OptionsSnapshot:
        run_card = RunCardService(self.store).start_run(
            RunCardType.OPTIONS_SNAPSHOT,
            title=f"Options Risk Snapshot: {request.symbol}",
            symbol=request.symbol,
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=OPTIONS_LENS_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            assumptions={"does_not_generate_options_strategy": True, "does_not_trade_options": True},
        )
        snapshot = OptionsSnapshot(**request.model_dump(), run_card_id=run_card.id)
        stored = self.store.create_options_snapshot(snapshot)
        warnings = []
        if stored.implied_move_pct is not None and stored.implied_move_pct >= HIGH_IMPLIED_MOVE_PCT:
            warnings.append(f"{stored.symbol} options implied move is elevated at {stored.implied_move_pct:.2f}%.")
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"has_implied_move": stored.implied_move_pct is not None},
            warnings=warnings,
            outputs={"options_snapshot_id": stored.id},
            dataset=stored.model_dump(mode="json"),
        )
        return stored

    def catalyst_warnings(self, symbol: str) -> list[str]:
        snapshots = self.store.list_options_snapshots(symbol=symbol, limit=1)
        if not snapshots:
            return []
        snapshot = snapshots[0]
        if snapshot.implied_move_pct is not None and snapshot.implied_move_pct >= HIGH_IMPLIED_MOVE_PCT:
            return [f"options implied move elevated ({snapshot.implied_move_pct:.2f}%); treat event-risk context as warning only"]
        return []

