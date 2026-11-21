"""Match state machine (design doc §2.2, §2.3, §2.5).

Status strings must match the matches_status_valid_for_flow constraint in
supabase/migrations/*_matches.sql (a test enforces this).
"""

from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType


class MatchFlow(StrEnum):
    EXTERNAL = "external"  # scraped ATS jobs
    DOUBLE_OPT_IN = "double_opt_in"  # direct-employer jobs


class MatchStatus(StrEnum):
    SUGGESTED = "suggested"
    # external flow
    CANDIDATE_VIEWED = "candidate_viewed"
    APPLIED_EXTERNAL = "applied_external"
    DISMISSED_BY_CANDIDATE = "dismissed_by_candidate"
    # double opt-in flow
    EMPLOYER_INTERESTED = "employer_interested"
    CANDIDATE_INTERESTED = "candidate_interested"
    CANDIDATE_REVEALED_JOB = "candidate_revealed_job"
    MUTUAL_INTEREST = "mutual_interest"
    UNLOCKED_BY_EMPLOYER = "unlocked_by_employer"
    DECLINED_BY_CANDIDATE = "declined_by_candidate"
    DECLINED_BY_EMPLOYER = "declined_by_employer"
    WITHDRAWN_BY_CANDIDATE = "withdrawn_by_candidate"
    EXPIRED = "expired"
    # both flows
    CLOSED = "closed"


