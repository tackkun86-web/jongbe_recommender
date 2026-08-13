import datetime

from leader_watch.providers.kiwoom.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)


def test_parse_ranking_row():
    code, name, rank = parse_ranking_row({"code": "005930", "name": "삼성전자", "rank": "3"})
    assert code == "005930"
    assert name == "삼성전자"
    assert rank == 3


def test_parse_sector_ranking_uses_rank_when_present():
    ranks = parse_sector_ranking([{"name": "반도체", "rank": 1}, {"name": "2차전지", "rank": 2}])
    assert ranks == {"반도체": 1, "2차전지": 2}


def test_parse_sector_ranking_falls_back_to_position_when_rank_missing():
    ranks = parse_sector_ranking([{"name": "반도체"}, {"name": "2차전지"}])
    assert ranks == {"반도체": 1, "2차전지": 2}


def _quote(**overrides):
    base = {
        "current_price": 70500, "open": 70000, "high": 71000, "low": 69800,
        "prev_close": 70000, "volume": 12345678, "trading_value": 870123456789,
        "sector": "반도체", "market": "KOSPI", "status": "normal",
    }
    base.update(overrides)
    return base


def test_quote_to_snapshot_maps_core_fields():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.code == "005930"
    assert snap.market == "KOSPI"
    assert snap.current_price == 70500.0
    assert snap.prev_close == 70000.0
    assert snap.open_price == 70000.0
    assert snap.high_price == 71000.0
    assert snap.low_price == 69800.0
    assert snap.cum_volume == 12345678
    assert snap.cum_trading_value == 870123456789.0
    assert snap.market_trading_value_rank == 5
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.news_today is False
    assert snap.news_continuing is False
    assert snap.avg_trading_value_same_time_20d is None
    assert snap.avg_volume_same_time_20d is None


def test_quote_to_snapshot_uses_market_field_when_present():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(market="KOSDAQ"), code="123456", name="어떤종목", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.market == "KOSDAQ"  # bridge-supplied market wins over the caller's fallback


def test_quote_to_snapshot_falls_back_to_caller_market_when_missing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(market=None), code="123456", name="어떤종목", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.market == "KOSPI"


def test_quote_to_snapshot_execution_strength_defaults_to_neutral_when_absent():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 100.0


def test_quote_to_snapshot_uses_execution_strength_when_present():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(execution_strength=145.3), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 145.3


def test_quote_to_snapshot_theme_none_when_sector_missing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(sector=None), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.theme is None
    assert snap.theme_trading_value_rank is None


def test_quote_to_snapshot_maps_administrative_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="administrative"), code="000001", name="관리종목", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_administrative is True
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_quote_to_snapshot_maps_investment_alert_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="investment_alert"), code="000002", name="투자위험", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_investment_alert is True


def test_quote_to_snapshot_maps_trading_halted_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="trading_halted"), code="000003", name="거래정지", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_trading_halted is True


def test_quote_to_snapshot_normal_status_excludes_nothing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="normal"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.is_administrative is False
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_parse_minute_bar():
    row = {"time": "093000", "open": 70000, "high": 70200, "low": 69900, "close": 70100, "volume": 12345}
    bar = parse_minute_bar(row, reference_date=datetime.date(2026, 8, 13))
    assert bar.timestamp == datetime.datetime(2026, 8, 13, 9, 30)
    assert bar.open == 70000.0
    assert bar.high == 70200.0
    assert bar.low == 69900.0
    assert bar.close == 70100.0
    assert bar.volume == 12345
