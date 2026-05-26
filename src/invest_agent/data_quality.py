from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .models import DataQualityReport, DataQualityRunRequest, DataQualityTargetType, RunCardActor, RunCardTriggerSource, RunCardType, utc_now
from .run_cards import RunCardService
from .store import Store


DATA_QUALITY_RULE_VERSION = "data_quality_v1"


class DataQualityService:
    def __init__(self, store: Store):
        self.store = store

    def run_report(
        self,
        request: DataQualityRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> DataQualityReport:
        missing_fields: list[dict] = []
        stale_data: list[dict] = []
        duplicate_rows: list[dict] = []
        unit_mismatch: list[dict] = []
        outliers: list[dict] = []
        target = request.target_type
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.FUNDAMENTALS}:
            _check_fundamentals(self.store, missing_fields, stale_data)
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.PRICE_BARS}:
            _check_price_bars(self.store, duplicate_rows, missing_fields, outliers)
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.TRADE_JOURNAL}:
            _check_trade_journal(self.store, missing_fields, duplicate_rows, outliers)
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.CATALYSTS}:
            _check_catalysts(self.store, missing_fields, stale_data)
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.EARNINGS_REVIEW}:
            _check_earnings_reviews(self.store, missing_fields)
        if target in {DataQualityTargetType.ALL, DataQualityTargetType.RUN_CARDS}:
            _check_run_cards(self.store, missing_fields)
        counts = {
            "missing_fields": len(missing_fields),
            "stale_data": len(stale_data),
            "duplicate_rows": len(duplicate_rows),
            "unit_mismatch": len(unit_mismatch),
            "outliers": len(outliers),
        }
        run_card = RunCardService(self.store).start_run(
            RunCardType.DATA_QUALITY_REPORT,
            title=f"Data Quality Report: {target.value}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=DATA_QUALITY_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            assumptions={"data_qa_only_raises_warnings": True, "creates_proposals": False},
        )
        report = DataQualityReport(
            target_type=target,
            target_id=request.target_id,
            missing_fields=missing_fields,
            stale_data=stale_data,
            duplicate_rows=duplicate_rows,
            unit_mismatch=unit_mismatch,
            outliers=outliers,
            severity_counts=counts,
            summary=f"Data QA found {sum(counts.values())} issue(s).",
            run_card_id=run_card.id,
        )
        stored = self.store.create_data_quality_report(report)
        warnings = [stored.summary] if sum(counts.values()) else []
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics=counts,
            warnings=warnings,
            outputs={"data_quality_report_id": stored.id, "summary": stored.summary},
            dataset=stored.model_dump(mode="json"),
        )
        return stored


def _check_fundamentals(store: Store, missing_fields: list[dict], stale_data: list[dict]) -> None:
    for snapshot in store.list_fundamentals():
        for metric in ["revenue", "net_income", "operating_cash_flow", "eps_diluted"]:
            if metric not in snapshot.metrics:
                missing_fields.append({"target": snapshot.symbol, "field": metric, "severity": "medium"})
        latest = max((metric.filed_at for metric in snapshot.metrics.values() if metric.filed_at), default=None)
        if latest and latest < utc_now() - timedelta(days=180):
            stale_data.append({"target": snapshot.symbol, "field": "companyfacts", "filed_at": latest.isoformat(), "severity": "medium"})


def _check_price_bars(store: Store, duplicate_rows: list[dict], missing_fields: list[dict], outliers: list[dict]) -> None:
    bars = store.list_price_bars(limit=100000)
    counts = Counter((bar.symbol, bar.ts.isoformat()) for bar in bars)
    for key, count in counts.items():
        if count > 1:
            duplicate_rows.append({"target": key[0], "ts": key[1], "count": count, "severity": "medium"})
    for bar in bars:
        if bar.close <= 0:
            missing_fields.append({"target": bar.symbol, "field": "close", "bar_id": bar.id, "severity": "high"})
        if bar.volume == 0:
            outliers.append({"target": bar.symbol, "field": "volume", "bar_id": bar.id, "value": 0, "severity": "low"})


def _check_trade_journal(store: Store, missing_fields: list[dict], duplicate_rows: list[dict], outliers: list[dict]) -> None:
    fills = store.list_trade_fills(limit=100000)
    counts = Counter(fill.raw_row_hash for fill in fills)
    for raw_hash, count in counts.items():
        if count > 1:
            duplicate_rows.append({"target": "trade_fill", "raw_row_hash": raw_hash, "count": count, "severity": "medium"})
    for fill in fills:
        if not fill.currency:
            missing_fields.append({"target": fill.id, "field": "currency", "severity": "medium"})
        if fill.qty <= 0:
            outliers.append({"target": fill.id, "field": "qty", "severity": "high"})


def _check_catalysts(store: Store, missing_fields: list[dict], stale_data: list[dict]) -> None:
    for catalyst in store.list_catalysts(limit=1000):
        if not catalyst.timezone:
            missing_fields.append({"target": catalyst.id, "field": "timezone", "severity": "medium"})
        if catalyst.status.value == "completed" and not store.list_catalyst_reviews(catalyst.id):
            stale_data.append({"target": catalyst.id, "field": "post_event_review", "severity": "high"})
        if catalyst.expected_impact.value == "high" and not catalyst.source_verified:
            missing_fields.append({"target": catalyst.id, "field": "source_verified", "severity": "medium"})


def _check_earnings_reviews(store: Store, missing_fields: list[dict]) -> None:
    for review in store.list_earnings_reviews(limit=1000):
        if not review.evidence_hash:
            missing_fields.append({"target": review.id, "field": "evidence_hash", "severity": "high"})
        if not review.run_card_id:
            missing_fields.append({"target": review.id, "field": "run_card_id", "severity": "medium"})
        if review.revenue_yoy is None:
            missing_fields.append({"target": review.id, "field": "revenue_yoy", "severity": "low"})


def _check_run_cards(store: Store, missing_fields: list[dict]) -> None:
    for run_card in store.list_run_cards(limit=1000):
        if not run_card.input_hash:
            missing_fields.append({"target": run_card.id, "field": "input_hash", "severity": "medium"})
        if run_card.status.value == "completed" and not run_card.output_hash:
            missing_fields.append({"target": run_card.id, "field": "output_hash", "severity": "medium"})
        if run_card.status.value == "completed" and not run_card.artifacts:
            missing_fields.append({"target": run_card.id, "field": "artifacts", "severity": "low"})

