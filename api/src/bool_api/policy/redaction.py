"""Field-level redaction of candidate data by MatchView (design doc §2.4).

Allowlist only: a field is returned only if the view explicitly permits it,
so new candidate fields stay hidden until someone decides otherwise.
"""

from collections.abc import Mapping
from typing import Any

from bool_api.policy.access import MatchView

# §2.4 anonymized card. Region (never city), experience band (never exact
# years), normalized skills, work models, and a summary that passed the
# de-identification check.
ANONYMIZED_FIELDS = frozenset(
    {"region_code", "experience_band", "skills", "work_models", "summary_deidentified"}
)
# Revealed only after a paid unlock (or to the candidate themselves).
IDENTITY_FIELDS = frozenset({"full_name", "email", "phone", "whatsapp_url", "cv_signed_url"})

_ALLOWED: dict[MatchView, frozenset[str]] = {
    MatchView.NONE: frozenset(),
    MatchView.STATUS_ONLY: frozenset(),
    MatchView.ANONYMIZED: ANONYMIZED_FIELDS,
    MatchView.FULL: ANONYMIZED_FIELDS | IDENTITY_FIELDS,
}


def redact_candidate(record: Mapping[str, Any], view: MatchView) -> dict[str, Any]:
    allowed = _ALLOWED[view]
    return {k: v for k, v in record.items() if k in allowed}


def experience_band(years: int | None) -> str | None:
    if years is None:
        return None
    if years < 0:
        raise ValueError("experience years cannot be negative")
    if years <= 2:
        return "0-2"
    if years <= 5:
        return "3-5"
    if years <= 10:
        return "6-10"
    return "10+"
