from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .advisor import AdvisorService
from .config import Settings, get_settings
from .market_news import external_ticker, resolve_watchlist_symbols
from .market_regime import MarketRegimeService
from .models import (
    AdvisorAnswer,
    AdvisorBriefItem,
    AdvisorBriefRequest,
    AdvisorConfidence,
    AdvisorFullBrief,
    AdvisorFullBriefType,
    AdvisorProfile,
    AdvisorProfileConfirmationRequest,
    AdvisorProfileUpdate,
    AdvisorProfileUpdateRequest,
    AdvisorProfileUpdateStatus,
    AdvisorPulse,
    AdvisorPulseSeverity,
    AdvisorQuestion,
    AdvisorQuestionRequest,
    AdvisorRecommendation,
    AdvisorSeverity,
    AdvisorSourceType,
    CatalystExpectedImpact,
    CatalystStatus,
    ProposalBias,
    RiskAppetite,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    SymbolResolutionStatus,
    ThesisStatus,
    new_id,
    utc_now,
)
from .run_cards import RunCardService, stable_hash
from .store import Store


ADVISOR_RULE_VERSION = "hermes_advisor_mode_v1"
NY_TZ = ZoneInfo("America/New_York")
SGT_TZ = ZoneInfo("Asia/Singapore")
CORE_ETFS = {"VOO", "SPY", "IVV", "VTI"}
TECH_SYMBOL_HINTS = {"AAPL", "AMD", "GOOG", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "QQQM", "TSLA"}
SYMBOL_STOP_WORDS = {
    "A",
    "AI",
    "AN",
    "AND",
    "ASK",
    "BUY",
    "DO",
    "ETF",
    "FOR",
    "HOLD",
    "HOW",
    "I",
    "INFO",
    "IPO",
    "IR",
    "ME",
    "MORE",
    "MY",
    "NEED",
    "NO",
    "NOW",
    "OR",
    "SEC",
    "SELL",
    "SGT",
    "THE",
    "TO",
    "USD",
    "US",
    "WATCH",
    "WHAT",
    "WHEN",
    "WHERE",
    "WHY",
    "YES",
}
PORTFOLIO_STRATEGY_TERMS = [
    "allocation",
    "portfolio",
    "strategy",
    "tonight",
    "risk budget",
    "配置",
    "組合",
    "策略",
    "今晚",
    "今日策略",
]
PRIVATE_OFFERING_TERMS = [
    "ipo",
    "pre-ipo",
    "private",
    "spacex",
    "未上市",
    "上市前",
    "私募",
    "配售",
]


@dataclass(frozen=True)
class AdvisorScheduleContext:
    market_session_date: str
    market_open_et: str
    market_close_et: str
    market_open_sgt: str
    market_close_sgt: str
    pre_market_brief_sgt: str
    post_close_brief_sgt: str
    quiet_hours_sgt: str = "00:00-07:00"

    def as_dict(self) -> dict[str, str]:
        return {
            "market_session_date": self.market_session_date,
            "market_open_et": self.market_open_et,
            "market_close_et": self.market_close_et,
            "market_open_sgt": self.market_open_sgt,
            "market_close_sgt": self.market_close_sgt,
            "pre_market_brief_sgt": self.pre_market_brief_sgt,
            "post_close_brief_sgt": self.post_close_brief_sgt,
            "quiet_hours_sgt": self.quiet_hours_sgt,
        }


@dataclass(frozen=True)
class SymbolResolution:
    original_symbol: str | None
    resolved_symbol: str | None
    status: SymbolResolutionStatus


