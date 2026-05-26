from __future__ import annotations

from datetime import timedelta, timezone

from .models import (
    AdvisorBrief,
    AdvisorBriefItem,
    AdvisorBriefRequest,
    AdvisorSeverity,
    BehaviorReport,
    BehaviorReportRunRequest,
    BehaviorSeverity,
    CatalystExpectedImpact,
    CatalystStatus,
    CatalystThesisDelta,
    ProposalStatus,
    RunCardActor,
    ShadowEventType,
    ThesisStatus,
    utc_now,
)
from .store import Store
from .trade_journal import TradeJournalService


class AdvisorService:
    def __init__(self, store: Store, *, paper_only: bool = True):
        self.store = store
        self.paper_only = paper_only

    def build_brief(self, request: AdvisorBriefRequest | None = None) -> AdvisorBrief:
        request = request or AdvisorBriefRequest()
        automated_actions: list[str] = []
        behavior_report = self._latest_behavior_report()
        fills = self.store.list_trade_fills(limit=100000)
        if request.run_light_analysis and fills:
            behavior_report = TradeJournalService(self.store).run_behavior_report(
                BehaviorReportRunRequest(),
                actor=RunCardActor.API,
            )
            automated_actions.append(f"建立最新交易行為報告 {behavior_report.id}")

        pending = self.store.list_proposals(status=ProposalStatus.PENDING, limit=100)
        proposals = self.store.list_proposals(limit=100)
        catalysts = self.store.list_catalysts(limit=100)
        earnings_reviews = self.store.list_earnings_reviews(limit=20)
        shadow_reports = self.store.list_shadow_reports(limit=5)
        shadow_events = self.store.list_shadow_events(limit=50)
        research_goals = self.store.list_research_goals(limit=20)
        positions = self.store.get_portfolio().positions
        active_theses = self.store.list_theses(status=ThesisStatus.ACTIVE, limit=100)
        active_thesis_symbols = {thesis.symbol for thesis in active_theses if thesis.human_confirmed}

        advice: list[AdvisorBriefItem] = []
        advice.extend(_pending_proposal_advice(pending))
        advice.extend(_catalyst_advice(catalysts))
        advice.extend(_earnings_advice(earnings_reviews))
        advice.extend(_behavior_advice(behavior_report))
        advice.extend(_shadow_advice(shadow_reports, shadow_events))
        advice.extend(_thesis_coverage_advice(positions, active_thesis_symbols))
        advice.extend(_research_goal_advice(research_goals))
        if not advice:
            advice.append(
                AdvisorBriefItem(
                    severity=AdvisorSeverity.INFO,
                    category="system",
                    title="目前沒有高優先級行動",
                    rationale="沒有 pending proposal、近期重大 catalyst warning、嚴重行為偏誤或 shadow report 偏離。",
                    next_action="維持觀察；需要新資料時按一次 AI Advisor Brief 重新整理。",
                )
            )

        advice = sorted(advice, key=_severity_rank, reverse=True)[: request.max_items]
        risk_level = advice[0].severity if advice else AdvisorSeverity.INFO
        summary = [
            f"{len(pending)} 個待審批提案",
            f"{len(active_theses)} 個 active thesis",
            f"{len(catalysts)} 個 catalyst 記錄",
            f"{len(shadow_reports)} 份 shadow report",
        ]
        if behavior_report:
            summary.append(f"最新 behavior report：{behavior_report.total_roundtrips} 個 roundtrip")
        headline = _headline(risk_level, len(advice), pending_count=len(pending))
        return AdvisorBrief(
            headline=headline,
            risk_level=risk_level,
            paper_only=self.paper_only,
            summary=summary,
            advice=advice,
            automated_actions=automated_actions,
            data_status={
                "pending_proposals": len(pending),
                "total_proposals": len(proposals),
                "trade_fills": len(fills),
                "behavior_report_id": behavior_report.id if behavior_report else None,
                "shadow_report_id": shadow_reports[0].id if shadow_reports else None,
                "active_thesis_symbols": sorted(active_thesis_symbols),
                "paper_only": self.paper_only,
            },
        )

    def _latest_behavior_report(self) -> BehaviorReport | None:
        reports = self.store.list_behavior_reports(limit=1)
        return reports[0] if reports else None


