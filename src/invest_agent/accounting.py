from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .models import (
    AccountingPosition,
    AccountingSnapshot,
    AccountingTaxLot,
    AccountingTransaction,
    AccountingTransactionCreate,
    AccountingTransactionType,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    TaxLotStatus,
    TradeFill,
    TradeFillSide,
    utc_now,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


ACCOUNTING_REBUILD_RULE_VERSION = "accounting_rebuild_v1"


class CanonicalAccountingService:
    def __init__(self, store: Store):
        self.store = store

    def record_transaction(self, request: AccountingTransactionCreate) -> AccountingSnapshot:
        transaction = _transaction_from_request(request)
        self.store.create_accounting_transaction(transaction)
        return self.rebuild(actor=RunCardActor.API)

    def sync_from_trade_journal(
        self,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
    ) -> AccountingSnapshot:
        fills = self.store.list_trade_fills(limit=100000, ascending=True)
        transactions = [_transaction_from_fill(fill) for fill in fills]
        self.store.add_accounting_transactions(transactions)
        return self.rebuild(actor=actor)

    def rebuild(
        self,
        *,
        actor: RunCardActor | str = RunCardActor.CLI,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> AccountingSnapshot:
        transactions = self.store.list_accounting_transactions(limit=100000, ascending=True)
        run_card = RunCardService(self.store).start_run(
            RunCardType.ACCOUNTING_REBUILD,
            title="Canonical Accounting Rebuild",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=ACCOUNTING_REBUILD_RULE_VERSION,
            inputs={"transaction_count": len(transactions)},
            dataset={"transactions": [item.model_dump(mode="json") for item in transactions]},
            assumptions={
                "lot_method": "fifo",
                "base_scope": "local_single_user_accounts",
                "unsupported_items_are_warnings": ["splits", "corporate_actions", "short_sales"],
                "creates_proposals": False,
                "approves_or_executes_trades": False,
            },
        )
        lots, warnings = _rebuild_fifo_lots(transactions)
        self.store.replace_accounting_tax_lots(lots)
        snapshot = _build_snapshot(transactions, lots, warnings, run_card.id)
        snapshot = self.store.create_accounting_snapshot(snapshot)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "transaction_count": snapshot.transaction_count,
                "open_lot_count": snapshot.open_lot_count,
                "position_count": len(snapshot.positions),
                "warning_count": len(snapshot.warnings),
            },
            warnings=snapshot.warnings,
            outputs={
                "accounting_snapshot_id": snapshot.id,
                "positions": [position.model_dump(mode="json") for position in snapshot.positions],
            },
            dataset={
                "transactions": [item.model_dump(mode="json") for item in transactions],
                "tax_lots": [item.model_dump(mode="json") for item in lots],
            },
        )
        return snapshot


def _transaction_from_request(request: AccountingTransactionCreate) -> AccountingTransaction:
    gross = request.gross_amount
    if gross is None and request.quantity is not None and request.price is not None:
        gross = request.quantity * request.price
    gross = float(gross or 0.0)
    net_cash_flow = request.net_cash_flow
    if net_cash_flow is None:
        net_cash_flow = _default_net_cash_flow(request.transaction_type, gross, request.fees, request.taxes)
    row_hash = request.row_hash or stable_hash(
        {
            "account_id": request.account_id,
            "transaction_type": request.transaction_type.value,
            "symbol": request.symbol,
            "quantity": request.quantity,
            "price": request.price,
            "gross_amount": gross,
            "fees": request.fees,
            "taxes": request.taxes,
            "net_cash_flow": net_cash_flow,
            "currency": request.currency,
            "occurred_at": request.occurred_at.isoformat(),
            "source": request.source,
            "source_id": request.source_id,
            "raw": request.raw,
        }
    )
    return AccountingTransaction(
        account_id=(request.account_id or "DEFAULT").strip().upper(),
        transaction_type=request.transaction_type,
        symbol=request.symbol,
        quantity=request.quantity,
        price=request.price,
        gross_amount=round(gross, 6),
        fees=request.fees,
        taxes=request.taxes,
        net_cash_flow=round(float(net_cash_flow), 6),
        currency=(request.currency or "USD").strip().upper(),
        occurred_at=request.occurred_at,
        settled_at=request.settled_at,
        source=request.source,
        source_id=request.source_id,
        raw=request.raw,
        row_hash=row_hash,
    )


