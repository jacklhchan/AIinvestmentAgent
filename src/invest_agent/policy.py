from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .models import PortfolioSnapshot, Proposal, ProposalCreate, RiskCheck, Side
from .store import Store


class RiskEngine:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def check_create(self, request: ProposalCreate, portfolio: PortfolioSnapshot) -> RiskCheck:
        reasons: list[str] = []
        warnings: list[str] = []
        notional = float(request.qty) * float(request.limit_price)
        total_value = max(portfolio.total_value_usd, 1.0)
        proposed_pct = notional / total_value * 100.0

        if notional > self.settings.max_trade_notional_usd:
            reasons.append(
                f"notional_usd {notional:.2f} exceeds max {self.settings.max_trade_notional_usd:.2f}"
            )

        if request.confidence < self.settings.min_confidence:
            reasons.append(
                f"confidence {request.confidence:.2f} below minimum {self.settings.min_confidence:.2f}"
            )

        if proposed_pct > self.settings.max_position_pct:
            reasons.append(
                f"proposal notional is {proposed_pct:.2f}% of portfolio, above max {self.settings.max_position_pct:.2f}%"
            )

        if request.side == Side.BUY and notional > portfolio.cash_usd:
            reasons.append(f"cash_usd {portfolio.cash_usd:.2f} is lower than proposal notional {notional:.2f}")

        duplicate = self.store.pending_for_symbol(request.symbol, request.side.value)
        if duplicate:
            reasons.append(f"duplicate pending proposal for {request.symbol} {request.side.value}")

        quote = self.store.get_quote(request.symbol)
        if not quote:
            warnings.append("no local quote found; approval will require manual caution")
        else:
            spread = None
            if quote.bid and quote.ask and quote.ask > 0:
                spread = (quote.ask - quote.bid) / quote.ask * 10000
                if spread > 50:
                    warnings.append(f"wide bid/ask spread {spread:.1f} bps")

        if request.counter_evidence and request.confidence > 0.8:
            warnings.append("high confidence supplied despite counter evidence")

        return RiskCheck(
            passed=not reasons,
            reasons=reasons,
            warnings=warnings,
            metrics={
                "notional_usd": round(notional, 2),
                "portfolio_pct": round(proposed_pct, 2),
                "cash_usd": round(portfolio.cash_usd, 2),
                "mode": "paper" if self.settings.is_paper else "live",
            },
        )

    def check_approval_revalidation(self, proposal: Proposal) -> RiskCheck:
        reasons: list[str] = []
        warnings: list[str] = []

        now = datetime.now(timezone.utc)
        if proposal.expires_at < now:
            reasons.append("proposal expired")

        quote = self.store.get_quote(proposal.symbol)
        latest_price = quote.last_price if quote else proposal.limit_price
        drift_bps = abs(latest_price - proposal.limit_price) / proposal.limit_price * 10000.0
        max_drift = proposal.max_slippage_bps or self.settings.max_price_drift_bps

        if drift_bps > max_drift:
            reasons.append(f"price drift {drift_bps:.1f} bps exceeds approval threshold {max_drift:.1f} bps")

        portfolio = self.store.get_portfolio()
        notional = proposal.notional_usd
        if proposal.side == Side.BUY and notional > portfolio.cash_usd:
            reasons.append(f"cash_usd {portfolio.cash_usd:.2f} is lower than proposal notional {notional:.2f}")

        if self.settings.allow_live_trading and self.settings.mode.lower() == "live":
            warnings.append("live mode is enabled; execution adapter must perform broker-side revalidation")
        else:
            warnings.append("paper mode active; no live order will be submitted")

        return RiskCheck(
            passed=not reasons,
            reasons=reasons,
            warnings=warnings,
            metrics={
                "latest_price": latest_price,
                "limit_price": proposal.limit_price,
                "price_drift_bps": round(drift_bps, 2),
                "max_price_drift_bps": max_drift,
            },
        )