def _pending_proposal_advice(pending) -> list[AdvisorBriefItem]:
    if not pending:
        return []
    risky = [proposal for proposal in pending if proposal.risk_check.warnings]
    return [
        AdvisorBriefItem(
            severity=AdvisorSeverity.ACTION,
            category="proposal",
            title=f"有 {len(pending)} 個待審批提案",
            rationale="系統已完成 policy check，但任何交易仍必須由你批准；agent 不會自動 approve。",
            next_action="先查看最高 confidence 且沒有 warning 的 proposal；若 catalyst 或 thesis 不完整，先不要批准。",
            related_ids=[proposal.id for proposal in pending[:5]],
        ),
        *(
            [
                AdvisorBriefItem(
                    severity=AdvisorSeverity.WATCH,
                    category="proposal",
                    title=f"{len(risky)} 個待審批提案有 warning",
                    rationale="有 warning 的 proposal 需要人工判斷，尤其是 catalyst window、confidence haircut 或資料不完整。",
                    next_action="先讀 warning，再決定 reject 或等待更多 evidence。",
                    related_ids=[proposal.id for proposal in risky[:5]],
                )
            ]
            if risky
            else []
        ),
    ]


def _catalyst_advice(catalysts) -> list[AdvisorBriefItem]:
    now = utc_now()
    items: list[AdvisorBriefItem] = []
    upcoming_high = [
        catalyst
        for catalyst in catalysts
        if catalyst.status == CatalystStatus.UPCOMING
        and catalyst.expected_impact == CatalystExpectedImpact.HIGH
        and timedelta(0) <= _aware(catalyst.event_date) - now <= timedelta(hours=48)
    ]
    if upcoming_high:
        items.append(
            AdvisorBriefItem(
                severity=AdvisorSeverity.BLOCKED,
                category="catalyst",
                title="48 小時內有高影響催化事件",
                rationale="新 proposal 容易受到 earnings / macro / regulatory event 噪音影響；系統 policy 也會阻止或降級。",
                next_action="等事件完成並建立 post-event review，再考慮新提案。",
                related_ids=[catalyst.id for catalyst in upcoming_high[:5]],
            )
        )
    completed_without_review = [
        catalyst
        for catalyst in catalysts
        if catalyst.status == CatalystStatus.COMPLETED and not catalyst.linked_research_goal_id
    ]
    if completed_without_review:
        items.append(
            AdvisorBriefItem(
                severity=AdvisorSeverity.ACTION,
                category="catalyst",
                title="有已完成事件尚未 review",
                rationale="事件後沒有 review 時，proposal 可能缺少 thesis delta 和 outcome evidence。",
                next_action="先跑 earnings/catalyst review，把 outcome 寫回 thesis。",
                related_ids=[catalyst.id for catalyst in completed_without_review[:5]],
            )
        )
    return items


def _earnings_advice(reviews) -> list[AdvisorBriefItem]:
    severe = [
        review
        for review in reviews
        if review.thesis_delta in {CatalystThesisDelta.WEAKENS, CatalystThesisDelta.INVALIDATES}
    ]
    if not severe:
        return []
    return [
        AdvisorBriefItem(
            severity=AdvisorSeverity.ACTION,
            category="earnings",
            title="最近財報檢討削弱 thesis",
            rationale="Earnings review 的 deterministic scoring 顯示至少一個標的的 thesis 被削弱或推翻。",
            next_action="不要直接加倉；先更新 thesis risk / invalidation condition，再看是否需要 reject 相關 proposal。",
            related_ids=[review.id for review in severe[:5]],
        )
    ]


def _behavior_advice(report: BehaviorReport | None) -> list[AdvisorBriefItem]:
    if not report:
        return [
            AdvisorBriefItem(
                severity=AdvisorSeverity.WATCH,
                category="behavior",
                title="尚未有交易行為報告",
                rationale="agent 還不能分析你的實際交易偏誤，例如追高、過度交易或處分效應。",
                next_action="匯入 Futu/generic CSV 後，按 AI Advisor Brief 讓系統自動建立 behavior report。",
            )
        ]
    items: list[AdvisorBriefItem] = []
    for key, diagnostic in report.diagnostics.items():
        if diagnostic.severity not in {BehaviorSeverity.HIGH, BehaviorSeverity.MEDIUM}:
            continue
        severity = AdvisorSeverity.ACTION if diagnostic.severity == BehaviorSeverity.HIGH else AdvisorSeverity.WATCH
        labels = {
            "disposition_effect": "處分效應",
            "overtrading": "過度交易",
            "chasing_momentum": "追高",
            "anchoring": "錨定",
        }
        items.append(
            AdvisorBriefItem(
                severity=severity,
                category="behavior",
                title=f"交易行為診斷：{labels.get(key, key)}",
                rationale=diagnostic.summary,
                next_action="把這個偏誤當成 proposal 審批前的檢查項，不要把它當成買賣訊號。",
                related_ids=[report.id],
            )
        )
    return items


