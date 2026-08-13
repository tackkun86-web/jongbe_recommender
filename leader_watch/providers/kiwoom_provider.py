"""KiwoomProvider — orchestrates the kiwoom_bridge HTTP client into a MarketDataProvider.

Directly ports leader_watch/providers/real.py's caching/staleness/bounded-
minute-bar-window design (see that file's comments for the full reasoning):
ranking/sector data is refreshed on a slow cadence, quotes are fetched fresh
every tick, minute bars are fetched only once per new minute per code (the
PREVIOUS completed minute, never the in-progress one), and each snapshot
gets a bounded COPY of the most recent minute bars rather than a live
reference to the growing cache.

Unlike RealProvider, this provider also eagerly checks bridge connectivity
at construction (`client.check_health()`) and raises KiwoomConfigError if
the bridge is unreachable, per the design doc's "브릿지가 아예 떠 있지
않음(connection refused)" requirement — the bridge being an entirely
separate local process makes "bridge simply isn't running yet" a much more
common failure mode than anything in the KIS integration.
"""
from __future__ import annotations

import datetime

from leader_watch.engine import call_with_retry
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kiwoom.client import KiwoomApiError, KiwoomClient
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError, load_kiwoom_config
from leader_watch.providers.kiwoom.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)

# Fallback market label when the bridge quote doesn't supply one (see
# kiwoom/mapping.py's quote_to_snapshot — the bridge's own "market" field
# wins when present; this is only used if that field is missing/null).
_DEFAULT_MARKET_FALLBACK = "KOSPI"

# See leader_watch/providers/real.py's `_MINUTE_BAR_WINDOW` for the full
# reasoning (scoring.py concatenates minute_bars_1m across engine.history
# assuming ~1 bar/snapshot; state_machine.py needs >=2 bars within a single
# snapshot). Same fixed window, same rationale, applied here from the start.
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


class KiwoomProvider(MarketDataProvider):
    """KiwoomProvider — thin orchestrator over the kiwoom_bridge HTTP client.

    Note on snapshot timestamp / staleness: every StockSnapshot produced by
    get_snapshot(now) is stamped with timestamp=now (the tick's own poll
    time), not a bridge-supplied trade timestamp, for the same reason
    documented on RealProvider: this provider polls synchronously, so `now`
    IS an honest observation time for this architecture. One consequence:
    engine.py's is_stale(snapshot, now, config) staleness check is a
    structural no-op for this provider too — an accepted, documented
    limitation, not a bug.
    """

    def __init__(self, config: KiwoomConfig | None = None) -> None:
        self._config = config or load_kiwoom_config()
        self._client = KiwoomClient(self._config)
        try:
            self._client.check_health()
        except KiwoomApiError as exc:
            raise KiwoomConfigError(
                f"kiwoom_bridge에 연결할 수 없습니다 ({self._config.bridge_url}): {exc}\n"
                "  kiwoom_bridge/bridge.py 가 32비트 환경에서 실행 중인지, "
                "KIWOOM_BRIDGE_TOKEN이 양쪽에 동일하게 설정되어 있는지 확인하세요."
            ) from exc

        self._ranking_cache: list[tuple[str, str, int]] = []
        self._ranking_cache_at: datetime.datetime | None = None
        self._sector_rank_cache: dict[str, int] = {}
        self._sector_rank_cache_at: datetime.datetime | None = None

        self._bars_1m: dict[str, list[MinuteBar]] = {}
        self._last_bar_minute: dict[str, tuple[int, int]] = {}

    def _refresh_ranking_if_stale(self, now: datetime.datetime) -> None:
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
        # Request the PREVIOUS completed minute, not `now`'s own minute —
        # see leader_watch/providers/real.py's `_update_minute_bar` for why.
        reference_time = (now - datetime.timedelta(minutes=1)).strftime("%H%M%S")
        try:
            rows = call_with_retry(lambda: self._client.get_minute_bars(code, reference_time))
        except KiwoomApiError:
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
                snapshot = quote_to_snapshot(
                    quote,
                    code=code,
                    name=name,
                    market=_DEFAULT_MARKET_FALLBACK,
                    received_at=now,
                    market_rank=rank,
                    theme_rank_by_sector=self._sector_rank_cache,
                )
            except (KiwoomApiError, KeyError, ValueError, TypeError):
                # Partial-failure tolerance: a bad/partial quote for one code
                # must not abort the whole tick — skip just this code.
                continue

            self._update_minute_bar(code, now)
            bars_1m_full = self._bars_1m.get(code, [])
            # Bounded COPY, never the live cached list — see _MINUTE_BAR_WINDOW above.
            snapshot.minute_bars_1m = list(bars_1m_full[-_MINUTE_BAR_WINDOW:])
            # `minute_bars_5m` intentionally aggregates over the FULL per-code
            # 1m-bar cache, not the bounded window above: state_machine's
            # `_declining_five_minute_highs` needs multiple completed 5-minute
            # candles to detect a decline, and unlike minute_bars_1m,
            # minute_bars_5m is never concatenated across engine.history by
            # scoring.py, so there is no O(n^2) blowup risk here (same as
            # RealProvider/real.py, which this KiwoomProvider ported the
            # aggregation logic from). `_aggregate_5m` always builds and
            # returns a fresh list, so there is no aliasing risk either.
            snapshot.minute_bars_5m = _aggregate_5m(bars_1m_full)
            snapshots.append(snapshot)

        return snapshots
