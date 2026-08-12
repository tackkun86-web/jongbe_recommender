"""Rate-limited, authenticated HTTP client for the KIS Developers API.

Endpoint methods are appended to this file/class across several plan tasks;
each method's TR_ID and path are commented `ASSUMPTION` where the exact
value could not be verified without a live account — see
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

from leader_watch.providers.kis.auth import KisAuth
from leader_watch.providers.kis.config import KisConfig


class KisApiError(Exception):
    """Raised when a KIS REST call returns a non-200 status or a non-zero rt_cd."""


class _RateLimiter:
    def __init__(
        self,
        max_requests_per_second: int,
        sleep_fn: Callable[[float], None] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._min_interval = 1.0 / max_requests_per_second
        self._sleep_fn = sleep_fn or time.sleep
        self._now_fn = now_fn or time.time
        self._last_call_at: float | None = None

    def wait(self) -> None:
        now = self._now_fn()
        if self._last_call_at is not None:
            elapsed = now - self._last_call_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep_fn(remaining)
        self._last_call_at = self._now_fn()


class KisClient:
    def __init__(self, config: KisConfig, auth: KisAuth) -> None:
        self._config = config
        self._auth = auth
        self._rate_limiter = _RateLimiter(config.max_requests_per_second)

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        self._rate_limiter.wait()
        token = self._auth.get_token()
        response = requests.get(
            f"{self._config.base_url}{path}",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self._config.app_key,
                "appsecret": self._config.app_secret,
                "tr_id": tr_id,
                "custtype": "P",
            },
            params=params,
            timeout=10,
        )
        if response.status_code != 200:
            raise KisApiError(f"KIS API call to {path} failed with status {response.status_code}: {response.text}")
        body = response.json()
        if body.get("rt_cd") != "0":
            raise KisApiError(f"KIS API call to {path} returned rt_cd={body.get('rt_cd')}: {body.get('msg1')}")
        return body
