from __future__ import annotations

from .config import Settings
from .market_news import resolve_watchlist_symbols
from .models import (
    IdeaCandidate,
    IdeaCandidateCreate,
    IdeaCandidateStatus,
    IdeaDirection,
    IdeaScreen,
    IdeaScreenRunRequest,
    ResearchGoalCreate,
    RunCardActor,
    RunCardTriggerSource,
    RunCardType,
    ThesisCreate,
    ThesisSide,
    ThesisStatus,
)
from .research_goals import ResearchGoalService
from .run_cards import RunCardService
from .store import Store
from .thesis_tracker import ThesisTrackerService


IDEA_SCREEN_RULE_VERSION = "idea_screen_v1"


class IdeaInboxService:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def create_candidate(self, request: IdeaCandidateCreate) -> IdeaCandidate:
        return self.store.create_idea_candidate(IdeaCandidate(**request.model_dump()))

    def run_screen(
        self,
        request: IdeaScreenRunRequest,
        *,
        actor: RunCardActor | str = RunCardActor.API,
    ) -> IdeaScreen:
        symbols = request.symbols or resolve_watchlist_symbols(self.settings, self.store)
        run_card = RunCardService(self.store).start_run(
            RunCardType.IDEA_SCREEN,
            title=f"Idea Screen: {request.screen_type}",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=IDEA_SCREEN_RULE_VERSION,
            inputs=request.model_dump(mode="json"),
            dataset={"symbols": symbols},
            assumptions={"idea_candidates_cannot_create_proposals": True},
        )
        screen = IdeaScreen(
            screen_type=request.screen_type,
            criteria=request.criteria,
            universe=request.universe,
            source_summary="Local watchlist and cached quote/news context.",
            run_card_id=run_card.id,
        )
        candidates = [
            IdeaCandidate(
                screen_id=screen.id,
                symbol=symbol,
                direction=IdeaDirection.NEUTRAL_WATCH,
                one_line_thesis=f"{symbol} requires further evidence before any proposal.",
                score=0.0,
                risks=["No evidence gate pass yet.", "Candidate cannot become a proposal directly."],
                next_research_step="Promote to research goal and attach verified evidence.",
            )
            for symbol in symbols[:10]
        ]
        stored = self.store.create_idea_screen(screen, candidates)
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"candidate_count": len(candidates)},
            warnings=[],
            outputs={"idea_screen_id": stored.id, "candidate_count": len(candidates)},
            dataset={"candidates": [candidate.model_dump(mode="json") for candidate in candidates]},
        )
        return stored

    def promote_to_research_goal(self, candidate_id: str) -> IdeaCandidate:
        candidate = self.require_candidate(candidate_id)
        goal = ResearchGoalService(self.store).create_goal(
            ResearchGoalCreate(
                symbol=candidate.symbol,
                objective=f"Research idea candidate {candidate.symbol} before any proposal.",
                claims=[candidate.one_line_thesis],
                criteria=[
                    "Attach recent directional evidence.",
                    "Attach verified primary-source or fundamentals evidence.",
                    "Keep idea candidate research-only until gate and policy checks pass.",
                ],
            )
        )
        candidate.status = IdeaCandidateStatus.RESEARCHING
        candidate.linked_research_goal_id = goal.id
        return self.store.update_idea_candidate(candidate)

    def promote_to_thesis(self, candidate_id: str) -> IdeaCandidate:
        candidate = self.require_candidate(candidate_id)
        thesis = ThesisTrackerService(self.store).create_thesis(
            ThesisCreate(
                symbol=candidate.symbol,
                side=ThesisSide.LONG if candidate.direction == IdeaDirection.LONG else ThesisSide.NEUTRAL_WATCH,
                thesis_statement=candidate.one_line_thesis,
                status=ThesisStatus.WATCH,
                human_confirmed=False,
                confirmed_by="",
            )
        )
        candidate.status = IdeaCandidateStatus.PROMOTED_TO_THESIS
        candidate.linked_thesis_id = thesis.id
        return self.store.update_idea_candidate(candidate)

    def require_candidate(self, candidate_id: str) -> IdeaCandidate:
        candidate = self.store.get_idea_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"idea candidate not found: {candidate_id}")
        return candidate

