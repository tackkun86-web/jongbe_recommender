"""Environment-driven credentials and tuning parameters for the KIS Developers API client."""
from __future__ import annotations

import os
from dataclasses import dataclass


class KisConfigError(Exception):
    """Raised when required KIS credentials are missing or a setting is invalid."""


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    env: str  # "real" | "paper"
    universe_size: int
    ranking_refresh_seconds: int
    max_requests_per_second: int

    @property
    def base_url(self) -> str:
        if self.env == "paper":
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"


_DEFAULTS = {
    "KIS_ENV": "real",
    "KIS_UNIVERSE_SIZE": "100",
    "KIS_RANKING_REFRESH_SECONDS": "20",
    "KIS_MAX_REQUESTS_PER_SECOND": "15",
}


def _parse_positive_int(name: str, raw_value: str) -> int:
    """Parse an env var into a positive int, raising KisConfigError (not a bare
    ValueError/ZeroDivisionError-later) on anything malformed. main.py only
    catches KisConfigError around RealProvider() construction, so a bare
    ValueError here would leak a traceback instead of a clean error message —
    and a non-positive `max_requests_per_second` would later cause a
    ZeroDivisionError in kis/client.py's `_RateLimiter.__init__`
    (`1.0 / max_requests_per_second`)."""
    try:
        value = int(raw_value)
    except ValueError:
        raise KisConfigError(f"{name} must be an integer, got {raw_value!r}") from None
    if value <= 0:
        raise KisConfigError(f"{name} must be a positive integer, got {value}")
    return value


def load_kis_config(env: dict | None = None) -> KisConfig:
    source = os.environ if env is None else env
    get = lambda key: source.get(key, _DEFAULTS.get(key, ""))  # noqa: E731

    app_key = get("KIS_APP_KEY")
    app_secret = get("KIS_APP_SECRET")
    if not app_key or not app_secret:
        raise KisConfigError(
            "KIS_APP_KEY and KIS_APP_SECRET must be set to use --provider real. "
            "See .env.example."
        )

    kis_env = get("KIS_ENV")
    if kis_env not in ("real", "paper"):
        raise KisConfigError(f"KIS_ENV must be 'real' or 'paper', got {kis_env!r}")

    return KisConfig(
        app_key=app_key,
        app_secret=app_secret,
        env=kis_env,
        universe_size=_parse_positive_int("KIS_UNIVERSE_SIZE", get("KIS_UNIVERSE_SIZE")),
        ranking_refresh_seconds=_parse_positive_int(
            "KIS_RANKING_REFRESH_SECONDS", get("KIS_RANKING_REFRESH_SECONDS")
        ),
        max_requests_per_second=_parse_positive_int(
            "KIS_MAX_REQUESTS_PER_SECOND", get("KIS_MAX_REQUESTS_PER_SECOND")
        ),
    )