def _transaction_from_fill(fill: TradeFill) -> AccountingTransaction:
    gross = fill.qty * fill.price
    tx_type = AccountingTransactionType.BUY if fill.side == TradeFillSide.BUY else AccountingTransactionType.SELL
    net_cash_flow = _default_net_cash_flow(tx_type, gross, fill.fees, 0.0)
    return AccountingTransaction(
        account_id="DEFAULT",
        transaction_type=tx_type,
        symbol=fill.symbol,
        quantity=fill.qty,
        price=fill.price,
        gross_amount=round(gross, 6),
        fees=fill.fees,
        taxes=0.0,
        net_cash_flow=round(net_cash_flow, 6),
        currency=fill.currency,
        occurred_at=fill.traded_at,
        source="trade_journal",
        source_id=fill.id,
        raw={"trade_fill": fill.model_dump(mode="json")},
        row_hash=f"trade_fill:{fill.raw_row_hash}",
    )


def _default_net_cash_flow(
    transaction_type: AccountingTransactionType,
    gross: float,
    fees: float,
    taxes: float,
) -> float:
    if transaction_type == AccountingTransactionType.BUY:
        return -(gross + fees + taxes)
    if transaction_type == AccountingTransactionType.SELL:
        return gross - fees - taxes
    if transaction_type in {AccountingTransactionType.DIVIDEND, AccountingTransactionType.INTEREST, AccountingTransactionType.CASH_DEPOSIT, AccountingTransactionType.TRANSFER_IN}:
        return gross - fees - taxes
    if transaction_type in {AccountingTransactionType.FEE, AccountingTransactionType.TAX_WITHHOLDING, AccountingTransactionType.CASH_WITHDRAWAL, AccountingTransactionType.TRANSFER_OUT}:
        return -(gross + fees + taxes)
    return 0.0


def _rebuild_fifo_lots(transactions: list[AccountingTransaction]) -> tuple[list[AccountingTaxLot], list[str]]:
    open_by_key: dict[tuple[str, str, str], deque[AccountingTaxLot]] = defaultdict(deque)
    all_lots: list[AccountingTaxLot] = []
    warnings: list[str] = []
    for tx in transactions:
        if tx.transaction_type in {AccountingTransactionType.SPLIT, AccountingTransactionType.CORPORATE_ACTION}:
            warnings.append(f"{tx.transaction_type.value} transaction {tx.id} is recorded but not applied to lots yet.")
            continue
        if not tx.symbol or not tx.quantity:
            continue
        key = (tx.account_id, tx.symbol, tx.currency)
        if tx.transaction_type == AccountingTransactionType.BUY:
            cost_basis = tx.gross_amount + tx.fees + tx.taxes
            lot = AccountingTaxLot(
                account_id=tx.account_id,
                symbol=tx.symbol,
                source_transaction_id=tx.id,
                opened_at=tx.occurred_at,
                quantity_original=tx.quantity,
                quantity_open=tx.quantity,
                cost_basis_original=round(cost_basis, 6),
                cost_basis_open=round(cost_basis, 6),
                currency=tx.currency,
            )
            open_by_key[key].append(lot)
            all_lots.append(lot)
        elif tx.transaction_type == AccountingTransactionType.SELL:
            remaining = tx.quantity
            while remaining > 1e-9 and open_by_key[key]:
                lot = open_by_key[key][0]
                matched = min(remaining, lot.quantity_open)
                ratio = matched / tx.quantity
                sell_costs = (tx.fees + tx.taxes) * ratio
                proceeds = matched * (tx.price or 0.0) - sell_costs
                unit_cost = lot.cost_basis_open / lot.quantity_open if lot.quantity_open else 0.0
                matched_cost = unit_cost * matched
                lot.quantity_open = round(lot.quantity_open - matched, 10)
                lot.cost_basis_open = round(max(0.0, lot.cost_basis_open - matched_cost), 6)
                lot.realized_pnl = round(lot.realized_pnl + proceeds - matched_cost, 6)
                lot.disposal_transaction_ids.append(tx.id)
                if lot.quantity_open <= 1e-9:
                    lot.quantity_open = 0.0
                    lot.cost_basis_open = 0.0
                    lot.status = TaxLotStatus.CLOSED
                    lot.closed_at = tx.occurred_at
                    open_by_key[key].popleft()
                remaining = round(remaining - matched, 10)
            if remaining > 1e-9:
                warnings.append(f"{tx.symbol} sell {tx.id} exceeds available FIFO lots by {remaining:.6f} share(s).")
    return all_lots, warnings


