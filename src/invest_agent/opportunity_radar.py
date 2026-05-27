from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings, get_settings
from .market_context import MarketContextService
from .market_news import external_ticker
from .market_regime import MarketRegimeService
from .models import (
    AdvisorConfidence,
    CatalystExpectedImpact,
    CatalystStatus,
    OpportunityCard,
    OpportunityCategory,
    OpportunityRadarRequest,
    OpportunityRadarRun,
    OpportunityRecommendationType,
    ProposalBias,
    RiskAppetite,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    utc_now,
    new_id,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


OPPORTUNITY_RADAR_RULE_VERSION = "opportunity_radar_v1"
SECTOR_THEME_SYMBOLS = "XLK,XLF,XLE,XLV,XLY,XLP,XLI,XLU,XLB,XLRE,SMH,SOXX,IGV,XBI,IBB,ITA,KRE,SCHD,SGOV,BIL"
TECH_RELATED = {"AAPL", "AMD", "GOOG", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "QQQM", "XLK", "SMH", "SOXX", "IGV"}
HIGH_BETA = {"AMD", "NVDA", "SMH", "SOXX", "IGV", "QQQ", "QQQM", "XLK", "XBI", "IBB", "KRE"}
ETF_LIKE = {
    "BIL",
    "DIA",
    "GLD",
    "IBB",
    "IGV",
    "IWM",
    "QQQ",
    "QQQM",
    "SCHD",
    "SGOV",
    "SMH",
    "SOXX",
    "SPY",
    "TLT",
    "USO",
    "VTI",
    "VOO",
    "XBI",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
}


@dataclass(frozen=True)
class OpportunitySpec:
    title: str
    category: OpportunityCategory
    symbols: tuple[str, ...]
    one_line: str
    thesis: str
    defensive: bool = False
    tech_related: bool = False
    high_beta: bool = False
    avoid_candidate: bool = False


OPPORTUNITY_SPECS = [
    OpportunitySpec(
        title="Core ETF / broad market",
        category=OpportunityCategory.CORE_ETF,
        symbols=("VOO", "SPY", "VTI"),
        one_line="若要增加風險，核心 ETF 比追單一熱門股更平衡。",
        thesis="core ETF 可以改善單一股票集中度，適合作為 portfolio-fit 觀察方向。",
    ),
    OpportunitySpec(
        title="Healthcare / defensive",
        category=OpportunityCategory.DEFENSIVE,
        symbols=("XLV", "XLP"),
        one_line="若波動或利率壓力升，防守型 sector 可作替代觀察。",
        thesis="defensive sector 在 caution / risk-off regime 下較能降低 portfolio beta。",
        defensive=True,
    ),
    OpportunitySpec(
        title="Cash-like / rates hedge",
        category=OpportunityCategory.CASH_LIKE,
        symbols=("SGOV", "BIL", "TLT"),
        one_line="如果目標是降低波動，現金替代與利率 exposure 值得研究。",
        thesis="cash-like / bond exposure 可在沒有高信心股票機會時保留選擇權。",
        defensive=True,
    ),
    OpportunitySpec(
        title="Financials / rate-sensitive value",
        category=OpportunityCategory.SECTOR_ROTATION,
        symbols=("XLF", "JPM", "V"),
        one_line="若 risk-on 延續且利率壓力不惡化，金融 / value 可作分散觀察。",
        thesis="financials 可提供不同於 mega-cap tech 的 sector exposure。",
    ),
    OpportunitySpec(
        title="Energy / inflation hedge",
        category=OpportunityCategory.SECTOR_ROTATION,
        symbols=("XLE", "XOM", "CVX"),
        one_line="若油價與通脹 headline 升溫，能源只宜列入研究而非追價。",
        thesis="energy 可對沖油價 / inflation pressure，但 headline risk 高。",
    ),
    OpportunitySpec(
        title="Quality software / mega-cap tech",
        category=OpportunityCategory.THEME,
        symbols=("IGV", "MSFT"),
        one_line="質素科技可以觀察，但要先檢查你現有科技曝險。",
        thesis="quality software 屬成長股 exposure，只有在 concentration 可接受時才值得升級。",
        tech_related=True,
        high_beta=True,
    ),
    OpportunitySpec(
        title="Semiconductors — only on pullback",
        category=OpportunityCategory.THEME,
        symbols=("SMH", "SOXX", "NVDA", "AMD"),
        one_line="半導體 theme 仍可觀察，但今晚不應追高。",
        thesis="AI / semis momentum 需要 primary-source catalyst 和較佳價格位置支持。",
        tech_related=True,
        high_beta=True,
    ),
    OpportunitySpec(
        title="NVDA / AMD 追買",
        category=OpportunityCategory.AVOID,
        symbols=("NVDA", "AMD"),
        one_line="已有科技曝險時，不應把熱門 AI 股追買當成新機會。",
        thesis="momentum single-name idea 容易放大 concentration 和 chasing risk。",
        tech_related=True,
        high_beta=True,
        avoid_candidate=True,
    ),
]


class OpportunityRadarService:
    def __init__(self, store: Store, *, settings: Settings | None = None):
        self.store = store
        self.settings = settings or get_settings()

    def run(
        self,
        request: OpportunityRadarRequest | None = None,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> OpportunityRadarRun:
        request = request or OpportunityRadarRequest()
        now = utc_now()
        run_id = new_id("opprun")
        run_card = RunCardService(self.store).start_run(
            RunCardType.OPPORTUNITY_RADAR,
            title="Advisor Opportunity Radar",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=OPPORTUNITY_RADAR_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            assumptions={
                "radar_output_is_research_only": True,
                "cannot_create_pending_proposals": True,
                "cannot_approve_or_execute_trades": True,
                "alpha_or_screening_evidence_is_supplementary": True,
            },
        )
        context = MarketContextService(self.settings, self.store).build_context()
        regime = MarketRegimeService(self.settings, self.store).refresh(
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
        )
        portfolio = self.store.get_portfolio()
        risk_snapshot = next(iter(self.store.list_portfolio_risk_snapshots(limit=1)), None)
        behavior_report = next(iter(self.store.list_behavior_reports(limit=1)), None)
        shadow_report = next(iter(self.store.list_shadow_reports(limit=1)), None)
        cards = self._build_cards(
            run_id,
            run_card.id,
            request,
            context,
            regime,
            portfolio,
            risk_snapshot,
            behavior_report,
            shadow_report,
            now=now,
        )
        radar = OpportunityRadarRun(
            id=run_id,
            question=request.question,
            run_type=request.run_type,
            market_regime_snapshot_id=regime.id,
            portfolio_risk_snapshot_id=risk_snapshot.id if risk_snapshot else None,
            run_card_id=run_card.id,
            summary=_radar_summary(cards),
            cards=cards,
            created_at=now,
        )
        stored = self.store.create_opportunity_radar_run(radar)
        dataset = {
            "request": request.model_dump(mode="json"),
            "market_context": context.model_dump(mode="json"),
            "market_regime": regime.model_dump(mode="json"),
            "portfolio": portfolio.model_dump(mode="json"),
            "portfolio_risk_snapshot_id": risk_snapshot.id if risk_snapshot else None,
            "behavior_report_id": behavior_report.id if behavior_report else None,
            "shadow_report_id": shadow_report.id if shadow_report else None,
            "cards": [card.model_dump(mode="json") for card in cards],
        }
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "card_count": len(cards),
                "watch_or_research": sum(
                    1
                    for card in cards
                    if card.recommendation_type
                    in {
                        OpportunityRecommendationType.WATCH,
                        OpportunityRecommendationType.RESEARCH,
                        OpportunityRecommendationType.ACTION_CANDIDATE,
                    }
                ),
                "blocked_or_avoid": sum(
                    1
                    for card in cards
                    if card.recommendation_type
                    in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID}
                ),
                "scoring_version": OPPORTUNITY_RADAR_RULE_VERSION,
            },
            warnings=[*context.risk_notes, *regime.warnings],
            outputs=stored.model_dump(mode="json"),
            dataset=dataset,
            evidence_hash=stable_hash(dataset),
            write_artifacts=False,
        )
        return stored

    def _build_cards(
        self,
        run_id: str,
        run_card_id: str,
        request: OpportunityRadarRequest,
        context,
        regime,
        portfolio,
        risk_snapshot,
        behavior_report,
        shadow_report,
        *,
        now,
    ) -> list[OpportunityCard]:
        quotes = {external_ticker(quote.symbol): quote for quote in self.store.list_quotes()}
        news_counts = _news_counts(self.store.list_news(limit=200))
        fundamentals = {external_ticker(item.symbol) for item in self.store.list_fundamentals()}
        active_theses = {
            external_ticker(item.symbol)
            for item in self.store.list_theses(limit=200)
            if item.human_confirmed
        }
        catalyst_blocks = _catalyst_blocks(self.store.list_catalysts(limit=200))
        total_value = portfolio.total_value_usd or portfolio.cash_usd + sum(item.market_value for item in portfolio.positions)
        cash_weight = portfolio.cash_usd / total_value if total_value else 0.0
        tech_weight = _tech_weight(portfolio)
        chasing_flag = _behavior_chasing_flag(behavior_report, shadow_report)

        positive: list[OpportunityCard] = []
        blocked: list[OpportunityCard] = []
        for spec in OPPORTUNITY_SPECS:
            card = self._card_from_spec(
                spec,
                run_id,
                run_card_id,
                context,
                regime,
                quotes,
                news_counts,
                fundamentals,
                active_theses,
                catalyst_blocks,
                tech_weight,
                cash_weight,
                chasing_flag,
                risk_snapshot,
                behavior_report,
                shadow_report,
                now=now,
            )
            if card.recommendation_type in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID}:
                blocked.append(card)
            else:
                positive.append(card)

        positive = sorted(positive, key=lambda item: item.score, reverse=True)[: request.max_watch]
        blocked = sorted(blocked, key=lambda item: (item.recommendation_type == OpportunityRecommendationType.AVOID, -item.score), reverse=True)[
            : request.max_blocked
        ]
        cards = [*positive, *blocked]
        for index, card in enumerate(cards, start=1):
            card.rank = index
        return cards

    def _card_from_spec(
        self,
        spec: OpportunitySpec,
        run_id: str,
        run_card_id: str,
        context,
        regime,
        quotes: dict[str, Any],
        news_counts: dict[str, int],
        fundamentals: set[str],
        active_theses: set[str],
        catalyst_blocks: dict[str, str],
        tech_weight: float,
        cash_weight: float,
        chasing_flag: bool,
        risk_snapshot,
        behavior_report,
        shadow_report,
        *,
        now,
    ) -> OpportunityCard:
        tickers = [external_ticker(symbol) for symbol in spec.symbols]
        move = _max_move(tickers, quotes)
        relative_move = _relative_move(move, quotes.get("SPY"))
        quote_count = sum(1 for ticker in tickers if ticker in quotes)
        news_count = sum(news_counts.get(ticker, 0) for ticker in tickers)
        primary_count = sum(1 for ticker in tickers if ticker in fundamentals or ticker in active_theses)
        has_single_stock = any(ticker not in ETF_LIKE for ticker in tickers)
        market_score, market_reason = _market_alignment_score(spec, regime)
        rotation_score, rotation_reason = _rotation_score(spec, move, relative_move, quote_count)
        portfolio_score, portfolio_reason, portfolio_risks = _portfolio_fit_score(spec, tech_weight, cash_weight)
        evidence_score, evidence_reason = _evidence_score(spec, quote_count, news_count, primary_count, has_single_stock)
        penalties, risk_reasons, blockers = _risk_penalties(
            spec,
            regime,
            move,
            tech_weight,
            chasing_flag,
            catalyst_blocks,
            tickers,
            has_single_stock,
            primary_count,
        )
        score = market_score + rotation_score + portfolio_score + evidence_score - penalties
        recommendation = _recommendation_from_score(score, blockers, spec)
        confidence = _confidence(score, blockers, quote_count, news_count, primary_count)
        evidence_layers = {
            "market_regime": [regime.summary, *regime.drivers[:2]],
            "sector_theme_rotation": [rotation_reason],
            "symbol_specific": _symbol_evidence(tickers, quotes, news_counts, fundamentals, active_theses, catalyst_blocks),
            "portfolio_fit": [portfolio_reason],
            "risk_gate": risk_reasons or ["沒有發現足以升級為交易建議的 gate-passing evidence。"],
            "behavior_shadow": [_behavior_evidence(chasing_flag, behavior_report, shadow_report)],
        }
        reasons = _clean(
            [
                market_reason,
                rotation_reason,
                portfolio_reason,
                evidence_reason,
            ]
        )[:3]
        risks = _clean([*portfolio_risks, *risk_reasons])[:3]
        linked = {
            "run_card_id": run_card_id,
            "market_regime_snapshot_id": regime.id,
            "portfolio_risk_snapshot_id": risk_snapshot.id if risk_snapshot else None,
            "behavior_report_id": behavior_report.id if behavior_report else None,
            "shadow_report_id": shadow_report.id if shadow_report else None,
            "quote_symbols": [ticker for ticker in tickers if ticker in quotes],
            "news_symbols": [ticker for ticker in tickers if news_counts.get(ticker)],
        }
        return OpportunityCard(
            run_id=run_id,
            title=f"{spec.title}：{_recommendation_label(recommendation)}",
            category=spec.category,
            symbols=list(spec.symbols),
            recommendation_type=recommendation,
            confidence=confidence,
            score=score,
            one_line=spec.one_line,
            reasons=reasons,
            risks=risks,
            evidence_layers=evidence_layers,
            upgrade_conditions=_upgrade_conditions(spec),
            downgrade_conditions=_downgrade_conditions(spec),
            linked_artifacts=linked,
            created_at=now,
        )


