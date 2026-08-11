"""MockProvider replays hand-authored per-minute scenarios for local testing."""
from __future__ import annotations

import datetime

from leader_watch.models import StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.mock_scenarios import build_scenarios

_MARKET_OPEN = datetime.time(9, 0)


class MockProvider(MarketDataProvider):
    def __init__(self) -> None:
        self._scenarios = build_scenarios()

    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        if now.time() < _MARKET_OPEN:
            return []

        result: list[StockSnapshot] = []
        for code, ticks in self._scenarios.items():
            candidates = [tick for tick in ticks if tick.timestamp <= now]
            if candidates:
                result.append(candidates[-1])
        return result