def _shadow_advice(reports, events) -> list[AdvisorBriefItem]:
    if not reports:
        return []
    latest = reports[0]
    event_types = {event.event_type for event in events if event.shadow_report_id == latest.id}
    items: list[AdvisorBriefItem] = []
    if ShadowEventType.THESIS_MISMATCH in event_types:
        items.append(
            AdvisorBriefItem(
                severity=AdvisorSeverity.ACTION,
                category="shadow",
                title="Shadow report 發現 thesis mismatch",
                rationale="有歷史交易沒有對應 active human-confirmed thesis；這代表交易紀律和論點資料庫沒有對齊。",
                next_action="先為常交易標的補 active thesis，或把不符合 thesis 的交易列為 watch-only。",
                related_ids=[latest.id],
            )
        )
    if ShadowEventType.IGNORED_CATALYST in event_types:
        items.append(
            AdvisorBriefItem(
                severity=AdvisorSeverity.ACTION,
                category="shadow",
                title="Shadow report 發現忽略高影響事件",
                rationale="有交易發生在 high-impact catalyst 前的敏感窗口。",
                next_action="審批新 proposal 前先檢查 catalyst calendar；必要時等待 post-event review。",
                related_ids=[latest.id],
            )
        )
    if ShadowEventType.EARLY_EXIT in event_types:
        items.append(
            AdvisorBriefItem(
                severity=AdvisorSeverity.WATCH,
                category="shadow",
                title="Shadow report 發現太早退出贏家",
                rationale="有 winning roundtrip 比你的 extracted holding rule 更早關閉。",
                next_action="若 thesis 沒有壞掉，審批減倉/賣出前先檢查是否只是情緒性落袋。",
                related_ids=[latest.id],
            )
        )
    return items


def _thesis_coverage_advice(positions, active_symbols: set[str]) -> list[AdvisorBriefItem]:
    uncovered = [position.symbol for position in positions if position.symbol not in active_symbols]
    if not uncovered:
        return []
    return [
        AdvisorBriefItem(
            severity=AdvisorSeverity.WATCH,
            category="thesis",
            title="部分持倉沒有 active thesis",
            rationale="沒有 active thesis 的持倉較難被 catalyst / earnings / shadow report 正確解釋。",
            next_action="先補齊核心持倉 thesis；補完前只把相關交易視為 watch-only。",
            related_ids=uncovered[:8],
        )
    ]


def _research_goal_advice(goals) -> list[AdvisorBriefItem]:
    weak = [goal for goal in goals if goal.status.value in {"INSUFFICIENT", "REJECTED"}]
    if not weak:
        return []
    return [
        AdvisorBriefItem(
            severity=AdvisorSeverity.WATCH,
            category="research",
            title="部分研究目標證據不足",
            rationale="Evidence gate 沒有通過時，系統不應把草稿升級成 pending proposal。",
            next_action="先補 source-verified primary evidence，再重新評估。",
            related_ids=[goal.id for goal in weak[:5]],
        )
    ]


def _severity_rank(item: AdvisorBriefItem) -> int:
    return {
        AdvisorSeverity.BLOCKED: 4,
        AdvisorSeverity.ACTION: 3,
        AdvisorSeverity.WATCH: 2,
        AdvisorSeverity.INFO: 1,
    }[item.severity]


def _headline(level: AdvisorSeverity, item_count: int, *, pending_count: int) -> str:
    if level == AdvisorSeverity.BLOCKED:
        return f"先暫停新交易：有高優先級風險需要處理，另有 {pending_count} 個待審批提案。"
    if level == AdvisorSeverity.ACTION:
        return f"今天先處理 {item_count} 個重點：agent 已整理好風險和下一步。"
    if level == AdvisorSeverity.WATCH:
        return "目前偏向觀察：沒有硬阻擋，但有幾個審批前檢查項。"
    return "目前沒有高優先級行動；保持 paper-only 觀察即可。"


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
