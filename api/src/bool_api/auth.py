"""Supabase access-token verification.

Tokens are verified only against the project's published JWKS (asymmetric
ES256/RS256 signing keys). Symmetric (HS256) tokens are rejected.
"""

from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALLOWED_ALGORITHMS = ["ES256", "RS256"]


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    role: str


class InvalidTokenError(Exception):
    pass


class KeyServiceUnavailableError(Exception):
    pass


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class TokenVerifier:
    def __init__(self, keys: SigningKeySource, issuer: str, audience: str) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience

    @classmethod
    def from_jwks_url(cls, jwks_url: str, issuer: str, audience: str) -> "TokenVerifier":
        return cls(jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600), issuer, audience)

    def verify(self, token: str) -> AuthUser:
        try:
            if jwt.get_unverified_header(token).get("alg") not in ALLOWED_ALGORITHMS:
                raise InvalidTokenError("unsupported algorithm")
            key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            return AuthUser(id=UUID(claims["sub"]), role=str(claims.get("role", "")))
        except jwt.PyJWKClientConnectionError as e:
            raise KeyServiceUnavailableError from e
        except (jwt.PyJWTError, ValueError) as e:
            raise InvalidTokenError from e


_bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    # Sync dependency: FastAPI runs it in a thread pool, so the (cached) JWKS
    # fetch never blocks the event loop.
    verifier: TokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured")
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid token", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        return verifier.verify(credentials.credentials)
    except KeyServiceUnavailableError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth keys unavailable") from e
    except InvalidTokenError as e:
        raise unauthorized from e


CurrentUser = Annotated[AuthUser, Depends(current_user)]
