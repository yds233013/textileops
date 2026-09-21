"""Application configuration.

All configuration comes from the environment (12-factor). Secrets are never
committed; ``infra/.env.example`` documents every variable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "TextileOps"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ---
    database_url: str = "postgresql+psycopg://textileops:textileops@localhost:55433/textileops"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Auth ---
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    # Seeded demo accounts are only created for non-production environments.
    demo_password: str = "textileops"

    # --- CORS ---
    # NoDecode: these arrive as comma-separated strings, not JSON, in .env files.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- AI provider ---
    # Absent credentials must never break the product: the stub provider returns
    # deterministic, clearly-labelled output so the whole app runs offline.
    ai_provider: Literal["anthropic", "stub", "auto"] = "auto"
    anthropic_api_key: str | None = None
    ai_model: str = "claude-sonnet-5"
    ai_max_tokens: int = 4096
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2

    # --- Ingestion ---
    upload_dir: str = "./var/uploads"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB
    allowed_upload_extensions: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [".csv", ".xlsx", ".xls", ".pdf", ".txt", ".md", ".eml"]
    )

    # --- Workers ---
    worker_poll_seconds: float = 1.0
    worker_batch_size: int = 10
    worker_max_attempts: int = 3

    # --- Engine tuning (business policy, not magic numbers in code) ---
    #: First-contact-with-real-data mode. TextileOps still ingests, reconciles,
    #: calculates, detects and proposes; what it stops doing is changing
    #: anything by itself. Every claim extracted from a supplier's message
    #: becomes something a person confirms rather than something that quietly
    #: moves a delivery date, and no action executes without a named human
    #: approval behind it.
    #:
    #: Enforced in the services, not in the routes or the UI — a mode that can
    #: be stepped around with a curl command is a label, not a control.
    pilot_mode: bool = False

    order_at_risk_buffer_days: int = 3
    po_late_grace_days: int = 0
    supplier_delay_warn_days: int = 2
    shipment_delay_grace_days: int = 1
    inventory_negative_tolerance: float = 0.0

    # --- Demo / simulation ---
    enable_simulation: bool = True
    #: A hosted demonstration on fictional data. Enables one-click sign-in as the
    #: seeded owner account, so a link can be sent to someone who has never
    #: seen the product without also sending them a password.
    #:
    #: It is a door with no lock, so it may only exist where there is nothing
    #: real behind it. Pilot mode is how an operator says "this is a real
    #: business's data"; the two refuse to run together (see
    #: `assert_consistent`).
    demo_mode: bool = False
    demo_account_email: str = "owner@kaveriknits.example"

    @field_validator("cors_origins", "allowed_upload_extensions", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    #: The value shipped in .env.example. Anyone who has read the repository
    #: can forge an owner token with it. ClassVar, or pydantic-settings takes
    #: it for a field.
    INSECURE_JWT_SECRET: ClassVar[str] = "dev-only-insecure-secret-change-me"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def assert_safe_for_production(self) -> None:
        """Refuse to start a production deployment with development defaults.

        SECURITY.md lists changing the JWT secret as a deployment step, which
        is a document telling a person to remember something. Nothing enforced
        it, and forging an `owner` token with the published default is a
        two-line script. A deployment that would be trivially forgeable should
        not start at all.
        """
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret == self.INSECURE_JWT_SECRET:
            problems.append(
                "JWT_SECRET is still the development default, so anyone who has "
                "read this repository can mint an owner token"
            )
        if self.debug:
            problems.append("DEBUG is on, which exposes internals in responses")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS allows any origin")
        if problems:
            raise RuntimeError(
                "Refusing to start in production:\n  - " + "\n  - ".join(problems)
            )

    def assert_consistent(self) -> None:
        """Refuse combinations that are unsafe in any environment."""
        if self.demo_mode and self.pilot_mode:
            raise RuntimeError(
                "Refusing to start: DEMO_MODE and PILOT_MODE are both on. Demo mode "
                "lets anyone with the link sign in as the owner without a password; "
                "pilot mode means this database holds a real business's data. "
                "Turn one of them off."
            )

    @property
    def ai_enabled(self) -> bool:
        """True when a real model provider can be reached."""
        if self.ai_provider == "stub":
            return False
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
