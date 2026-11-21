"""Every state x role combination for visibility, plus transition authorization.

EXPECTED_VIEWS is the spec, written out by hand (design doc §2.3, §2.4, §2.7).
"""

from uuid import UUID

import pytest

from bool_api.policy import (
    FLOW_STATUSES,
    Actor,
    CompanyDisclosure,
    ForbiddenError,
    IllegalTransitionError,
    MatchContext,
    MatchFlow,
    MatchStatus,
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

S = MatchStatus
E, D = MatchFlow.EXTERNAL, MatchFlow.DOUBLE_OPT_IN
V, CD = MatchView, CompanyDisclosure

CANDIDATE_ID = UUID("00000000-0000-0000-0000-00000000000a")
EMPLOYER_ID = UUID("00000000-0000-0000-0000-00000000000b")
OTHER_EMPLOYER_ID = UUID("00000000-0000-0000-0000-00000000000c")
ADMIN_ID = UUID("00000000-0000-0000-0000-00000000000d")
STRANGER_ID = UUID("00000000-0000-0000-0000-00000000000e")
COMPANY = UUID("00000000-0000-0000-0000-0000000000c1")
OTHER_COMPANY = UUID("00000000-0000-0000-0000-0000000000c2")

VIEWERS = {
    "candidate": Viewer(CANDIDATE_ID, frozenset({"candidate"})),
    "employer": Viewer(EMPLOYER_ID, frozenset({"employer"}), frozenset({COMPANY})),
    "other_employer": Viewer(
        OTHER_EMPLOYER_ID, frozenset({"employer"}), frozenset({OTHER_COMPANY})
    ),
    "admin": Viewer(ADMIN_ID, frozenset({"admin"})),
    "stranger": Viewer(STRANGER_ID, frozenset({"candidate"})),
}


def ctx(flow, status, *, score=90, confidential=False, blocked=False) -> MatchContext:
    return MatchContext(
        flow=flow,
        status=status,
        candidate_user_id=CANDIDATE_ID,
        job_company_id=COMPANY,
        job_is_confidential=confidential,
        ai_rerank_score=score,
        company_blocked_by_candidate=blocked,
    )


# (flow, status) -> {role: (candidate data view, company disclosure)}
# Score 90 (above both thresholds), non-confidential job, not blocked.
_UNRELATED = {
    "other_employer": (V.NONE, CD.HIDDEN),
    "stranger": (V.NONE, CD.HIDDEN),
    "admin": (V.ANONYMIZED, CD.NAMED),
}


def row(candidate, employer):
    return {"candidate": candidate, "employer": employer, **_UNRELATED}


EXPECTED_VIEWS = {
    (E, S.SUGGESTED): row((V.FULL, CD.NAMED), (V.NONE, CD.HIDDEN)),
    (E, S.CANDIDATE_VIEWED): row((V.FULL, CD.NAMED), (V.NONE, CD.HIDDEN)),
    (E, S.APPLIED_EXTERNAL): row((V.FULL, CD.NAMED), (V.NONE, CD.HIDDEN)),
    (E, S.DISMISSED_BY_CANDIDATE): row((V.FULL, CD.NAMED), (V.NONE, CD.HIDDEN)),
    (E, S.CLOSED): row((V.FULL, CD.NAMED), (V.NONE, CD.HIDDEN)),
    (D, S.SUGGESTED): row((V.FULL, CD.HIDDEN), (V.ANONYMIZED, CD.NAMED)),
    (D, S.EMPLOYER_INTERESTED): row((V.FULL, CD.HIDDEN), (V.ANONYMIZED, CD.NAMED)),
    (D, S.CANDIDATE_INTERESTED): row((V.FULL, CD.HIDDEN), (V.ANONYMIZED, CD.NAMED)),
    (D, S.CANDIDATE_REVEALED_JOB): row((V.FULL, CD.NAMED), (V.ANONYMIZED, CD.NAMED)),
    (D, S.MUTUAL_INTEREST): row((V.FULL, CD.NAMED), (V.ANONYMIZED, CD.NAMED)),
    (D, S.UNLOCKED_BY_EMPLOYER): row((V.FULL, CD.NAMED), (V.FULL, CD.NAMED)),
    (D, S.DECLINED_BY_CANDIDATE): row((V.FULL, CD.HIDDEN), (V.STATUS_ONLY, CD.NAMED)),
    (D, S.DECLINED_BY_EMPLOYER): row((V.FULL, CD.HIDDEN), (V.STATUS_ONLY, CD.NAMED)),
    (D, S.WITHDRAWN_BY_CANDIDATE): row((V.FULL, CD.HIDDEN), (V.NONE, CD.HIDDEN)),
    (D, S.EXPIRED): row((V.FULL, CD.HIDDEN), (V.STATUS_ONLY, CD.NAMED)),
    (D, S.CLOSED): row((V.FULL, CD.HIDDEN), (V.NONE, CD.HIDDEN)),
}

ALL_CASES = [
    (flow, status, role) for (flow, status), roles in EXPECTED_VIEWS.items() for role in roles
]


def test_spec_covers_every_state_and_role() -> None:
    states = {(f, s) for f in MatchFlow for s in FLOW_STATUSES[f]}
    assert set(EXPECTED_VIEWS) == states
    assert all(set(roles) == set(VIEWERS) for roles in EXPECTED_VIEWS.values())


@pytest.mark.parametrize(("flow", "status", "role"), ALL_CASES)
def test_views(flow, status, role) -> None:
    c = ctx(flow, status)
    viewer = VIEWERS[role]
    expected = EXPECTED_VIEWS[(flow, status)][role]
    assert (candidate_data_view(viewer, c), company_disclosure(viewer, c)) == expected


def test_employer_identity_only_after_unlock() -> None:
    employer = VIEWERS["employer"]
    full = [
        (f, s)
        for f in MatchFlow
        for s in FLOW_STATUSES[f]
        if candidate_data_view(employer, ctx(f, s)) is V.FULL
    ]
    assert full == [(D, S.UNLOCKED_BY_EMPLOYER)]


# --- Score thresholds -------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "candidate_sees", "employer_sees"),
    [
        (None, V.NONE, V.NONE),
        (74, V.NONE, V.NONE),
        (75, V.FULL, V.NONE),
        (79, V.FULL, V.NONE),
        (80, V.FULL, V.ANONYMIZED),
    ],
)
def test_suggested_visibility_thresholds(score, candidate_sees, employer_sees) -> None:
    c = ctx(D, S.SUGGESTED, score=score)
    assert candidate_data_view(VIEWERS["candidate"], c) is candidate_sees
    assert candidate_data_view(VIEWERS["employer"], c) is employer_sees