def _news_counts(items) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not item.symbol:
            continue
        ticker = external_ticker(item.symbol)
        counts[ticker] = counts.get(ticker, 0) + 1
    return counts


def _catalyst_blocks(catalysts) -> dict[str, str]:
    blockers: dict[str, str] = {}
    for catalyst in catalysts:
        if not catalyst.symbol:
            continue
        ticker = external_ticker(catalyst.symbol)
        if catalyst.status == CatalystStatus.UPCOMING and catalyst.expected_impact == CatalystExpectedImpact.HIGH:
            blockers[ticker] = "高影響 catalyst 尚未完成 / review。"
        elif catalyst.status == CatalystStatus.COMPLETED and not catalyst.linked_research_goal_id:
            blockers[ticker] = "catalyst 已完成但未有 post-event review。"
    return blockers


def _tech_weight(portfolio) -> float:
    total = portfolio.total_value_usd or portfolio.cash_usd + sum(position.market_value for position in portfolio.positions)
    if total <= 0:
        return 0.0
    return sum(
        position.market_value
        for position in portfolio.positions
        if external_ticker(position.symbol) in TECH_RELATED
    ) / total


def _behavior_chasing_flag(behavior_report, shadow_report) -> bool:
    if behavior_report:
        for key, diagnostic in behavior_report.diagnostics.items():
            text = f"{key} {diagnostic.summary}".lower()
            if any(token in text for token in ["chasing", "momentum", "overtrading", "追高"]):
                if diagnostic.score >= 0.5:
                    return True
    if shadow_report:
        text = " ".join(str(value) for value in shadow_report.diagnostics.values()).lower()
        if any(token in text for token in ["chasing", "momentum", "追高"]):
            return True
    return False