def _build_snapshot(
    transactions: list[AccountingTransaction],
    lots: list[AccountingTaxLot],
    warnings: list[str],
    run_card_id: str,
) -> AccountingSnapshot:
    cash_by_currency: dict[str, float] = defaultdict(float)
    fees_by_currency: dict[str, float] = defaultdict(float)
    tax_by_currency: dict[str, float] = defaultdict(float)
    dividends_by_symbol: dict[str, float] = defaultdict(float)
    realized_by_symbol: dict[str, float] = defaultdict(float)
    for tx in transactions:
        cash_by_currency[tx.currency] += tx.net_cash_flow
        fees_by_currency[tx.currency] += tx.fees
        tax_by_currency[tx.currency] += tx.taxes
        if tx.transaction_type == AccountingTransactionType.FEE:
            fees_by_currency[tx.currency] += abs(tx.gross_amount)
        if tx.transaction_type == AccountingTransactionType.TAX_WITHHOLDING:
            tax_by_currency[tx.currency] += abs(tx.gross_amount)
        if tx.transaction_type == AccountingTransactionType.DIVIDEND and tx.symbol:
            dividends_by_symbol[tx.symbol] += tx.gross_amount
    positions_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for lot in lots:
        realized_by_symbol[lot.symbol] += lot.realized_pnl
        if lot.status == TaxLotStatus.OPEN and lot.quantity_open > 0:
            key = (lot.account_id, lot.symbol, lot.currency)
            current = positions_by_key.setdefault(key, {"quantity": 0.0, "cost_basis": 0.0})
            current["quantity"] += lot.quantity_open
            current["cost_basis"] += lot.cost_basis_open
    positions = [
        AccountingPosition(
            account_id=account_id,
            symbol=symbol,
            quantity=round(data["quantity"], 10),
            cost_basis=round(data["cost_basis"], 6),
            avg_cost=round(data["cost_basis"] / data["quantity"], 6) if data["quantity"] else 0.0,
            currency=currency,
        )
        for (account_id, symbol, currency), data in sorted(positions_by_key.items())
    ]
    return AccountingSnapshot(
        as_of=utc_now(),
        transaction_count=len(transactions),
        open_lot_count=sum(1 for lot in lots if lot.status == TaxLotStatus.OPEN),
        positions=positions,
        cash_by_currency={key: round(value, 6) for key, value in sorted(cash_by_currency.items())},
        realized_pnl_by_symbol={key: round(value, 6) for key, value in sorted(realized_by_symbol.items()) if abs(value) > 1e-9},
        dividend_income_by_symbol={key: round(value, 6) for key, value in sorted(dividends_by_symbol.items()) if abs(value) > 1e-9},
        fees_by_currency={key: round(value, 6) for key, value in sorted(fees_by_currency.items()) if abs(value) > 1e-9},
        tax_withheld_by_currency={key: round(value, 6) for key, value in sorted(tax_by_currency.items()) if abs(value) > 1e-9},
        warnings=warnings,
        run_card_id=run_card_id,
    )