class Actor(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"
    SYSTEM = "system"  # nightly worker: expiry, job closure


class PolicyError(Exception):
    """Base class for authorization-policy rejections."""


class IllegalTransitionError(PolicyError):
    """The requested status change is not allowed for this flow, state, or actor."""


S = MatchStatus

FLOW_STATUSES: MappingProxyType[MatchFlow, frozenset[MatchStatus]] = MappingProxyType(
    {
        MatchFlow.EXTERNAL: frozenset(
            {
                S.SUGGESTED,
                S.CANDIDATE_VIEWED,
                S.APPLIED_EXTERNAL,
                S.DISMISSED_BY_CANDIDATE,
                S.CLOSED,
            }
        ),
        MatchFlow.DOUBLE_OPT_IN: frozenset(
            {
                S.SUGGESTED,
                S.EMPLOYER_INTERESTED,
                S.CANDIDATE_INTERESTED,
                S.CANDIDATE_REVEALED_JOB,
                S.MUTUAL_INTEREST,
                S.UNLOCKED_BY_EMPLOYER,
                S.DECLINED_BY_CANDIDATE,
                S.DECLINED_BY_EMPLOYER,
                S.WITHDRAWN_BY_CANDIDATE,
                S.EXPIRED,
                S.CLOSED,
            }
        ),
    }
)

# States in the double opt-in flow that can still end in a contact unlock.
_OPEN_PRE_UNLOCK = (
    S.SUGGESTED,
    S.EMPLOYER_INTERESTED,
    S.CANDIDATE_INTERESTED,
    S.CANDIDATE_REVEALED_JOB,
    S.MUTUAL_INTEREST,
)
# States waiting on a decision; they expire after EXPIRY_WINDOW (§2.5).
_EXPIRABLE = (
    S.EMPLOYER_INTERESTED,
    S.CANDIDATE_REVEALED_JOB,
    S.CANDIDATE_INTERESTED,
    S.MUTUAL_INTEREST,
)

_EXTERNAL: dict[tuple[MatchStatus, MatchStatus], Actor] = {
    (S.SUGGESTED, S.CANDIDATE_VIEWED): Actor.CANDIDATE,
    # Dismissing straight from the feed, without opening the job, is allowed.
    (S.SUGGESTED, S.DISMISSED_BY_CANDIDATE): Actor.CANDIDATE,
    (S.CANDIDATE_VIEWED, S.APPLIED_EXTERNAL): Actor.CANDIDATE,
    (S.CANDIDATE_VIEWED, S.DISMISSED_BY_CANDIDATE): Actor.CANDIDATE,
    (S.SUGGESTED, S.CLOSED): Actor.SYSTEM,
    (S.CANDIDATE_VIEWED, S.CLOSED): Actor.SYSTEM,
}

_DOUBLE_OPT_IN: dict[tuple[MatchStatus, MatchStatus], Actor] = {
    # Stage 1a / 1b: either side starts, for free.
    (S.SUGGESTED, S.EMPLOYER_INTERESTED): Actor.EMPLOYER,
    (S.SUGGESTED, S.CANDIDATE_INTERESTED): Actor.CANDIDATE,
    # Stage 2: the candidate reveals the job, then decides. Declining without
    # revealing first is allowed; accepting requires the reveal.
    (S.EMPLOYER_INTERESTED, S.CANDIDATE_REVEALED_JOB): Actor.CANDIDATE,
    (S.EMPLOYER_INTERESTED, S.DECLINED_BY_CANDIDATE): Actor.CANDIDATE,
    (S.CANDIDATE_REVEALED_JOB, S.MUTUAL_INTEREST): Actor.CANDIDATE,
    (S.CANDIDATE_REVEALED_JOB, S.DECLINED_BY_CANDIDATE): Actor.CANDIDATE,
    # Stage 1b answer: the employer accepts or declines the candidate's interest.
    (S.CANDIDATE_INTERESTED, S.MUTUAL_INTEREST): Actor.EMPLOYER,
    (S.CANDIDATE_INTERESTED, S.DECLINED_BY_EMPLOYER): Actor.EMPLOYER,
    # Stage 3: paid contact unlock.
    (S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER): Actor.EMPLOYER,
    # §2.5 lifecycle.
    **{(s, S.EXPIRED): Actor.SYSTEM for s in _EXPIRABLE},
    **{(s, S.WITHDRAWN_BY_CANDIDATE): Actor.CANDIDATE for s in _OPEN_PRE_UNLOCK},
    **{(s, S.CLOSED): Actor.SYSTEM for s in _OPEN_PRE_UNLOCK},
}

TRANSITIONS: MappingProxyType[MatchFlow, MappingProxyType[tuple[MatchStatus, MatchStatus], Actor]]
TRANSITIONS = MappingProxyType(
    {
        MatchFlow.EXTERNAL: MappingProxyType(_EXTERNAL),
        MatchFlow.DOUBLE_OPT_IN: MappingProxyType(_DOUBLE_OPT_IN),
    }
)

# Transitions that charge the employer's wallet; billing must confirm the debit.
PAID_TRANSITIONS = frozenset({(S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER)})


def is_terminal(flow: MatchFlow, status: MatchStatus) -> bool:
    return not any(src == status for src, _ in TRANSITIONS[flow])


def check_transition(
    flow: MatchFlow, current: MatchStatus, target: MatchStatus, actor: Actor
) -> None:
    """Raise IllegalTransitionError unless `actor` may move a match from `current` to `target`."""
    allowed_statuses = FLOW_STATUSES[flow]
    if current not in allowed_statuses or target not in allowed_statuses:
        raise IllegalTransitionError(f"{current} -> {target} is not part of the {flow} flow")
    required = TRANSITIONS[flow].get((current, target))
    if required is None:
        raise IllegalTransitionError(f"{flow}: {current} -> {target} is not a valid transition")
    if required != actor:
        raise IllegalTransitionError(f"{flow}: only {required} may move {current} -> {target}")


EXPIRY_WINDOW = timedelta(days=14)

_CLOCK_STARTS = frozenset({S.EMPLOYER_INTERESTED, S.CANDIDATE_INTERESTED, S.MUTUAL_INTEREST})
# Revealing the job does not restart the clock started by employer interest.
_CLOCK_CONTINUES = frozenset({S.CANDIDATE_REVEALED_JOB})


def next_expires_at(
    target: MatchStatus,
    current_expires_at: datetime | None,
    now: datetime,
    window: timedelta = EXPIRY_WINDOW,
) -> datetime | None:
    """The matches.expires_at value to store when entering `target`."""
    if target in _CLOCK_STARTS:
        return now + window
    if target in _CLOCK_CONTINUES:
        return current_expires_at
    return None
