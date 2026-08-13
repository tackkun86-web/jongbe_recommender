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

# Bounded window for the per-tick `snapshot.minute_bars_1m` handed out below.
#
# `minute_bars_1m` must satisfy two downstream contracts this module cannot
# change (leader_watch/scoring.py and leader_watch/state_machine.py are both
# read-only):
#   - scoring.py's `_minute_flow_points` concatenates `snap.minute_bars_1m`
#     across every snapshot in `engine.history` for a code (it was written
#     assuming MockProvider puts exactly one bar per snapshot — see
#     leader_watch/providers/mock_scenarios.py). If every snapshot instead
#     carried the FULL cumulative per-code bar history (as this module did
#     before this fix), that concatenation becomes O(ticks^2) work per code
#     per tick at steady state, and since it was also the SAME mutable list
#     object handed out every tick, past snapshots would retroactively
#     "gain" future bars (aliasing bug).
#   - state_machine.py reads `snapshot.minute_bars_1m` directly on a single
#     snapshot and needs at least 2 bars within that one snapshot for its
#     장대음봉 (long bearish candle) rejection/weakness checks.
#
# A small fixed window satisfies both: state_machine gets >=2 bars as soon
# as 2 minutes of data exist, and scoring's per-tick concatenation cost
# becomes O(history_length * _MINUTE_BAR_WINDOW) = linear, not quadratic.
# Each snapshot below gets its own COPY of this window (never the live
# cached list), so old snapshots can no longer be mutated by future ticks.
# 5 was picked to match the 5-bar 5m-aggregation grouping size below.
_MINUTE_BAR_WINDOW = 5


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
    """RealProvider — thin orchestrator over the KIS Developers API client.

    Note on snapshot timestamp / staleness: every `StockSnapshot` produced by
    `get_snapshot(now)` is stamped with `timestamp=now` (the tick's own poll
    time), not a KIS-supplied trade timestamp. This is intentional, not an
    oversight: the KIS `inquire-price` quote endpoint used here
    (kis/mapping.py's `quote_to_snapshot`) does not carry a field that is
    both reliably present and usable as a genuine per-code observation time
    across this whole flow (see the design doc's "구현 중 반드시 검증해야 할
    가정" section — no such field was confirmed). Because this provider polls
    synchronously and quote data for a code is fetched at essentially the
    moment `now` is stamped, `now` IS an honest observation time for this
    provider's architecture — unlike, say, an async push-feed provider where
    "poll time" and "data time" could genuinely diverge.
    One consequence: `leader_watch/engine.py`'s `is_stale(snapshot, now,
    config)` staleness check compares `now` against `snapshot.timestamp`,
    which for RealProvider is always the same `now` — so staleness detection
    is a structural no-op for this provider. This is a known, accepted
    limitation of this synchronous-poll architecture, not a bug to silently
    paper over with a fabricated timestamp from a field that doesn't exist.
    """

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
        # Request the PREVIOUS completed minute, not `now`'s own minute. At
        # the first tick of a new minute, `now`'s minute has barely started
        # (maybe 0-2 seconds of trades), so asking KIS for bars up to
        # `now`'s own HHMMSS would return a near-empty partial candle that
        # then pollutes volume-based heuristics downstream. `now - 1 minute`
        # is always a fully-formed, completed 1-minute candle.
        reference_time = (now - datetime.timedelta(minutes=1)).strftime("%H%M%S")
        try:
            rows = call_with_retry(lambda: self._client.get_minute_bars(code, reference_time))
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
                # `received_at=now` intentionally IS the observed time here (see
                # class docstring "Note on snapshot timestamp / staleness" above):
                # this is a synchronous poll, so `now` is when this code's data
                # was actually fetched, not a placeholder.
                quote = call_with_retry(lambda code=code: self._client.get_quote(code))
                snapshot = quote_to_snapshot(
                    quote,
                    code=code,
                    name=name,
                    market=_MARKET,
                    received_at=now,
                    market_rank=rank,
                    theme_rank_by_sector=self._sector_rank_cache,
                )
            except (KisApiError, KeyError, ValueError, TypeError):
                # Partial-failure tolerance (design doc "부분 실패 허용"): a bad
                # or partial quote for one code (KisApiError from the HTTP call,
                # or KeyError/ValueError/TypeError from mapping.py's
                # `quote_to_snapshot` when the KIS response is missing required
                # fields / has malformed data) must not abort the whole tick —
                # skip just this code and keep going.
                continue

            self._update_minute_bar(code, now)
            bars_1m_full = self._bars_1m.get(code, [])
            # See `_MINUTE_BAR_WINDOW` above: hand out a bounded COPY, never the
            # live cached list.
            snapshot.minute_bars_1m = list(bars_1m_full[-_MINUTE_BAR_WINDOW:])
            # `minute_bars_5m` intentionally aggregates over the FULL per-code
            # 1m-bar cache, not the bounded window above: state_machine's
            # `_declining_five_minute_highs` needs multiple completed 5-minute
            # candles to detect a decline, and unlike minute_bars_1m,
            # minute_bars_5m is never concatenated across engine.history by
            # scoring.py, so there is no O(n^2) blowup risk here. `_aggregate_5m`
            # always builds and returns a fresh list, so there is no aliasing
            # risk either.
            snapshot.minute_bars_5m = _aggregate_5m(bars_1m_full)
            snapshots.append(snapshot)

        return snapshots
