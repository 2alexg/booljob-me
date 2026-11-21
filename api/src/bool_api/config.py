from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from BOOL_* environment variables.

    Secrets are injected by Cloud Run from Secret Manager (infra/gcp/bootstrap.sh).
    Optional settings are optional only until the matching service exists; routes
    that need an unconfigured dependency return 503.
    """

    model_config = SettingsConfigDict(env_prefix="BOOL_", extra="ignore")

    environment: Literal["local", "test", "staging", "prod"] = "local"
    log_level: str = "INFO"

    # Shared secret the Next.js BFF sends as X-Internal-Secret. Required by the
    # API service (create_app refuses to start without it); unused by the worker.
    internal_secret: SecretStr | None = Field(default=None, min_length=32)

    # e.g. https://<project-ref>.supabase.co. Tokens are verified against its JWKS.
    supabase_url: str | None = None
    jwt_audience: str = "authenticated"

    # Direct Postgres connection (bypasses RLS; authorization lives in this service).
    database_url: SecretStr | None = None

    @property
    def jwt_issuer(self) -> str | None:
        if self.supabase_url is None:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str | None:
        issuer = self.jwt_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None