class AdvisorOrchestrator:
    def __init__(self, store: Store, *, settings: Settings | None = None, paper_only: bool | None = None):
        self.store = store
        self.settings = settings or get_settings()
        self.paper_only = self.settings.is_paper if paper_only is None else paper_only

    def answer_user_question(
        self,
        request: AdvisorQuestionRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> AdvisorAnswer:
        intent = _question_intent(request.question)
        resolution = self._resolve_question_symbol(request.question, request.symbol, intent=intent)
        symbol = resolution.resolved_symbol
        inputs = request.model_dump(mode="json")
        inputs.update(
            {
                "original_symbol": resolution.original_symbol,
                "resolved_symbol": resolution.resolved_symbol,
                "symbol_resolution_status": resolution.status.value,
                "question_intent": intent,
            }
        )
        question_id = new_id("advq")
        run_card = RunCardService(self.store).start_run(
            RunCardType.ADVISOR_QUESTION,
            title="Hermes Advisor Question",
            symbol=symbol,
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=ADVISOR_RULE_VERSION,
            inputs=inputs,
            assumptions={
                "advisor_output_is_research_only": True,
                "cannot_create_pending_proposals": True,
                "cannot_approve_or_execute_trades": True,
            },
        )
        brief = AdvisorService(self.store, settings=self.settings, paper_only=self.paper_only).build_brief(
            AdvisorBriefRequest(max_items=12)
        )
        profile = self.store.get_advisor_profile()
        decision = self._build_answer(question_id, request.question, resolution, brief, run_card.id, profile)
        question = AdvisorQuestion(
            id=question_id,
            user_question=request.question,
            symbol=symbol,
            original_symbol=resolution.original_symbol,
            resolved_symbol=resolution.resolved_symbol,
            symbol_resolution_status=resolution.status,
            answer_summary=decision.summary,
            recommendation_type=decision.recommendation_type,
            confidence=decision.confidence,
            run_card_id=run_card.id,
            created_at=decision.created_at,
        )
        self.store.create_advisor_question(question)
        self.store.create_advisor_recommendation(
            AdvisorRecommendation(
                source_type=AdvisorSourceType.QUESTION,
                source_id=question.id,
                symbol=symbol,
                recommendation_type=decision.recommendation_type,
                title=decision.conclusion,
                summary=decision.summary,
                suggested_user_action=decision.suggested_user_action,
                confidence=decision.confidence,
                reasons=decision.reasons,
                risks=decision.risks,
                linked_artifacts=decision.linked_artifacts_json,
                created_at=decision.created_at,
            )
        )
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "recommendation_type": decision.recommendation_type.value,
                "confidence": decision.confidence.value,
                "reason_count": len(decision.reasons),
                "risk_count": len(decision.risks),
                "advisor_profile_version": profile.version if profile else None,
            },
            warnings=[],
            outputs=decision.model_dump(mode="json"),
            dataset={"advisor_brief_hash": stable_hash(brief.model_dump(mode="json"))},
            write_artifacts=False,
        )
        return decision

    def get_advisor_profile(self) -> dict[str, Any]:
        return {
            "profile": self.store.get_advisor_profile(),
            "pending_updates": self.store.list_advisor_profile_updates(
                status=AdvisorProfileUpdateStatus.PENDING,
                limit=10,
            ),
        }

    def suggest_profile_update(self, request: AdvisorProfileUpdateRequest) -> AdvisorProfileUpdate:
        changes = _profile_changes_from_request(request)
        if not changes:
            raise ValueError("profile update suggestion must include at least one preference")
        update = AdvisorProfileUpdate(
            proposed_changes=changes,
            rationale=request.rationale,
            source_question_id=request.source_question_id,
            proposed_by=request.proposed_by,
        )
        return self.store.create_advisor_profile_update(update)

    def confirm_profile_update(
        self,
        update_id: str,
        request: AdvisorProfileConfirmationRequest | None = None,
    ) -> AdvisorProfileUpdate:
        request = request or AdvisorProfileConfirmationRequest()
        update = self.store.get_advisor_profile_update(update_id)
        if not update:
            raise ValueError(f"advisor profile update not found: {update_id}")
        if update.status != AdvisorProfileUpdateStatus.PENDING:
            raise ValueError(f"advisor profile update is already {update.status.value}: {update_id}")
        if not request.confirmed:
            update.status = AdvisorProfileUpdateStatus.REJECTED
            update.confirmed_at = utc_now()
            update.confirmed_by = request.confirmed_by
            update.rejection_reason = request.rejection_reason or "Rejected by user"
            return self.store.update_advisor_profile_update(update)

        current = self.store.get_advisor_profile()
        profile = _apply_profile_changes(current, update, confirmed_by=request.confirmed_by)
        stored_profile = self.store.upsert_advisor_profile(profile)
        update.status = AdvisorProfileUpdateStatus.CONFIRMED
        update.confirmed_at = stored_profile.updated_at
        update.confirmed_by = request.confirmed_by
        update.applied_profile_version = stored_profile.version
        return self.store.update_advisor_profile_update(update)

    def run_hourly_pulse(
        self,
        *,
        now: datetime | None = None,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> AdvisorPulse:
        now = _aware_utc(now or utc_now())
        pulse_id = new_id("advpulse")
        run_card = RunCardService(self.store).start_run(
            RunCardType.ADVISOR_PULSE,
            title="Hermes Hourly Advisor Pulse",
            actor=actor,
            trigger_source=RunCardTriggerSource.SCHEDULED,
            rule_version=ADVISOR_RULE_VERSION,
            inputs={"now": now.isoformat()},
            assumptions={
                "pulse_checks_only_urgent_local_state": True,
                "cannot_create_pending_proposals": True,
                "urgent_can_bypass_quiet_hours": True,
            },
        )
        recommendations = self._build_pulse_recommendations(pulse_id, now)
        severity = _pulse_severity(recommendations)
        quiet = _is_quiet_hours(now)
        should_notify = severity == AdvisorPulseSeverity.URGENT or (
            severity == AdvisorPulseSeverity.WATCH and not quiet
        )
        summary = _pulse_summary(severity, recommendations)
        pulse = AdvisorPulse(
            id=pulse_id,
            severity=severity,
            summary=summary,
            recommendations=recommendations,
            should_notify=should_notify,
            sent_to_user=False,
            run_card_id=run_card.id,
            created_at=now,
        )
        self.store.create_advisor_pulse(pulse)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={
                "severity": severity.value,
                "recommendation_count": len(recommendations),
                "should_notify": should_notify,
                "quiet_hours": quiet,
            },
            warnings=[],
            outputs=pulse.model_dump(mode="json"),
            dataset={"recommendations": [item.model_dump(mode="json") for item in recommendations]},
            write_artifacts=False,
        )
        return pulse

    def run_full_advisor_brief(
        self,
        brief_type: AdvisorFullBriefType,
        *,
        now: datetime | None = None,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> AdvisorFullBrief:
        now = _aware_utc(now or utc_now())
        session_date = market_session_date(now, brief_type)
        schedule = advisor_schedule_context(session_date)
        regime = MarketRegimeService(self.settings, self.store).refresh(
            actor=actor,
            trigger_source=RunCardTriggerSource.SCHEDULED,
        )
        advisor = AdvisorService(self.store, settings=self.settings, paper_only=self.paper_only).build_brief(
            AdvisorBriefRequest(max_items=20)
        )
        brief_id = new_id("advbrief")
        recommendations = [
            _recommendation_from_brief_item(
                item,
                source_id=brief_id,
                source_type=AdvisorSourceType.BRIEF,
                created_at=now,
            )
            for item in advisor.advice
        ]
        committee_ids = [item.id for item in self.store.list_committee_reviews(limit=3)]
        run_card = RunCardService(self.store).start_run(
            RunCardType.ADVISOR_BRIEF,
            title=f"Hermes {brief_type.value} Advisor Brief",
            actor=actor,
            trigger_source=RunCardTriggerSource.SCHEDULED,
            rule_version=ADVISOR_RULE_VERSION,
            inputs={"brief_type": brief_type.value, "now": now.isoformat()},
            dataset={
                "advisor_brief_hash": stable_hash(advisor.model_dump(mode="json")),
                "market_regime_snapshot_id": regime.id,
                "schedule": schedule.as_dict(),
            },
            assumptions={
                "full_brief_is_research_only": True,
                "cannot_create_pending_proposals": True,
                "cannot_approve_or_execute_trades": True,
            },
        )
        record = AdvisorFullBrief(
            id=brief_id,
            brief_type=brief_type,
            market_session_date=session_date.isoformat(),
            summary=_full_brief_summary(brief_type, advisor.risk_level, regime.proposal_bias),
            market_regime_snapshot_id=regime.id,
            recommendations=recommendations,
            committee_review_ids_json=committee_ids,
            run_card_id=run_card.id,
            sent_to_user=False,
            schedule_context=schedule.as_dict(),
            created_at=now,
        )
        self.store.create_advisor_brief(record)
        grouped = _group_recommendations(recommendations)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={key: len(value) for key, value in grouped.items()},
            warnings=[],
            outputs={
                "advisor_brief_id": record.id,
                "brief_type": record.brief_type.value,
                "market_session_date": record.market_session_date,
            },
            dataset=record.model_dump(mode="json"),
            write_artifacts=False,
        )
        return record

    def _build_answer(
        self,
        question_id: str,
        question: str,
        resolution: SymbolResolution,
        brief,
        run_card_id: str,
        profile: AdvisorProfile | None = None,
    ) -> AdvisorAnswer:
        symbol = resolution.resolved_symbol
        intent = _question_intent(question)
        regime = brief.data_status.get("market_regime", {})
        proposal_bias = regime.get("proposal_bias", ProposalBias.CAUTION.value)
        risk_appetite = regime.get("risk_appetite", RiskAppetite.NEUTRAL.value)
        relevant_items = [] if not symbol and intent != "portfolio" else self._relevant_brief_items(symbol, brief.advice)
        top_candidates = relevant_items or (brief.advice if symbol or intent == "portfolio" else [])
        top_item = max(top_candidates, key=_advisor_item_rank, default=None)
        quote = self.store.get_quote(symbol) if symbol else None
        position = self._position(symbol)
        active_theses = self.store.list_theses(status=ThesisStatus.ACTIVE, symbol=symbol, limit=5) if symbol else []
        catalysts = self.store.list_catalysts(symbol=symbol, limit=20) if symbol else []
        high_catalyst_block = any(
            item.status == CatalystStatus.UPCOMING and item.expected_impact == CatalystExpectedImpact.HIGH
            for item in catalysts
        )
        completed_without_review = any(
            item.status == CatalystStatus.COMPLETED and not item.linked_research_goal_id for item in catalysts
        )
        hard_block = (
            bool(top_item and top_item.severity == AdvisorSeverity.BLOCKED)
            or high_catalyst_block
            or completed_without_review
        )
        caution = (
            proposal_bias in {ProposalBias.CAUTION.value, ProposalBias.DEFENSIVE_ONLY.value}
            or risk_appetite == RiskAppetite.RISK_OFF.value
        )
        lacks_thesis = bool(symbol and position and not active_theses)
        artifacts = _linked_artifacts(symbol, relevant_items, run_card_id, quote, active_theses, catalysts)

        extra_reasons: list[str] = []
        extra_risks: list[str] = []
        profile_reasons, profile_risks, profile_blocks = self._profile_context(
            profile,
            intent,
            symbol,
            quote,
            position,
            resolution,
        )
        if profile:
            artifacts.append({"type": "advisor_profile", "id": profile.id, "version": profile.version})

        if not symbol and resolution.status == SymbolResolutionStatus.PRIVATE_COMPANY:
            recommendation = AdvisorSeverity.BLOCKED
            subject = _private_subject(question)
            conclusion = f"{subject}：未有公開可交易資料前，不建議投資。"
            summary = "這類 IPO / 未上市機會不應由 Hermes 直接給入場金額或建立買入 proposal。"
            action = "先做研究任務；等 S-1 / prospectus、定價、估值、lock-up、流動性與可交易渠道清楚後再評估。"
            confidence = AdvisorConfidence.MEDIUM
            extra_reasons = [
                "目前沒有本機可驗證 ticker / primary-source package 支持直接行動。",
                "未上市或 IPO 配售不屬於現有 paper-only proposal 的直接交易範圍。",
            ]
            extra_risks = [
                "估值、配售條款、lock-up、流動性與資訊不對稱風險可能很高。",
            ]
        elif not symbol and resolution.status == SymbolResolutionStatus.PORTFOLIO_SCOPE:
            if top_item and top_item.severity in {AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED}:
                recommendation = top_item.severity
            else:
                recommendation = AdvisorSeverity.WATCH
            if recommendation == AdvisorSeverity.ACTION:
                conclusion = "Portfolio：有 item 需要你處理，但不要追高。"
            elif recommendation == AdvisorSeverity.BLOCKED:
                conclusion = "Portfolio：有風險阻擋，暫停新增風險。"
            else:
                conclusion = "Portfolio：今晚偏保守，先 Hold / Watch。"
            summary = "這是 portfolio strategy 問題；Advisor 會用 regime、持倉風險與最新 brief 給你前台建議。"
            action = (
                top_item.next_action
                if top_item and recommendation == AdvisorSeverity.ACTION
                else "暫時不要追高或主動加大風險；若你仍想買賣，先建立手動 proposal 並走 evidence / policy / human confirmation。"
            )
            confidence = AdvisorConfidence.MEDIUM
            extra_reasons = ["問題屬於 portfolio-level strategy，不應被抽成單一假 ticker。"]
        elif not symbol and resolution.status == SymbolResolutionStatus.UNKNOWN:
            subject = resolution.original_symbol or "未知代號"
            recommendation = AdvisorSeverity.BLOCKED
            conclusion = f"{subject}：未在本機 universe 內，先不要買賣。"
            summary = "Advisor 找不到 holdings / watchlist / quote / thesis / catalyst context，不能把它當成可行交易建議。"
            action = "先加入觀察或建立研究任務；等 evidence、可交易市場與 policy gate 清楚後再評估。"
            confidence = AdvisorConfidence.LOW
            extra_reasons = [
                f"{subject} 未通過本機 known universe / holdings / watchlist / quote cache 解析。",
                "未知 symbol 不應直接進入 proposal pipeline。",
            ]
            extra_risks = ["如果這其實是有效 ticker，仍需要先補齊資料來源與交易範圍。"]
        elif not symbol:
            recommendation = AdvisorSeverity.WATCH
            conclusion = "需要更多資料：請指定股票代號。"
            summary = "我可以先看 portfolio / regime，但要回答買賣問題需要明確 symbol。"
            action = "用例如「Hermes，我而家應唔應該買 AAPL？」再問一次。"
            confidence = AdvisorConfidence.LOW
        elif intent == "buy":
            if (
                profile_blocks
                or hard_block
                or proposal_bias == ProposalBias.DEFENSIVE_ONLY.value
                or risk_appetite == RiskAppetite.RISK_OFF.value
            ):
                recommendation = AdvisorSeverity.BLOCKED
                conclusion = f"{symbol}：暫時不要買。"
                summary = "不建議現在建立新 BUY；先等 profile / event / evidence / regime 重新通過。"
                action = "先 watch；若你仍想買，只能建立手動 proposal，並接受 evidence、thesis、catalyst、policy check。"
                confidence = AdvisorConfidence.HIGH if hard_block or profile_blocks else AdvisorConfidence.MEDIUM
            elif caution or lacks_thesis or not active_theses:
                recommendation = AdvisorSeverity.WATCH
                conclusion = f"{symbol}：暫時不建議追買，建議觀察。"
                summary = "目前更像 watch / research 狀態，不是直接加倉狀態。"
                action = "先建立研究任務或等 pullback / verified catalyst；不要直接建立 pending proposal。"
                confidence = AdvisorConfidence.MEDIUM
            else:
                recommendation = AdvisorSeverity.ACTION
                conclusion = f"{symbol}：可以考慮小注，但要先過 proposal gate。"
                summary = "目前沒有明顯硬阻擋；若你決定行動，仍需走本機 proposal、policy 與人工確認。"
                action = "用手動 proposal 進入 InvestmentService 檢查；Hermes 不能批准或下單。"
                confidence = AdvisorConfidence.MEDIUM
        elif intent == "sell":
            if not position:
                recommendation = AdvisorSeverity.INFO
                conclusion = f"{symbol}：本機 portfolio 未見持倉，不需要賣。"
                summary = "目前沒有可賣出的本機持倉紀錄。"
                action = "如資料不準，先刷新 Futu read-only snapshot。"
                confidence = AdvisorConfidence.MEDIUM
            elif hard_block or (top_item and top_item.category in {"earnings", "shadow"} and top_item.severity == AdvisorSeverity.ACTION):
                recommendation = AdvisorSeverity.ACTION
                conclusion = f"{symbol}：可以研究減倉 / 賣出，但不要讓 Hermes 直接執行。"
                summary = "有 thesis / catalyst / behavior 相關警示，值得你作人工決定。"
                action = "先看詳情；若要交易，建立手動 proposal 並走人工確認。"
                confidence = AdvisorConfidence.MEDIUM
            else:
                recommendation = AdvisorSeverity.WATCH
                conclusion = f"{symbol}：不建議立即賣出，建議降低觀察門檻。"
                summary = "未見明確 thesis-breaking 訊號；但 regime 或資料完整性仍要跟進。"
                action = "Hold / watch；如跌穿 thesis risk trigger 或出現負面 primary-source event，再重評。"
                confidence = AdvisorConfidence.MEDIUM
        else:
            recommendation = top_item.severity if top_item else AdvisorSeverity.INFO
            conclusion = f"{symbol}：目前以 {recommendation.value} 處理。"
            summary = top_item.title if top_item else "目前沒有高優先級 advisor item。"
            action = top_item.next_action if top_item else "保持觀察；需要交易時仍要走 proposal gate。"
            confidence = AdvisorConfidence.MEDIUM if top_item else AdvisorConfidence.LOW

        reasons = _clean_list(
            [
                *profile_reasons,
                *extra_reasons,
                *_top_reasons(symbol, relevant_items, quote, active_theses, regime, recommendation),
            ]
        )
        risks = _clean_list([*profile_risks, *extra_risks, *_top_risks(intent, recommendation, caution)])
        return AdvisorAnswer(
            question_id=question_id,
            recommendation=recommendation,
            recommendation_type=recommendation,
            original_symbol=resolution.original_symbol,
            resolved_symbol=resolution.resolved_symbol,
            symbol_resolution_status=resolution.status,
            conclusion=conclusion,
            summary=summary,
            confidence=confidence,
            suggested_user_action=action,
            reasons=reasons[:3],
            risks=risks[:3],
            decision_required=recommendation == AdvisorSeverity.ACTION,
            details_available=bool(artifacts),
            linked_artifacts_json=artifacts,
            run_card_id=run_card_id,
            paper_only=self.paper_only,
        )

    def _profile_context(
        self,
        profile: AdvisorProfile | None,
        intent: str,
        symbol: str | None,
        quote,
        position,
        resolution: SymbolResolution,
    ) -> tuple[list[str], list[str], bool]:
        if not profile:
            return [], [], False
        reasons = [f"已套用 Advisor Profile v{profile.version}（{profile.risk_profile.value}）。"]
        risks: list[str] = []
        blocks = False
        if resolution.status == SymbolResolutionStatus.PRIVATE_COMPANY and profile.allow_ipo_or_private is False:
            reasons.append("你的 profile 不允許 IPO / 未上市私募類投資；只能保留為研究。")
            blocks = True
        if intent == "buy" and quote and quote.change_pct is not None and profile.avoid_chasing_after_big_move:
            if quote.change_pct >= 3:
                reasons.append(f"你的 profile 設定不追高；{symbol} 本機行情已變動 {quote.change_pct:+.2f}%。")
                blocks = True
        if intent == "buy" and symbol and profile.prefer_core_etf and external_ticker(symbol) not in CORE_ETFS:
            reasons.append("你的 profile 偏好核心 ETF 優先；單股加倉需要更強 evidence。")
        if intent == "buy" and position and profile.max_single_stock_weight is not None:
            total = self.store.get_portfolio().total_value_usd or 0
            if total > 0:
                weight = position.market_value / total
                if weight >= profile.max_single_stock_weight:
                    reasons.append(
                        f"{symbol} 已佔 portfolio 約 {weight:.1%}，高於你確認的單股上限 {profile.max_single_stock_weight:.1%}。"
                    )
                    blocks = True
        if intent in {"buy", "portfolio"} and profile.max_tech_exposure is not None:
            tech_weight = _tech_exposure_weight(self.store.get_portfolio())
            if tech_weight >= profile.max_tech_exposure:
                reasons.append(
                    f"科技相關曝險約 {tech_weight:.1%}，高於你確認的上限 {profile.max_tech_exposure:.1%}。"
                )
                blocks = True
        if profile.min_cash_weight is not None:
            portfolio = self.store.get_portfolio()
            total = portfolio.total_value_usd or portfolio.cash_usd + sum(item.market_value for item in portfolio.positions)
            if total > 0 and portfolio.cash_usd / total < profile.min_cash_weight:
                risks.append(f"現金比例低於你確認的底線 {profile.min_cash_weight:.1%}；新增買入會降低 buffer。")
        return _clean_list(reasons)[:3], _clean_list(risks)[:3], blocks

    def _build_pulse_recommendations(self, pulse_id: str, now: datetime) -> list[AdvisorRecommendation]:
        recommendations: list[AdvisorRecommendation] = []
        regime = MarketRegimeService(self.settings, self.store).build_snapshot()
        if regime.proposal_bias != ProposalBias.NORMAL or regime.risk_appetite == RiskAppetite.RISK_OFF:
            recommendations.append(
                _make_recommendation(
                    source_type=AdvisorSourceType.PULSE,
                    source_id=pulse_id,
                    recommendation_type=AdvisorSeverity.WATCH
                    if regime.proposal_bias != ProposalBias.DEFENSIVE_ONLY
                    else AdvisorSeverity.BLOCKED,
                    title=f"Market regime: {regime.risk_appetite.value} / {regime.proposal_bias.value}",
                    summary=regime.summary or "市場狀態需要納入新 proposal 前的風險檢查。",
                    suggested_user_action="今晚不要主動增加 portfolio risk，除非有高信心 verified catalyst。",
                    confidence=AdvisorConfidence.MEDIUM,
                    reasons=[*regime.drivers[:2], *regime.warnings[:1]] or [regime.summary],
                    risks=["若市場快速 risk-on，watch stance 可能錯過短線升幅。"],
                    linked_artifacts=[{"type": "market_regime", "id": regime.id}],
                    created_at=now,
                )
            )

        held_symbols = {position.symbol for position in self.store.get_portfolio().positions}
        for catalyst in self.store.list_catalysts(limit=100):
            if catalyst.status == CatalystStatus.UPCOMING and catalyst.expected_impact == CatalystExpectedImpact.HIGH:
                event_date = _aware_utc(catalyst.event_date)
                if timedelta(0) <= event_date - now <= timedelta(hours=48):
                    symbol = catalyst.symbol
                    urgent = not symbol or symbol in held_symbols
                    recommendations.append(
                        _make_recommendation(
                            source_type=AdvisorSourceType.PULSE,
                            source_id=pulse_id,
                            symbol=symbol,
                            recommendation_type=AdvisorSeverity.BLOCKED if urgent else AdvisorSeverity.WATCH,
                            title=f"{symbol or 'Portfolio'} 高影響催化事件接近",
                            summary="高影響事件窗口內不應追買或建立未經 review 的新 proposal。",
                            suggested_user_action="暫停新 BUY；等事件完成並做 post-event review。",
                            confidence=AdvisorConfidence.HIGH,
                            reasons=[catalyst.title, "高影響 catalyst 進入 48 小時窗口。"],
                            risks=["事件結果可能直接削弱 thesis。"],
                            linked_artifacts=[{"type": "catalyst", "id": catalyst.id}],
                            created_at=now,
                        )
                    )
            if catalyst.status == CatalystStatus.COMPLETED and not catalyst.linked_research_goal_id:
                recommendations.append(
                    _make_recommendation(
                        source_type=AdvisorSourceType.PULSE,
                        source_id=pulse_id,
                        symbol=catalyst.symbol,
                        recommendation_type=AdvisorSeverity.BLOCKED
                        if catalyst.symbol in held_symbols
                        else AdvisorSeverity.WATCH,
                        title=f"{catalyst.symbol or 'Portfolio'} 事件完成但未 review",
                        summary="事件後缺少 thesis delta，系統應先 block 新 proposal。",
                        suggested_user_action="先建立 post-event review，再考慮任何新買賣。",
                        confidence=AdvisorConfidence.HIGH,
                        reasons=[catalyst.title, "completed catalyst 尚未連到 research goal / review。"],
                        risks=["用未 review 事件作依據容易把舊 thesis 當成仍有效。"],
                        linked_artifacts=[{"type": "catalyst", "id": catalyst.id}],
                        created_at=now,
                    )
                )

        for quote in self.store.list_quotes():
            move = quote.change_pct
            if move is None or abs(move) < 5:
                continue
            is_holding = quote.symbol in held_symbols
            urgent = is_holding and abs(move) >= 8
            recommendations.append(
                _make_recommendation(
                    source_type=AdvisorSourceType.PULSE,
                    source_id=pulse_id,
                    symbol=quote.symbol,
                    recommendation_type=AdvisorSeverity.ACTION if urgent else AdvisorSeverity.WATCH,
                    title=f"{quote.symbol} 大幅波動 {move:+.2f}%",
                    summary="本機 quote 顯示異常波動，需要檢查是否有 catalyst / news / thesis trigger。",
                    suggested_user_action="先看 primary-source 或 news spike；不要因波動本身直接追單。",
                    confidence=AdvisorConfidence.HIGH if urgent else AdvisorConfidence.MEDIUM,
                    reasons=[f"quote change_pct={move:+.2f}%", f"source={quote.source}"],
                    risks=["只用價格波動可能誤判；需配合 evidence。"],
                    linked_artifacts=[{"type": "quote", "id": quote.symbol}],
                    created_at=now,
                )
            )

        latest_risk = self.store.list_portfolio_risk_snapshots(limit=1)
        if latest_risk and latest_risk[0].concentration_warnings:
            recommendations.append(
                _make_recommendation(
                    source_type=AdvisorSourceType.PULSE,
                    source_id=pulse_id,
                    recommendation_type=AdvisorSeverity.ACTION,
                    title="Portfolio risk breach / concentration warning",
                    summary="最新 portfolio risk snapshot 有集中度或 drift warning。",
                    suggested_user_action="暫停增加同方向風險；先 review concentration。",
                    confidence=AdvisorConfidence.MEDIUM,
                    reasons=latest_risk[0].concentration_warnings[:3],
                    risks=["忽略集中度可能放大單一事件損失。"],
                    linked_artifacts=[{"type": "portfolio_risk", "id": latest_risk[0].id}],
                    created_at=now,
                )
            )

        latest_quality = self.store.list_data_quality_reports(limit=1)
        if latest_quality and latest_quality[0].severity_counts.get("critical", 0):
            recommendations.append(
                _make_recommendation(
                    source_type=AdvisorSourceType.PULSE,
                    source_id=pulse_id,
                    recommendation_type=AdvisorSeverity.BLOCKED,
                    title="Data quality critical issue",
                    summary="資料品質報告出現 critical issue，advisor 應停止新 proposal 建議。",
                    suggested_user_action="先修復資料品質，再重新跑 advisor brief。",
                    confidence=AdvisorConfidence.HIGH,
                    reasons=[latest_quality[0].summary or "critical data quality issue detected"],
                    risks=["錯誤資料會污染 thesis、risk 與 proposal gate。"],
                    linked_artifacts=[{"type": "data_quality", "id": latest_quality[0].id}],
                    created_at=now,
                )
            )
        return recommendations[:12]

    def _resolve_question_symbol(
        self,
        question: str,
        requested_symbol: str | None = None,
        *,
        intent: str | None = None,
    ) -> SymbolResolution:
        intent = intent or _question_intent(question)
        requested = _normalize_symbol_candidate(requested_symbol)
        if intent == "private":
            return SymbolResolution(
                original_symbol=requested or _private_original_symbol(question),
                resolved_symbol=None,
                status=SymbolResolutionStatus.PRIVATE_COMPANY,
            )

        candidates = self._symbol_candidates()
        if requested:
            resolved = _resolve_symbol_candidate(requested, candidates)
            if resolved:
                return SymbolResolution(requested, resolved, SymbolResolutionStatus.RESOLVED)
            if _is_plausible_unknown_symbol(requested):
                return SymbolResolution(requested, None, SymbolResolutionStatus.UNKNOWN)

        for token in _uppercase_symbol_tokens(question):
            resolved = _resolve_symbol_candidate(token, candidates)
            if resolved:
                return SymbolResolution(token, resolved, SymbolResolutionStatus.RESOLVED)
        for token in _uppercase_symbol_tokens(question):
            if _is_plausible_unknown_symbol(token):
                return SymbolResolution(token, None, SymbolResolutionStatus.UNKNOWN)
        if intent == "portfolio":
            return SymbolResolution(requested, None, SymbolResolutionStatus.PORTFOLIO_SCOPE)
        return SymbolResolution(requested, None, SymbolResolutionStatus.NO_SYMBOL)

    def _extract_symbol(self, question: str) -> str | None:
        return self._resolve_question_symbol(question).resolved_symbol

    def _symbol_candidates(self) -> dict[str, str]:
        symbols: list[str] = []
        symbols.extend(resolve_watchlist_symbols(self.settings, self.store))
        symbols.extend(position.symbol for position in self.store.get_portfolio().positions)
        symbols.extend(quote.symbol for quote in self.store.list_quotes())
        symbols.extend(snapshot.symbol for snapshot in self.store.list_fundamentals())
        symbols.extend(thesis.symbol for thesis in self.store.list_theses(limit=200) if thesis.symbol)
        symbols.extend(catalyst.symbol for catalyst in self.store.list_catalysts(limit=200) if catalyst.symbol)

        candidates: dict[str, str] = {}
        for raw in symbols:
            symbol = _normalize_symbol_candidate(raw)
            if not symbol:
                continue
            candidates[symbol] = symbol
            candidates[external_ticker(symbol)] = symbol
        return candidates

    def _position(self, symbol: str | None):
        if not symbol:
            return None
        ticker = external_ticker(symbol)
        return next((position for position in self.store.get_portfolio().positions if external_ticker(position.symbol) == ticker), None)

    def _relevant_brief_items(self, symbol: str | None, items: list[AdvisorBriefItem]) -> list[AdvisorBriefItem]:
        if not symbol:
            return list(items)
        ticker = external_ticker(symbol)
        relevant = []
        for item in items:
            haystack = " ".join([item.title, item.rationale, item.next_action, *item.related_ids]).upper()
            if ticker in haystack or symbol.upper() in haystack:
                relevant.append(item)
        generic = [item for item in items if item.category in {"market", "market_regime", "behavior", "shadow", "research"}]
        return [*relevant, *[item for item in generic if item not in relevant]]


