from __future__ import annotations

from .models import AdvisorProfile, AdvisorRiskProfile, InvestorPolicyStatement, utc_now
from .store import Store


class InvestorPolicyService:
    def __init__(self, store: Store):
        self.store = store

    def get_current(self) -> InvestorPolicyStatement | None:
        return self.store.get_investor_policy_statement()

    def upsert_from_advisor_profile(
        self,
        profile: AdvisorProfile,
        *,
        confirmed_by: str | None = None,
    ) -> InvestorPolicyStatement:
        current = self.store.get_investor_policy_statement()
        next_version = (current.version + 1) if current else 1
        policy = InvestorPolicyStatement(
            version=next_version,
            source_profile_version=profile.version,
            risk_profile=profile.risk_profile,
            investment_horizon=_horizon_from_notes(profile.notes),
            max_single_stock_weight=profile.max_single_stock_weight,
            max_tech_exposure=profile.max_tech_exposure,
            max_sector_exposure=profile.max_sector_exposure,
            min_cash_weight=profile.min_cash_weight,
            max_drawdown_tolerance=_default_drawdown(profile.risk_profile),
            core_satellite_target=_default_core_satellite(profile.risk_profile),
            target_allocations=current.target_allocations if current else {},
            prohibited_assets=_default_prohibited_assets(profile),
            review_cadence="quarterly",
            notes=_policy_notes(profile),
            confirmed_by=confirmed_by or profile.confirmed_by,
            updated_at=utc_now(),
        )
        return self.store.upsert_investor_policy_statement(policy)


def _horizon_from_notes(notes: list[str]) -> str:
    text = " ".join(notes).lower()
    if "中長期" in text or "medium-to-long" in text or "medium to long" in text:
        return "medium_to_long_term"
    return "unspecified"


def _default_drawdown(risk_profile: AdvisorRiskProfile) -> float:
    mapping = {
        AdvisorRiskProfile.CONSERVATIVE: 0.1,
        AdvisorRiskProfile.MODERATE_CONSERVATIVE: 0.15,
        AdvisorRiskProfile.MODERATE: 0.2,
        AdvisorRiskProfile.GROWTH: 0.3,
        AdvisorRiskProfile.AGGRESSIVE: 0.4,
    }
    return mapping.get(risk_profile, 0.2)


def _default_core_satellite(risk_profile: AdvisorRiskProfile) -> dict[str, float]:
    if risk_profile in {AdvisorRiskProfile.GROWTH, AdvisorRiskProfile.AGGRESSIVE}:
        return {"core": 0.6, "satellite": 0.4}
    if risk_profile == AdvisorRiskProfile.CONSERVATIVE:
        return {"core": 0.85, "satellite": 0.15}
    return {"core": 0.75, "satellite": 0.25}


def _default_prohibited_assets(profile: AdvisorProfile) -> list[str]:
    result: list[str] = []
    if profile.allow_options is False:
        result.append("options_without_explicit_user_request")
    if profile.allow_ipo_or_private is False:
        result.append("private_company_or_ipo_without_prospectus_review")
    return result


def _policy_notes(profile: AdvisorProfile) -> list[str]:
    notes = list(profile.notes)
    if profile.avoid_chasing_after_big_move:
        notes.append("Avoid chasing after large single-day moves; require pullback or source-verified catalyst review.")
    if profile.prefer_core_etf:
        notes.append("Prefer core ETF allocation before adding high-beta single-name exposure.")
    return list(dict.fromkeys(note for note in notes if note))
