"""Application configuration.

All configuration comes from the environment (12-factor). Secrets are never
committed; ``infra/.env.example`` documents every variable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

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

    @field_validator("cors_origins", "allowed_upload_extensions", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