def advisor_schedule_context(session_date: date) -> AdvisorScheduleContext:
    open_et, close_et = market_open_close(session_date)
    pre = open_et - timedelta(minutes=45)
    post = close_et + timedelta(minutes=30)
    return AdvisorScheduleContext(
        market_session_date=session_date.isoformat(),
        market_open_et=open_et.isoformat(),
        market_close_et=close_et.isoformat(),
        market_open_sgt=open_et.astimezone(SGT_TZ).isoformat(),
        market_close_sgt=close_et.astimezone(SGT_TZ).isoformat(),
        pre_market_brief_sgt=pre.astimezone(SGT_TZ).isoformat(),
        post_close_brief_sgt=post.astimezone(SGT_TZ).isoformat(),
    )


def market_session_date(now: datetime, brief_type: AdvisorFullBriefType) -> date:
    ny_now = _aware_utc(now).astimezone(NY_TZ)
    current = ny_now.date()
    if brief_type == AdvisorFullBriefType.PRE_MARKET:
        if is_trading_day(current):
            _, close_et = market_open_close(current)
            if ny_now < close_et:
                return current
        return next_trading_day(current + timedelta(days=1))
    if is_trading_day(current):
        _, close_et = market_open_close(current)
        if ny_now >= close_et:
            return current
    return previous_trading_day(current - timedelta(days=1))


