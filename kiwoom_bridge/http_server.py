"""Pure HTTP-routing logic for kiwoom_bridge (see kiwoom_bridge/README.md).

Deliberately separated from any actual socket/HTTP-server machinery, and
from kiwoom_bridge/tr_client.py's win32com dependency, so this file's
routing/response-shaping logic — the part most likely to have copy-paste
bugs — is fully unit testable without a live Kiwoom login or even a real
HTTP server. kiwoom_bridge/bridge.py (Task 6) wires this dispatch function
into an actual http.server.HTTPServer; that wiring is NOT unit tested (see
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "테스트 계획").
"""
from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qs, urlparse


class TrClient(Protocol):
    def get_trading_value_ranking(self, count: int) -> list[dict]: ...
    def get_sector_ranking(self) -> list[dict]: ...
    def get_quote(self, code: str) -> dict: ...
    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]: ...


def handle_request(
    method: str,
    path: str,
    headers: dict,
    tr_client: TrClient,
    expected_token: str,
) -> tuple[int, dict | list]:
    """Route one HTTP request to a TrClient call. Returns (status_code, json_body)."""
    if method != "GET":
        return 404, {"error": f"unsupported method {method}"}

    if headers.get("X-Bridge-Token") != expected_token:
        return 401, {"error": "invalid or missing X-Bridge-Token"}

    parsed = urlparse(path)
    route = parsed.path
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    try:
        if route == "/health":
            return 200, {"status": "ok"}
        if route == "/ranking/trading-value":
            count = int(query.get("count", "100"))
            return 200, tr_client.get_trading_value_ranking(count)
        if route == "/ranking/sector":
            return 200, tr_client.get_sector_ranking()
        if route.startswith("/quote/"):
            code = route[len("/quote/"):]
            if not code:
                return 404, {"error": "missing stock code"}
            return 200, tr_client.get_quote(code)
        if route.startswith("/minute-bars/"):
            code = route[len("/minute-bars/"):]
            if not code:
                return 404, {"error": "missing stock code"}
            reference_time = query.get("reference_time", "")
            if not reference_time:
                return 400, {"error": "reference_time query param is required"}
            return 200, tr_client.get_minute_bars(code, reference_time)
    except Exception as exc:  # noqa: BLE001 - any TR failure becomes a clean 503, never a raised exception
        return 503, {"error": str(exc)}

    return 404, {"error": f"unknown route {route}"}
