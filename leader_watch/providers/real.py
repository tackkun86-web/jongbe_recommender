"""RealProvider — orchestrates the KIS Developers API client into a MarketDataProvider.

Implements the caching/staleness policy from
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md ("데이터 흐름 & 캐싱
정책"): ranking/sector data is refreshed on a slow cadence, quotes are fetched
fresh every tick (rate-limited by KisClient), and minute bars are fetched only
once per new minute per code.

Note on nested retry: each individual KIS network call inside this module is
wrapped with `leader_watch.engine.call_with_retry` (3 attempts, exponential
backoff), and `engine.py`'s own `run_once` separately wraps the whole
`get_snapshot()` call the same way. This is intentional, not a mistake — both
layers already exist in reviewed code and both are bounded (never infinite),
so a persistent outage fails within a bounded number of attempts either way.
"""
from __future__ import annotations

import datetime

from leader_watch.engine import call_with_retry
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kis.auth import KisAuth
from leader_watch.providers.kis.client import KisApiError, KisClient
from leader_watch.providers.kis.config import KisConfig, load_kis_config
from leader_watch.providers.kis.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)

# ASSUMPTION: the ranking/quote endpoints used here do not distinguish
# KOSPI vs KOSDAQ in their response; every tracked stock is labeled KOSPI
# until a real account confirms otherwise.
_MARKET = "KOSPI"


def _aggregate_5m(bars_1m: list[MinuteBar]) -> list[MinuteBar]:
    """Group a chronological list of 1-minute bars into completed 5-minute candles."""
    aggregated: list[MinuteBar] = []
    complete_len = len(bars_1m) - (len(bars_1m) % 5)
    for start in range(0, complete_len, 5):
        chunk = bars_1m[start:start + 5]
        aggregated.append(
            MinuteBar(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
                volume=sum(b.volume for b in chunk),
            )
        )
    return aggregated


class RealProvider(MarketDataProvider):
    def __init__(self, config: KisConfig | None = None) -> None:
        self._config = config or load_kis_config()
        self._auth = KisAuth(self._config)
        self._client = KisClient(self._config, self._auth)

        self._ranking_cache: list[tuple[str, str, int]] = []
        self._ranking_cache_at: datetime.datetime | None = None
        self._sector_rank_cache: dict[str, int] = {}
        self._sector_rank_cache_at: datetime.datetime | None = None

        self._bars_1m: dict[str, list[MinuteBar]] = {}
        self._last_bar_minute: dict[str, tuple[int, int]] = {}

    def _refresh_ranking_if_stale(self, now: datetime.datetime) -> None:
        # Staleness is measured against the tick's own `now` (not real wall-clock
        # time.time()) so this is deterministic and testable with simulated
        # timestamps, consistent with `_update_minute_bar` below.
        if (
            self._ranking_cache_at is not None
            and (now - self._ranking_cache_at).total_seconds() < self._config.ranking_refresh_seconds
        ):
            return
        rows = call_with_retry(lambda: self._client.get_trading_value_ranking(self._config.universe_size))
        self._ranking_cache = [parse_ranking_row(row) for row in rows]
        self._ranking_cache_at = now

    def _refresh_sector_ranking_if_stale(self, now: datetime.datetime) -> None:
        if (
            self._sector_rank_cache_at is not None
            and (now - self._sector_rank_cache_at).total_seconds() < self._config.ranking_refresh_seconds
        ):
            return
        rows = call_with_retry(lambda: self._client.get_sector_ranking())
        self._sector_rank_cache = parse_sector_ranking(rows)
        self._sector_rank_cache_at = now

    def _update_minute_bar(self, code: str, now: datetime.datetime) -> None:
        current_minute = (now.hour, now.minute)
        if self._last_bar_minute.get(code) == current_minute:
            return
        try:
            rows = call_with_retry(lambda: self._client.get_minute_bars(code, now.strftime("%H%M%S")))
        except KisApiError:
            return
        if not rows:
            return
        bar = parse_minute_bar(rows[0], now.date())
        self._bars_1m.setdefault(code, []).append(bar)
        self._last_bar_minute[code] = current_minute

    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        self._refresh_ranking_if_stale(now)
        self._refresh_sector_ranking_if_stale(now)

        snapshots: list[StockSnapshot] = []
        for code, name, rank in self._ranking_cache:
            try:
                quote = call_with_retry(lambda code=code: self._client.get_quote(code))
            except KisApiError:
                continue

            self._update_minute_bar(code, now)
            bars_1m = self._bars_1m.get(code, [])
            bars_5m = _aggregate_5m(bars_1m)

            snapshot = quote_to_snapshot(
                quote,
                code=code,
                name=name,
                market=_MARKET,
                received_at=now,
                market_rank=rank,
                theme_rank_by_sector=self._sector_rank_cache,
            )
            snapshot.minute_bars_1m = bars_1m
            snapshot.minute_bars_5m = bars_5m
            snapshots.append(snapshot)

        return snapshots