def _max_move(tickers: list[str], quotes: dict[str, Any]) -> float | None:
    moves = [quotes[ticker].change_pct for ticker in tickers if ticker in quotes and quotes[ticker].change_pct is not None]
    if not moves:
        return None
    return max(moves, key=abs)


def _relative_move(move: float | None, spy_quote) -> float | None:
    if move is None or not spy_quote or spy_quote.change_pct is None:
        return None
    return move - spy_quote.change_pct


def _market_alignment_score(spec: OpportunitySpec, regime) -> tuple[int, str]:
    if spec.defensive and regime.proposal_bias in {ProposalBias.CAUTION, ProposalBias.DEFENSIVE_ONLY}:
        return 2, f"{spec.title} 配合目前 {regime.proposal_bias.value} 的風險預算。"
    if spec.defensive and regime.risk_appetite == RiskAppetite.RISK_OFF:
        return 2, "risk_off 下，防守 / 現金替代方向比高 beta 單股更合理。"
    if spec.high_beta and regime.risk_appetite == RiskAppetite.RISK_OFF:
        return -3, "risk_off 下，高 beta theme 只能列入 blocked/watch，不應追。"
    if regime.risk_appetite == RiskAppetite.RISK_ON and not spec.defensive:
        return 2, "市場 regime 偏 risk_on，可研究但仍不可跳過 evidence gate。"
    if spec.category == OpportunityCategory.CORE_ETF:
        return 1, "核心 ETF 可作為 portfolio-level 風險配置，而不是單一股票訊號。"
    return 0, f"市場 regime：{regime.risk_appetite.value} / {regime.proposal_bias.value}。"


