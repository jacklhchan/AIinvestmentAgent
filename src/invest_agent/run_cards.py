from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .models import (
    ResearchRunCard,
    RunCardActor,
    RunCardStatus,
    RunCardTriggerSource,
    RunCardType,
    utc_now,
)
from .store import Store


RUN_CARD_SCHEMA_VERSION = "run_card_v1"


class RunCardService:
    def __init__(self, store: Store, artifact_root: Path | str | None = None):
        self.store = store
        self.artifact_root = Path(artifact_root) if artifact_root else _default_artifact_root(store)

    def start_run(
        self,
        run_type: RunCardType | str,
        *,
        title: str,
        symbol: str | None = None,
        actor: RunCardActor | str = RunCardActor.SYSTEM,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.SYSTEM,
        rule_version: str = "",
        inputs: dict[str, Any] | None = None,
        dataset: dict[str, Any] | None = None,
        assumptions: dict[str, Any] | None = None,
        links: dict[str, Any] | None = None,
    ) -> ResearchRunCard:
        links = links or {}
        run_card = ResearchRunCard(
            schema_version=RUN_CARD_SCHEMA_VERSION,
            run_type=RunCardType(run_type),
            status=RunCardStatus.RUNNING,
            symbol=symbol,
            title=title,
            actor=RunCardActor(actor),
            trigger_source=RunCardTriggerSource(trigger_source),
            code_version=_git_commit(),
            rule_version=rule_version,
            input_hash=stable_hash(inputs or {}),
            dataset_hash=stable_hash(dataset or {}),
            assumptions=assumptions or {},
            research_goal_id=links.get("research_goal_id"),
            thesis_id=links.get("thesis_id"),
            catalyst_id=links.get("catalyst_id"),
            catalyst_review_id=links.get("catalyst_review_id"),
            earnings_review_id=links.get("earnings_review_id"),
            proposal_id=links.get("proposal_id"),
        )
        return self.store.create_run_card(run_card)

    def complete_run(
        self,
        run_id: str,
        *,
        metrics: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        outputs: dict[str, Any] | None = None,
        dataset: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        evidence_hash: str | None = None,
        links: dict[str, Any] | None = None,
        write_artifacts: bool = True,
    ) -> ResearchRunCard:
        run_card = self.require_run_card(run_id)
        links = links or {}
        run_card.status = RunCardStatus.COMPLETED
        run_card.completed_at = utc_now()
        run_card.duration_ms = _duration_ms(run_card)
        run_card.metrics = metrics or {}
        run_card.warnings = warnings or []
        run_card.outputs = outputs or {}
        run_card.artifacts = artifacts or []
        if dataset is not None:
            run_card.dataset_hash = stable_hash(dataset)
        run_card.output_hash = stable_hash({"metrics": run_card.metrics, "outputs": run_card.outputs})
        run_card.evidence_hash = evidence_hash
        run_card.research_goal_id = links.get("research_goal_id", run_card.research_goal_id)
        run_card.thesis_id = links.get("thesis_id", run_card.thesis_id)
        run_card.catalyst_id = links.get("catalyst_id", run_card.catalyst_id)
        run_card.catalyst_review_id = links.get("catalyst_review_id", run_card.catalyst_review_id)
        run_card.earnings_review_id = links.get("earnings_review_id", run_card.earnings_review_id)
        run_card.proposal_id = links.get("proposal_id", run_card.proposal_id)
        stored = self.store.update_run_card(run_card, "run_card_completed")
        if write_artifacts:
            stored = self.write_artifacts(stored)
        return stored

    def fail_run(
        self,
        run_id: str,
        *,
        error: str,
        warnings: list[str] | None = None,
        outputs: dict[str, Any] | None = None,
        write_artifacts: bool = True,
    ) -> ResearchRunCard:
        run_card = self.require_run_card(run_id)
        run_card.status = RunCardStatus.FAILED
        run_card.completed_at = utc_now()
        run_card.duration_ms = _duration_ms(run_card)
        run_card.error = error
        run_card.warnings = warnings or []
        run_card.outputs = outputs or {}
        run_card.output_hash = stable_hash({"error": error, "outputs": run_card.outputs})
        stored = self.store.update_run_card(run_card, "run_card_failed")
        if write_artifacts:
            stored = self.write_artifacts(stored)
        return stored

    def write_artifacts(self, run_card: ResearchRunCard) -> ResearchRunCard:
        run_dir = self.artifact_root / run_card.started_at.strftime("%Y-%m-%d") / run_card.id
        run_dir.mkdir(parents=True, exist_ok=True)
        json_path = run_dir / "run_card.json"
        md_path = run_dir / "run_card.md"
        json_payload = _artifact_payload(run_card)
        run_card_hash = str(json_payload["hashes"]["run_card_hash"])
        json_bytes = _canonical_json(json_payload)
        json_path.write_bytes(json_bytes)
        md_path.write_text(_markdown(run_card, run_card_hash), encoding="utf-8")
        run_card.artifacts = [
            *run_card.artifacts,
            {"kind": "json", "path": str(json_path), "sha256": sha256_file(json_path)},
            {"kind": "markdown", "path": str(md_path), "sha256": sha256_file(md_path)},
        ]
        return self.store.update_run_card(run_card, "run_card_artifacts_written")

    def get_artifact_text(self, run_card_id: str, kind: str = "json") -> str:
        run_card = self.require_run_card(run_card_id)
        artifact = next((item for item in run_card.artifacts if item.get("kind") == kind), None)
        if not artifact:
            raise ValueError(f"run card artifact not found: {kind}")
        path = Path(str(artifact.get("path") or ""))
        if not path.exists():
            raise ValueError(f"run card artifact path missing: {path}")
        return path.read_text(encoding="utf-8")

    def require_run_card(self, run_card_id: str) -> ResearchRunCard:
        run_card = self.store.get_run_card(run_card_id)
        if not run_card:
            raise ValueError(f"run card not found: {run_card_id}")
        return run_card


