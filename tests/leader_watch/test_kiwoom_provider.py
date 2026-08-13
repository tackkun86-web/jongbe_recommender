import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kiwoom.client import KiwoomApiError
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError
from leader_watch.providers.kiwoom_provider import KiwoomProvider

CFG = KiwoomConfig(bridge_url="http://127.0.0.1:8000", bridge_token="tok", universe_size=100, ranking_refresh_seconds=20)


@pytest.fixture
def _no_real_sleep(monkeypatch):
    """KiwoomProvider wraps each bridge call in leader_watch.engine.call_with_retry,
    whose default backoff sleeps for real. Tests that deliberately exhaust all
    retry attempts patch that sleep to keep the test fast, matching the
    convention already used for RealProvider's equivalent test."""
    monkeypatch.setattr("leader_watch.engine.time.sleep", lambda seconds: None)


class _FakeClient:
    """Stands in for KiwoomClient — KiwoomProvider only calls these four methods
    (health is checked separately at construction, see the _healthy_provider helper)."""

    def __init__(self):
        self.ranking_calls = 0
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.ranking_rows = [{"code": "005930", "name": "삼성전자", "rank": 1}]
        self.sector_rows = [{"name": "반도체", "rank": 1}]
        self.quote_by_code = {
            "005930": {
                "current_price": 70500, "open": 70000, "high": 71000, "low": 69800,
                "prev_close": 70000, "volume": 1000000, "trading_value": 70000000000,
                "sector": "반도체", "market": "KOSPI", "status": "normal",
            },
        }
        self.minute_bar_by_code = {
            "005930": [{"time": "093000", "open": 70000, "high": 70200, "low": 69900, "close": 70100, "volume": 12345}],
        }
        self.quote_should_fail_for: set[str] = set()

    def get_trading_value_ranking(self, count):
        self.ranking_calls += 1
        return self.ranking_rows[:count]

    def get_sector_ranking(self):
        self.sector_calls += 1
        return self.sector_rows

    def get_quote(self, code):
        self.quote_calls.append(code)
        if code in self.quote_should_fail_for:
            raise KiwoomApiError(f"simulated failure for {code}")
        return self.quote_by_code.get(code, {})

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return self.minute_bar_by_code.get(code, [])


def _provider_with_fake_client():
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
        provider = KiwoomProvider(config=CFG)
    fake_client = _FakeClient()
    provider._client = fake_client
    return provider, fake_client


def test_kiwoom_provider_is_a_market_data_provider():
    provider, _ = _provider_with_fake_client()
    assert isinstance(provider, MarketDataProvider)


def test_constructor_raises_kiwoom_config_error_when_bridge_unreachable():
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        with pytest.raises(KiwoomConfigError):
            KiwoomProvider(config=CFG)


def test_constructor_uses_load_kiwoom_config_when_no_config_given(monkeypatch):
    monkeypatch.setenv("KIWOOM_BRIDGE_TOKEN", "envtoken")
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
        provider = KiwoomProvider()
    assert provider._config.bridge_token == "envtoken"


def test_get_snapshot_returns_snapshot_per_ranked_code():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert isinstance(snap, StockSnapshot)
    assert snap.code == "005930"
    assert snap.market == "KOSPI"
    assert snap.market_trading_value_rank == 1
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.timestamp == now


def test_get_snapshot_includes_minute_bars():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots[0].minute_bars_1m) == 1
    assert isinstance(snapshots[0].minute_bars_1m[0], MinuteBar)


def test_get_snapshot_does_not_refetch_minute_bar_within_same_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 30))
    assert len(client.minute_bar_calls) == 1


def test_get_snapshot_refetches_minute_bar_on_new_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(client.minute_bar_calls) == 2


def test_update_minute_bar_requests_previous_completed_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert client.minute_bar_calls == [("005930", "093000")]


def test_get_snapshot_accumulates_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(snapshots[0].minute_bars_1m) == 2


def test_get_snapshot_does_not_alias_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    tick1_snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    tick1_bars = tick1_snapshots[0].minute_bars_1m
    assert len(tick1_bars) == 1
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(tick1_bars) == 1  # the tick-1 snapshot's own list must not have grown


def test_get_snapshot_minute_bars_1m_is_bounded_to_window():
    provider, client = _provider_with_fake_client()
    for minute in range(30, 38):  # 8 ticks, 8 minutes
        snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, minute, 0))
    assert len(snapshots[0].minute_bars_1m) == 5


def test_get_snapshot_does_not_refetch_ranking_within_refresh_window():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 5))
    assert client.ranking_calls == 1
    assert client.sector_calls == 1


def test_get_snapshot_refetches_ranking_after_refresh_window_elapses():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 25))  # > 20s KIWOOM_RANKING_REFRESH_SECONDS
    assert client.ranking_calls == 2
    assert client.sector_calls == 2


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_whose_quote_fails():
    provider, client = _provider_with_fake_client()
    client.quote_should_fail_for.add("005930")
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert snapshots == []


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_with_malformed_quote_but_keeps_others():
    provider, client = _provider_with_fake_client()
    client.ranking_rows = [
        {"code": "005930", "name": "삼성전자", "rank": 1},
        {"code": "000660", "name": "SK하이닉스", "rank": 2},
    ]
    client.quote_by_code["000660"] = {}  # missing required fields -> KeyError inside mapping
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    assert snapshots[0].code == "005930"