def market_open_close(session_date: date) -> tuple[datetime, datetime]:
    open_at = datetime.combine(session_date, time(9, 30), tzinfo=NY_TZ)
    close_hour = 13 if is_early_close(session_date) else 16
    close_at = datetime.combine(session_date, time(close_hour, 0), tzinfo=NY_TZ)
    return open_at, close_at


def is_trading_day(value: date) -> bool:
    return value.weekday() < 5 and value not in market_holidays(value.year)


def next_trading_day(value: date) -> date:
    cursor = value
    for _ in range(21):
        if is_trading_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return value


def previous_trading_day(value: date) -> date:
    cursor = value
    for _ in range(21):
        if is_trading_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return value


def market_holidays(year: int) -> set[date]:
    years = (year - 1, year, year + 1)
    holidays: set[date] = set()
    for item_year in years:
        holidays.update(
            {
                _observed(date(item_year, 1, 1)),
                _nth_weekday(item_year, 1, 0, 3),
                _nth_weekday(item_year, 2, 0, 3),
                _easter_date(item_year) - timedelta(days=2),
                _last_weekday(item_year, 5, 0),
                _observed(date(item_year, 6, 19)),
                _observed(date(item_year, 7, 4)),
                _nth_weekday(item_year, 9, 0, 1),
                _nth_weekday(item_year, 11, 3, 4),
                _observed(date(item_year, 12, 25)),
            }
        )
    return holidays