def _rotation_score(spec: OpportunitySpec, move: float | None, relative_move: float | None, quote_count: int) -> tuple[int, str]:
    if quote_count == 0:
        return 0, "sector/theme quote coverage 未齊，先作 research-only 觀察。"
    score = 0
    if move is not None and move >= 1.0:
        score += 1
    if relative_move is not None and relative_move >= 0.5:
        score += 1
    if move is not None and move <= -1.5:
        score -= 1
    if score > 0:
        return score, f"{spec.title} 本機 quote 顯示相對強勢 / 動能，但仍要避免單靠價格追買。"
    if score < 0:
        return score, f"{spec.title} 本機 quote 偏弱，不足以升級。"
    return score, f"{spec.title} 未見明顯 sector rotation 優勢。"


def _portfolio_fit_score(spec: OpportunitySpec, tech_weight: float, cash_weight: float) -> tuple[int, str, list[str]]:
    risks: list[str] = []
    if spec.tech_related and tech_weight >= 0.4:
        risks.append(f"科技相關持倉約 {tech_weight:.1%}，再加 AI/tech 會提高集中度。")
        return -3, "你的 portfolio 已偏科技，新增科技 theme 的 portfolio fit 較弱。", risks
    if spec.tech_related and tech_weight >= 0.25:
        risks.append(f"科技相關持倉約 {tech_weight:.1%}，需要小心 concentration。")
        return -1, "科技曝險已不低，科技 theme 只能 watch。", risks
    if spec.category in {OpportunityCategory.CORE_ETF, OpportunityCategory.DEFENSIVE, OpportunityCategory.CASH_LIKE}:
        score = 2 if tech_weight >= 0.25 else 1
        if cash_weight >= 0.2:
            score += 1
        return score, "這個方向有助分散現有持倉，不會直接加重單一科技股風險。", risks
    return 0, "portfolio fit 中性；需要看 sector evidence 和風險 gate。", risks


