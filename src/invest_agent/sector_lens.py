from __future__ import annotations

import math
from datetime import timedelta

from .models import (
    CorrelationRunRequest,
    CorrelationSnapshot,
    PeerGroup,
    PeerGroupCreate,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    SectorSnapshot,
    SectorSnapshotRunRequest,
    utc_now,
)
from .run_cards import RunCardService
from .store import Store


CORRELATION_RULE_VERSION = "correlation_snapshot_v1"
SECTOR_RULE_VERSION = "sector_snapshot_v1"


class SectorLensService:
    def __init__(self, store: Store):
        self.store = store

    def create_peer_group(self, request: PeerGroupCreate) -> PeerGroup:
        return self.store.create_peer_group(
            PeerGroup(name=request.name, sector=request.sector, symbols=request.symbols, theme=request.theme)
        )

    def run_correlation(
        self,
        request: CorrelationRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> CorrelationSnapshot:
        symbols = request.symbols or _symbols_from_peer_groups(self.store)
        if not symbols:
            symbols = sorted({bar.symbol for bar in self.store.list_price_bars(limit=100000)})
        cutoff = utc_now() - timedelta(days=request.lookback_days)
        closes = {symbol: _returns(self.store.list_price_bars(symbol=symbol, start=cutoff.isoformat(), limit=100000)) for symbol in symbols}
        matrix: dict[str, dict[str, float]] = {}
        warnings: list[str] = []
        for left in symbols:
            matrix[left] = {}
            for right in symbols:
                corr = _corr(closes.get(left, []), closes.get(right, []))
                matrix[left][right] = round(corr, 4) if corr is not None else 0.0
        for left in symbols:
            for right in symbols:
                if left >= right:
                    continue
                if matrix[left][right] >= 0.85:
                    warnings.append(f"{left} and {right} are highly correlated; diversification benefit may be limited.")
        run_card = RunCardService(self.store).start_run(
            RunCardType.CORRELATION_SNAPSHOT,
            title="Sector / Peer Correlation Snapshot",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=CORRELATION_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"symbols": symbols, "return_lengths": {key: len(value) for key, value in closes.items()}},
            assumptions={"correlation_is_context_only": True, "creates_proposals": False},
        )
        snapshot = CorrelationSnapshot(
            symbols=symbols,
            lookback_days=request.lookback_days,
            correlation_matrix=matrix,
            warnings=warnings,
            run_card_id=run_card.id,
        )
        stored = self.store.create_correlation_snapshot(snapshot)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"symbol_count": len(symbols), "warning_count": len(warnings)},
            warnings=warnings,
            outputs={"correlation_snapshot_id": stored.id},
            dataset=stored.model_dump(mode="json"),
        )
        return stored

    def run_sector_snapshot(
        self,
        request: SectorSnapshotRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> SectorSnapshot:
        symbols = request.symbols or [
            symbol
            for group in self.store.list_peer_groups(sector=request.sector, limit=20)
            for symbol in group.symbols
        ]
        moves = {}
        for symbol in symbols:
            bars = self.store.list_price_bars(symbol=symbol, limit=2, ascending=False)
            if len(bars) >= 2 and bars[1].close:
                moves[symbol] = (bars[0].close - bars[1].close) / bars[1].close
        leaders = [symbol for symbol, _move in sorted(moves.items(), key=lambda item: item[1], reverse=True)[:3]]
        laggards = [symbol for symbol, _move in sorted(moves.items(), key=lambda item: item[1])[:3]]
        warnings = [] if moves else ["No cached price bars; sector snapshot is stale/context-only."]
        run_card = RunCardService(self.store).start_run(
            RunCardType.SECTOR_SNAPSHOT,
            title=f"Sector Snapshot: {request.sector}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=SECTOR_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"symbols": symbols, "moves": moves},
            assumptions={"sector_snapshot_is_context_only": True, "creates_proposals": False},
        )
        snapshot = SectorSnapshot(
            sector=request.sector,
            leaders=leaders,
            laggards=laggards,
            valuation_context={"status": "not_modelled_in_v1"},
            risk_notes=warnings,
            source_summary="Cached price bars and local peer-group definitions.",
            run_card_id=run_card.id,
        )
        stored = self.store.create_sector_snapshot(snapshot)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"symbol_count": len(symbols), "leader_count": len(leaders), "laggard_count": len(laggards)},
            warnings=warnings,
            outputs={"sector_snapshot_id": stored.id},
            dataset=stored.model_dump(mode="json"),
        )
        return stored


def _symbols_from_peer_groups(store: Store) -> list[str]:
    return sorted({symbol for group in store.list_peer_groups(limit=100) for symbol in group.symbols})


def _returns(bars) -> list[float]:
    ordered = sorted(bars, key=lambda item: item.ts)
    values = []
    for previous, current in zip(ordered, ordered[1:]):
        if previous.close:
            values.append((current.close - previous.close) / previous.close)
    return values


def _corr(left: list[float], right: list[float]) -> float | None:
    n = min(len(left), len(right))
    if n < 2:
        return None
    left = left[-n:]
    right = right[-n:]
    mean_l = sum(left) / n
    mean_r = sum(right) / n
    cov = sum((a - mean_l) * (b - mean_r) for a, b in zip(left, right))
    var_l = sum((a - mean_l) ** 2 for a in left)
    var_r = sum((b - mean_r) ** 2 for b in right)
    denom = math.sqrt(var_l * var_r)
    return None if denom == 0 else cov / denom