def is_early_close(value: date) -> bool:
    thanksgiving = _nth_weekday(value.year, 11, 3, 4)
    christmas_eve = date(value.year, 12, 24)
    july_third = date(value.year, 7, 3)
    return value in {thanksgiving + timedelta(days=1), christmas_eve, july_third} and value.weekday() < 5


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    cursor = date(year, month, 1)
    while cursor.weekday() != weekday:
        cursor += timedelta(days=1)
    return cursor + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    cursor = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _make_recommendation(
    *,
    source_type: AdvisorSourceType,
    source_id: str,
    title: str,
    summary: str,
    suggested_user_action: str,
    recommendation_type: AdvisorSeverity,
    confidence: AdvisorConfidence,
    reasons: list[str] | None = None,
    risks: list[str] | None = None,
    linked_artifacts: list[dict[str, Any]] | None = None,
    symbol: str | None = None,
    created_at: datetime | None = None,
) -> AdvisorRecommendation:
    return AdvisorRecommendation(
        source_type=source_type,
        source_id=source_id,
        symbol=symbol,
        recommendation_type=recommendation_type,
        title=title,
        summary=summary,
        suggested_user_action=suggested_user_action,
        confidence=confidence,
        reasons=_clean_list(reasons or [])[:3],
        risks=_clean_list(risks or [])[:3],
        linked_artifacts=linked_artifacts or [],
        created_at=created_at or utc_now(),
    )


