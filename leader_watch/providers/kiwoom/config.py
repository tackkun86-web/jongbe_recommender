"""Environment-driven configuration for the kiwoom_bridge HTTP client.

Numeric env vars are parsed through `_parse_positive_int` so malformed input
(e.g. "abc", "0", "-5") raises `KiwoomConfigError` instead of a bare
`ValueError`/allowing a zero/negative value through — main.py only knows how
to catch `KiwoomConfigError` cleanly (see Task 9), so anything else here
would leak a traceback. This mirrors a fix applied to the KIS integration's
`load_kis_config` after its final review found the same gap.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class KiwoomConfigError(Exception):
    """Raised when required kiwoom bridge configuration is missing or invalid,
    or (per KiwoomProvider's constructor, Task 8) when the bridge itself is
    unreachable."""


@dataclass(frozen=True)
class KiwoomConfig:
    bridge_url: str
    bridge_token: str
    universe_size: int
    ranking_refresh_seconds: int


_DEFAULTS = {
    "KIWOOM_BRIDGE_URL": "http://127.0.0.1:8000",
    "KIWOOM_UNIVERSE_SIZE": "100",
    "KIWOOM_RANKING_REFRESH_SECONDS": "20",
}


def _parse_positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise KiwoomConfigError(f"{name} must be an integer, got {value!r}") from None
    if parsed <= 0:
        raise KiwoomConfigError(f"{name} must be a positive integer, got {parsed}")
    return parsed


def load_kiwoom_config(env: dict | None = None) -> KiwoomConfig:
    source = os.environ if env is None else env
    get = lambda key: source.get(key, _DEFAULTS.get(key, ""))  # noqa: E731

    bridge_token = get("KIWOOM_BRIDGE_TOKEN")
    if not bridge_token:
        raise KiwoomConfigError(
            "KIWOOM_BRIDGE_TOKEN must be set to use --provider kiwoom. See .env.example."
        )

    return KiwoomConfig(
        bridge_url=get("KIWOOM_BRIDGE_URL"),
        bridge_token=bridge_token,
        universe_size=_parse_positive_int(get("KIWOOM_UNIVERSE_SIZE"), "KIWOOM_UNIVERSE_SIZE"),
        ranking_refresh_seconds=_parse_positive_int(
            get("KIWOOM_RANKING_REFRESH_SECONDS"), "KIWOOM_RANKING_REFRESH_SECONDS"
        ),
    )
