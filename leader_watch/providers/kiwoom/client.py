"""HTTP client for the local kiwoom_bridge process (see kiwoom_bridge/).

The bridge is a plain, unauthenticated-by-default local HTTP server other
than the shared-secret `X-Bridge-Token` header, so every request carries it.
`requests.RequestException` (timeouts, connection refused, etc.) is
normalized to `KiwoomApiError` here so a down/unreachable bridge never
surfaces as a raw, uncaught requests exception to callers — the same fix
applied to `leader_watch/providers/kis/client.py` after the KIS
integration's final review found the gap.
"""
from __future__ import annotations

import requests

from leader_watch.providers.kiwoom.config import KiwoomConfig


class KiwoomApiError(Exception):
    """Raised when a kiwoom_bridge HTTP call fails or the bridge is unreachable."""


class KiwoomClient:
    def __init__(self, config: KiwoomConfig) -> None:
        self._config = config

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        try:
            response = requests.get(
                f"{self._config.bridge_url}{path}",
                headers={"X-Bridge-Token": self._config.bridge_token},
                params=params or {},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise KiwoomApiError(f"kiwoom_bridge call to {path} failed: {exc}") from exc
        if response.status_code != 200:
            raise KiwoomApiError(
                f"kiwoom_bridge call to {path} failed with status {response.status_code}: {response.text}"
            )
        return response.json()

    def check_health(self) -> None:
        self._get("/health")

    def get_trading_value_ranking(self, count: int) -> list[dict]:
        body = self._get("/ranking/trading-value", params={"count": count})
        return body if isinstance(body, list) else []

    def get_sector_ranking(self) -> list[dict]:
        body = self._get("/ranking/sector")
        return body if isinstance(body, list) else []

    def get_quote(self, code: str) -> dict:
        body = self._get(f"/quote/{code}")
        return body if isinstance(body, dict) else {}

    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]:
        body = self._get(f"/minute-bars/{code}", params={"reference_time": reference_time})
        return body if isinstance(body, list) else []