def _recommendation_from_brief_item(
    item: AdvisorBriefItem,
    *,
    source_id: str,
    source_type: AdvisorSourceType,
    created_at: datetime,
) -> AdvisorRecommendation:
    symbol = next((value for value in item.related_ids if re.fullmatch(r"[A-Z]{1,6}", value)), None)
    return _make_recommendation(
        source_type=source_type,
        source_id=source_id,
        symbol=symbol,
        recommendation_type=item.severity,
        title=item.title,
        summary=item.rationale,
        suggested_user_action=item.next_action,
        confidence=AdvisorConfidence.MEDIUM,
        reasons=[item.rationale],
        risks=[item.next_action] if item.severity in {AdvisorSeverity.ACTION, AdvisorSeverity.BLOCKED} else [],
        linked_artifacts=[{"type": item.category, "id": related_id} for related_id in item.related_ids[:5]],
        created_at=created_at,
    )


def _profile_changes_from_request(request: AdvisorProfileUpdateRequest) -> dict[str, Any]:
    raw = request.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"rationale", "source_question_id", "proposed_by"},
    )
    return {key: value for key, value in raw.items() if value != []}


def _apply_profile_changes(
    current: AdvisorProfile | None,
    update: AdvisorProfileUpdate,
    *,
    confirmed_by: str,
) -> AdvisorProfile:
    next_version = (current.version + 1) if current else 1
    base = current.model_dump(mode="json") if current else AdvisorProfile(version=1).model_dump(mode="json")
    notes = list(base.get("notes") or [])
    changes = dict(update.proposed_changes)
    if "notes" in changes:
        notes = _clean_list([*notes, *changes.pop("notes")])
    base.update(changes)
    base.update(
        {
            "id": "default",
            "version": next_version,
            "notes": notes,
            "confirmed_by": confirmed_by,
            "source_update_id": update.id,
            "updated_at": utc_now().isoformat(),
        }
    )
    return AdvisorProfile.model_validate(base)


