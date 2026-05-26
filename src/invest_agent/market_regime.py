from __future__ import annotations

from typing import Any

from .config import Settings
from .market_context import MarketContextService
from .market_news import external_ticker
from .models import (
    GrowthPressure,
    InflationPressure,
    MarketContextSnapshot,
    MarketRegimeSnapshot,
    ProposalBias,
    RatesPressure,
    RiskAppetite,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    VolatilityRegime,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


MARKET_REGIME_RULE_VERSION = "market_regime_v1"
POSITIVE_MOVE = 0.3
NEGATIVE_MOVE = -0.5
MATERIAL_UNDERPERFORMANCE = -0.7
VOL_ELEVATED_MOVE = 1.0
VOL_STRESSED_MOVE = 3.0
RATES_MOVE = 0.5
INFLATION_MOVE = 1.0


class MarketRegimeService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def build_snapshot(self) -> MarketRegimeSnapshot:
        context = MarketContextService(self.settings, self.store).build_context()
        return self._snapshot_from_context(context)

    def refresh(
        self,
        *,
        actor: RunCardActor | str = RunCardActor.API,
        trigger_source: RunCardTriggerSource | str = RunCardTriggerSource.MANUAL,
    ) -> MarketRegimeSnapshot:
        context = MarketContextService(self.settings, self.store).build_context()
        inputs = {"market_context": context.model_dump(mode="json"), "rule_version": MARKET_REGIME_RULE_VERSION}
        run_card = RunCardService(self.store).start_run(
            RunCardType.MARKET_REGIME,
            title="Market Regime Snapshot",
            actor=actor,
            trigger_source=trigger_source,
            rule_version=MARKET_REGIME_RULE_VERSION,
            inputs=inputs,
            dataset=inputs,
            assumptions=_assumptions(),
        )
        try:
            snapshot = self._snapshot_from_context(context, run_card_id=run_card.id)
            stored = self.store.create_market_regime_snapshot(snapshot)
            RunCardService(self.store).complete_run(
                run_card.id,
                metrics=stored.metrics,
                warnings=stored.warnings,
                outputs={
                    "market_regime_snapshot_id": stored.id,
                    "risk_appetite": stored.risk_appetite.value,
                    "proposal_bias": stored.proposal_bias.value,
                    "summary": stored.summary,
                },
                dataset=inputs,
            )
            return stored
        except Exception as exc:
            RunCardService(self.store).fail_run(run_card.id, error=str(exc), write_artifacts=True)
            raise

    def _snapshot_from_context(
        self,
        context: MarketContextSnapshot,
        *,
        run_card_id: str | None = None,
    ) -> MarketRegimeSnapshot:
        changes = {
            external_ticker(item.symbol): item.change_pct
            for item in context.items
            if item.change_pct is not None
        }
        news_counts = {external_ticker(item.symbol): item.news_count for item in context.items}
        quote_coverage = int(context.coverage_summary.get("with_quote", 0) or 0)
        news_coverage = int(context.coverage_summary.get("with_news", 0) or 0)
        change_coverage = len(changes)
        warnings = list(context.risk_notes)
        drivers: list[str] = []

        spy = changes.get("SPY")
        qqq = changes.get("QQQ")
        iwm = changes.get("IWM")
        vixy = changes.get("VIXY") if "VIXY" in changes else changes.get("VIX")
        tlt = changes.get("TLT")
        gld = changes.get("GLD")
        uso = changes.get("USO")

        risk_appetite = _risk_appetite(spy, qqq, vixy)
        growth_pressure = _growth_pressure(spy, qqq, iwm)
        rates_pressure = _rates_pressure(tlt)
        volatility_regime = _volatility_regime(vixy, news_counts)
        inflation_pressure = _inflation_pressure(uso, gld)
        proposal_bias = _proposal_bias(
            risk_appetite,
            growth_pressure,
            rates_pressure,
            volatility_regime,
            inflation_pressure,
            change_coverage,
        )

        _append_driver(drivers, "SPY", spy)
        _append_driver(drivers, "QQQ", qqq)
        _append_driver(drivers, "IWM", iwm)
        _append_driver(drivers, "VIXY", vixy)
        _append_driver(drivers, "TLT", tlt)
        _append_driver(drivers, "GLD", gld)
        _append_driver(drivers, "USO", uso)
        if qqq is not None and spy is not None and qqq - spy <= MATERIAL_UNDERPERFORMANCE:
            drivers.append("QQQ 明顯弱於 SPY，成長股承壓。")
        if iwm is not None and spy is not None and iwm - spy <= -1.0:
            drivers.append("IWM 明顯弱於 SPY，小型股 / 週期風險偏弱。")
        if tlt is not None and tlt <= -RATES_MOVE:
            drivers.append("TLT 下跌，長端利率壓力偏高。")
        if uso is not None and gld is not None and uso >= INFLATION_MOVE and gld >= 0.5:
            drivers.append("USO 與 GLD 同步走強，通脹 / 避險壓力需要留意。")
        if change_coverage == 0:
            warnings.append("Market regime lacks quote change data; treating the backdrop as caution until Futu quote moves are available.")
        elif change_coverage < max(3, len(context.items) // 2):
            warnings.append("Market regime has partial quote change coverage; use as approval background, not as a trade signal.")

        metrics = {
            "quote_coverage": quote_coverage,
            "news_coverage": news_coverage,
            "change_coverage": change_coverage,
            "moves_pct": {key: value for key, value in sorted(changes.items())},
            "thresholds": _assumptions(),
        }
        input_payload: dict[str, Any] = {
            "context": context.model_dump(mode="json"),
            "metrics": metrics,
            "rule_version": MARKET_REGIME_RULE_VERSION,
        }
        return MarketRegimeSnapshot(
            symbols=context.symbols,
            quote_coverage=quote_coverage,
            news_coverage=news_coverage,
            risk_appetite=risk_appetite,
            growth_pressure=growth_pressure,
            rates_pressure=rates_pressure,
            volatility_regime=volatility_regime,
            inflation_pressure=inflation_pressure,
            proposal_bias=proposal_bias,
            summary=_summary(
                risk_appetite,
                growth_pressure,
                rates_pressure,
                volatility_regime,
                inflation_pressure,
                proposal_bias,
            ),
            warnings=warnings,
            drivers=drivers[:8],
            metrics=metrics,
            input_hash=stable_hash(input_payload),
            run_card_id=run_card_id,
        )


def _risk_appetite(spy: float | None, qqq: float | None, vixy: float | None) -> RiskAppetite:
    if (spy is not None and qqq is not None and spy <= NEGATIVE_MOVE and qqq <= NEGATIVE_MOVE) or (
        vixy is not None and vixy >= VOL_STRESSED_MOVE
    ):
        return RiskAppetite.RISK_OFF
    if (
        spy is not None
        and qqq is not None
        and spy >= POSITIVE_MOVE
        and qqq >= POSITIVE_MOVE
        and (vixy is None or vixy <= 0)
    ):
        return RiskAppetite.RISK_ON
    return RiskAppetite.NEUTRAL


def _growth_pressure(spy: float | None, qqq: float | None, iwm: float | None) -> GrowthPressure:
    if qqq is not None and qqq <= NEGATIVE_MOVE:
        return GrowthPressure.PRESSURED
    if qqq is not None and spy is not None and qqq - spy <= MATERIAL_UNDERPERFORMANCE:
        return GrowthPressure.PRESSURED
    if iwm is not None and spy is not None and iwm - spy <= -1.0:
        return GrowthPressure.PRESSURED
    if qqq is not None and qqq >= 0.5 and (spy is None or qqq - spy >= -0.3):
        return GrowthPressure.SUPPORTIVE
    return GrowthPressure.MIXED


def _rates_pressure(tlt: float | None) -> RatesPressure:
    if tlt is None:
        return RatesPressure.NEUTRAL
    if tlt <= -RATES_MOVE:
        return RatesPressure.RISING_YIELDS
    if tlt >= RATES_MOVE:
        return RatesPressure.FALLING_YIELDS
    return RatesPressure.NEUTRAL


def _volatility_regime(vixy: float | None, news_counts: dict[str, int]) -> VolatilityRegime:
    if vixy is not None and vixy >= VOL_STRESSED_MOVE:
        return VolatilityRegime.STRESSED
    if vixy is not None and vixy >= VOL_ELEVATED_MOVE:
        return VolatilityRegime.ELEVATED
    if vixy is not None and vixy <= -1.0:
        return VolatilityRegime.CALM
    if news_counts.get("VIXY", 0) or news_counts.get("VIX", 0):
        return VolatilityRegime.ELEVATED
    return VolatilityRegime.ELEVATED if vixy is None else VolatilityRegime.CALM


def _inflation_pressure(uso: float | None, gld: float | None) -> InflationPressure:
    if (uso is not None and uso >= 2.0) or (gld is not None and gld >= 1.5):
        return InflationPressure.OIL_GOLD_PRESSURE
    if uso is not None and gld is not None and uso >= INFLATION_MOVE and gld >= 0.5:
        return InflationPressure.OIL_GOLD_PRESSURE
    if uso is not None and gld is not None and uso <= -0.5 and gld <= 0.5:
        return InflationPressure.BENIGN
    return InflationPressure.MIXED


def _proposal_bias(
    risk_appetite: RiskAppetite,
    growth_pressure: GrowthPressure,
    rates_pressure: RatesPressure,
    volatility_regime: VolatilityRegime,
    inflation_pressure: InflationPressure,
    change_coverage: int,
) -> ProposalBias:
    if change_coverage == 0:
        return ProposalBias.CAUTION
    if risk_appetite == RiskAppetite.RISK_OFF and volatility_regime == VolatilityRegime.STRESSED:
        return ProposalBias.DEFENSIVE_ONLY
    if growth_pressure == GrowthPressure.PRESSURED and rates_pressure == RatesPressure.RISING_YIELDS:
        return ProposalBias.DEFENSIVE_ONLY
    if risk_appetite == RiskAppetite.RISK_OFF:
        return ProposalBias.CAUTION
    if rates_pressure == RatesPressure.RISING_YIELDS:
        return ProposalBias.CAUTION
    if volatility_regime in {VolatilityRegime.ELEVATED, VolatilityRegime.STRESSED}:
        return ProposalBias.CAUTION
    if inflation_pressure == InflationPressure.OIL_GOLD_PRESSURE:
        return ProposalBias.CAUTION
    return ProposalBias.NORMAL


def _summary(
    risk_appetite: RiskAppetite,
    growth_pressure: GrowthPressure,
    rates_pressure: RatesPressure,
    volatility_regime: VolatilityRegime,
    inflation_pressure: InflationPressure,
    proposal_bias: ProposalBias,
) -> str:
    return (
        f"市場狀態：{risk_appetite.value} / {proposal_bias.value}。"
        f" Growth={growth_pressure.value}, rates={rates_pressure.value}, "
        f"volatility={volatility_regime.value}, inflation={inflation_pressure.value}。"
    )


def _append_driver(drivers: list[str], symbol: str, change_pct: float | None) -> None:
    if change_pct is None:
        return
    direction = "上升" if change_pct >= 0 else "下跌"
    drivers.append(f"{symbol} {direction} {change_pct:.2f}%。")


def _assumptions() -> dict[str, Any]:
    return {
        "rule_version": MARKET_REGIME_RULE_VERSION,
        "positive_move_pct": POSITIVE_MOVE,
        "negative_move_pct": NEGATIVE_MOVE,
        "material_underperformance_pct": MATERIAL_UNDERPERFORMANCE,
        "vol_elevated_move_pct": VOL_ELEVATED_MOVE,
        "vol_stressed_move_pct": VOL_STRESSED_MOVE,
        "rates_move_pct": RATES_MOVE,
        "inflation_move_pct": INFLATION_MOVE,
        "research_only": True,
        "proposal_source": False,
    }