def test_thresholds_only_apply_to_suggested() -> None:
    c = ctx(D, S.CANDIDATE_INTERESTED, score=10)
    assert candidate_data_view(VIEWERS["employer"], c) is V.ANONYMIZED


# --- Confidential jobs ------------------------------------------------------


@pytest.mark.parametrize(
    "status", [S.CANDIDATE_REVEALED_JOB, S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER]
)
def test_confidential_job_shows_generic_profile_after_reveal(status) -> None:
    c = ctx(D, status, confidential=True)
    assert company_disclosure(VIEWERS["candidate"], c) is CD.GENERIC
    assert company_disclosure(VIEWERS["employer"], c) is CD.NAMED


def test_confidential_job_hidden_before_reveal() -> None:
    c = ctx(D, S.EMPLOYER_INTERESTED, confidential=True)
    assert company_disclosure(VIEWERS["candidate"], c) is CD.HIDDEN


# --- Blocklist --------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(FLOW_STATUSES[D]))
def test_blocked_employer_sees_nothing(status) -> None:
    c = ctx(D, status, blocked=True)
    assert candidate_data_view(VIEWERS["employer"], c) is V.NONE
    assert company_disclosure(VIEWERS["employer"], c) is CD.HIDDEN


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.SUGGESTED, S.EMPLOYER_INTERESTED),
        (S.CANDIDATE_INTERESTED, S.MUTUAL_INTEREST),
        (S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER),
    ],
)
def test_blocked_employer_cannot_act(current, target) -> None:
    with pytest.raises(ForbiddenError):
        authorize_transition(VIEWERS["employer"], ctx(D, current, blocked=True), target)


