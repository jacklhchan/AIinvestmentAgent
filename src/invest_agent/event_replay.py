from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings
from .models import EventReplayResult, FundamentalSnapshot, NewsItem, PortfolioSnapshot, Quote
from .proposal_drafts import ProposalDraftEngine
from .services import InvestmentService
from .store import Store


DEFAULT_REPLAY_PATH = Path("artifacts/replay/latest-events.jsonl")


def export_event_replay(store: Store, path: Path | str = DEFAULT_REPLAY_PATH, *, news_limit: int = 100) -> EventReplayResult:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    counts = {"portfolio": 0, "quote": 0, "news_item": 0, "fundamental_snapshot": 0}
    with output_path.open("w", encoding="utf-8") as handle:
        _write_event(handle, "portfolio", store.get_portfolio())
        counts["portfolio"] += 1
        for quote in store.list_quotes():
            _write_event(handle, "quote", quote)
            counts["quote"] += 1
        for item in store.list_news(limit=news_limit):
            _write_event(handle, "news_item", item)
            counts["news_item"] += 1
        for snapshot in store.list_fundamentals():
            _write_event(handle, "fundamental_snapshot", snapshot)
            counts["fundamental_snapshot"] += 1

    store.audit("event_replay_exported", "event_replay", str(output_path), counts)
    return EventReplayResult(path=str(output_path), exported_counts=counts)


def replay_event_file(
    settings: Settings,
    store: Store,
    path: Path | str = DEFAULT_REPLAY_PATH,
    *,
    create_proposals: bool = False,
    run_drafts: bool = True,
) -> EventReplayResult:
    input_path = Path(path)
    counts: dict[str, int] = {}
    errors: list[str] = []
    if not input_path.exists():
        return EventReplayResult(path=str(input_path), errors=[f"event replay file not found: {input_path}"])

    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
                event_type = str(event.get("type") or "")
                payload = event.get("payload")
                _apply_event(store, event_type, payload)
                counts[event_type] = counts.get(event_type, 0) + 1
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"line {line_number}: {exc}")

    draft_result = None
    if run_drafts:
        draft_result = ProposalDraftEngine(settings, store, InvestmentService(settings, store)).draft_from_watchlist(
            create_proposals=create_proposals
        )

    store.audit(
        "events_replayed",
        "event_replay",
        str(input_path),
        {"imported_counts": counts, "errors": errors, "create_proposals": create_proposals},
    )
    return EventReplayResult(path=str(input_path), imported_counts=counts, errors=errors, draft_result=draft_result)


def _write_event(handle, event_type: str, model: Any) -> None:
    payload = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
    handle.write(json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False) + "\n")


def _apply_event(store: Store, event_type: str, payload: Any) -> None:
    if event_type == "portfolio":
        store.upsert_portfolio(PortfolioSnapshot.model_validate(payload))
        return
    if event_type == "quote":
        store.upsert_quote(Quote.model_validate(payload))
        return
    if event_type == "news_item":
        store.upsert_news(NewsItem.model_validate(payload))
        return
    if event_type == "fundamental_snapshot":
        store.upsert_fundamentals(FundamentalSnapshot.model_validate(payload))
        return
    raise ValueError(f"unsupported event type {event_type!r}")