def _evidence_score(
    spec: OpportunitySpec,
    quote_count: int,
    news_count: int,
    primary_count: int,
    has_single_stock: bool,
) -> tuple[int, str]:
    score = 0
    if quote_count:
        score += 1
    if news_count:
        score += 1
    if primary_count:
        score += 2
    if has_single_stock and primary_count == 0:
        return score - 1, "包含單股但沒有 active thesis / fundamentals primary evidence，只能 research/watch。"
    if score >= 3:
        return score, "已有 quote/news/primary-source 或 thesis coverage 支持列入候選。"
    if score:
        return score, "有部分 quote/news evidence，但未足以成為 action candidate。"
    return 0, "本機 evidence coverage 不足，先保留為 research。"


def _risk_penalties(
    spec: OpportunitySpec,
    regime,
    move: float | None,
    tech_weight: float,
    chasing_flag: bool,
    catalyst_blocks: dict[str, str],
    tickers: list[str],
    has_single_stock: bool,
    primary_count: int,
) -> tuple[int, list[str], list[str]]:
    penalty = 0
    risks: list[str] = []
    blockers: list[str] = []
    if spec.avoid_candidate:
        blockers.append("這是 chasing / concentration watch-out，不應列為買入機會。")
        penalty += 4
    if regime.risk_appetite == RiskAppetite.RISK_OFF and spec.high_beta:
        blockers.append("market regime risk_off，阻擋高 beta 新增風險。")
        penalty += 3
    if spec.tech_related and tech_weight >= 0.4:
        blockers.append("portfolio tech exposure 已高，阻擋追高式科技加倉。")
        penalty += 3
    if move is not None and move >= 3.0 and spec.high_beta:
        blockers.append(f"本機 quote 顯示相關標的已變動 {move:+.2f}%，屬 chasing risk。")
        penalty += 3
    elif move is not None and move >= 2.0:
        risks.append(f"本機 quote 顯示相關標的已變動 {move:+.2f}%，不要用市價追。")
        penalty += 1
    if chasing_flag and spec.high_beta:
        risks.append("Behavior / shadow evidence 顯示近期可能有追高或 momentum chasing 風險。")
        penalty += 2
    for ticker in tickers:
        if ticker in catalyst_blocks:
            blockers.append(f"{ticker}: {catalyst_blocks[ticker]}")
            penalty += 3
    if has_single_stock and primary_count == 0:
        blockers.append("包含單股但缺少 source-backed thesis / SEC / IR / fundamentals evidence；不可升級為 action_candidate。")
        penalty += 3
    return penalty, _clean([*risks, *blockers]), blockers


def _recommendation_from_score(score: int, blockers: list[str], spec: OpportunitySpec) -> OpportunityRecommendationType:
    if spec.avoid_candidate:
        return OpportunityRecommendationType.AVOID
    if blockers or score < 0:
        return OpportunityRecommendationType.BLOCKED
    if score >= 5:
        return OpportunityRecommendationType.ACTION_CANDIDATE
    if score >= 2:
        return OpportunityRecommendationType.WATCH
    return OpportunityRecommendationType.RESEARCH


