# kiwoom_bridge/bridge.py
"""kiwoom_bridge/bridge.py — entrypoint. 32-bit Python + pywin32 ONLY.

Run this from your existing 32-bit Kiwoom OpenAPI+ environment, after
logging in through the OpenAPI+ login program, per kiwoom_bridge/README.md's
manual test protocol. Not part of the automated test suite — see
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "테스트 계획".
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from kiwoom_bridge.http_server import handle_request
from kiwoom_bridge.tr_client import KiwoomTrClient


def _make_handler(tr_client: KiwoomTrClient, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required name by BaseHTTPRequestHandler
            status, body = handle_request("GET", self.path, dict(self.headers), tr_client, token)
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            print(f"[kiwoom_bridge] {self.address_string()} - {format % args}")

    return Handler


def main() -> None:
    port = int(os.environ.get("KIWOOM_BRIDGE_PORT", "8000"))
    token = os.environ.get("KIWOOM_BRIDGE_TOKEN", "")
    if not token:
        raise SystemExit("KIWOOM_BRIDGE_TOKEN environment variable must be set before starting the bridge.")

    tr_client = KiwoomTrClient()
    server = HTTPServer(("127.0.0.1", port), _make_handler(tr_client, token))
    print(f"[kiwoom_bridge] listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
