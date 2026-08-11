import datetime
from leader_watch.providers.mock import MockProvider


def test_mock_provider_returns_snapshots_for_known_tick():
    provider = MockProvider()
    now = datetime.datetime(2026, 8, 11, 9, 1)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) > 0
    assert all(s.timestamp <= now for s in snapshots)


def test_mock_provider_returns_empty_before_market_open():
    provider = MockProvider()
    now = datetime.datetime(2026, 8, 11, 8, 55)
    assert provider.get_snapshot(now) == []


def test_mock_provider_scenario_stock_confirms_and_holds():
    provider = MockProvider()
    early = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 6))
    confirm = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 30))
    codes_early = {s.code for s in early}
    codes_confirm = {s.code for s in confirm}
    assert "LEAD01" in codes_early
    assert "LEAD01" in codes_confirm


def test_mock_provider_scenario_gap_over_8pct_flagged():
    provider = MockProvider()
    confirm = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 30))
    gap_stock = next(s for s in confirm if s.code == "GAP01")
    assert gap_stock.gap_from_prev_close_pct > 8


def test_mock_provider_returns_latest_snapshot_at_or_before_requested_time():
    provider = MockProvider()
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 7, 30))
    lead = next(s for s in snapshots if s.code == "LEAD01")
    assert lead.timestamp <= datetime.datetime(2026, 8, 11, 9, 7, 30)
