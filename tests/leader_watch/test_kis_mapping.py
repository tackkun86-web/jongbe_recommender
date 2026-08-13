import datetime

from leader_watch.providers.kis.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)


def test_parse_ranking_row():
    row = {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자", "data_rank": "3"}
    code, name, rank = parse_ranking_row(row)
    assert code == "005930"
    assert name == "삼성전자"
    assert rank == 3


def test_parse_sector_ranking_uses_data_rank_when_present():
    rows = [
        {"hts_kor_isnm": "반도체", "data_rank": "1"},
        {"hts_kor_isnm": "2차전지", "data_rank": "2"},
    ]
    ranks = parse_sector_ranking(rows)
    assert ranks == {"반도체": 1, "2차전지": 2}


def test_parse_sector_ranking_falls_back_to_position_when_rank_missing():
    rows = [
        {"hts_kor_isnm": "반도체"},
        {"hts_kor_isnm": "2차전지"},
    ]
    ranks = parse_sector_ranking(rows)
    assert ranks == {"반도체": 1, "2차전지": 2}


def _quote(**overrides):
    base = {
        "stck_prpr": "70500",
        "stck_oprc": "70000",
        "stck_hgpr": "71000",
        "stck_lwpr": "69800",
        "prdy_vrss": "500",
        "acml_vol": "12345678",
        "acml_tr_pbmn": "870123456789",
        "bstp_kor_isnm": "반도체",
        "iscd_stat_cls_code": "00",
    }
    base.update(overrides)
    return base


def test_quote_to_snapshot_maps_core_fields():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.code == "005930"
    assert snap.current_price == 70500.0
    assert snap.prev_close == 70000.0  # 70500 - 500
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


def test_quote_to_snapshot_execution_strength_defaults_to_neutral_when_absent():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 100.0


def test_quote_to_snapshot_uses_execution_strength_when_present():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(pgtr_symp_str="145.3"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 145.3


def test_quote_to_snapshot_theme_none_when_sector_missing():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(bstp_kor_isnm=""), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.theme is None
    assert snap.theme_trading_value_rank is None


def test_quote_to_snapshot_maps_administrative_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="51"), code="000001", name="관리종목", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_administrative is True
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_quote_to_snapshot_maps_investment_alert_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="52"), code="000002", name="투자위험", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_investment_alert is True


def test_quote_to_snapshot_maps_trading_halted_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="58"), code="000003", name="거래정지", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_trading_halted is True


def test_quote_to_snapshot_normal_status_code_excludes_nothing():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="00"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.is_administrative is False
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_parse_minute_bar():
    row = {"stck_cntg_hour": "093000", "stck_oprc": "70000", "stck_hgpr": "70200", "stck_lwpr": "69900", "stck_prpr": "70100", "cntg_vol": "12345"}
    bar = parse_minute_bar(row, reference_date=datetime.date(2026, 8, 12))
    assert bar.timestamp == datetime.datetime(2026, 8, 12, 9, 30)
    assert bar.open == 70000.0
    assert bar.high == 70200.0
    assert bar.low == 69900.0
    assert bar.close == 70100.0
    assert bar.volume == 12345
