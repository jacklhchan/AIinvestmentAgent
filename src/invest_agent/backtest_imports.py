from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    BacktestImportRequest,
    ExternalBacktestImport,
    ExternalBacktestValidationStatus,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
)
from .run_cards import RunCardService, sha256_file, stable_hash
from .store import Store


BACKTEST_IMPORT_RULE_VERSION = "external_backtest_import_v1"


class BacktestImportService:
    def __init__(self, store: Store):
        self.store = store

    def import_run_card(
        self,
        request: BacktestImportRequest,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> ExternalBacktestImport:
        path = Path(request.path)
        if not path.exists():
            raise ValueError(f"backtest artifact not found: {path}")
        if path.suffix.lower() not in {".json", ".md", ".markdown"}:
            raise ValueError("only JSON or Markdown backtest artifacts may be imported")
        payload = _load_payload(path)
        hashes = payload.get("hashes") if isinstance(payload.get("hashes"), dict) else {}
        run_card_hash = str(hashes.get("run_card_hash") or payload.get("run_card_hash") or "")
        if path.suffix.lower() == ".json" and not run_card_hash:
            raise ValueError("imported run_card.json must include hashes.run_card_hash")
        if path.suffix.lower() == ".json" and not (hashes.get("input_hash") or payload.get("input_hash")):
            raise ValueError("imported run_card.json must include input_hash")
        if not run_card_hash:
            run_card_hash = stable_hash({"path": str(path), "file_hash": sha256_file(path)})
        run_card = RunCardService(self.store).start_run(
            RunCardType.EXTERNAL_BACKTEST_IMPORT,
            title="External Backtest Run Card Import",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=BACKTEST_IMPORT_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"path": str(path), "run_card_hash": run_card_hash, "file_hash": sha256_file(path)},
            assumptions={
                "never_execute_external_code": True,
                "supplementary_evidence_only": True,
                "cannot_pass_proposal_gate": True,
            },
            links={"research_goal_id": request.linked_research_goal_id},
        )
        item = ExternalBacktestImport(
            source=request.source,
            imported_run_card_path=str(path),
            run_card_hash=run_card_hash,
            strategy_name=_strategy_name(payload, path),
            universe=_universe(payload),
            period_start=_period_value(payload, "period_start"),
            period_end=_period_value(payload, "period_end"),
            metrics=_metrics(payload),
            warnings=_warnings(payload),
            validation_status=ExternalBacktestValidationStatus.IMPORTED,
            linked_hypothesis_id=request.linked_hypothesis_id,
            linked_research_goal_id=request.linked_research_goal_id,
            file_hash=sha256_file(path),
        )
        stored = self.store.create_external_backtest_import(item)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"metric_count": len(stored.metrics), "warning_count": len(stored.warnings)},
            warnings=["External backtest is supplementary evidence only and cannot pass proposal gate."],
            outputs={"external_backtest_import_id": stored.id, "run_card_hash": stored.run_card_hash},
            dataset=stored.model_dump(mode="json"),
        )
        return stored


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return {"markdown": path.read_text(encoding="utf-8")}


def _strategy_name(payload: dict[str, Any], path: Path) -> str:
    return str(payload.get("strategy_name") or payload.get("title") or payload.get("name") or path.stem)


def _metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _warnings(payload: dict[str, Any]) -> list[str]:
    warnings = payload.get("warnings")
    return warnings if isinstance(warnings, list) else []


def _universe(payload: dict[str, Any]) -> list[str]:
    universe = payload.get("universe") or payload.get("symbols") or []
    if isinstance(universe, str):
        return [item.strip().upper() for item in universe.split(",") if item.strip()]
    if isinstance(universe, list):
        return [str(item).strip().upper() for item in universe if str(item).strip()]
    return []


def _period_value(payload: dict[str, Any], key: str) -> str | None:
    period = payload.get("period") if isinstance(payload.get("period"), dict) else {}
    value = payload.get(key) or period.get(key)
    return str(value) if value else None
