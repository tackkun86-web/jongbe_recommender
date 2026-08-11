"""Real broker/exchange API provider — NOT YET IMPLEMENTED.

TODO: Wire this up to an actual real-time market data source once one is
chosen (e.g. a securities-firm Open API providing 1-min/5-min bars,
체결강도, and live market/theme trading-value ranks). Naver Finance HTML
scraping (used by the existing daily-batch `data_fetcher.py`) does NOT
provide these real-time fields and cannot be reused here.

Implementers must:
  1. Authenticate using credentials read from environment variables
     (never hardcode secrets).
  2. Return `StockSnapshot` objects with `timestamp` set to the actual
     exchange data timestamp (not `datetime.now()`), so the staleness
     check in `engine.py` works correctly.
  3. Wrap network calls with the retry/backoff helper in
     `leader_watch/engine.py` (`call_with_retry`).
"""
from __future__ import annotations

import datetime

from leader_watch.models import StockSnapshot
from leader_watch.providers.base import MarketDataProvider


class RealProvider(MarketDataProvider):
    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        raise NotImplementedError(
            "RealProvider is not implemented yet — no real-time market data "
            "source is configured. See the module docstring for what an "
            "implementation must do."
        )