def _confidence(score: int, blockers: list[str], quote_count: int, news_count: int, primary_count: int) -> AdvisorConfidence:
    if blockers:
        return AdvisorConfidence.MEDIUM
    if score >= 5 and quote_count and (news_count or primary_count):
        return AdvisorConfidence.HIGH
    if score >= 2 or quote_count or news_count or primary_count:
        return AdvisorConfidence.MEDIUM
    return AdvisorConfidence.LOW


def _symbol_evidence(
    tickers: list[str],
    quotes: dict[str, Any],
    news_counts: dict[str, int],
    fundamentals: set[str],
    active_theses: set[str],
    catalyst_blocks: dict[str, str],
) -> list[str]:
    evidence: list[str] = []
    for ticker in tickers[:5]:
        parts: list[str] = []
        quote = quotes.get(ticker)
        if quote and quote.change_pct is not None:
            parts.append(f"quote {quote.change_pct:+.2f}%")
        if news_counts.get(ticker):
            parts.append(f"{news_counts[ticker]} news")
        if ticker in fundamentals:
            parts.append("fundamentals")
        if ticker in active_theses:
            parts.append("active thesis")
        if ticker in catalyst_blocks:
            parts.append("catalyst blocker")
        if parts:
            evidence.append(f"{ticker}: {', '.join(parts)}")
    return evidence or ["本機未有足夠 symbol-specific coverage。"]


def _behavior_evidence(chasing_flag: bool, behavior_report, shadow_report) -> str:
    if chasing_flag:
        return "behavior/shadow evidence 有 chasing 或 momentum 風險，會 downgrade 高 beta idea。"
    if behavior_report or shadow_report:
        return "已檢查最新 behavior/shadow artifacts，未見嚴重 chasing blocker。"
    return "暫未有最新 behavior/shadow evidence；不會因此升級任何 idea。"


def _upgrade_conditions(spec: OpportunitySpec) -> list[str]:
    conditions = [
        "market regime 不可是 risk_off。",
        "sector/theme strength 要持續，不是單一 tick noise。",
        "portfolio concentration 仍在你確認的 risk profile 上限內。",
        "沒有未 review 的 high-impact catalyst / earnings event。",
        "若涉及單股，要有 source-backed thesis / SEC / IR / fundamentals evidence。",
        "即使升級，也只可進入 research/proposal candidate，仍需 policy check 與人工確認。",
    ]
    if spec.tech_related:
        conditions.append("科技 / AI exposure 回到可接受區間，且不是追高。")
    return conditions[:6]


def _downgrade_conditions(spec: OpportunitySpec) -> list[str]:
    conditions = [
        "市場轉 risk_off 或 volatility proxy 急升。",
        "相關 ETF / sector 明顯跑輸 SPY/QQQ。",
        "出現 thesis-breaking primary-source event。",
        "資料品質或 quote/news coverage 不足。",
    ]
    if spec.high_beta:
        conditions.append("價格急升後只剩 momentum chasing，而非新 evidence。")
    return conditions


def _radar_summary(cards: list[OpportunityCard]) -> str:
    positives = [
        card
        for card in cards
        if card.recommendation_type
        in {
            OpportunityRecommendationType.ACTION_CANDIDATE,
            OpportunityRecommendationType.WATCH,
            OpportunityRecommendationType.RESEARCH,
        }
    ]
    blocked = [
        card
        for card in cards
        if card.recommendation_type in {OpportunityRecommendationType.BLOCKED, OpportunityRecommendationType.AVOID}
    ]
    if positives:
        return f"有 {len(positives)} 個值得觀察 / 研究的方向，但不等於買入；另有 {len(blocked)} 個 blocked / avoid idea。"
    return "暫時沒有足夠 evidence-ranked opportunity；今晚以觀察與風險控制為主。"


def _recommendation_label(value: OpportunityRecommendationType) -> str:
    return {
        OpportunityRecommendationType.ACTION_CANDIDATE: "ACTION_CANDIDATE",
        OpportunityRecommendationType.WATCH: "WATCH",
        OpportunityRecommendationType.RESEARCH: "RESEARCH",
        OpportunityRecommendationType.BLOCKED: "BLOCKED",
        OpportunityRecommendationType.AVOID: "AVOID",
    }[value]


def _clean(items: list[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for item in items:
        value = " ".join(str(item).split())
        if value and value not in seen:
            clean.append(value)
            seen.add(value)
    return clean