def stable_hash(value: Any) -> str:
    return sha256_bytes(_canonical_json(value))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _artifact_payload(run_card: ResearchRunCard) -> dict[str, Any]:
    payload = run_card.model_dump(mode="json", exclude={"artifacts"})
    payload["hashes"] = {
        "input_hash": run_card.input_hash,
        "output_hash": run_card.output_hash,
        "dataset_hash": run_card.dataset_hash,
    }
    payload["hashes"]["run_card_hash"] = stable_hash(payload)
    return payload


def _markdown(run_card: ResearchRunCard, run_card_hash: str) -> str:
    metric_lines = "\n".join(f"| {key} | {value} |" for key, value in sorted(run_card.metrics.items()))
    warning_lines = "\n".join(f"- {warning}" for warning in run_card.warnings) or "None"
    return (
        f"# {run_card.title}\n\n"
        f"Run ID: {run_card.id}\n\n"
        f"Type: {run_card.run_type.value}\n\n"
        f"Status: {run_card.status.value}\n\n"
        f"Symbol: {run_card.symbol or 'portfolio'}\n\n"
        f"Rule version: {run_card.rule_version or 'n/a'}\n\n"
        f"Evidence hash: {run_card.evidence_hash or 'n/a'}\n\n"
        f"Run card hash: {run_card_hash}\n\n"
        "## Links\n\n"
        f"- Research goal: {run_card.research_goal_id or 'n/a'}\n"
        f"- Thesis: {run_card.thesis_id or 'n/a'}\n"
        f"- Catalyst: {run_card.catalyst_id or 'n/a'}\n"
        f"- Catalyst review: {run_card.catalyst_review_id or 'n/a'}\n"
        f"- Earnings review: {run_card.earnings_review_id or 'n/a'}\n\n"
        "## Metrics\n\n"
        "| Metric | Value |\n|---|---:|\n"
        f"{metric_lines or '| n/a | n/a |'}\n\n"
        "## Warnings\n\n"
        f"{warning_lines}\n"
    )


def _default_artifact_root(store: Store) -> Path:
    db_parent = store.db_path.parent
    repo_root = db_parent.parent if db_parent.name == "data" else db_parent
    return repo_root / "artifacts" / "run_cards"


def _duration_ms(run_card: ResearchRunCard) -> int:
    completed = run_card.completed_at or utc_now()
    return max(0, int((completed - run_card.started_at).total_seconds() * 1000))


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL)
            .strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
