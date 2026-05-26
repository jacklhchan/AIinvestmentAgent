from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .models import (
    DataImport,
    DataImportRequest,
    DataSchema,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    SymbolClassification,
)
from .run_cards import RunCardService, sha256_file, stable_hash
from .store import Store


DATA_IMPORT_ROOT = PROJECT_ROOT / "artifacts" / "imports"
DATA_IMPORT_RULE_VERSION = "data_bridge_import_v1"
ALLOWED_EXTENSIONS = {".csv"}


class DataBridgeService:
    def __init__(self, store: Store, import_root: Path | None = None):
        self.store = store
        self.import_root = import_root or DATA_IMPORT_ROOT

    def ensure_default_schemas(self) -> list[DataSchema]:
        existing = {(schema.name, schema.version) for schema in self.store.list_data_schemas(limit=1000)}
        schemas = [
            DataSchema(
                id="schema_symbol_classification_v1",
                name="symbol_classification",
                version="v1",
                required_columns=["symbol", "asset_class"],
                optional_columns=["sector", "region", "style", "risk_bucket"],
                canonical_mapping={
                    "symbol": "symbol",
                    "asset_class": "asset_class",
                    "sector": "sector",
                    "region": "region",
                    "style": "style",
                    "risk_bucket": "risk_bucket",
                },
            ),
            DataSchema(
                id="schema_generic_csv_v1",
                name="generic_csv",
                version="v1",
                required_columns=[],
                optional_columns=[],
                canonical_mapping={},
            ),
        ]
        stored: list[DataSchema] = []
        for schema in schemas:
            if (schema.name, schema.version) not in existing:
                stored.append(self.store.upsert_data_schema(schema))
        return stored

    def import_file(
        self,
        request: DataImportRequest,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
        allow_absolute: bool = False,
    ) -> DataImport:
        self.ensure_default_schemas()
        schema = self._schema(request.schema_name)
        path = self._resolve_path(request.path, allow_absolute=allow_absolute)
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("unsupported data import extension")
        rows = _read_csv(path)
        warnings = _validate_rows(rows, schema)
        dataset_hash = stable_hash({"schema": schema.model_dump(mode="json"), "rows": rows})
        run_card = RunCardService(self.store).start_run(
            RunCardType.DATA_IMPORT,
            title=f"Data Import: {schema.name}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=DATA_IMPORT_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"file_hash": sha256_file(path), "row_count": len(rows), "dataset_hash": dataset_hash},
            assumptions={"mcp_read_only": True, "allowed_import_root": str(self.import_root)},
        )
        item = DataImport(
            source_name=request.source_name,
            file_hash=sha256_file(path),
            file_type=path.suffix.lower().lstrip("."),
            schema_name=schema.name,
            schema_version=schema.version,
            row_count=len(rows),
            dataset_hash=dataset_hash,
            validation_warnings=warnings,
            run_card_id=run_card.id,
        )
        if schema.name == "symbol_classification":
            self._apply_symbol_classification(rows)
        stored = self.store.create_data_import(item)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"row_count": len(rows), "warning_count": len(warnings)},
            warnings=warnings,
            outputs={"data_import_id": stored.id, "schema_name": stored.schema_name},
            dataset={"rows": rows},
        )
        return stored

    def _schema(self, schema_name: str) -> DataSchema:
        for schema in self.store.list_data_schemas(limit=1000):
            if schema.name == schema_name:
                return schema
        raise ValueError(f"unknown data schema: {schema_name}")

    def _resolve_path(self, value: str, *, allow_absolute: bool) -> Path:
        path = Path(value)
        if allow_absolute and path.is_absolute():
            return path
        root = self.import_root.resolve()
        candidate = (root / path).resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("data import path traversal is not allowed")
        if not candidate.exists():
            raise ValueError(f"data import file not found: {candidate}")
        return candidate

    def _apply_symbol_classification(self, rows: list[dict[str, str]]) -> None:
        for row in rows:
            self.store.upsert_symbol_classification(
                SymbolClassification(
                    symbol=row["symbol"],
                    asset_class=row.get("asset_class") or "equity",
                    sector=row.get("sector") or "unknown",
                    region=row.get("region") or "US",
                    style=row.get("style") or "unknown",
                    risk_bucket=row.get("risk_bucket") or "medium",
                )
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _validate_rows(rows: list[dict[str, str]], schema: DataSchema) -> list[str]:
    warnings: list[str] = []
    if not rows:
        warnings.append("import contains no rows")
        return warnings
    columns = set(rows[0].keys())
    for column in schema.required_columns:
        if column not in columns:
            raise ValueError(f"missing required column: {column}")
    return warnings

