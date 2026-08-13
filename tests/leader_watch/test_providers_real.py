import datetime

import pytest
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kis.client import KisApiError
from leader_watch.providers.kis.config import KisConfig
from leader_watch.providers.real import RealProvider

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


@pytest.fixture
def _no_real_sleep(monkeypatch):
    """RealProvider wraps each KIS call in leader_watch.engine.call_with_retry, whose
    default backoff sleeps for real. Tests that deliberately trigger repeated
    failures (exhausting all retry attempts) patch that sleep to keep the test
    fast, matching the existing convention in tests/leader_watch/test_engine.py
    (which passes base_delay_seconds=0 directly to call_with_retry — not an
    option here since RealProvider calls it internally with its default)."""
    monkeypatch.setattr("leader_watch.engine.time.sleep", lambda seconds: None)


class _FakeClient:
    """Stands in for KisClient — RealProvider only calls these four methods."""

    def __init__(self):
        self.ranking_calls = 0
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.ranking_rows = [
            {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자", "data_rank": "1"},
        ]
        self.sector_rows = [{"hts_kor_isnm": "반도체", "data_rank": "1"}]
        self.quote_by_code = {
            "005930": {
                "stck_prpr": "70500", "stck_oprc": "70000", "stck_hgpr": "71000", "stck_lwpr": "69800",
                "prdy_vrss": "500", "acml_vol": "1000000", "acml_tr_pbmn": "70000000000",
                "bstp_kor_isnm": "반도체", "iscd_stat_cls_code": "00",
            },
        }
        self.minute_bar_by_code = {
            "005930": [{"stck_cntg_hour": "093000", "stck_oprc": "70000", "stck_hgpr": "70200", "stck_lwpr": "69900", "stck_prpr": "70100", "cntg_vol": "12345"}],
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
            raise KisApiError(f"simulated failure for {code}")
        return self.quote_by_code.get(code, {})

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return self.minute_bar_by_code.get(code, [])


def _provider_with_fake_client():
    provider = RealProvider(config=CFG)
    fake_client = _FakeClient()
    provider._client = fake_client
    return provider, fake_client


def test_real_provider_is_a_market_data_provider():
    provider, _ = _provider_with_fake_client()
    assert isinstance(provider, MarketDataProvider)


def test_get_snapshot_returns_snapshot_per_ranked_code():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert isinstance(snap, StockSnapshot)
    assert snap.code == "005930"
    assert snap.market_trading_value_rank == 1
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.timestamp == now


def test_get_snapshot_includes_minute_bars():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots[0].minute_bars_1m) == 1
    assert isinstance(snapshots[0].minute_bars_1m[0], MinuteBar)


def test_get_snapshot_does_not_refetch_minute_bar_within_same_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 30))
    assert len(client.minute_bar_calls) == 1


def test_get_snapshot_refetches_minute_bar_on_new_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 31, 0))
    assert len(client.minute_bar_calls) == 2


def test_get_snapshot_accumulates_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 31, 0))
    assert len(snapshots[0].minute_bars_1m) == 2


def test_get_snapshot_does_not_refetch_ranking_within_refresh_window():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 5))
    assert client.ranking_calls == 1
    assert client.sector_calls == 1


def test_get_snapshot_refetches_ranking_after_refresh_window_elapses():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 25))  # > 20s KIS_RANKING_REFRESH_SECONDS
    assert client.ranking_calls == 2
    assert client.sector_calls == 2


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_whose_quote_fails():
    provider, client = _provider_with_fake_client()
    client.quote_should_fail_for.add("005930")
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert snapshots == []


def test_constructor_uses_load_kis_config_when_no_config_given(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "envkey")
    monkeypatch.setenv("KIS_APP_SECRET", "envsecret")
    provider = RealProvider()
    assert provider._config.app_key == "envkey"
