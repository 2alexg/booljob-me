"""Exhaustive tests for the match state machine.

EXPECTED_TRANSITIONS is the spec, written out by hand from design doc §2.2,
§2.3 and §2.5. Every (flow, from, to, actor) combination not listed must be
rejected.
"""

import re
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path

import pytest

from bool_api.policy import (
    EXPIRY_WINDOW,
    FLOW_STATUSES,
    PAID_TRANSITIONS,
    Actor,
    IllegalTransitionError,
    MatchFlow,
    MatchStatus,
    check_transition,
    is_terminal,
    next_expires_at,
)

E, D = MatchFlow.EXTERNAL, MatchFlow.DOUBLE_OPT_IN
S = MatchStatus
C, EMP, SYS = Actor.CANDIDATE, Actor.EMPLOYER, Actor.SYSTEM

EXPECTED_TRANSITIONS = {
    # External flow (§2.2)
    (E, S.SUGGESTED, S.CANDIDATE_VIEWED, C),
    (E, S.SUGGESTED, S.DISMISSED_BY_CANDIDATE, C),
    (E, S.CANDIDATE_VIEWED, S.APPLIED_EXTERNAL, C),
    (E, S.CANDIDATE_VIEWED, S.DISMISSED_BY_CANDIDATE, C),
    (E, S.SUGGESTED, S.CLOSED, SYS),
    (E, S.CANDIDATE_VIEWED, S.CLOSED, SYS),
    # Double opt-in (§2.3)
    (D, S.SUGGESTED, S.EMPLOYER_INTERESTED, EMP),
    (D, S.SUGGESTED, S.CANDIDATE_INTERESTED, C),
    (D, S.EMPLOYER_INTERESTED, S.CANDIDATE_REVEALED_JOB, C),
    (D, S.EMPLOYER_INTERESTED, S.DECLINED_BY_CANDIDATE, C),
    (D, S.CANDIDATE_REVEALED_JOB, S.MUTUAL_INTEREST, C),
    (D, S.CANDIDATE_REVEALED_JOB, S.DECLINED_BY_CANDIDATE, C),
    (D, S.CANDIDATE_INTERESTED, S.MUTUAL_INTEREST, EMP),
    (D, S.CANDIDATE_INTERESTED, S.DECLINED_BY_EMPLOYER, EMP),
    (D, S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER, EMP),
    # Expiry (§2.5)
    (D, S.EMPLOYER_INTERESTED, S.EXPIRED, SYS),
    (D, S.CANDIDATE_REVEALED_JOB, S.EXPIRED, SYS),
    (D, S.CANDIDATE_INTERESTED, S.EXPIRED, SYS),
    (D, S.MUTUAL_INTEREST, S.EXPIRED, SYS),
    # Withdrawal from any pre-unlock state (§2.5)
    (D, S.SUGGESTED, S.WITHDRAWN_BY_CANDIDATE, C),
    (D, S.EMPLOYER_INTERESTED, S.WITHDRAWN_BY_CANDIDATE, C),
    (D, S.CANDIDATE_INTERESTED, S.WITHDRAWN_BY_CANDIDATE, C),
    (D, S.CANDIDATE_REVEALED_JOB, S.WITHDRAWN_BY_CANDIDATE, C),
    (D, S.MUTUAL_INTEREST, S.WITHDRAWN_BY_CANDIDATE, C),
    # Job closed (§2.5)
    (D, S.SUGGESTED, S.CLOSED, SYS),
    (D, S.EMPLOYER_INTERESTED, S.CLOSED, SYS),
    (D, S.CANDIDATE_INTERESTED, S.CLOSED, SYS),
    (D, S.CANDIDATE_REVEALED_JOB, S.CLOSED, SYS),
    (D, S.MUTUAL_INTEREST, S.CLOSED, SYS),
}

