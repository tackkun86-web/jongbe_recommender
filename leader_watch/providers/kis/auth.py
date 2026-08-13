"""OAuth token acquisition and in-process caching for the KIS Developers API."""
from __future__ import annotations

import time
from typing import Callable

import requests

from leader_watch.providers.kis.config import KisConfig

_TOKEN_PATH = "/oauth2/tokenP"
_REFRESH_MARGIN_SECONDS = 300  # refresh this many seconds before actual expiry


class KisAuthError(Exception):
    """Raised when the KIS OAuth token endpoint fails or returns an unexpected shape."""


class KisAuth:
    def __init__(self, config: KisConfig, now_fn: Callable[[], float] = time.time) -> None:
        self._config = config
        self._now_fn = now_fn
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._access_token is not None and self._now_fn() < self._expires_at - _REFRESH_MARGIN_SECONDS:
            return self._access_token
        self._refresh()
        assert self._access_token is not None
        return self._access_token

    def _refresh(self) -> None:
        try:
            response = requests.post(
                f"{self._config.base_url}{_TOKEN_PATH}",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self._config.app_key,
                    "appsecret": self._config.app_secret,
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            # Normalize network-level failures (timeouts, connection errors)
            # to KisAuthError so callers see one consistent exception type
            # instead of a raw `requests` exception escaping.
            raise KisAuthError(f"KIS token request failed: {exc}") from exc
        if response.status_code != 200:
            raise KisAuthError(f"KIS token request failed with status {response.status_code}: {response.text}")
        body = response.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not token or not isinstance(expires_in, (int, float)):
            raise KisAuthError(f"KIS token response missing access_token/expires_in: {body}")
        self._access_token = token
        self._expires_at = self._now_fn() + float(expires_in)
