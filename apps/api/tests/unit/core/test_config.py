"""Production refuses to boot with demo secrets or unsafe options."""

from __future__ import annotations

import pytest

from dataquality.core.config import Settings

STRONG = {
    "session_secret": "s" * 40,
    "api_key_pepper": "p" * 40,
    "local_master_key": "m" * 40,
}


def prod(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "cookie_secure": True,
        "mail_backend": "smtp",
        "storage": "s3",
        **STRONG,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_a_safe_production_configuration_boots() -> None:
    prod().guard()


def test_development_never_refuses() -> None:
    Settings(environment="development").guard()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"session_secret": "dev-session-secret-not-for-production"}, "SESSION_SECRET"),
        ({"api_key_pepper": "short"}, "API_KEY_PEPPER"),
        ({"api_key_pepper": "s" * 40}, "must differ"),
        ({"local_master_key": "change-me"}, "LOCAL_MASTER_KEY"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"mail_backend": "log"}, "MAIL_BACKEND"),
        ({"storage": "local"}, "STORAGE"),
        ({"DATAQUALITY_CLOUD": "aws", "aws_endpoint_url": "http://floci:4566"}, "AWS_ENDPOINT_URL"),
    ],
)
def test_unsafe_production_settings_are_refused(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        prod(**overrides).guard()


def test_kms_mode_does_not_need_a_local_master_key() -> None:
    prod(key_mode="kms", local_master_key="").guard()


def test_cors_origins_split_from_a_comma_list() -> None:
    s = Settings(cors_origins="http://a.example, http://b.example,")  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.example", "http://b.example"]
    assert s.cache_backend == "memory"
    assert Settings(redis_url="redis://x:6379/0").cache_backend == "redis"