def _tech_exposure_weight(portfolio) -> float:
    total = portfolio.total_value_usd or portfolio.cash_usd + sum(position.market_value for position in portfolio.positions)
    if total <= 0:
        return 0.0
    tech_value = sum(
        position.market_value
        for position in portfolio.positions
        if external_ticker(position.symbol) in TECH_SYMBOL_HINTS
    )
    return tech_value / total


def _question_intent(question: str) -> str:
    text = question.lower()
    if any(token in text for token in PRIVATE_OFFERING_TERMS):
        return "private"
    if any(token in text for token in ["buy", "invest", "買", "加倉", "追買", "入", "投資"]):
        return "buy"
    if any(token in text for token in ["sell", "賣", "減倉", "trim", "exit", "沽"]):
        return "sell"
    if any(token in text for token in PORTFOLIO_STRATEGY_TERMS):
        return "portfolio"
    return "review"


def _normalize_symbol_candidate(symbol: str | None) -> str | None:
    if not symbol:
        return None
    value = symbol.strip().upper()
    return value or None


def _resolve_symbol_candidate(symbol: str, candidates: dict[str, str]) -> str | None:
    ticker = external_ticker(symbol)
    return candidates.get(symbol) or candidates.get(ticker)


def _uppercase_symbol_tokens(question: str) -> list[str]:
    return re.findall(r"\b[A-Z][A-Z0-9.]{0,5}\b", question)


def _is_plausible_unknown_symbol(symbol: str) -> bool:
    ticker = external_ticker(symbol)
    if ticker in SYMBOL_STOP_WORDS or symbol in SYMBOL_STOP_WORDS:
        return False
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,5}", symbol):
        return False
    return any(char.isalpha() for char in symbol)


def _private_subject(question: str) -> str:
    lowered = question.lower()
    if "spacex" in lowered:
        return "SpaceX IPO"
    if "ipo" in lowered:
        return "IPO / 未上市機會"
    return "未上市 / 私募機會"


def _private_original_symbol(question: str) -> str | None:
    lowered = question.lower()
    if "spacex" in lowered:
        return "SPACEX"
    if "ipo" in lowered:
        return "IPO"
    return None


def _top_reasons(
    symbol: str | None,
    items: list[AdvisorBriefItem],
    quote,
    active_theses,
    regime: dict[str, Any],
    recommendation: AdvisorSeverity,
) -> list[str]:
    reasons: list[str] = []
    if regime:
        reasons.append(
            f"市場 regime：{regime.get('risk_appetite', 'unknown')} / {regime.get('proposal_bias', 'unknown')}。"
        )
    if quote and quote.change_pct is not None:
        reasons.append(f"{symbol} 本機行情變動 {quote.change_pct:+.2f}%，不可單靠價格動作追單。")
    if symbol and active_theses:
        reasons.append(f"{symbol} 有 {len(active_theses)} 個 active thesis，可作為後續 review 背景。")
    elif symbol and recommendation in {AdvisorSeverity.WATCH, AdvisorSeverity.BLOCKED}:
        reasons.append(f"{symbol} 暫未有足夠已確認 thesis / evidence 支持直接行動。")
    for item in items:
        reasons.append(item.rationale)
    return _clean_list(reasons)[:3] or ["目前沒有足夠高信心資料支持直接交易。"]


def _top_risks(intent: str, recommendation: AdvisorSeverity, caution: bool) -> list[str]:
    risks: list[str] = []
    if intent == "private":
        risks.append("未上市 / IPO 機會可能有高估值、低流動性與條款不透明風險。")
    if intent == "portfolio":
        risks.append("Portfolio-level 建議可能未覆蓋每一隻股票的最新單一催化事件。")
    if intent == "buy" and recommendation in {AdvisorSeverity.WATCH, AdvisorSeverity.BLOCKED}:
        risks.append("如果市場重新 risk-on，可能錯過短線上升。")
    if intent == "buy" and recommendation == AdvisorSeverity.ACTION:
        risks.append("即使可以考慮小注，仍可能被 evidence gate / policy check 擋下。")
    if intent == "sell" and recommendation in {AdvisorSeverity.WATCH, AdvisorSeverity.INFO}:
        risks.append("若之後出現負面 primary-source event，可能需要更快重新評估。")
    if caution:
        risks.append("市場偏 caution 時，新增風險或追高容易放大回撤。")
    risks.append("Advice 不等於交易；任何買賣仍需 human confirmation。")
    return _clean_list(risks)[:3]


def _linked_artifacts(symbol: str | None, items: list[AdvisorBriefItem], run_card_id: str, quote, theses, catalysts) -> list[dict[str, Any]]:
    artifacts = [{"type": "run_card", "id": run_card_id}]
    artifacts.extend({"type": item.category, "id": related_id} for item in items for related_id in item.related_ids[:2])
    if quote:
        artifacts.append({"type": "quote", "id": quote.symbol})
    artifacts.extend({"type": "thesis", "id": item.id} for item in theses[:3])
    artifacts.extend({"type": "catalyst", "id": item.id} for item in catalysts[:3])
    if symbol:
        artifacts.append({"type": "symbol", "id": symbol})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (str(artifact.get("type")), str(artifact.get("id")))
        if key not in seen:
            seen.add(key)
            deduped.append(artifact)
    return deduped[:12]


def _pulse_severity(recommendations: list[AdvisorRecommendation]) -> AdvisorPulseSeverity:
    if not recommendations:
        return AdvisorPulseSeverity.SILENT
    if any(item.recommendation_type in {AdvisorSeverity.BLOCKED, AdvisorSeverity.ACTION} and item.confidence == AdvisorConfidence.HIGH for item in recommendations):
        return AdvisorPulseSeverity.URGENT
    if any(item.recommendation_type in {AdvisorSeverity.BLOCKED, AdvisorSeverity.ACTION, AdvisorSeverity.WATCH} for item in recommendations):
        return AdvisorPulseSeverity.WATCH
    return AdvisorPulseSeverity.INFO


def _pulse_summary(severity: AdvisorPulseSeverity, recommendations: list[AdvisorRecommendation]) -> str:
    if severity == AdvisorPulseSeverity.SILENT:
        return "No urgent event. Stored hourly pulse."
    first = recommendations[0]
    if severity == AdvisorPulseSeverity.URGENT:
        return f"Urgent: {first.title}。建議先暫停相關新 proposal。"
    if severity == AdvisorPulseSeverity.WATCH:
        return f"Watch: {first.title}。建議降低新增風險。"
    return first.summary


def _full_brief_summary(brief_type: AdvisorFullBriefType, risk_level: AdvisorSeverity, proposal_bias: ProposalBias) -> str:
    if brief_type == AdvisorFullBriefType.PRE_MARKET:
        if risk_level in {AdvisorSeverity.BLOCKED, AdvisorSeverity.ACTION} or proposal_bias != ProposalBias.NORMAL:
            return "今晚 stance 偏保守；可以觀察，但不建議主動加大風險。"
        return "今晚未見高優先級阻擋；仍保持 paper-only proposal discipline。"
    if risk_level in {AdvisorSeverity.BLOCKED, AdvisorSeverity.ACTION}:
        return "今日有需要跟進的 research / risk item；明日前先不要自動新增倉位。"
    return "今日沒有新的 actionable trade；明日保持 watch。"


def _group_recommendations(items: list[AdvisorRecommendation]) -> dict[str, list[AdvisorRecommendation]]:
    return {
        "action": [item for item in items if item.recommendation_type == AdvisorSeverity.ACTION],
        "watch": [item for item in items if item.recommendation_type == AdvisorSeverity.WATCH],
        "blocked": [item for item in items if item.recommendation_type == AdvisorSeverity.BLOCKED],
        "info": [item for item in items if item.recommendation_type == AdvisorSeverity.INFO],
    }


def _advisor_item_rank(item: AdvisorBriefItem) -> int:
    return {
        AdvisorSeverity.BLOCKED: 4,
        AdvisorSeverity.ACTION: 3,
        AdvisorSeverity.WATCH: 2,
        AdvisorSeverity.INFO: 1,
    }[item.severity]


def _clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value).split())
        if not item or item in seen:
            continue
        cleaned.append(item)
        seen.add(item)
    return cleaned


def _is_quiet_hours(now: datetime) -> bool:
    local = _aware_utc(now).astimezone(SGT_TZ)
    return 0 <= local.hour < 7


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
