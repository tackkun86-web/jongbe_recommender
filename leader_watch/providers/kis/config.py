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
        universe_size=int(get("KIS_UNIVERSE_SIZE")),
        ranking_refresh_seconds=int(get("KIS_RANKING_REFRESH_SECONDS")),
        max_requests_per_second=int(get("KIS_MAX_REQUESTS_PER_SECOND")),
    )
