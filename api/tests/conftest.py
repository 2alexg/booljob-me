import json
import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bool_api.auth import TokenVerifier
from bool_api.config import Settings
from bool_api.main import create_app

INTERNAL_SECRET = "test-internal-secret-0123456789abcdef"
SUPABASE_URL = "https://example.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "test-key"


class StaticKeys:
    """Stands in for PyJWKClient: serves one public key, no network."""

    def __init__(self, private_key: ec.EllipticCurvePrivateKey) -> None:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
        self._key = jwt.PyJWK({**jwk, "kid": KID, "alg": "ES256"})

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if jwt.get_unverified_header(token).get("kid") != KID:
            raise jwt.PyJWKClientError("unknown kid")
        return self._key


@pytest.fixture(scope="session")
def private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        internal_secret=INTERNAL_SECRET,
        supabase_url=SUPABASE_URL,
        database_url=None,
    )


@pytest.fixture
def app(settings: Settings, private_key: ec.EllipticCurvePrivateKey) -> FastAPI:
    verifier = TokenVerifier(StaticKeys(private_key), ISSUER, settings.jwt_audience)
    return create_app(settings, token_verifier=verifier)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_token(private_key: ec.EllipticCurvePrivateKey) -> Callable[..., str]:
    def _make(**overrides: Any) -> str:
        claims: dict[str, Any] = {
            "sub": "11111111-1111-1111-1111-111111111111",
            "aud": "authenticated",
            "iss": ISSUER,
            "role": "authenticated",
            "exp": int(time.time()) + 300,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": KID})

    return _make


def headers(token: str | None = None, secret: str | None = INTERNAL_SECRET) -> dict[str, str]:
    h = {}
    if secret is not None:
        h["X-Internal-Secret"] = secret
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    return h
