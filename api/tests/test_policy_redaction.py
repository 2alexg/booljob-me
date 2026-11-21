import pytest

from bool_api.policy import MatchView, experience_band, redact_candidate

RECORD = {
    # Card fields
    "region_code": "center",
    "experience_band": "6-10",
    "skills": ["python", "sql"],
    "work_models": ["hybrid"],
    "summary_deidentified": "Backend engineer with payments experience.",
    # Identity
    "full_name": "Dana Cohen",
    "email": "dana@example.com",
    "phone": "+972501234567",
    "whatsapp_url": "https://wa.me/972501234567",
    "cv_signed_url": "https://storage.example/cv?token=x",
    # Never exposed through matches
    "locality_id": 6400,
    "experience_years": 8,
    "previous_employers": ["Acme"],
    "profile_summary_for_ai": "raw summary with names",
    "cv_parsed": {"raw": "..."},
}

CARD = {"region_code", "experience_band", "skills", "work_models", "summary_deidentified"}
IDENTITY = {"full_name", "email", "phone", "whatsapp_url", "cv_signed_url"}


@pytest.mark.parametrize(
    ("view", "expected_keys"),
    [
        (MatchView.NONE, set()),
        (MatchView.STATUS_ONLY, set()),
        (MatchView.ANONYMIZED, CARD),
        (MatchView.FULL, CARD | IDENTITY),
    ],
)
def test_redaction_is_an_allowlist(view, expected_keys) -> None:
    assert set(redact_candidate(RECORD, view)) == expected_keys


def test_unknown_fields_never_leak() -> None:
    assert redact_candidate({"new_field": "x"}, MatchView.FULL) == {}


def test_missing_fields_are_skipped() -> None:
    assert redact_candidate({"skills": ["go"]}, MatchView.ANONYMIZED) == {"skills": ["go"]}


@pytest.mark.parametrize(
    ("years", "band"),
    [
        (None, None),
        (0, "0-2"),
        (2, "0-2"),
        (3, "3-5"),
        (5, "3-5"),
        (6, "6-10"),
        (10, "6-10"),
        (11, "10+"),
        (40, "10+"),
    ],
)
def test_experience_band(years, band) -> None:
    assert experience_band(years) == band


def test_negative_experience_rejected() -> None:
    with pytest.raises(ValueError):
        experience_band(-1)
