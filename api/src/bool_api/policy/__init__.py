"""Central authorization policy (design doc §2, §3.1).

Every access-control decision about matches goes through this package:
which transitions are legal and who may make them, what each viewer may see
of the candidate and of the company, and unlock gating. Route handlers must
not make their own checks.

The package is pure: callers load facts from the database (match state,
relationships, blocklist result) into a MatchContext and a Viewer.
"""

from bool_api.policy.access import (
    CANDIDATE_MIN_RERANK,
    RECRUITER_MIN_RERANK,
    CompanyDisclosure,
    ForbiddenError,
    MatchContext,
    MatchView,
    Relationship,
    Viewer,
    authorize_transition,
    can_unlock,
    candidate_data_view,
    company_disclosure,
    is_company_blocked,
    relationship,
)
from bool_api.policy.redaction import experience_band, redact_candidate
from bool_api.policy.states import (
    EXPIRY_WINDOW,
    FLOW_STATUSES,
    PAID_TRANSITIONS,
    TRANSITIONS,
    Actor,
    IllegalTransitionError,
    MatchFlow,
    MatchStatus,
    PolicyError,
    check_transition,
    is_terminal,
    next_expires_at,
)

__all__ = [
    "CANDIDATE_MIN_RERANK",
    "EXPIRY_WINDOW",
    "FLOW_STATUSES",
    "PAID_TRANSITIONS",
    "RECRUITER_MIN_RERANK",
    "TRANSITIONS",
    "Actor",
    "CompanyDisclosure",
    "ForbiddenError",
    "IllegalTransitionError",
    "MatchContext",
    "MatchFlow",
    "MatchStatus",
    "MatchView",
    "PolicyError",
    "Relationship",
    "Viewer",
    "authorize_transition",
    "can_unlock",
    "candidate_data_view",
    "check_transition",
    "company_disclosure",
    "experience_band",
    "is_company_blocked",
    "is_terminal",
    "next_expires_at",
    "redact_candidate",
    "relationship",
]
