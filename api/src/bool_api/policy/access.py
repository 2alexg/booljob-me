"""Who may see and do what with a match (design doc §2.1, §2.3, §2.4).

Two independent questions per viewer:
  - candidate_data_view: how much of the candidate the viewer may see
  - company_disclosure: how much of the hiring company the viewer may see
"""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from bool_api.policy.states import (
    Actor,
    MatchFlow,
    MatchStatus,
    PolicyError,
    check_transition,
)

S = MatchStatus

# Score thresholds (design doc §5.B).
CANDIDATE_MIN_RERANK = 75  # shown in the candidate feed
RECRUITER_MIN_RERANK = 80  # shown to recruiters as an anonymized card


class ForbiddenError(PolicyError):
    """The viewer has no right to act on this match."""


class Relationship(StrEnum):
    CANDIDATE = "candidate"  # the match's candidate
    EMPLOYER = "employer"  # a member of the job's company
    ADMIN = "admin"
    NONE = "none"


class MatchView(StrEnum):
    NONE = "none"  # the match does not exist for this viewer
    STATUS_ONLY = "status_only"  # match id and status, no candidate fields
    ANONYMIZED = "anonymized"  # §2.4 card
    FULL = "full"  # identity and contact details


class CompanyDisclosure(StrEnum):
    HIDDEN = "hidden"
    GENERIC = "generic"  # confidential role: generic company profile
    NAMED = "named"


@dataclass(frozen=True)
class Viewer:
    user_id: UUID
    roles: frozenset[str]
    # Companies the user belongs to (employers table), any employer role.
    employer_company_ids: frozenset[UUID] = field(default_factory=frozenset)


@dataclass(frozen=True)
class MatchContext:
    flow: MatchFlow
    status: MatchStatus
    candidate_user_id: UUID
    job_company_id: UUID
    job_is_confidential: bool
    ai_rerank_score: int | None
    # True if the job's company (or a parent/subsidiary, or a conservative
    # fuzzy match on an unresolved name) is on the candidate's blocklist.
    company_blocked_by_candidate: bool


def is_company_blocked(
    blocked_company_ids: frozenset[UUID], company_lineage_ids: frozenset[UUID]
) -> bool:
    """`company_lineage_ids` is the company plus all its ancestors and descendants."""
    return not blocked_company_ids.isdisjoint(company_lineage_ids)


def relationship(viewer: Viewer, ctx: MatchContext) -> Relationship:
    if "candidate" in viewer.roles and viewer.user_id == ctx.candidate_user_id:
        return Relationship.CANDIDATE
    if "employer" in viewer.roles and ctx.job_company_id in viewer.employer_company_ids:
        return Relationship.EMPLOYER
    if "admin" in viewer.roles:
        return Relationship.ADMIN
    return Relationship.NONE


def _score_at_least(ctx: MatchContext, threshold: int) -> bool:
    return ctx.ai_rerank_score is not None and ctx.ai_rerank_score >= threshold


# What an employer sees of the candidate in the double opt-in flow.
_EMPLOYER_VIEW: dict[MatchStatus, MatchView] = {
    S.SUGGESTED: MatchView.ANONYMIZED,  # only above RECRUITER_MIN_RERANK
    S.EMPLOYER_INTERESTED: MatchView.ANONYMIZED,
    S.CANDIDATE_INTERESTED: MatchView.ANONYMIZED,
    S.CANDIDATE_REVEALED_JOB: MatchView.ANONYMIZED,
    S.MUTUAL_INTEREST: MatchView.ANONYMIZED,
    S.UNLOCKED_BY_EMPLOYER: MatchView.FULL,  # the only state that reveals identity
    S.DECLINED_BY_CANDIDATE: MatchView.STATUS_ONLY,
    S.DECLINED_BY_EMPLOYER: MatchView.STATUS_ONLY,
    S.EXPIRED: MatchView.STATUS_ONLY,
    # A withdrawal hides the match entirely; a closed job's matches are not shown.
    S.WITHDRAWN_BY_CANDIDATE: MatchView.NONE,
    S.CLOSED: MatchView.NONE,
}

# Double opt-in states in which the candidate has learned which company it is.
_COMPANY_REVEALED = frozenset({S.CANDIDATE_REVEALED_JOB, S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER})


def candidate_data_view(viewer: Viewer, ctx: MatchContext) -> MatchView:
    rel = relationship(viewer, ctx)
    if rel is Relationship.CANDIDATE:
        if ctx.status is S.SUGGESTED and not _score_at_least(ctx, CANDIDATE_MIN_RERANK):
            return MatchView.NONE
        return MatchView.FULL  # their own data
    if rel is Relationship.EMPLOYER:
        if ctx.flow is MatchFlow.EXTERNAL or ctx.company_blocked_by_candidate:
            return MatchView.NONE
        if ctx.status is S.SUGGESTED and not _score_at_least(ctx, RECRUITER_MIN_RERANK):
            return MatchView.NONE
        return _EMPLOYER_VIEW[ctx.status]
    if rel is Relationship.ADMIN:
        # Support and QA see cards only; revealing identity needs a separate,
        # audited admin path.
        return MatchView.ANONYMIZED
    return MatchView.NONE


def company_disclosure(viewer: Viewer, ctx: MatchContext) -> CompanyDisclosure:
    rel = relationship(viewer, ctx)
    if rel is Relationship.ADMIN:
        return CompanyDisclosure.NAMED
    if candidate_data_view(viewer, ctx) is MatchView.NONE:
        return CompanyDisclosure.HIDDEN
    if rel is Relationship.EMPLOYER:
        return CompanyDisclosure.NAMED  # their own company
    # Candidate.
    if ctx.flow is MatchFlow.EXTERNAL:
        return CompanyDisclosure.NAMED  # public ATS posting
    if ctx.status in _COMPANY_REVEALED:
        return CompanyDisclosure.GENERIC if ctx.job_is_confidential else CompanyDisclosure.NAMED
    return CompanyDisclosure.HIDDEN


def authorize_transition(viewer: Viewer | None, ctx: MatchContext, target: MatchStatus) -> Actor:
    """Check that `viewer` (None = the system worker) may move the match to `target`.

    Returns the acting role, to record in match_status_events.actor_kind.
    Raises ForbiddenError or IllegalTransitionError.
    """
    if viewer is None:
        actor = Actor.SYSTEM
    else:
        rel = relationship(viewer, ctx)
        if rel is Relationship.CANDIDATE:
            actor = Actor.CANDIDATE
        elif rel is Relationship.EMPLOYER:
            actor = Actor.EMPLOYER
        else:
            raise ForbiddenError("viewer is neither the candidate nor the hiring employer")
        # Nobody may act on a match they cannot see (blocklist, score threshold).
        if candidate_data_view(viewer, ctx) is MatchView.NONE:
            raise ForbiddenError("match is not visible to this viewer")
    check_transition(ctx.flow, ctx.status, target, actor)
    return actor


def can_unlock(viewer: Viewer, ctx: MatchContext) -> bool:
    """Whether `viewer` may pay to unlock the candidate's contact details."""
    try:
        authorize_transition(viewer, ctx, S.UNLOCKED_BY_EMPLOYER)
    except PolicyError:
        return False
    return True