EXPECTED_TERMINAL = {
    E: {S.APPLIED_EXTERNAL, S.DISMISSED_BY_CANDIDATE, S.CLOSED},
    D: {
        S.UNLOCKED_BY_EMPLOYER,
        S.DECLINED_BY_CANDIDATE,
        S.DECLINED_BY_EMPLOYER,
        S.WITHDRAWN_BY_CANDIDATE,
        S.EXPIRED,
        S.CLOSED,
    },
}


def test_every_combination_is_allowed_exactly_when_specified() -> None:
    mismatches = []
    for flow, current, target, actor in product(MatchFlow, MatchStatus, MatchStatus, Actor):
        expected = (flow, current, target, actor) in EXPECTED_TRANSITIONS
        try:
            check_transition(flow, current, target, actor)
            allowed = True
        except IllegalTransitionError:
            allowed = False
        if allowed != expected:
            mismatches.append((flow, current, target, actor, f"allowed={allowed}"))
    assert mismatches == []


@pytest.mark.parametrize(("flow", "current", "target", "actor"), sorted(EXPECTED_TRANSITIONS))
def test_specified_transition_is_allowed(flow, current, target, actor) -> None:
    check_transition(flow, current, target, actor)


def test_wrong_actor_message_names_the_required_actor() -> None:
    with pytest.raises(IllegalTransitionError, match="only employer"):
        check_transition(D, S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER, C)


def test_cross_flow_status_rejected() -> None:
    with pytest.raises(IllegalTransitionError, match="not part of the external flow"):
        check_transition(E, S.SUGGESTED, S.EMPLOYER_INTERESTED, EMP)


@pytest.mark.parametrize("flow", list(MatchFlow))
def test_terminal_states(flow: MatchFlow) -> None:
    terminal = {s for s in FLOW_STATUSES[flow] if is_terminal(flow, s)}
    assert terminal == EXPECTED_TERMINAL[flow]


def test_only_unlock_is_paid() -> None:
    assert PAID_TRANSITIONS == {(S.MUTUAL_INTEREST, S.UNLOCKED_BY_EMPLOYER)}


def test_statuses_match_database_constraint() -> None:
    """FLOW_STATUSES must mirror matches_status_valid_for_flow in the migration."""
    migrations = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
    sql = next(migrations.glob("*_matches.sql")).read_text()
    for flow in MatchFlow:
        block = re.search(rf"flow = '{flow}' and status in \((.*?)\)", sql, re.S)
        assert block, f"no constraint block for {flow}"
        db_statuses = set(re.findall(r"'([a-z_]+)'", block.group(1)))
        assert db_statuses == {s.value for s in FLOW_STATUSES[flow]}


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=3)


@pytest.mark.parametrize(
    "target", [S.EMPLOYER_INTERESTED, S.CANDIDATE_INTERESTED, S.MUTUAL_INTEREST]
)
def test_waiting_states_start_a_fresh_clock(target: MatchStatus) -> None:
    assert next_expires_at(target, EARLIER + EXPIRY_WINDOW, NOW) == NOW + timedelta(days=14)


def test_reveal_keeps_the_existing_clock() -> None:
    deadline = EARLIER + EXPIRY_WINDOW
    assert next_expires_at(S.CANDIDATE_REVEALED_JOB, deadline, NOW) == deadline


@pytest.mark.parametrize(
    "target",
    [
        s
        for s in MatchStatus
        if s
        not in {
            S.EMPLOYER_INTERESTED,
            S.CANDIDATE_INTERESTED,
            S.MUTUAL_INTEREST,
            S.CANDIDATE_REVEALED_JOB,
        }
    ],
)
def test_other_states_clear_the_clock(target: MatchStatus) -> None:
    assert next_expires_at(target, NOW, NOW) is None


def test_expiry_window_is_configurable() -> None:
    assert next_expires_at(S.MUTUAL_INTEREST, None, NOW, timedelta(days=7)) == NOW + timedelta(
        days=7
    )