def test_blocklist_lineage() -> None:
    parent, child, unrelated = (UUID(int=i) for i in (1, 2, 3))
    assert is_company_blocked(frozenset({parent}), frozenset({child, parent}))
    assert not is_company_blocked(frozenset({unrelated}), frozenset({child, parent}))
    assert not is_company_blocked(frozenset(), frozenset({child}))


# --- Relationships ----------------------------------------------------------


def test_relationship_requires_the_role() -> None:
    # Right user id, but without the candidate role: not treated as the candidate.
    c = ctx(D, S.SUGGESTED)
    assert relationship(Viewer(CANDIDATE_ID, frozenset({"employer"})), c) is Relationship.NONE
    # Member of the company, but without the employer role.
    no_role = Viewer(EMPLOYER_ID, frozenset(), frozenset({COMPANY}))
    assert relationship(no_role, c) is Relationship.NONE


# --- Transition authorization ----------------------------------------------


def test_actor_is_derived_from_relationship() -> None:
    assert (
        authorize_transition(VIEWERS["candidate"], ctx(D, S.SUGGESTED), S.CANDIDATE_INTERESTED)
        is Actor.CANDIDATE
    )
    assert (
        authorize_transition(VIEWERS["employer"], ctx(D, S.SUGGESTED), S.EMPLOYER_INTERESTED)
        is Actor.EMPLOYER
    )
    assert authorize_transition(None, ctx(D, S.MUTUAL_INTEREST), S.EXPIRED) is Actor.SYSTEM


@pytest.mark.parametrize("role", ["other_employer", "stranger", "admin"])
def test_unrelated_viewers_cannot_act(role) -> None:
    with pytest.raises(ForbiddenError):
        authorize_transition(VIEWERS[role], ctx(D, S.SUGGESTED), S.EMPLOYER_INTERESTED)


def test_employer_cannot_express_interest_below_recruiter_threshold() -> None:
    with pytest.raises(ForbiddenError):
        authorize_transition(
            VIEWERS["employer"], ctx(D, S.SUGGESTED, score=79), S.EMPLOYER_INTERESTED
        )


def test_candidate_cannot_act_on_a_hidden_suggestion() -> None:
    with pytest.raises(ForbiddenError):
        authorize_transition(
            VIEWERS["candidate"], ctx(D, S.SUGGESTED, score=60), S.CANDIDATE_INTERESTED
        )


def test_users_cannot_perform_system_transitions() -> None:
    with pytest.raises(IllegalTransitionError):
        authorize_transition(VIEWERS["employer"], ctx(D, S.MUTUAL_INTEREST), S.EXPIRED)
    with pytest.raises(IllegalTransitionError):
        authorize_transition(VIEWERS["candidate"], ctx(D, S.SUGGESTED), S.CLOSED)


def test_candidate_cannot_accept_without_revealing() -> None:
    with pytest.raises(IllegalTransitionError):
        authorize_transition(VIEWERS["candidate"], ctx(D, S.EMPLOYER_INTERESTED), S.MUTUAL_INTEREST)


# --- Unlock gating ----------------------------------------------------------


@pytest.mark.parametrize("status", sorted(FLOW_STATUSES[D]))
def test_unlock_only_from_mutual_interest(status) -> None:
    assert can_unlock(VIEWERS["employer"], ctx(D, status)) == (status is S.MUTUAL_INTEREST)


@pytest.mark.parametrize("role", ["candidate", "other_employer", "admin", "stranger"])
def test_only_the_hiring_employer_can_unlock(role) -> None:
    assert not can_unlock(VIEWERS[role], ctx(D, S.MUTUAL_INTEREST))


def test_blocked_employer_cannot_unlock() -> None:
    assert not can_unlock(VIEWERS["employer"], ctx(D, S.MUTUAL_INTEREST, blocked=True))


def test_external_matches_cannot_be_unlocked() -> None:
    for status in FLOW_STATUSES[E]:
        assert not can_unlock(VIEWERS["employer"], ctx(E, status))
