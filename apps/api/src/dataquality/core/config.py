"""Runtime configuration, validated once at boot.

Every setting comes from the environment and is read here only. The API and the scan
worker share one ``Settings``. Security-relevant settings are checked by ``guard()`` so a
misconfigured production deployment refuses to start instead of running with demo secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}


def _split(v: object) -> object:
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


def _insecure(value: str) -> bool:
    return value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cloud: Literal["local", "floci", "aws"] = Field("local", alias="DATAQUALITY_CLOUD")

    database_url: str = "postgresql+asyncpg://dataquality:dataquality@localhost:4942/dataquality"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Rate limits and caches. Optional: without it they live in process (one replica).
    redis_url: str = ""
    memory_cache_max_bytes: int = Field(64_000_000, ge=1_000_000)

    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105 dev default, refused in production by guard()
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4910"]
    )
    # Where people open the app; used in alert emails and links.
    public_url: str = "http://localhost:4910"

    # Source passwords, REST headers, Slack and webhook URLs are sealed before storage.
    key_mode: Literal["local", "kms"] = "local"
    local_master_key: str = "dev-local-master-key-not-for-production"
    kms_key_id: str = "alias/dataquality-local"

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Uploaded files, SQLite databases, pushed batches. Rows keep only the key.
    objects_bucket: str = "dataquality-local-objects"
    storage: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.data/objects"

    # Mail for alerts: "log" (development), "smtp" (Mailpit locally, any relay), "ses" (AWS).
    mail_backend: Literal["log", "smtp", "ses"] = "log"
    mail_from: str = "DataQuality <alerts@dataquality.local>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(1025, ge=1, le=65535)

    # Sources. Databases usually live on private networks, so private hosts are allowed;
    # link-local and instance metadata addresses never are.
    source_allow_private: bool = True
    # REST datasets, Slack and webhooks: private addresses only when allowed (a demo sink).
    outbound_allow_private: bool = False
    statement_timeout_s: int = Field(300, ge=1, le=86_400)
    max_upload_bytes: int = Field(500_000_000, ge=1_000_000)
    max_push_records: int = Field(50_000, ge=1)
    max_push_bytes: int = Field(25_000_000, ge=10_000)
    rest_max_bytes: int = Field(50_000_000, ge=10_000)
    # Datasets larger than this are profiled over their first rows (checks stay exact).
    profile_max_rows: int = Field(5_000_000, ge=1_000)
    duckdb_memory_limit: str = "2GB"
    work_dir: str = "./.data/work"

    # The scan worker.
    worker_concurrency: int = Field(4, ge=1, le=64)
    lease_s: float = Field(60.0, ge=10, le=3600)
    max_attempts: int = Field(3, ge=1, le=10)
    worker_poll_interval_s: float = Field(2.0, gt=0, le=60)
    task_interval_s: float = Field(15.0, gt=0, le=600)
    worker_metrics_port: int = Field(9464, ge=0, le=65535)

    # Optional AI: off unless an admin turns it on and sets an endpoint.
    ai_allow_private_endpoints: bool = True
    ai_timeout_s: float = Field(30.0, gt=0, le=300)

    scan_rpm: int = 30
    max_body_bytes: int = 2_000_000
    otel_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        return _split(v)

    @property
    def cache_backend(self) -> Literal["redis", "memory"]:
        return "redis" if self.redis_url else "memory"

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        names = ("session_secret", "api_key_pepper")
        problems: list[str] = [
            f"{name.upper()} must be a random value of at least 32 chars"
            for name in names
            if _insecure(getattr(self, name))
        ]
        if self.key_mode == "local" and _insecure(self.local_master_key):
            problems.append("LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)")
        secrets = [getattr(self, n) for n in names]
        if len(set(secrets)) != len(secrets):
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when DATAQUALITY_CLOUD=aws")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.mail_backend == "log":
            problems.append("MAIL_BACKEND must be smtp or ses in production (alerts)")
        if self.storage == "local":
            problems.append("STORAGE must be s3 in production (several replicas share uploads)")
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings
