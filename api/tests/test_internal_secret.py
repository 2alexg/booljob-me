import pytest
from fastapi.testclient import TestClient

from tests.conftest import headers


@pytest.mark.parametrize("path", ["/ready", "/v1/me", "/does-not-exist"])
def test_missing_secret_is_forbidden(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_wrong_secret_is_forbidden(client: TestClient) -> None:
    response = client.get("/ready", headers=headers(secret="wrong-secret"))
    assert response.status_code == 403


def test_correct_secret_passes_through(client: TestClient) -> None:
    assert client.get("/ready", headers=headers()).status_code == 200
    # Unknown route: past the gateway, so a normal 404 rather than 403.
    assert client.get("/does-not-exist", headers=headers()).status_code == 404


def test_secret_checked_before_auth(client: TestClient, make_token) -> None:
    # A valid user token alone is not enough; the BFF secret is required too.
    response = client.get("/v1/me", headers=headers(token=make_token(), secret=None))
    assert response.status_code == 403
