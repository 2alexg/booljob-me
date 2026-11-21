import json
import logging

import pytest
from pydantic import ValidationError

from bool_api.config import Settings
from bool_api.logging_setup import REDACTED, JsonFormatter, scrub


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("contact dana.cohen@example.co.il now", "contact [EMAIL] now"),
        ("call +972501234567", "call [PHONE]"),
        ("call +972 50-123-4567", "call [PHONE]"),
        ("call 050-1234567", "call [PHONE]"),
        ("token eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl here", "token [JWT] here"),
        ("job 42 matched candidate 7", "job 42 matched candidate 7"),
    ],
)
def test_scrub_free_text(raw: str, expected: str) -> None:
    assert scrub(raw) == expected


def test_scrub_sensitive_keys_recursively() -> None:
    data = {
        "user_id": "abc",
        "Email": "x@y.com",
        "nested": {"phone": "+972501234567", "note": "mail x@y.com"},
        "items": [{"token": "t"}],
    }
    assert scrub(data) == {
        "user_id": "abc",
        "Email": REDACTED,
        "nested": {"phone": REDACTED, "note": "mail [EMAIL]"},
        "items": [{"token": REDACTED}],
    }


def test_formatter_emits_cloud_logging_json() -> None:
    record = logging.LogRecord(
        "bool_api.test", logging.WARNING, __file__, 1, "user %s signed in", ("a@b.com",), None
    )
    record.match_id = "m-1"
    record.email = "a@b.com"
    entry = json.loads(JsonFormatter().format(record))
    assert entry["severity"] == "WARNING"
    assert entry["message"] == "user [EMAIL] signed in"
    assert entry["extra"] == {"match_id": "m-1", "email": REDACTED}


def test_internal_secret_must_be_long() -> None:
    with pytest.raises(ValidationError):
        Settings(internal_secret="too-short")


def test_api_requires_internal_secret() -> None:
    from bool_api.main import create_app

    with pytest.raises(RuntimeError, match="BOOL_INTERNAL_SECRET"):
        create_app(Settings(internal_secret=None))
