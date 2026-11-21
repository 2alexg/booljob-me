import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from bool_api.config import Settings
from bool_api.main import create_app
from tests.conftest import KID, headers


def test_valid_token_reaches_route(client: TestClient, make_token) -> None:
    response = client.get("/v1/me", headers=headers(token=make_token()))
    assert response.status_code == 200
    assert response.json() == {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "role": "authenticated",
    }


def test_missing_token(client: TestClient) -> None:
    response = client.get("/v1/me", headers=headers())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_token(client: TestClient, make_token) -> None:
    token = make_token(exp=int(time.time()) - 10)
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_wrong_audience(client: TestClient, make_token) -> None:
    token = make_token(aud="something-else")
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_wrong_issuer(client: TestClient, make_token) -> None:
    token = make_token(iss="https://evil.example/auth/v1")
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_missing_exp(client: TestClient, make_token) -> None:
    token = make_token(exp=None)
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_non_uuid_subject(client: TestClient, make_token) -> None:
    token = make_token(sub="not-a-uuid")
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_token_signed_by_another_key(client: TestClient) -> None:
    other = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": int(time.time()) + 300,
        },
        other,
        algorithm="ES256",
        headers={"kid": KID},
    )
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_hs256_token_rejected(client: TestClient) -> None:
    token = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": int(time.time()) + 300,
        },
        "a-shared-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": KID},
    )
    assert client.get("/v1/me", headers=headers(token=token)).status_code == 401


def test_garbage_token(client: TestClient) -> None:
    assert client.get("/v1/me", headers=headers(token="not.a.jwt")).status_code == 401


def test_auth_not_configured(settings: Settings, make_token) -> None:
    app = create_app(settings.model_copy(update={"supabase_url": None}))
    response = TestClient(app).get("/v1/me", headers=headers(token=make_token()))
    assert response.status_code == 503
